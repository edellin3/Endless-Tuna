"""Conservative PDF matching. arXiv and web search never establish membership."""
import hashlib
import json
import os
import re
import time
import unicodedata
from typing import Protocol
from urllib.parse import urlencode, urlsplit, quote
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


def resolve(record,collection,fetch=fetch_bytes):
    if record.pdf_url:
        validate_url(record.pdf_url,resolve=False)
        return Candidate(record.pdf_url,record.title,[a.name for a in record.authors],record.version),[],None
    errors=[]
    try:
        candidates=arxiv_candidates(record,collection,fetch)
    except CollectionError as error:
        errors.append(str(error));candidates=[]
    with storage.connect(collection) as con:
        rejected={r['url'] for r in con.execute("SELECT c.url FROM pdf_candidates c JOIN papers p ON p.id=c.paper_id WHERE p.canonical_url=? AND c.status='rejected'",(record.source_url,))}
    candidates=[c for c in candidates if c.url not in rejected]
    strong=[c for c in candidates if strong_match(record,c)]
    if len(strong)==1:
        return strong[0],[],None
    if candidates:
        return None,candidates,'Ambiguous arXiv candidates: exact title and complete author evidence did not identify one unique version.'
    if os.getenv('TUNA_SEARCH_ENDPOINT'):
        try:
            rows=[c for c in JSONSearchProvider(os.environ['TUNA_SEARCH_ENDPOINT']).search(record.title,[a.name for a in record.authors]) if c.url not in rejected]
            if rows:return None,rows,'General web-search candidates require analyst confirmation.'
        except CollectionError as error:errors.append(str(error))
    return None,[], '; '.join(errors) or 'No accessible PDF resolved. Web search '+('returned no candidates.' if os.getenv('TUNA_SEARCH_ENDPOINT') else 'is not configured; use manual search or supply a PDF URL.')
