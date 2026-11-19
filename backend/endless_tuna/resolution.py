"""Conservative PDF matching. arXiv and web search never establish membership."""
import hashlib
import json
import os
import re
import time
import unicodedata
from typing import Protocol
from urllib.parse import quote, unquote, urlencode, urlsplit
from xml.etree import ElementTree as ET
from dataclasses import dataclass, asdict
from collections import Counter
from . import db as storage
from .adapters import canonical_url
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
    doi: str = ''


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
            pdf_id = normalize_arxiv_id(url)
            result.append(Candidate(url.replace('http://','https://',1),title,authors,'arxiv:'+(pdf_id or arxiv_id),arxiv_id))
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


def normalize_arxiv_id(value):
    value = re.sub(r'^arxiv:\s*|^https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/', '', value.strip(), flags=re.I)
    value = value.removesuffix('.pdf')
    if re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v[1-9]\d*)?', value, re.ASCII | re.I):
        return value.lower()
    return ''


def doi_id(value):
    value = value.strip()
    if re.match(r'^https?://(?:dx\.)?doi\.org/', value, re.I):
        url = urlsplit(value)
        value = unquote(url.path.removeprefix('/'))
    value = re.sub(r'^doi:\s*', '', value, flags=re.I)
    if re.fullmatch(r'10\.\d{4,9}/[^\s\x00-\x1f\x7f]+', value):
        return value.lower()
    return ''


def cached_candidates(collection, key, load):
    with storage.connect(collection) as con:
        cached=con.execute('SELECT * FROM resolution_cache WHERE key=?',(key,)).fetchone()
    if cached and cached['created']>time.time()-86400:
        return [Candidate(**r) for r in json.loads(cached['result'])]
    candidates = load()
    with storage.connect(collection) as con:
        con.execute('INSERT INTO resolution_cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET result=excluded.result,created=excluded.created',(key,json.dumps([asdict(r) for r in candidates]),time.time()))
    return candidates


def fetch_arxiv(collection, params, fetch):
    # Cross-process reservation: arXiv requests are spaced by at least 3.1 seconds.
    with storage.connect(collection) as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT next_at FROM network_slots WHERE host='export.arxiv.org'").fetchone()
        slot=max(time.time(),row['next_at'] if row else 0)
        con.execute("INSERT INTO network_slots VALUES('export.arxiv.org',?) ON CONFLICT(host) DO UPDATE SET next_at=excluded.next_at",(slot+3.1,))
    time.sleep(max(0,slot-time.time()))
    raw,_=fetch('https://export.arxiv.org/api/query?'+urlencode(params),limit=2_000_000)
    return parse_arxiv(raw)


def arxiv_candidates(record,collection,fetch=fetch_bytes):
    query='ti:"'+record.title.replace('"',' ')+'"'
    key='arxiv:'+hashlib.sha256(query.encode()).hexdigest()
    params = {'search_query': query, 'start': 0, 'max_results': 5}
    return cached_candidates(collection, key, lambda: fetch_arxiv(collection, params, fetch))


def arxiv_matches_id(candidate, identifier):
    returned = normalize_arxiv_id(candidate.identifier)
    # A versioned request requires the same version. An unversioned request
    # permits the version returned by Atom, which is recorded on the download.
    same_id = returned == identifier or re.sub(r'v[1-9]\d*$', '', returned) == identifier
    return bool(returned) and same_id and urlsplit(candidate.url).path.startswith('/pdf/') and normalize_arxiv_id(candidate.url) == returned


def resolve_identifiers(record, collection, fetch, identifiers, rejected, errors):
    expected_authors = {author_key(person.name) for person in record.authors} - {''}
    for namespace, values in identifiers.items():
        if not values:
            continue
        identifier = next(iter(values))
        try:
            if namespace == 'arxiv':
                params = {'id_list': identifier, 'max_results': 5}
                candidates = cached_candidates(collection, 'arxiv:id:' + identifier,
                                               lambda: fetch_arxiv(collection, params, fetch))
            else:
                candidates = openalex_candidates(record, collection, fetch, doi=identifier)
        except CollectionError as error:
            errors.append(f'{namespace} lookup: {error}')
            continue
        candidates = [candidate for candidate in candidates if candidate.url not in rejected]
        if not candidates:
            continue
        matches = [candidate for candidate in candidates
                   if (arxiv_matches_id(candidate, identifier) if namespace == 'arxiv' else candidate.doi == identifier)]
        if len(matches) != len(candidates) or (namespace == 'arxiv' and len({c.identifier for c in matches}) > 1):
            return None, candidates, f'Conflicting {namespace} identifier evidence; confirm the paper and version before downloading.'
        actual_authors = {author_key(name) for name in matches[0].authors} - {''}
        if expected_authors and actual_authors and expected_authors.isdisjoint(actual_authors):
            return None, candidates, f'The {namespace} result has conflicting author evidence; confirm the paper before downloading.'
        return matches[0], [], None
    return None


