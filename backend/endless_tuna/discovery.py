"""Conference discovery from official directories, without search scraping or LAS."""
import copy
import re
import threading
import time
from typing import Literal
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from fastapi import Depends, Query
from pydantic import BaseModel, Field, ValidationError
from . import db as storage
from .adapters import adapter_for, canonical_url
from .collection import CollectionError
from .network import fetch_bytes
from .proceedings import pmlr_volume

DIRECTORY = 'https://proceedings.mlr.press/'
STARTERS = [
    dict(name="WACV · Winter Conference on Applications of Computer Vision", year=2026, source_url="https://wacv.thecvf.com/virtual/2026/papers.html", publisher="CVF", topics="computer vision image applications", adapter="wacv-2026-program"),
    dict(name='CoRL · Conference on Robot Learning', year=2024, source_url=DIRECTORY+'v270/', publisher='PMLR', topics='robotics imitation learning manipulation navigation', adapter='pmlr-volume'),
    dict(name='ICML · International Conference on Machine Learning', year=2024, source_url=DIRECTORY+'v235/', publisher='PMLR', topics='machine learning artificial intelligence', adapter='pmlr-volume'),
    dict(name='RSS · Robotics: Science and Systems', year=2025, source_url='https://www.roboticsproceedings.org/rss21/', publisher='RSS', topics='robotics navigation manipulation', adapter='rss-2025'),
    dict(name='NeurIPS · Neural Information Processing Systems', year=2024, source_url='https://papers.nips.cc/paper_files/paper/2024', publisher='NeurIPS', topics='machine learning artificial intelligence neuroscience', adapter='neurips-2024-main'),
    dict(name='NeurIPS · Neural Information Processing Systems', year=2026, source_url='https://neurips.cc/virtual/2026/papers.html', publisher='NeurIPS', topics='machine learning artificial intelligence neuroscience', adapter='neurips-2026-program'),
]
ALIASES = {
    'corl': 'conference on robot learning robotics',
    'icml': 'international conference on machine learning',
    'aistats': 'artificial intelligence and statistics',
    'colt': 'conference on learning theory',
    'uai': 'uncertainty artificial intelligence',
    'l4dc': 'learning dynamics control',
    'mlhc': 'machine learning healthcare',
}
_lock = threading.Lock()
_cache = {'rows': [], 'fetched_at': None, 'attempted_at': 0, 'warning': None}


def parse_directory(raw, final):
    u = urlsplit(final)
    if u.hostname != 'proceedings.mlr.press' or u.path not in ('','/') or u.query:
        raise CollectionError('Official conference directory redirected away from PMLR.')
    soup = BeautifulSoup(raw, 'html.parser')
    rows = {}
    for a in soup.select('li a[href]'):
        href = urljoin(DIRECTORY, a['href'])
        if not pmlr_volume(href): continue
        li = a.find_parent('li')
        text = li.get_text(' ', strip=True)
        name = re.sub(r'^Volume\s+\d+\s*', '', text).strip()
        if not name: continue
        year = re.search(r'\b(19\d{2}|20\d{2})\b', name)
        tokens = set(re.findall(r'\w+', name.casefold()))
        aliases = ' '.join(value for key,value in ALIASES.items() if key in tokens)
        href = DIRECTORY + urlsplit(href).path.strip('/') + '/'
        rows[href] = dict(name=name, year=int(year[0]) if year else None, source_url=href,
            publisher='PMLR', topics=aliases, adapter='pmlr-volume')
    if not rows: raise CollectionError('PMLR directory has no recognized volumes; its structure may have changed.')
    return list(rows.values())


def directory_rows(force=False):
    with _lock:
        now = time.time()
        ttl = 60 if _cache['warning'] else 3600
        if force or now - _cache['attempted_at'] >= ttl:
            _cache['attempted_at'] = now
            try:
                raw, final = fetch_bytes(DIRECTORY, limit=2_000_000)
                rows = parse_directory(raw, final)
                _cache.update(rows=rows, fetched_at=time.time(), warning=None)
            except CollectionError as error:
                _cache['warning'] = 'Official directory unavailable. Showing starter sources and any cached entries. ' + str(error)
        return copy.deepcopy(_cache)


