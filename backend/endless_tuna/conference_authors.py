"""Conference-scoped paper-time affiliations; never merge authors by name."""
import csv
import io
import tempfile
from fastapi import Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, ConfigDict
from . import db
from .enrichment import enrich_paper, EnrichmentError
from .exports import safe_cell
from . import las_settings
from .las import LASError


class ConferenceExtraction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    use_las:bool=False
    all_papers:bool=False


ROWS = """
WITH members AS (SELECT DISTINCT paper_id FROM paper_editions WHERE edition_id=?)
SELECT p.id paper_id,p.title paper_title,a.id author_id,a.name author,
       au.position author_position,o.name institution,
       COALESCE(aa.status,'missing') status,aa.method,aa.source_url,aa.page,aa.excerpt,
       COALESCE(es.status,'not_started') extraction_status,es.code extraction_code,es.error extraction_error
FROM members m JOIN papers p ON p.id=m.paper_id
JOIN authorship au ON au.paper_id=p.id JOIN authors a ON a.id=au.author_id
LEFT JOIN author_assertions aa ON aa.paper_id=p.id AND aa.author_id=a.id
    AND aa.kind='affiliation' AND aa.status NOT IN ('rejected','superseded')
LEFT JOIN organizations o ON o.id=aa.organization_id
LEFT JOIN enrichment_state es ON es.paper_id=p.id
"""


def selection(edition, q, status):
    sql=ROWS+' WHERE 1=1';args=[edition]
    if q:
        # Treat %, _ and backslash as literal search characters.
        term='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        sql+=" AND (a.name LIKE ? ESCAPE '\\' OR o.name LIKE ? ESCAPE '\\' OR p.title LIKE ? ESCAPE '\\')"
        args.extend([term]*3)
    if status:
        sql+=" AND COALESCE(aa.status,'missing')=?";args.append(status)
    return sql,args


def extraction_diagnostics(con,edition):
    counts=dict(con.execute("""SELECT COUNT(*) papers,
        COALESCE(SUM(EXISTS(SELECT 1 FROM downloads d WHERE d.paper_id=m.paper_id AND d.status='available' AND pdf_exists(d.path))),0) pdfs,
        COALESCE(SUM(EXISTS(SELECT 1 FROM downloads d JOIN pdf_pages pp ON pp.download_id=d.id
          WHERE d.paper_id=m.paper_id AND d.status='available' AND pdf_exists(d.path) AND d.source_url IS NOT NULL AND trim(pp.text)<>'')),0) readable_papers
        FROM (SELECT DISTINCT paper_id FROM paper_editions WHERE edition_id=?) m""",(edition,)).fetchone())
    counts['missing_pdfs']=counts['papers']-counts['pdfs']
    counts['pdfs_without_text']=counts['pdfs']-counts['readable_papers']
    counts['with_institutions']=con.execute("SELECT COUNT(*) FROM authorship au WHERE au.paper_id IN (SELECT paper_id FROM paper_editions WHERE edition_id=?) AND EXISTS(SELECT 1 FROM author_assertions aa WHERE aa.paper_id=au.paper_id AND aa.author_id=au.author_id AND aa.kind='affiliation' AND aa.status NOT IN ('rejected','superseded'))",(edition,)).fetchone()[0]
    counts['issues']=[dict(r) for r in con.execute("SELECT es.code,es.error,COUNT(*) papers FROM enrichment_state es WHERE es.paper_id IN (SELECT paper_id FROM paper_editions WHERE edition_id=?) AND es.code IS NOT NULL GROUP BY es.code,es.error ORDER BY papers DESC",(edition,))]
    job=con.execute('SELECT message FROM jobs WHERE edition_id=? ORDER BY updated DESC LIMIT 1',(edition,)).fetchone()
    counts['collection_message']=job['message'] if job else ''
    try:
        las_settings.configured_client().config.require(model=True)
        counts.update(las_ready=True,las_message='LAS configuration is present; live access has not been verified.')
    except LASError as error:counts.update(las_ready=False,las_message=str(error))
    return counts


