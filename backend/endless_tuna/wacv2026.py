"""WACV 2026 official program: bounded public HTML/JSON, no JS or LAS."""
import json
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from pydantic import ValidationError
from .adapters import Inventory
from .collection import CollectionError, Metadata, Person
from .network import validate_url

HOST='wacv.thecvf.com'
HOME=f'https://{HOST}/Conferences/2026'
INDEX=f'https://{HOST}/virtual/2026/index.html'
LISTING=f'https://{HOST}/virtual/2026/papers.html'
FEED=f'https://{HOST}/static/virtual/data/wacv-2026-orals-posters.json'
GROUP='https://openreview.net/group?id=thecvf.com/WACV/2026/Conference'
PATHS={'/Conferences/2026','/virtual/2026/index.html','/virtual/2026/papers.html'}


def supports(url):
    u=urlsplit(url)
    return (u.scheme in ('http','https') and u.hostname==HOST and not u.username and not u.password
            and not u.query and not u.fragment and u.path.rstrip('/') in PATHS)


def listing_page(url,fetch):
    # Follow only the inspected same-edition official homepage -> virtual site
    # -> Papers chain. Arbitrary links and unrelated years are never crawled.
    for _ in range(3):
        raw,final=fetch(url,limit=3_000_000)
        if not supports(final):raise CollectionError('WACV source redirected outside the supported official 2026 pages.')
        if urlsplit(final).path.rstrip('/')=='/virtual/2026/papers.html':return raw,LISTING
        soup=BeautifulSoup(raw,'html.parser')
        targets=[urljoin(final,a['href']) for a in soup.select('a[href]')]
        target=next((x for x in targets if supports(x) and urlsplit(x).path==urlsplit(LISTING).path),None)
        if target is None and urlsplit(final).path.rstrip('/')=='/Conferences/2026':
            target=next((x for x in targets if supports(x) and urlsplit(x).path==urlsplit(INDEX).path),None)
        if target is None:raise CollectionError('WACV page no longer links to its recognized 2026 Papers page. Review the source structure.')
        url=target
    raise CollectionError('WACV source exceeded its bounded homepage-to-papers link chain.')


def parse_program(raw,page):
    try:
        data=json.loads(raw);rows=data['results']
        if (not isinstance(rows,list) or not rows or len(rows)>10000 or type(data.get('count')) is not int or data.get('count')!=len(rows)
                or data.get('next') or data.get('previous')):raise ValueError('Incomplete or paginated WACV program.')
        soup=BeautifulSoup(page,'html.parser');listed={}
        for a in soup.select('noscript a[href]'):
            u=urlsplit(urljoin(LISTING,a['href']))
            match=re.fullmatch(r'/virtual/2026/poster/([1-9][0-9]*)',u.path)
            if u.hostname==HOST and match and not u.query and not u.fragment:
                listed[int(match[1])]=a.get_text(' ',strip=True)
        if not listed:raise ValueError('Official WACV page has no recognized static paper listing.')
        found={};source_ids=set();orals=[]
        for row in rows:
            if row.get('visible') is False:continue
            if row.get('eventtype')=='Oral':orals.append(row);continue
            if row.get('eventtype')!='Poster':continue
            if row.get('sourceurl')!=GROUP:raise ValueError('WACV paper has an unrecognized track source; workshops must remain separate.')
            if not str(row.get('decision','')).casefold().startswith('accept'):raise ValueError('WACV paper has no accepted-paper decision.')
            event=row['id'];source_id=row['sourceid']
            if type(event) is not int or event<1 or type(source_id) is not int or source_id<1:raise ValueError('Invalid WACV paper ID.')
            if event in found or source_id in source_ids:raise ValueError('Duplicate WACV poster/source ID; refusing ambiguous membership.')
            source_ids.add(source_id)
            authors=[];warnings=[]
            for position,author in enumerate(row['authors'],1):
                name=author.get('fullname')
                if not isinstance(name,str) or not name.strip():
                    name='[Name missing in official source]';warnings.append(f'Author name missing at position {position}; needs review.')
                authors.append(Person(name=name))
            if not authors: warnings.append('No ordered authors supplied by the official program; needs review.')
            pdf=row.get('paper_pdf_url') or None
            if pdf:
                validate_url(pdf,resolve=False)
                if urlsplit(pdf).hostname==HOST and '/media/' in urlsplit(pdf).path:
                    raise ValueError('WACV media assets are slides/posters, not paper PDFs.')
            # Generic `url` is a project/code page, and eventmedia contains slides,
            # posters and video. Neither is promoted to a paper PDF.
            identifiers={'wacv-program-event':str(event),'wacv-source-id':str(source_id),'wacv-inventory-feed':FEED}
            found[event]=Metadata(title=row['name'],abstract=row.get('abstract') or '',authors=authors,
                source_url=f'https://{HOST}/virtual/2026/poster/{event}',pdf_url=pdf,
                identifiers=identifiers,year=2026,inventory_url=FEED,source_warnings=warnings)
        if set(found)!=set(listed):raise ValueError('WACV feed and static paper listing disagree; refusing a complete inventory claim.')
        for oral in orals:
            related=oral.get('related_events_ids',[])
            if not isinstance(related,list):raise ValueError('Invalid WACV oral relationships.')
            matches=[event for event in related if type(event) is int and event in found]
            if len(matches)!=1:raise ValueError('WACV oral lacks a unique official poster relationship; cannot establish paper coverage.')
            event=oral['id']
            if type(event) is not int or event<1:raise ValueError('Invalid WACV oral ID.')
            found[matches[0]].identifiers['wacv-oral-event']=str(event)
        return Inventory([found[event] for event in sorted(found)],len(found),LISTING)
    except (ValueError,KeyError,TypeError,AttributeError,ValidationError) as error:
        reason=str(error) if type(error) is ValueError else 'Invalid official program fields.'
        raise CollectionError('WACV 2026 inventory could not be validated. '+reason) from None


class WACV2026:
    name='wacv-2026-program'
    def inventory(self,url,fetch):
        page,final=listing_page(url,fetch)
        soup=BeautifulSoup(page,'html.parser')
        scripts='\n'.join(s.get_text() for s in soup.find_all('script') if not s.get('src'))
        paths=re.findall(r'''["'](/static/virtual/data/wacv-2026-orals-posters\.json)["']''',scripts)
        if not paths:raise CollectionError('WACV Papers page no longer references its recognized public program feed.')
        raw,resolved=fetch(FEED,limit=12_000_000)
        if resolved!=FEED:raise CollectionError('WACV program feed redirected; review source access before collection.')
        # Abstracts are inline in the inspected feed. The page references a
        # separate abstracts URL that currently returns 404; it is not needed.
        return parse_program(raw,page)
    def hydrate(self,record,fetch):return record
