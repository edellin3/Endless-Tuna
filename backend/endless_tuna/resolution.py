"""Conservative PDF matching. arXiv and web search never establish membership."""
import hashlib
import json
import os
import re
import time
import unicodedata
from typing import Protocol
from urllib.parse import urlencode, urlsplit, quote, urljoin
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET
from dataclasses import dataclass, asdict
from collections import Counter
from . import db as storage
from .collection import CollectionError
from .network import fetch_bytes, validate_url


def normalize(text):
    return ' '.join(re.findall(r'\w+',''.join(c for c in unicodedata.normalize('NFKD',text) if not unicodedata.combining(c)).lower()))


def author_key(name):
    parts=name.split(',',1)
    if len(parts)==2:name=parts[1]+' '+parts[0]
    return normalize(name)


@dataclass
class Candidate:
    url: str
    title: str
    authors: list[str]
    version: str
    identifier: str = ''


def strong_match(record,candidate):
    expected=Counter(author_key(a.name) for a in record.authors)
    actual=Counter(author_key(a) for a in candidate.authors)
    # Exact normalized title AND the complete author-name set. No fuzzy acceptance.
    return bool(expected) and '' not in expected and bool(normalize(record.title)) and normalize(record.title)==normalize(candidate.title) and expected==actual


def parse_arxiv(raw):
    try:
        root=ET.fromstring(raw)
        ns={'a':'http://www.w3.org/2005/Atom'}
        if root.tag!='{http://www.w3.org/2005/Atom}feed':raise ValueError
        result=[]
        for entry in root.findall('a:entry',ns):
            identifier=entry.findtext('a:id','',ns)
            if '/api/errors' in identifier:raise ValueError
            title=' '.join(entry.findtext('a:title','',ns).split())
            authors=[a.findtext('a:name','',ns) for a in entry.findall('a:author',ns)]
            url=next((l.get('href') for l in entry.findall('a:link',ns) if l.get('title')=='pdf' or l.get('type')=='application/pdf'),None)
            if not url:continue
            if urlsplit(url).hostname not in ('arxiv.org','export.arxiv.org'):continue
            arxiv_id=identifier.split('/abs/')[-1]
            result.append(Candidate(url.replace('http://','https://',1),title,authors,'arxiv:'+arxiv_id,arxiv_id))
        return result
    except (ET.ParseError,ValueError):
        raise CollectionError('arXiv returned a malformed/error Atom response.') from None


class SearchProvider(Protocol):
    def search(self,title: str,authors: list[str]) -> list[Candidate]: ...


class JSONSearchProvider:
    """Public JSON GET endpoint: ?q=..., response {results:[{url,title,authors}]}.

    No scraping and no credentials in URLs. Untrusted results always need analyst review.
    """
    def __init__(self,endpoint):self.endpoint=endpoint
    def search(self,title,authors):
        validate_url(self.endpoint,resolve=False)
        if urlsplit(self.endpoint).query:raise CollectionError('Search provider endpoint must not contain a query.')
        raw,_=fetch_bytes(self.endpoint+'?'+urlencode({'q':title+' '+' '.join(authors[:2])}),limit=1_000_000)
        try:
            rows=json.loads(raw)['results']
            if not isinstance(rows,list):raise ValueError
            result=[]
            for row in rows[:10]:
                if not isinstance(row,dict) or not isinstance(row.get('title'),str):raise ValueError
                validate_url(row['url'],resolve=False)
                names=row.get('authors',[])
                if not isinstance(names,list) or not all(isinstance(a,str) for a in names):raise ValueError
                result.append(Candidate(row['url'],row['title'],names,'web-candidate'))
            return result
        except (ValueError,KeyError,TypeError):
            raise CollectionError('Web-search provider returned malformed results.') from None


def search_status():
    return {'configured':bool(os.getenv('TUNA_SEARCH_ENDPOINT')),'provider':'public-json' if os.getenv('TUNA_SEARCH_ENDPOINT') else 'not configured'}


def manual_search(title):
    return 'https://www.google.com/search?'+urlencode({'q':'"'+title+'" PDF'})


