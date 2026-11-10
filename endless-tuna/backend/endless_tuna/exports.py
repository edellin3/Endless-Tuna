"""Relational Excel and bounded disk-backed ZIP exports. No LAS or network calls."""
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
from typing import Literal
import uuid
import zipfile
from fastapi import Depends,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font,PatternFill
from . import db as storage
from .search import paper_rows,conference_results
from .pipeline_store import coverage
from .network import number
from .collection import CollectionError


class Filters(BaseModel):
    model_config=ConfigDict(extra='forbid')
    q:str=Field(default='',max_length=500)
    year:int|None=None
    conference:str|None=None
    organization:str|None=None
    country:str|None=None
    pdf:Literal['yes','no','']|None=None
    review:Literal['confirmed','uncertain','rejected','']|None=None


class ExportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scope:Literal['all','conference','filtered']='filtered'
    edition_id:str|None=None
    filters:Filters=Field(default_factory=Filters)
    max_bundle_mb:int|None=Field(default=None,ge=1,le=500)


def safe_cell(value):
    if value is None:return ''
    if isinstance(value,(int,float,bool)):return value
    if not isinstance(value,str):value=json.dumps(value,ensure_ascii=False)
    value=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]','�',value)
    if len(value)>32000:value=value[:31950]+' [TRUNCATED: see original source]'
    if value.lstrip(' \t\r\n\ufeff').startswith(('=','+','-','@')):value="'"+value
    return value


def iso(value):return datetime.fromtimestamp(value,timezone.utc).isoformat() if value else ''


def select(con,body):
    if body.scope=='conference' and not body.edition_id:raise ValueError('Choose a conference for conference-scoped exports.')
    if body.edition_id and not con.execute('SELECT 1 FROM editions WHERE id=?',(body.edition_id,)).fetchone():raise ValueError('Conference not found.')
    filters=body.filters.model_dump() if body.scope=='filtered' else {}
    edition=body.edition_id if body.scope!='all' else None
    rows=paper_rows(con,edition=edition,all_memberships=True,include_evidence=False,**filters)
    ids=list(dict.fromkeys(r['id'] for r in rows))
    max_papers=int(number('TUNA_EXPORT_MAX_PAPERS',10000,1,100000))
    if len(ids)>max_papers:raise ValueError('Export exceeds TUNA_EXPORT_MAX_PAPERS. Narrow the selected filters.')
    con.execute('CREATE TEMP TABLE selected_papers(id TEXT PRIMARY KEY)')
    con.executemany('INSERT INTO selected_papers VALUES(?)',((pid,) for pid in ids))
    groups=conference_results(con,edition=edition,**filters)
    return ids,groups,{'collection_scope':body.scope,'edition_id':edition,'filters':filters,'all_result_pages':True,'selected_papers':len(ids),'created_utc':iso(time.time())}


def root(c):
    folder=storage.DATA/f'{c}-exports';folder.mkdir(parents=True,exist_ok=True);return folder


def cleanup(con,c):
    for row in con.execute('SELECT id,kind FROM export_files WHERE expires<?',(time.time(),)).fetchall():
        (root(c)/(row['id']+'.'+row['kind'])).unlink(missing_ok=True)
        con.execute('DELETE FROM export_files WHERE id=?',(row['id'],))


def publish(con,c,path,kind,count,name):
    ttl=number('TUNA_EXPORT_TTL_HOURS',24,1,168)
    with storage.connect(c) as registry:
        registry.execute('INSERT INTO export_files VALUES(?,?,?,?,?,?,?)',(path.stem,name,kind,path.stat().st_size,count,time.time(),time.time()+ttl*3600))
    return {'id':path.stem,'name':name,'size_bytes':path.stat().st_size,'included_papers':count,'download_url':f'/api/exports/files/{path.stem}?collection={c}','expires_in_hours':ttl}


def selected_authors(con):
    return 'SELECT DISTINCT author_id FROM authorship WHERE paper_id IN (SELECT id FROM selected_papers)'


