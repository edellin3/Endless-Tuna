"""Link-first intake. Source content is data; no JavaScript, instructions or LAS."""
import json
import re
import time
import uuid
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from . import db as storage
from .adapters import adapter_for, canonical_url, Inventory
from .collection import CollectionError, Metadata, Person
from .network import fetch_bytes, validate_url
from .proceedings import event_year


def clean_link(value):
    value=value.strip()
    match=re.fullmatch(r'\[[^\]]*\]\((https?://[^\s]+)\)',value)
    if match:value=match[1]
    value=value.strip('<>')
    validate_url(value,resolve=False)
    return value


def listed_inventory(raw, final):
    """Recognize explicit paper containers only; navigation is never a paper list."""
    soup=BeautifulSoup(raw,'html.parser');records={}
    for container in soup.select('.paper, .paper-item, li.paper, article[data-paper]'):
        title=container.select_one('.title, .paper-title, h2, h3')
        if not title:continue
        title_link=title if title.name=='a' else title.find('a',href=True)
        link=title_link or next((a for a in container.select('a[href]') if a.get_text(strip=True).lower() in ('abstract','paper','details','abs')),None)
        if not link:continue
        url=urljoin(final,link.get('href',''))
        validate_url(url,resolve=False)
        if canonical_url(url)==canonical_url(final):continue
        text=title.get_text(' ',strip=True)
        if len(text)<4:continue
        direct_pdf=url if urlsplit(url).path.lower().endswith('.pdf') else None
        pdf=direct_pdf or next((urljoin(final,a['href']) for a in container.select('a[href]') if urlsplit(a['href']).path.lower().endswith('.pdf')),None)
        records[canonical_url(url)]=Metadata(title=text,source_url=url,pdf_url=pdf,detail_pending=not bool(direct_pdf),inventory_url=final)
    if not records:
        raise CollectionError('No readable paper list found on this page. Try its Accepted papers or Proceedings link, or import a CSV list. JavaScript-only and sign-in pages need a source-specific connector.')
    if len(records)>10000:raise CollectionError('Paper listing exceeds the 10,000-record intake limit; narrow the source to one edition.')
    return Inventory(list(records.values()),None,final)


class LinkedPaperList:
    name='linked-paper-list'
    def inventory(self,url,fetch):
        raw,final=fetch(url,limit=5_000_000)
        return listed_inventory(raw,final)
    def hydrate(self,record,fetch):
        raw,final=fetch(record.source_url,limit=2_000_000)
        if canonical_url(final)!=canonical_url(record.source_url):raise CollectionError('Paper page redirected away from its listed source.')
        soup=BeautifulSoup(raw,'html.parser')
        def values(name):return [m.get('content','').strip() for m in soup.find_all('meta',attrs={'name':name}) if m.get('content','').strip()]
        titles,names,pdfs=values('citation_title'),values('citation_author'),values('citation_pdf_url')
        abstract=soup.select_one('#abstract, .abstract')
        return record.model_copy(update=dict(title=titles[0] if titles else record.title,
            authors=[Person(name=n) for n in names],abstract=abstract.get_text(' ',strip=True) if abstract else record.abstract,
            pdf_url=urljoin(final,pdfs[0]) if pdfs else record.pdf_url,detail_pending=False))


class PreviewRequest(BaseModel):
    url:str=Field(min_length=1,max_length=2500)


class AutoCollectRequest(BaseModel):
    url:str=Field(min_length=1,max_length=2500)
    full_collection:bool=False
    paper_limit:int=Field(default=10,ge=1,le=100)
    preview_id:str|None=None
    name:str|None=Field(default=None,min_length=2,max_length=180)
    year:int|None=Field(default=None,ge=1900,le=2100)


class StartRequest(BaseModel):
    automatic:bool=False
    preview_id:str
    name:str=Field(min_length=2,max_length=180)
    year:int=Field(ge=1900,le=2100)
    full_collection:bool=False
    paper_limit:int=Field(default=10,ge=1,le=100)