def arxiv_candidates(record,collection,fetch=fetch_bytes):
    query='ti:"'+record.title.replace('"',' ')+'"'
    key='arxiv:'+hashlib.sha256(query.encode()).hexdigest()
    with storage.connect(collection) as con:
        cached=con.execute('SELECT * FROM resolution_cache WHERE key=?',(key,)).fetchone()
    if cached and cached['created']>time.time()-86400:
        return [Candidate(**r) for r in json.loads(cached['result'])]
    # Cross-process reservation: arXiv requests are spaced by at least 3.1 seconds.
    with storage.connect(collection) as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT next_at FROM network_slots WHERE host='export.arxiv.org'").fetchone()
        slot=max(time.time(),row['next_at'] if row else 0)
        con.execute("INSERT INTO network_slots VALUES('export.arxiv.org',?) ON CONFLICT(host) DO UPDATE SET next_at=excluded.next_at",(slot+3.1,))
    time.sleep(max(0,slot-time.time()))
    raw,_=fetch('https://export.arxiv.org/api/query?'+urlencode({'search_query':query,'start':0,'max_results':5}),limit=2_000_000)
    candidates=parse_arxiv(raw)
    with storage.connect(collection) as con:
        con.execute('INSERT INTO resolution_cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET result=excluded.result,created=excluded.created',(key,json.dumps([asdict(r) for r in candidates]),time.time()))
    return candidates


def resolve(record,collection,fetch=fetch_bytes,*,wide=False,excluded_urls=()):
    if record.pdf_url and record.pdf_url not in excluded_urls:
        validate_url(record.pdf_url,resolve=False)
        return Candidate(record.pdf_url,record.title,[a.name for a in record.authors],record.version),[],None
    errors=[]
    with storage.connect(collection) as con:
        rejected={r['url'] for r in con.execute("SELECT c.url FROM pdf_candidates c JOIN papers p ON p.id=c.paper_id WHERE p.canonical_url=? AND c.status='rejected'",(record.source_url,))}
    rejected.update(excluded_urls)
    cvf_review=[]
    if wide and record.year==2026 and urlsplit(record.source_url).hostname=='wacv.thecvf.com':
        try:
            cvf=[c for c in cvf_candidates(record,collection,fetch) if c.url not in rejected]
            strong_cvf=[c for c in cvf if strong_match(record,c)]
            if len(strong_cvf)==1:return strong_cvf[0],[],None
            cvf_review=cvf
        except CollectionError as error:errors.append('CVF lookup: '+str(error))
    try:
        candidates=arxiv_candidates(record,collection,fetch)
    except CollectionError as error:
        errors.append(str(error));candidates=[]
    candidates=cvf_review+candidates
    candidates=[c for c in candidates if c.url not in rejected]
    strong=[c for c in candidates if strong_match(record,c)]
    if len(strong)==1:
        return strong[0],[],None
    if wide:
        try:
            oa=[c for c in openalex_candidates(record,collection,fetch) if c.url not in rejected]
            strong_oa=[c for c in oa if strong_match(record,c)]
            identities={c.identifier for c in strong_oa}
            if len(identities)==1 and not strong:
                return strong_oa[0],[],None
            candidates+=oa
        except CollectionError as error:errors.append('Open-access lookup: '+str(error))
    if candidates:
        return None,candidates,'Ambiguous PDF candidates: exact title and complete author evidence did not identify one unique version.'
    if os.getenv('TUNA_SEARCH_ENDPOINT'):
        try:
            rows=[c for c in JSONSearchProvider(os.environ['TUNA_SEARCH_ENDPOINT']).search(record.title,[a.name for a in record.authors]) if c.url not in rejected]
            if rows:return None,rows,'General web-search candidates require analyst confirmation.'
        except CollectionError as error:errors.append(str(error))
    return None,[], '; '.join(errors) or 'No accessible PDF resolved. Web search '+('returned no candidates.' if os.getenv('TUNA_SEARCH_ENDPOINT') else 'is not configured; use manual search or supply a PDF URL.')