def workbook(con,c,body):
    ids,groups,scope=select(con,body)
    wb=Workbook(write_only=True)
    def sheet(name,headers,rows):
        ws=wb.create_sheet(name);ws.freeze_panes='A2'
        cells=[]
        for header in headers:
            cell=WriteOnlyCell(ws,value=header);cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='2459D3');cells.append(cell)
        ws.append(cells)
        count=1
        for row in rows:
            ws.append([safe_cell(v) for v in row]);count+=1
        from openpyxl.utils import get_column_letter
        ws.auto_filter.ref=f'A1:{get_column_letter(len(headers))}{count}'
    # Include related editions as context so membership IDs never point at omitted conferences.
    con.execute('CREATE TEMP TABLE selected_editions(id TEXT PRIMARY KEY)')
    con.execute('INSERT INTO selected_editions SELECT DISTINCT edition_id FROM paper_editions WHERE paper_id IN (SELECT id FROM selected_papers)')
    matching_editions={r['id'] for r in groups}
    con.executemany('INSERT OR IGNORE INTO selected_editions VALUES(?)',((eid,) for eid in matching_editions))
    if body.scope=='conference':con.execute('INSERT OR IGNORE INTO selected_editions VALUES(?)',(body.edition_id,))
    def conferences():
        for row in con.execute('SELECT e.*,s.name FROM editions e JOIN series s ON s.id=e.series_id WHERE e.id IN (SELECT id FROM selected_editions) ORDER BY e.year DESC,s.name COLLATE NOCASE,e.id'):
            cov=coverage(con,row['id'])
            yield [c,body.scope,row['id'],row['series_id'],row['name'],row['year'],row['description'],row['source_url'],row['official_count'],cov['inventory_records'],bool(row['inventory_complete']),cov['pdfs'],cov['fulltext'],iso(row['inventory_retrieved']),row['id'] in matching_editions]
    sheet('Conferences',['collection','export_scope','edition_id','series_id','name','year','description','source_url','official_inventory_count','collected_records','full_inventory_complete','pdfs_available','papers_with_fulltext','inventory_retrieved_utc','matches_scope'],conferences())
    def papers():
        for row in con.execute('SELECT p.* FROM papers p JOIN selected_papers x ON x.id=p.id ORDER BY p.title COLLATE NOCASE,p.id'):
            identifiers=[dict(r) for r in con.execute('SELECT namespace,value FROM paper_identifiers WHERE paper_id=? ORDER BY namespace,value',(row['id'],))]
            for m in con.execute('SELECT m.*,e.year,t.name track FROM paper_editions m JOIN editions e ON e.id=m.edition_id JOIN tracks t ON t.id=m.track_id WHERE m.paper_id=? ORDER BY m.edition_id,m.track_id',(row['id'],)):
                yield [c,body.scope,row['id'],m['edition_id'],m['track_id'],m['track'],m['year'],row['title'],row['abstract'],row['review_status'],row['canonical_url'],m['official_url'],m['inventory_url'],iso(m['retrieved']),identifiers,bool(con.execute("SELECT 1 FROM downloads WHERE paper_id=? AND status='available' AND pdf_exists(path)",(row['id'],)).fetchone()),bool(con.execute('SELECT 1 FROM fulltext_fts WHERE paper_id=? LIMIT 1',(row['id'],)).fetchone())]
    sheet('Papers',['collection','export_scope','paper_id','edition_id','track_id','track','paper_year','title','abstract','review_status','canonical_url','official_paper_url','inventory_evidence_url','membership_retrieved_utc','external_identifiers','pdf_available','fulltext_indexed'],papers())
    def authors():
        for r in con.execute('SELECT au.*,a.name FROM authorship au JOIN authors a ON a.id=au.author_id JOIN selected_papers x ON x.id=au.paper_id ORDER BY au.paper_id,au.position'):
            orcids=[v[0] for v in con.execute("SELECT value FROM author_assertions WHERE author_id=? AND kind='orcid' AND status='verified'",(r['author_id'],))]
            yield [r['paper_id'],r['author_id'],r['position'],r['name'],orcids]
    sheet('Paper Authors',['paper_id','author_id','author_position','original_author_name','verified_orcids'],authors())
    def affiliations():
        for r in con.execute(f"SELECT a.*,o.name organization FROM author_assertions a LEFT JOIN organizations o ON o.id=a.organization_id WHERE (a.paper_id IN (SELECT id FROM selected_papers) OR a.paper_id IS NULL AND a.author_id IN ({selected_authors(con)})) AND a.kind IN ('affiliation','current_affiliation','organization_country','organization_city') ORDER BY a.paper_id,a.author_id,a.created,a.id"):
            yield [r['id'],r['paper_id'],r['author_id'],r['author_name'],r['paper_year'],r['time_context'],r['kind'],r['organization_id'],r['organization'],r['value'],r['status'],r['source_url'],r['excerpt'],r['page'],r['method'],iso(r['created']),r['supersedes_id']]
        for r in con.execute("SELECT f.*,o.name,a.name author_name,e.year FROM affiliations f JOIN organizations o ON o.id=f.organization_id JOIN authors a ON a.id=f.author_id JOIN papers p ON p.id=f.paper_id JOIN editions e ON e.id=p.edition_id WHERE f.paper_id IN (SELECT id FROM selected_papers) AND NOT EXISTS(SELECT 1 FROM author_assertions v WHERE v.paper_id=f.paper_id AND v.author_id=f.author_id AND v.kind='affiliation') ORDER BY f.paper_id,f.author_id,f.organization_id"):
            yield ['legacy:'+r['paper_id']+':'+r['author_id']+':'+r['organization_id'],r['paper_id'],r['author_id'],r['author_name'],r['year'],'paper','affiliation',r['organization_id'],r['name'],r['name'],'needs_evidence','','',None,'legacy_metadata','',None]
    sheet('Affiliations',['assertion_id','paper_id','author_id','original_author_name','paper_year','time_context','kind','organization_id','organization','value','verification_status','evidence_url','excerpt','page','extraction_method','extracted_utc','supersedes_id'],affiliations())
    def sources():
        for r in con.execute('SELECT ev.*,s.url,s.label FROM evidence ev JOIN sources s ON s.id=ev.source_id WHERE ev.paper_id IN (SELECT id FROM selected_papers) ORDER BY ev.paper_id,ev.id'):
            yield [r['source_id'],r['id'],r['paper_id'],None,'membership',r['url'],r['quote'],None,'inventory_metadata','unverified','',None,None]
        for r in con.execute(f'SELECT * FROM author_assertions WHERE paper_id IN (SELECT id FROM selected_papers) OR paper_id IS NULL AND author_id IN ({selected_authors(con)}) ORDER BY created,id'):
            yield [r['id'],r['id'],r['paper_id'],r['author_id'],r['kind'],r['source_url'],r['excerpt'],r['page'],r['method'],r['status'],iso(r['created']),None,None]
        for r in con.execute('SELECT * FROM downloads WHERE paper_id IN (SELECT id FROM selected_papers) ORDER BY paper_id,id'):
            yield [r['id'],r['id'],r['paper_id'],None,'pdf:'+r['version'],r['source_url'],'',None,r['parse_status'],r['status'],iso(r['retrieved']),r['sha256'],r['size_bytes']]
    sheet('Sources',['source_id','assertion_or_evidence_id','paper_id','author_id','kind','source_url','excerpt','page','method','verification_status','retrieved_or_extracted_utc','sha256','size_bytes'],sources())
    def missing():
        for r in con.execute("SELECT p.id,p.title FROM papers p JOIN selected_papers x ON x.id=p.id WHERE NOT EXISTS(SELECT 1 FROM downloads d WHERE d.paper_id=p.id AND d.status='available' AND pdf_exists(d.path)) ORDER BY p.id"):
            errors=[d[0] for d in con.execute('SELECT error FROM downloads WHERE paper_id=? AND error IS NOT NULL',(r['id'],))]
            yield [r['id'],r['title'],'; '.join(errors) or 'No accessible local PDF; source unresolved, download missing, or stored file unavailable.']
    sheet('Missing PDFs',['paper_id','title','reason'],missing())
    def review_queue():
        for r in con.execute("SELECT * FROM papers WHERE id IN (SELECT id FROM selected_papers) AND review_status='uncertain' ORDER BY id"):
            yield ['paper',r['id'],r['id'],None,'uncertain',r['title'],r['canonical_url'],'',None,None]
        for r in con.execute(f"SELECT * FROM author_assertions WHERE (paper_id IN (SELECT id FROM selected_papers) OR paper_id IS NULL AND author_id IN ({selected_authors(con)})) AND status IN ('extracted','needs_review') ORDER BY id"):
            yield ['author_assertion',r['id'],r['paper_id'],r['author_id'],r['status'],r['kind']+': '+r['value'],r['source_url'],r['excerpt'],r['page'],r['method']]
        for r in con.execute("SELECT * FROM pdf_candidates WHERE paper_id IN (SELECT id FROM selected_papers) AND status='pending' ORDER BY id"):
            yield ['pdf_candidate',r['id'],r['paper_id'],None,r['status'],r['reason'],r['url'],r['title'],None,r['version']]
        for r in con.execute(f"SELECT * FROM identity_proposals WHERE status='pending' AND (left_author_id IN ({selected_authors(con)}) OR right_author_id IN ({selected_authors(con)})) ORDER BY id"):
            yield ['identity_match',r['id'],None,r['left_author_id'],r['status'],r['reason']+' Other original author: '+r['right_author_id'],r['source_url'],r['excerpt'],None,'identity_evidence']
        for r in con.execute("SELECT jp.* FROM job_papers jp WHERE jp.paper_id IN (SELECT id FROM selected_papers) AND status IN ('failed','missing','review') ORDER BY jp.job_id,jp.paper_id"):
            yield ['paper_job',r['job_id']+':'+r['paper_id'],r['paper_id'],None,r['status'],r['error'],'','',None,r['stage']]
    sheet('Review Queue',['record_type','record_id','paper_id','author_id','status','summary','evidence_url','excerpt','page','method'],review_queue())
    path=root(c)/(uuid.uuid4().hex+'.xlsx')
    try:wb.save(path)
    except Exception:path.unlink(missing_ok=True);raise
    result=publish(con,c,path,'xlsx',len(ids),f'endless-tuna-{c}-{body.scope}.xlsx')
    return {**result,'scope':scope,'sheets':wb.sheetnames}