def resolve(record,collection,fetch=fetch_bytes,*,wide=False,excluded_urls=()):
    if record.pdf_url and record.pdf_url not in excluded_urls:
        validate_url(record.pdf_url,resolve=False)
        return Candidate(record.pdf_url,record.title,[a.name for a in record.authors],record.version),[],None
    errors=[]
    source = canonical_url(record.source_url) if record.source_url else None
    normalize_ids = {'arxiv': normalize_arxiv_id, 'doi': doi_id}
    identifiers = {namespace: set() for namespace in normalize_ids}
    with storage.connect(collection) as con:
        rejected={r['url'] for r in con.execute("SELECT c.url FROM pdf_candidates c JOIN papers p ON p.id=c.paper_id WHERE p.canonical_url=? AND c.status='rejected'",(source,))}
        stored = con.execute("""SELECT i.namespace, i.value FROM paper_identifiers i
            JOIN papers p ON p.id=i.paper_id WHERE p.canonical_url=? AND i.namespace IN ('arxiv','doi')""", (source,)).fetchall()
    rejected.update(excluded_urls)
    for namespace, value in [*record.identifiers.items(), *stored]:
        if namespace in normalize_ids and (normalized := normalize_ids[namespace](value)):
            identifiers[namespace].add(normalized)
    arxiv_ids = identifiers['arxiv']
    # Prefer a single supplied version over an additional unversioned alias.
    arxiv_ids.difference_update({re.sub(r'v[1-9]\d*$', '', value) for value in arxiv_ids if re.search(r'v[1-9]\d*$', value)})
    stored_conflict = any(len(values) > 1 for values in identifiers.values())
    review_reason = None
    if stored_conflict:
        review_reason = 'Conflicting stored paper identifiers; confirm the paper and version before downloading.'
        errors.append(review_reason)
    else:
        match = resolve_identifiers(record, collection, fetch, identifiers, rejected, errors)
        if match is not None:
            return match
    try:
        candidates=arxiv_candidates(record,collection,fetch)
    except CollectionError as error:
        errors.append(str(error));candidates=[]
    candidates=[c for c in candidates if c.url not in rejected]
    strong=[c for c in candidates if strong_match(record,c)]
    if not stored_conflict and len(strong)==1:
        expected_id = next(iter(arxiv_ids), normalize_arxiv_id(strong[0].identifier))
        if arxiv_matches_id(strong[0], expected_id):
            return strong[0],[],None
        review_reason = ('The title match conflicts with the stored arXiv identifier; confirm the paper and version before downloading.'
                         if arxiv_ids else 'The arXiv entry and PDF link disagree; confirm the version before downloading.')
    if wide:
        try:
            oa=[c for c in openalex_candidates(record,collection,fetch) if c.url not in rejected]
            strong_oa=[c for c in oa if strong_match(record,c)]
            identities={c.identifier for c in strong_oa}
            if not stored_conflict and len(identities)==1 and not strong:
                if not identifiers['doi'] or not strong_oa[0].doi or strong_oa[0].doi in identifiers['doi']:
                    return strong_oa[0],[],None
                review_reason = 'The title match conflicts with the stored DOI; confirm the paper before downloading.'
            candidates+=oa
        except CollectionError as error:errors.append('Open-access lookup: '+str(error))
    if candidates:
        return None,candidates,review_reason or 'Ambiguous PDF candidates: exact title and complete author evidence did not identify one unique version.'
    if os.getenv('TUNA_SEARCH_ENDPOINT'):
        try:
            rows=[c for c in JSONSearchProvider(os.environ['TUNA_SEARCH_ENDPOINT']).search(record.title,[a.name for a in record.authors]) if c.url not in rejected]
            if rows:return None,rows,review_reason or 'General web-search candidates require analyst confirmation.'
        except CollectionError as error:errors.append(str(error))
    return None,[], '; '.join(errors) or 'No accessible PDF resolved. Web search '+('returned no candidates.' if os.getenv('TUNA_SEARCH_ENDPOINT') else 'is not configured; use manual search or supply a PDF URL.')


def openalex_candidates(record,collection,fetch=fetch_bytes,*,doi=None):
    """Public no-key OpenAlex lookup of OA copies; no paid/fulltext endpoints."""
    endpoint = 'https://api.openalex.org/works'
    if doi:
        key = 'openalex:doi:' + doi
        endpoint += '/doi:' + quote(doi, safe='/')
        params = {}
    else:
        key = 'openalex:title:' + hashlib.sha256(record.title.encode()).hexdigest()
        params = {'search': record.title, 'per_page': 5}
    params['select'] = 'id,doi,title,authorships,locations'
    return cached_candidates(collection, key, lambda: fetch_openalex(endpoint, params, fetch, singleton=bool(doi)))


def fetch_openalex(endpoint, params, fetch, *, singleton):
    raw,_=fetch(endpoint+'?'+urlencode(params),limit=2_000_000)
    try:
        data=json.loads(raw);rows=[data] if singleton else data['results']
        if not isinstance(rows,list):raise ValueError
        result=[]
        for row in rows[:5]:
            title=row['title'];people=row['authorships'];locations=row['locations']
            work_id = row['id']
            if not isinstance(work_id,str) or not re.fullmatch(r'https://openalex.org/W[0-9]+',work_id):raise ValueError
            if not isinstance(title,str) or not isinstance(people,list) or not isinstance(locations,list):raise ValueError
            names=[p.get('raw_author_name') or p.get('author',{}).get('display_name','') for p in people]
            if not all(isinstance(n,str) for n in names):raise ValueError
            doi = doi_id(row.get('doi') or '')
            for loc in locations[:100]:
                if loc.get('is_oa') is not True or not isinstance(loc.get('pdf_url'),str):continue
                url=loc['pdf_url']
                try:validate_url(url,resolve=False)
                except CollectionError:continue
                version = f"openalex:{work_id.rsplit('/', 1)[-1]}:{loc.get('version') or 'unknown'}"
                result.append(Candidate(url, title, names, version, work_id, doi))
        result=list({r.url:r for r in result}.values())[:30]
    except (ValueError,KeyError,TypeError,AttributeError):
        raise CollectionError('OpenAlex returned malformed open-access metadata.') from None
    return result