class InspectSource(BaseModel):
    source_url: str = Field(min_length=1, max_length=2000)


def register_discovery(app, collection):
    @app.get('/api/discovery/conferences')
    def discover(q: str = Query(default='',max_length=200), year: int|None = Query(default=None,ge=1900,le=2100),
                 publisher: Literal['all','PMLR','RSS','NeurIPS','CVF']='all',
                 directory: Literal['starter','official']='starter',
                 page: int=Query(default=1,ge=1,le=100000), page_size:int=Query(default=12,ge=1,le=100), c=Depends(collection)):
        cached = directory_rows() if directory == 'official' else dict(rows=[], fetched_at=None, warning=None)
        rows = {canonical_url(r['source_url']): dict(r, origin='Official PMLR directory') for r in cached['rows']}
        for row in STARTERS:
            key = canonical_url(row['source_url'])
            if key in rows:
                rows[key]['topics'] += ' ' + row['topics']
                rows[key]['name'] = row['name']
            else: rows[key] = dict(row, origin='Starter source catalog')
        terms = re.findall(r'\w+', q.casefold())
        with storage.connect('real') as db:
            existing = {canonical_url(r['source_url']): r['id'] for r in db.execute('SELECT id,source_url FROM editions ORDER BY rowid DESC')}
        results = []
        for key,row in rows.items():
            if year and row['year'] != year or publisher != 'all' and row['publisher'] != publisher: continue
            haystack = ' '.join(str(row.get(k) or '') for k in ('name','year','topics','publisher')).casefold()
            if not all(term in haystack for term in terms): continue
            row.update(track='All published tracks' if row['adapter']=='neurips-2026-program' else ('Main Conference' if row['adapter']=='wacv-2026-program' else 'Published proceedings'),
                       support='collector_available', inspection_status='not_checked', pdf_status='not_checked',
                       existing_edition_id=existing.get(key))
            results.append(row)
        results.sort(key=lambda r: (-(r['year'] or 0), r['name'].casefold(), r['source_url']))
        pages = max(1,(len(results)+page_size-1)//page_size); page=min(page,pages)
        return dict(items=results[(page-1)*page_size:page*page_size],total=len(results),page=page,pages=pages,page_size=page_size,
                    directory=directory, directory_url=DIRECTORY, fetched_at=cached['fetched_at'], warning=cached['warning'],
                    message='Searches conference names, abbreviations and known subjects, not paper contents. A supported collector does not guarantee every PDF is accessible.')

    @app.post('/api/discovery/inspect')
    def inspect(body: InspectSource, c=Depends(collection)):
        try:
            from .network import validate_url
            validate_url(body.source_url, resolve=False)
            adapter = adapter_for(body.source_url)
            if adapter.name not in ('pmlr-volume','rss-2025','neurips-2024-main','neurips-2026-program','wacv-2026-program'):
                raise CollectionError('Source check supports WACV 2026, official PMLR volumes, RSS 2025 and the supported NeurIPS listings only. Use CSV import for other sources.')
            inventory = adapter.inventory(body.source_url, fetch_bytes)
        except ValidationError:
            return dict(ok=False, status="unavailable", message="Official source metadata is invalid or exceeds supported limits. No papers were added.")
        except CollectionError as error:
            # Unsupported/private inputs and access failures never create editions or jobs.
            return dict(ok=False, status='unavailable', message=str(error))
        return dict(ok=True,status='inventory_accessible',adapter=adapter.name,source_url=inventory.url,
                    official_count=inventory.official_count,year=next((r.year for r in inventory.records if r.year),None),
                    checked_at=time.time(),sample_titles=[r.title for r in inventory.records[:3]],pdf_status='not_checked',
                    message='Official paper inventory is readable. PDF access and text extraction are checked by collection jobs; some files may be unavailable. No papers were added.')