def safe_pdf_path(c,value):
    try:
        folder=(storage.DATA/f'{c}-pdfs').resolve();path=(folder/(value or '')).resolve()
        return path if value and path.is_relative_to(folder) and path.is_file() else None
    except (OSError,ValueError):return None


def pdf_items(con,c,ids):
    items=[]
    for pid in ids:
        paper=con.execute('SELECT title,review_status FROM papers WHERE id=?',(pid,)).fetchone()
        item={'paper_id':pid,'title':paper['title'],'paper_review_status':paper['review_status'],'archive_name':None,'status':'missing','reason':'No accessible local PDF.','size_bytes':0}
        for row in con.execute("SELECT * FROM downloads WHERE paper_id=? AND status='available' ORDER BY (version='proceedings') DESC,retrieved DESC,id",(pid,)):
            path=safe_pdf_path(c,row['path'])
            if not path:item['reason']='Recorded PDF file is missing or outside the storage boundary.';continue
            digest=hashlib.sha256()
            try:
                with path.open('rb') as stream:
                    if not stream.read(8).lstrip().startswith(b'%PDF-'):item['reason']='Stored file is not PDF content.';continue
                    stream.seek(0)
                    for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
                if row['sha256'] and digest.hexdigest()!=row['sha256']:item['reason']='Stored PDF hash mismatch; recollect before exporting.';continue
                slug=re.sub('[^A-Za-z0-9_-]+','-',paper['title']).strip('-')[:60] or 'paper'
                ident=re.sub('[^A-Za-z0-9_-]','_',pid)[:60]+'-'+hashlib.sha256(pid.encode()).hexdigest()[:8]
                item.update({'status':'included','archive_name':'papers/'+slug+'-'+ident+'.pdf','reason':None,'size_bytes':path.stat().st_size,'sha256':digest.hexdigest(),'source_url':row['source_url'],'final_url':row['final_url'],'version':row['version'],'retrieved_utc':iso(row['retrieved']),'_path':path})
                break
            except OSError:item['reason']='Stored PDF could not be read.'
        items.append(item)
    return items


