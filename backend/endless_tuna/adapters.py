"""Conference adapters implement inventory + hydrate; no fixed paper inventories."""
import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Protocol, Callable
from urllib.parse import urlsplit, urljoin, urlunsplit
from bs4 import BeautifulSoup
from .collection import Metadata, Person, CollectionError, parse_metadata

NEURIPS_HOSTS = {'papers.nips.cc', 'proceedings.neurips.cc'}


def neurips_homepage(url):
    u=urlsplit(url)
    return u.hostname in ('neurips.cc','www.neurips.cc') and (not u.path.strip('/') or re.fullmatch(r'/Conferences/\d{4}/?',u.path) is not None)


HOMEPAGE_ERROR = ('The NeurIPS conference homepage is not a paper inventory or CSV file. '
                  'Use Auto with edition year 2026 to collect its official virtual-program listing, or NeurIPS 2024 main proceedings at '
                  'https://papers.nips.cc/paper_files/paper/2024. '
                  'CSV requires an actual CSV inventory file URL.')


def canonical_url(url):
    u = urlsplit(url)
    host = 'papers.nips.cc' if u.hostname in NEURIPS_HOSTS else u.hostname
    return urlunsplit(('https' if u.hostname in NEURIPS_HOSTS else u.scheme, host, u.path.rstrip('/'), u.query, ''))


@dataclass
class Inventory:
    records: list[Metadata]
    official_count: int | None
    url: str


class ConferenceAdapter(Protocol):
    name: str
    def inventory(self, url: str, fetch: Callable) -> Inventory: ...
    def hydrate(self, record: Metadata, fetch: Callable) -> Metadata: ...


class NeurIPS2024:
    name = 'neurips-2024-main'

    def inventory(self, url, fetch):
        raw, final = fetch(url, limit=12_000_000)
        if not supports_neurips(final):
            raise CollectionError('Official inventory redirected outside the supported NeurIPS 2024 proceedings.')
        soup = BeautifulSoup(raw, 'html.parser')
        found = {}
        for link in soup.select('a[href]'):
            href = urljoin(final, link['href'])
            if not re.fullmatch(r'/paper_files/paper/2024/hash/[a-f0-9]{32}-Abstract-Conference.html', urlsplit(href).path):
                continue  # workshop and other track links cannot enter the main inventory
            if urlsplit(href).hostname not in NEURIPS_HOSTS:
                continue
            container=link.find_parent(class_='paper-content')
            if container is None:continue
            authors = container.select_one('.paper-authors')
            if canonical_url(href) in found:continue
            found[canonical_url(href)] = Metadata(title=link.get_text(' ', strip=True),
                authors=[Person(name=name.strip()) for name in authors.get_text(' ',strip=True).split(',') if name.strip()] if authors else [],
                source_url=canonical_url(href), detail_pending=True)
        if not found:
            raise CollectionError('NeurIPS inventory contains no recognized main-proceedings links; adapter structure may have changed.')
        return Inventory(list(found.values()), len(found), canonical_url(final))

    def hydrate(self, record, fetch):
        raw, final = fetch(record.source_url, limit=2_000_000)
        if canonical_url(final) != canonical_url(record.source_url):
            raise CollectionError('Paper page redirected away from its official inventory record.')
        soup = BeautifulSoup(raw, 'html.parser')
        values = lambda name: [m.get('content','').strip() for m in soup.find_all('meta', attrs={'name':name})]
        title = values('citation_title')
        names = values('citation_author')
        if not title or not names:
            raise CollectionError('Official NeurIPS paper metadata is incomplete; inventory membership retained.')
        abstract = soup.select_one('.paper-abstract')
        # BeautifulSoup handles the official nested <p> markup inside this element.
        text = abstract.get_text(' ',strip=True) if abstract else ''
        if not text:
            heading = soup.find(['h2','h3'],string=re.compile(r'^\s*Abstract\s*$'))
            if heading:
                text = ' '.join(p.get_text(' ',strip=True) for p in heading.find_next_siblings('p'))
        def display_name(name):
            parts = name.split(',',1)
            return (parts[1].strip()+' '+parts[0].strip()) if len(parts)==2 else name
        pdfs = values('citation_pdf_url')
        paper_link = next((a['href'] for a in soup.select('a[href]') if a.get_text(strip=True)=='Paper'), None)
        identifiers = dict(record.identifiers)
        for field, namespace in [('citation_doi','doi'),('citation_arxiv_id','arxiv')]:
            if values(field):identifiers[namespace]=values(field)[0]
        identifiers['neurips'] = urlsplit(record.source_url).path.split('/')[-1].split('-')[0]
        return Metadata(title=title[0],abstract=text,authors=[Person(name=display_name(n)) for n in names],
            source_url=canonical_url(record.source_url),pdf_url=urljoin(final,pdfs[0] if pdfs else paper_link) if pdfs or paper_link else None,
            identifiers=identifiers,version='proceedings')