def cvf_candidates(record,collection,fetch=fetch_bytes):
    """Inspected WACV 2026 main-track catalog; PDF discovery, never membership."""
    key='cvf:WACV2026:v1';source='https://openaccess.thecvf.com/WACV2026?day=all'
    with storage.connect(collection) as con:cached=con.execute('SELECT * FROM resolution_cache WHERE key=?',(key,)).fetchone()
    if cached and cached['created']>time.time()-86400:
        candidates=[Candidate(**r) for r in json.loads(cached['result'])]
    else:
        raw,final=fetch(source,limit=4_000_000)
        if urlsplit(final).hostname!='openaccess.thecvf.com' or urlsplit(final).path!='/WACV2026':raise CollectionError('CVF redirected outside the inspected main-track catalog.')
        soup=BeautifulSoup(raw,'html.parser');candidates=[]
        for entry in soup.select('dt.ptitle'):
            title=entry.select_one('a[href]');people=entry.find_next_sibling('dd')
            links=people.find_next_sibling('dd') if people else None
            if not title or people is None or links is None:raise CollectionError('CVF catalog layout changed; missing title, authors or PDF links.')
            names=[a.get('value','').strip() for a in people.select('input[name=query_author]')]
            urls=[urljoin(source,a['href']) for a in links.select('a[href]') if a.get_text(strip=True)=='pdf']
            if not names or not all(names) or len(urls)!=1:raise CollectionError('CVF catalog has incomplete authors or ambiguous PDF links.')
            pdf=urls[0];u=urlsplit(pdf)
            if u.hostname!='openaccess.thecvf.com' or not u.path.startswith('/content/WACV2026/papers/') or not u.path.endswith('_WACV_2026_paper.pdf'):raise CollectionError('CVF PDF link is outside the inspected main-track paper path.')
            validate_url(pdf,resolve=False)
            candidates.append(Candidate(pdf,title.get_text(' ',strip=True),names,'cvf:WACV2026',urljoin(source,title['href'])))
        if not candidates or len(candidates)>10000:raise CollectionError('CVF returned an empty or oversized paper catalog.')
        with storage.connect(collection) as con:con.execute('INSERT INTO resolution_cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET result=excluded.result,created=excluded.created',(key,json.dumps([asdict(c) for c in candidates]),time.time()))
    return [c for c in candidates if normalize(c.title)==normalize(record.title)]


def openalex_candidates(record,collection,fetch=fetch_bytes):
    """Public no-key OpenAlex lookup of OA copies; no paid/fulltext endpoints."""
    key='openalex:'+hashlib.sha256(record.title.encode()).hexdigest()
    with storage.connect(collection) as con:
        cached=con.execute('SELECT * FROM resolution_cache WHERE key=?',(key,)).fetchone()
    if cached and cached['created']>time.time()-86400:return [Candidate(**r) for r in json.loads(cached['result'])]
    params={'search':record.title,'per_page':5,'select':'id,title,authorships,locations'}
    raw,_=fetch('https://api.openalex.org/works?'+urlencode(params),limit=2_000_000)
    try:
        data=json.loads(raw);rows=data['results']
        if not isinstance(rows,list):raise ValueError
        result=[]
        for row in rows[:5]:
            title=row['title'];people=row['authorships'];locations=row['locations']
            if not isinstance(row.get('id'),str) or not re.fullmatch(r'https://openalex.org/W[0-9]+',row['id']):raise ValueError
            if not isinstance(title,str) or not isinstance(people,list) or not isinstance(locations,list):raise ValueError
            names=[p.get('raw_author_name') or p.get('author',{}).get('display_name','') for p in people]
            if not all(isinstance(n,str) for n in names):raise ValueError
            for loc in locations[:100]:
                if loc.get('is_oa') is not True or not isinstance(loc.get('pdf_url'),str):continue
                url=loc['pdf_url']
                try:validate_url(url,resolve=False)
                except CollectionError:continue
                result.append(Candidate(url,title,names,'openalex:'+str(row.get('id','')).rsplit('/',1)[-1]+':'+str(loc.get('version') or 'unknown'),str(row.get('id',''))))
        result=list({r.url:r for r in result}.values())[:30]
    except (ValueError,KeyError,TypeError,AttributeError):
        raise CollectionError('OpenAlex returned malformed open-access metadata.') from None
    with storage.connect(collection) as con:
        con.execute('INSERT INTO resolution_cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET result=excluded.result,created=excluded.created',(key,json.dumps([asdict(r) for r in result]),time.time()))
    return result