def preview_link(url,fetch):
    url=clean_link(url)
    raw,final=fetch(url,limit=12_000_000)
    soup=BeautifulSoup(raw,'html.parser')
    def cached_fetch(target,**kwargs):return (raw,final) if target==url else fetch(target,**kwargs)
    try:adapter=adapter_for(final)
    except CollectionError:adapter=LinkedPaperList()
    try:inventory=adapter.inventory(final,lambda target,**kwargs:(raw,final) if target==final else cached_fetch(target,**kwargs))
    except CollectionError as error:
        links={}
        for a in soup.select('a[href]'):
            label=a.get_text(' ',strip=True);href=urljoin(final,a['href'])
            if canonical_url(href)==canonical_url(final):continue
            if not re.search(r'proceedings|accepted.{0,12}papers|paper.{0,6}list|^papers$',label,re.I):continue
            try:validate_url(href,resolve=False)
            except CollectionError:continue
            links[href]={'url':href,'label':label[:180]}
            if len(links)>=8:break
        # A conference home URL can identify an edition, but a suggested proceedings
        # volume is never counted as membership until that volume is inspected.
        host=urlsplit(final).hostname or ''
        match=re.fullmatch(r'(20\d{2})\.corl\.org',host)
        if match:
            from .discovery import DIRECTORY,parse_directory
            try:
                data,directory_final=fetch(DIRECTORY,limit=2_000_000)
                for row in parse_directory(data,directory_final):
                    if row['year']==int(match[1]) and re.search(r'\bCoRL\b',row['name'],re.I):
                        links[row['source_url']]={'url':row['source_url'],'label':row['name']+' · PMLR proceedings'}
            except CollectionError:pass
        return {'ok':False,'message':str(error),'suggestions':list(links.values())[:8],'source_url':final}
    if adapter.name=='neurips-2026-program':
        from .neurips2026 import LISTING as program_page
        inventory.url=program_page  # Keep the executable source page separate from feed provenance.
    heading=next((h.get_text(' ',strip=True) for h in soup.select('h1,h2') if re.match(r'Volume \d+:',h.get_text())),None)
    heading=heading or (soup.select_one('h1').get_text(' ',strip=True) if soup.select_one('h1') else '')
    heading=heading or (soup.title.get_text(' ',strip=True) if soup.title else urlsplit(final).hostname)
    year=next((r.year for r in inventory.records if r.year),None) or event_year(soup)
    if year is None:
        match=re.search(r'\b(19\d{2}|20\d{2})\b',heading+' '+final)
        year=int(match[0]) if match else None
    name=re.sub(r'^Volume \d+:\s*','',heading).split(',')[0].strip()[:180]
    if adapter.name=='wacv-2026-program':name,year='WACV',2026
    if adapter.name=='neurips-2024-main':name,year='NeurIPS',2024
    if adapter.name=='neurips-2026-program':name,year='NeurIPS',2026
    return {'ok':True,'inventory':inventory,'adapter':adapter.name,'name':name,'year':year,'source_url':inventory.url}