class MetadataAdapter:
    name = 'metadata'
    def inventory(self,url,fetch):
        raw, final=fetch(url,limit=5_000_000)
        records=parse_metadata(raw,final)
        from .network import validate_url
        for record in records:validate_url(record.source_url,resolve=False)
        if len({r.source_url for r in records})!=len(records):raise CollectionError('Each manifest paper requires its own distinct official source_url.')
        return Inventory(records,None,final)
    def hydrate(self,record,fetch):return record


class CSVAdapter:
    name = 'csv'
    def inventory(self,url,fetch):
        if neurips_homepage(url):raise CollectionError(HOMEPAGE_ERROR)
        raw, final=fetch(url,limit=10_000_000)
        return Inventory(parse_csv(raw),None,final)
    def hydrate(self,record,fetch):return record


def supports_neurips(url):
    u=urlsplit(url)
    return u.hostname in NEURIPS_HOSTS and u.path.rstrip('/')=='/paper_files/paper/2024'


def adapter_for(url, requested='auto') -> ConferenceAdapter:
    if requested == "linked-paper-list":
        from .intake import LinkedPaperList
        return LinkedPaperList()
    from .wacv2026 import supports as supports_wacv, WACV2026
    if supports_wacv(url):
        if requested not in ("auto", WACV2026.name):
            raise CollectionError("Use Auto or WACV 2026 for this conference link; it is not a CSV or JSON inventory file.")
        return WACV2026()
    from .neurips2026 import supports, NeurIPS2026
    from .proceedings import pmlr_volume, rss_volume, PMLR, RSS2025
    for predicate, adapter in ((pmlr_volume, PMLR), (rss_volume, RSS2025)):
        if predicate(url):
            if requested not in ('auto', adapter.name):
                raise CollectionError('Adapter does not match this official proceedings URL.')
            return adapter()
    if supports(url):
        if requested not in ('auto','neurips-2026-program'):raise CollectionError('Choose Auto or the NeurIPS 2026 program adapter for this listing; it is not a CSV file.')
        return NeurIPS2026()
    if supports_neurips(url):
        if requested not in ('auto','neurips-2024-main'):raise CollectionError('Adapter does not match the official source URL.')
        return NeurIPS2024()
    if requested=='metadata' or requested=='auto' and urlsplit(url).path.endswith('.json'):
        return MetadataAdapter()
    if requested=='csv' or requested=='auto' and urlsplit(url).path.endswith('.csv'):
        return CSVAdapter()
    raise CollectionError('Unsupported conference URL. Supported: WACV 2026, PMLR volumes, RSS 2025 proceedings, NeurIPS 2026 official paper listing, NeurIPS 2024 main proceedings, CSV inventory, or explicitly selected citation-metadata/JSON adapter. Arbitrary conference scraping is not supported.')


def parse_csv(raw):
    if raw.lstrip().lower().startswith((b'<!doctype html',b'<html')):
        raise CollectionError('Invalid CSV inventory: the source returned an HTML web page. Use a CSV inventory file URL or import CSV text; selecting CSV does not turn a conference website into an inventory.')
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        required={'title','authors','official_url','inventory_url','year','track'}
        if not required.issubset(reader.fieldnames or []):raise ValueError
        records=[]
        for row in reader:
            if len(records)>=10000:raise ValueError
            authors=json.loads(row['authors'])
            if not isinstance(authors,list) or not all(isinstance(a,str) and a.strip() for a in authors):raise ValueError
            for key in ('official_url','inventory_url'):
                from .network import validate_url
                validate_url(row[key],resolve=False)
            identifiers={key:row[key] for key in ('doi','arxiv') if row.get(key)}
            record=Metadata(title=row['title'],abstract=row.get('abstract',''),authors=[Person(name=a) for a in authors],source_url=row['official_url'],pdf_url=row.get('pdf_url') or None,identifiers=identifiers,inventory_url=row['inventory_url'],year=int(row['year']),track=row['track'])
            # Import metadata is kept separate from canonical paper fields.
            records.append(record)
        if not records:raise ValueError
        return records
    except (ValueError,TypeError,KeyError,UnicodeError):
        raise CollectionError('Invalid CSV inventory. Required columns: title, authors (JSON array), official_url, inventory_url, year, track.') from None
