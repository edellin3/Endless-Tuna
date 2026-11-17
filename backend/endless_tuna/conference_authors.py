"""Conference-scoped paper-time affiliations; never merge authors by name."""
import csv
import io
import tempfile
from fastapi import Depends, Query
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from . import db
from .enrichment import enrich_paper, EnrichmentError
from .exports import safe_cell


ROWS = """
WITH members AS (SELECT DISTINCT paper_id FROM paper_editions WHERE edition_id=?)
SELECT p.id paper_id,p.title paper_title,a.id author_id,a.name author,
       au.position author_position,o.name institution,
       COALESCE(aa.status,'missing') status,aa.method,aa.source_url,aa.page,aa.excerpt,
       COALESCE(es.status,'not_started') extraction_status
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


def register_conference_authors(app, collection, get):
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
            columns=['collection','conference_id','conference','year','paper_id','paper_title','author_id','author','author_position','institution','status','method','source_url','page','excerpt','extraction_status']
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
    def extract(id:str,after:str=Query('',max_length=200),c=Depends(collection)):
        # Small resumable batches keep old downloads usable without long HTTP requests.
        with db.connect(c) as con:
            get(con,'editions',id)
            ids=[r[0] for r in con.execute("""SELECT DISTINCT pe.paper_id FROM paper_editions pe
                WHERE pe.edition_id=? AND pe.paper_id>? AND EXISTS(SELECT 1 FROM downloads d
                WHERE d.paper_id=pe.paper_id AND d.status='available' AND pdf_exists(d.path))
                ORDER BY pe.paper_id LIMIT 11""",(id,after))]
        results=[]
        for pid in ids[:10]:
            try:results.append({'paper_id':pid,**enrich_paper(c,pid,use_las=False)})
            except EnrichmentError as error:results.append({'paper_id':pid,'status':'failed','error':str(error)})
        return {'results':results,'next_after':ids[9] if len(ids)>10 else None}

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