def register_intake(app,collection):
    @app.post('/api/intake/preview')
    def preview(body:PreviewRequest,c=Depends(collection)):
        try:result=preview_link(body.url,fetch_bytes)
        except CollectionError as error:
            return {'ok':False,'message':str(error),'suggestions':[]}
        except ValueError:
            return {'ok':False,'message':'Could not read this source. Use a public conference or proceedings URL without credentials. Check source access and try again.','suggestions':[]}
        if not result['ok']:return result
        inventory=result.pop('inventory');pid=str(uuid.uuid4());now=time.time()
        with storage.connect(c) as con:
            con.execute('DELETE FROM intake_previews WHERE created < ?',(now-86400,))
            con.execute('INSERT INTO intake_previews VALUES(?,?,?,?,?,?,?,?)',(pid,inventory.url,result['adapter'],result['name'],result['year'],json.dumps([r.model_dump() for r in inventory.records]),inventory.official_count,now))
        # Preview is not collection. Only summary and a bounded title preview reach the browser.
        return {**result,'preview_id':pid,'listed_count':len(inventory.records),'official_count':inventory.official_count,
                'titles':[r.title for r in inventory.records[:8]],'completeness':'official inventory' if inventory.official_count is not None else 'recognized list; completeness unverified',
                'message':'Review the conference and scope, then save its paper list. No PDFs downloaded.'}

    @app.post('/api/intake/start',status_code=201)
    def start(body:StartRequest,c=Depends(collection)):
        if c!='real':raise HTTPException(422,'Conference links belong in Real collection.')
        with storage.connect(c) as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT * FROM intake_previews WHERE id=? AND created>?',(body.preview_id,time.time()-86400)).fetchone()
            if not row:raise HTTPException(410,'This source check expired. Collect the conference link again.')
            if row['year'] and row['year']!=body.year:raise HTTPException(422,'Edition year must match the source. Check that the link points to the right edition.')
            existing=next((r for r in con.execute('SELECT id,source_url FROM editions WHERE year=?',(body.year,)) if canonical_url(r['source_url'])==canonical_url(row['source_url'])),None)
            if existing and not body.automatic:
                return {'id':existing['id'],'existing':True,'message':'This conference is already in Real collection.'}
            records=json.loads(row['records'])
            if existing:
                eid=existing['id']
                active=con.execute("SELECT id FROM jobs WHERE edition_id=? AND status IN ('queued','running') ORDER BY updated DESC LIMIT 1",(eid,)).fetchone()
                if active:return {'id':eid,'job_id':active['id'],'existing':True,'message':'Collection is already running.'}
                tid=con.execute('SELECT id FROM tracks WHERE edition_id=? ORDER BY id LIMIT 1',(eid,)).fetchone()['id']
                available={canonical_url(r['canonical_url']) for r in con.execute("SELECT DISTINCT p.canonical_url FROM papers p JOIN paper_editions m ON m.paper_id=p.id JOIN downloads d ON d.paper_id=p.id WHERE m.edition_id=? AND d.status='available' AND pdf_exists(d.path)=1 AND p.canonical_url IS NOT NULL",(eid,))}
                records=[r for r in records if canonical_url(r['source_url']) not in available]
                if not records:return {'id':eid,'existing':True,'message':'All listed papers already have PDFs.'}
            else:
                sid,eid,tid=[str(uuid.uuid4()) for _ in range(3)]
                name=body.name.strip()
                if len(name)<2:raise HTTPException(422,'Enter a conference name.')
                track='All published tracks' if row['adapter']=='neurips-2026-program' else ('Main Conference' if row['adapter']=='wacv-2026-program' else 'Published proceedings')
                con.execute('INSERT INTO series VALUES(?,?)',(sid,name))
                con.execute('INSERT INTO editions(id,series_id,year,description,status,source_url,adapter) VALUES(?,?,?,?,?,?,?)',(eid,sid,body.year,'Collecting papers and free PDFs' if body.automatic else 'Paper list collection','queued',row['source_url'],row['adapter']))
                con.execute('INSERT INTO tracks VALUES(?,?,?)',(tid,eid,track))
                con.execute('INSERT INTO sources VALUES(?,?,?,?)',(str(uuid.uuid4()),eid,row['source_url'],'Conference paper listing'))
            if not body.full_collection:records=records[:body.paper_limit]
            jid=str(uuid.uuid4());kind='automatic' if body.automatic else 'inventory'
            con.execute("INSERT INTO jobs(id,edition_id,status,message,updated,paper_limit,track_id,kind) VALUES(?,?,'queued',?,?,?,?,?)",(jid,eid,'Collecting papers' if body.automatic else 'Saving paper list',time.time(),None if body.full_collection else body.paper_limit,tid,kind))
            con.execute('INSERT INTO job_payloads VALUES(?,?)',(jid,json.dumps({'records':records,'official_count':row['official_count'],'url':row['source_url']})))
        return {'id':eid,'job_id':jid,'message':'Collection started. Titles and free PDFs will appear automatically.' if body.automatic else 'Paper list queued.'}

    @app.post('/api/intake/collect')
    def collect(body:AutoCollectRequest,c=Depends(collection)):
        if c!='real':raise HTTPException(422,'Conference links belong in Real collection.')
        if body.preview_id:
            with storage.connect(c) as con:
                row=con.execute('SELECT * FROM intake_previews WHERE id=? AND created>?',(body.preview_id,time.time()-86400)).fetchone()
                if not row:raise HTTPException(410,'This source check expired. Collect the conference link again.')
                result={'ok':True,'preview_id':row['id'],'name':row['name'],'year':row['year']}
        else:
            result=preview(PreviewRequest(url=body.url),c)
        if not result['ok']:return result
        name=body.name or result['name'];year=body.year or result['year']
        if not year or not name or len(name.strip())<2:
            return {'ok':False,'needs_details':True,'preview_id':result['preview_id'],'name':name,'year':year,'message':'We found the papers. Confirm the conference details so we can file them correctly.'}
        value=start(StartRequest(preview_id=result['preview_id'],name=name,year=year,full_collection=body.full_collection,paper_limit=body.paper_limit,automatic=True),c)
        return {'ok':True,**value}