def register_conference_authors(app, collection, get):
    @app.get('/api/conferences/{id}/authors/extraction-status')
    def extraction_status(id:str,c=Depends(collection)):
        with db.connect(c) as con:
            get(con,'editions',id)
            return extraction_diagnostics(con,id)

    @app.get('/api/author-conferences')
    def find_conferences(q:str=Query('',max_length=200),page:int=Query(1,ge=1),c=Depends(collection)):
        # Match conference names/years only; paper content is a separate search.
        terms=q.split()
        if not terms:return {'items':[],'total':0,'page':page,'pages':0,'page_size':25}
        where=[];args=[]
        for term in terms:
            literal=term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            where.append("(s.name || ' ' || e.year) LIKE ? ESCAPE '\\'")
            args.append('%'+literal+'%')
        base=' FROM editions e JOIN series s ON s.id=e.series_id WHERE '+' AND '.join(where)
        with db.connect(c) as con:
            total=con.execute('SELECT COUNT(*)'+base,args).fetchone()[0]
            rows=[dict(r) for r in con.execute('SELECT e.id,s.name,e.year,e.inventory_complete'+base+' ORDER BY e.year DESC,s.name,e.id LIMIT 25 OFFSET ?',args+[(page-1)*25])]
            for row in rows:
                row['papers']=con.execute('SELECT COUNT(DISTINCT paper_id) FROM paper_editions WHERE edition_id=?',(row['id'],)).fetchone()[0]
                row['author_records']=con.execute('SELECT COUNT(*) FROM authorship WHERE paper_id IN (SELECT paper_id FROM paper_editions WHERE edition_id=?)',(row['id'],)).fetchone()[0]
            return {'items':rows,'total':total,'page':page,'pages':(total+24)//25,'page_size':25}

    @app.get('/api/conferences/{id}/authors')
    def directory(id:str,q:str=Query('',max_length=200),status:str=Query('',pattern='^(|missing|extracted|needs_review|verified)$'),page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),c=Depends(collection)):
        with db.connect(c) as con:
            get(con,'editions',id)
            sql,args=selection(id,q,status)
            total=con.execute('SELECT COUNT(*) FROM ('+sql+')',args).fetchone()[0]
            items=[dict(r) for r in con.execute(sql+' ORDER BY p.title,p.id,au.position,aa.id LIMIT ? OFFSET ?',args+[page_size,(page-1)*page_size])]
            coverage=dict(con.execute("""SELECT COUNT(*) author_paper_pairs,
                COALESCE(SUM(EXISTS(SELECT 1 FROM author_assertions aa WHERE aa.paper_id=au.paper_id
                  AND aa.author_id=au.author_id AND aa.kind='affiliation'
                  AND aa.status NOT IN ('rejected','superseded'))),0) with_institutions
                FROM authorship au WHERE au.paper_id IN (SELECT paper_id FROM paper_editions WHERE edition_id=?)""",(id,)).fetchone())
            coverage['papers_without_authors']=con.execute('SELECT COUNT(DISTINCT pe.paper_id) FROM paper_editions pe WHERE pe.edition_id=? AND NOT EXISTS(SELECT 1 FROM authorship au WHERE au.paper_id=pe.paper_id)',(id,)).fetchone()[0]
            return dict(items=items,total=total,page=page,page_size=page_size,pages=(total+page_size-1)//page_size,coverage=coverage)

    @app.get('/api/conferences/{id}/authors.csv')
    def export(id:str,q:str=Query('',max_length=200),status:str=Query('',pattern='^(|missing|extracted|needs_review|verified)$'),c=Depends(collection)):
        with db.connect(c) as con:get(con,'editions',id)
        def chunks():
            columns=['collection','conference_id','conference','year','paper_id','paper_title','author_id','author','author_position','institution','status','method','source_url','page','excerpt','extraction_status','extraction_code','extraction_error']
            stream=io.StringIO();writer=csv.writer(stream)
            writer.writerow(columns);yield '\ufeff'+stream.getvalue()
            with db.connect(c) as con:
                con.execute('BEGIN')
                edition=get(con,'editions',id)
                name=get(con,'series',edition['series_id'])['name']
                sql,args=selection(id,q,status)
                for record in con.execute(sql+' ORDER BY p.title,p.id,au.position,aa.id',args):
                    row={**dict(record),'collection':c,'conference_id':id,'conference':name,'year':edition['year']}
                    stream.seek(0);stream.truncate(0)
                    writer.writerow([safe_cell(row.get(key)) for key in columns]);yield stream.getvalue()
        return StreamingResponse(chunks(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="conference-authors.csv"'})

    @app.post('/api/conferences/{id}/authors/extract')
    def extract(id:str,body:ConferenceExtraction=ConferenceExtraction(),after:str=Query('',max_length=200),c=Depends(collection)):
        # Small resumable batches keep old downloads usable without long HTTP requests.
        with db.connect(c) as con:
            get(con,'editions',id)
            if body.use_las:
                try:las_settings.configured_client().config.require(model=True)
                except LASError as error:raise HTTPException(409,'AI extraction cannot start: '+str(error)+' Configure LAS in Settings or turn off AI to run local extraction.') from None
            ids=[r[0] for r in con.execute("""SELECT DISTINCT pe.paper_id FROM paper_editions pe
                WHERE pe.edition_id=? AND pe.paper_id>? AND (? OR EXISTS(SELECT 1 FROM downloads d
                WHERE d.paper_id=pe.paper_id AND d.status='available' AND pdf_exists(d.path)))
                ORDER BY pe.paper_id LIMIT 11""",(id,after,body.all_papers))]
        results=[]
        for pid in ids[:10]:
            try:results.append({'paper_id':pid,**enrich_paper(c,pid,use_las=body.use_las)})
            except EnrichmentError as error:results.append({'paper_id':pid,'status':'failed','error':str(error)})
            except Exception:results.append({'paper_id':pid,'status':'failed','error':'Paper extraction failed. Saved records were preserved; review or retry this paper.'})
        diagnostics=None
        if len(ids)<=10:
            with db.connect(c) as con:diagnostics=extraction_diagnostics(con,id)
        return {'results':results,'next_after':ids[9] if len(ids)>10 else None,'diagnostics':diagnostics}

    @app.get('/api/conferences/{id}/authors.pdf')
    def pdf_report(id:str,q:str=Query('',max_length=200),status:str=Query('',pattern='^(|missing|extracted|needs_review|verified)$'),c=Depends(collection)):
        from .author_report import write_report
        stream=tempfile.SpooledTemporaryFile(max_size=8*1024*1024,mode='w+b')
        try:
            with db.connect(c) as con:
                con.execute('BEGIN')
                edition=get(con,'editions',id)
                name=get(con,'series',edition['series_id'])['name']
                missing=con.execute('SELECT COUNT(DISTINCT pe.paper_id) FROM paper_editions pe WHERE pe.edition_id=? AND NOT EXISTS(SELECT 1 FROM authorship au WHERE au.paper_id=pe.paper_id)',(id,)).fetchone()[0]
                sql,args=selection(id,q,status)
                write_report(stream,con.execute(sql+' ORDER BY p.title,p.id,au.position,aa.id',args),conference=name,year=edition['year'],collection=c,q=q,status=status,missing_rosters=missing)
            stream.seek(0)
        except BaseException:
            stream.close();raise
        def chunks():
            try:
                while chunk:=stream.read(64*1024):yield chunk
            finally:stream.close()
        return StreamingResponse(chunks(),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="conference-authors.pdf"'},background=BackgroundTask(stream.close))