def report_bytes(items,scope,index,count):
    public=[{k:v for k,v in item.items() if not k.startswith('_')} for item in items]
    manifest=json.dumps({'scope':scope,'part':index,'parts':count,'included_papers':sum(i['status']=='included' for i in items),'items':public},ensure_ascii=False,indent=2).encode()
    stream=io.StringIO();writer=csv.writer(stream);writer.writerow(['paper_id','title','reason'])
    for item in items:
        if item['status']!='included':writer.writerow([safe_cell(item['paper_id']),safe_cell(item['title']),safe_cell(item['reason'])])
    return manifest,stream.getvalue().encode('utf-8')


def predicted_size(items,scope,index):
    manifest,missing=report_bytes(items,scope,index,99999)
    total=22+len(manifest)+76+2*len('manifest.json')+len(missing)+76+2*len('missing-files.csv')
    return total+sum(i['size_bytes']+76+2*len(i['archive_name']) for i in items if i['status']=='included')


def bundles(con,c,body):
    ids,groups,scope=select(con,body)
    maximum=int(min(number('TUNA_ZIP_MAX_MB',100,1,500),body.max_bundle_mb or 500)*1_000_000)
    items=pdf_items(con,c,ids);parts=[];current=[]
    for item in items:
        if item['status']=='included' and predicted_size([item],scope,len(parts)+1)>maximum:
            item={**item,'status':'excluded','reason':'PDF exceeds this bundle size limit; increase the limit or download this version separately.','archive_name':None,'size_bytes':0};item.pop('_path',None)
        if current and predicted_size(current+[item],scope,len(parts)+1)>maximum:parts.append(current);current=[]
        current.append(item)
    if current or not parts:parts.append(current)
    budget=number('TUNA_EXPORT_TOTAL_MB',1024,1,100000)*1_000_000
    if sum(predicted_size(part,scope,i+1) for i,part in enumerate(parts))>budget:raise ValueError('Export exceeds the total size budget. Narrow filters or increase TUNA_EXPORT_TOTAL_MB.')
    outputs=[];created=[]
    try:
        for index,part in enumerate(parts,1):
            path=root(c)/(uuid.uuid4().hex+'.zip');created.append(path)
            manifest,missing=report_bytes(part,scope,index,len(parts))
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED,strict_timestamps=False) as archive:
                for item in part:
                    if item['status']=='included':archive.write(item['_path'],arcname=item['archive_name'])
                archive.writestr('manifest.json',manifest);archive.writestr('missing-files.csv',missing)
            if path.stat().st_size>maximum:raise ValueError('Bundle exceeded its size limit. Choose narrower filters.')
            entry=publish(con,c,path,'zip',sum(i['status']=='included' for i in part),f'endless-tuna-{c}-{body.scope}-part-{index:03d}.zip')
            entry['missing_papers']=sum(i['status']!='included' for i in part);outputs.append(entry)
    except Exception:
        for path in created:path.unlink(missing_ok=True)
        with storage.connect(c) as registry:
            registry.executemany('DELETE FROM export_files WHERE id=?',((p.stem,) for p in created))
        raise
    return {'scope':scope,'max_bundle_bytes':maximum,'selected_papers':len(ids),'included_papers':sum(p['included_papers'] for p in outputs),'missing_papers':sum(p['missing_papers'] for p in outputs),'parts':outputs}


def register_exports(app,collection):
    def build(c,body,kind):
        try:
            with storage.connect(c) as registry:cleanup(registry,c)
            with storage.connect(c) as con:
                con.execute('BEGIN')  # consistent snapshot across related workbook/manifest rows
                return workbook(con,c,body) if kind=='xlsx' else bundles(con,c,body)
        except (ValueError,CollectionError) as error:raise HTTPException(422,str(error)) from None
        except OSError:raise HTTPException(507,'Export storage is unavailable. Free disk space and retry.') from None

    @app.post('/api/exports/workbook')
    def export_workbook(body:ExportRequest,c=Depends(collection)):return build(c,body,'xlsx')

    @app.post('/api/exports/pdf-bundles')
    def export_bundles(body:ExportRequest,c=Depends(collection)):return build(c,body,'zip')

    @app.get('/api/exports/files/{id}')
    def export_file(id:str,collection:Literal['demo','real']='demo'):
        if not re.fullmatch('[a-f0-9]{32}',id):raise HTTPException(404,'Export not found')
        with storage.connect(collection) as con:row=con.execute('SELECT * FROM export_files WHERE id=?',(id,)).fetchone()
        if not row or row['expires']<time.time():raise HTTPException(404,'Export expired or not found. Generate it again.')
        path=root(collection)/(id+'.'+row['kind'])
        if not path.is_file():raise HTTPException(404,'Export file is missing. Generate it again.')
        return FileResponse(path,filename=row['name'],media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if row['kind']=='xlsx' else 'application/zip')
