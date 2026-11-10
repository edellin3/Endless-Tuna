"""Pipeline actions kept separate from the browsing API and LAS endpoints."""
import json
import time
import uuid
from typing import Literal
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from . import db as storage
from .adapters import parse_csv
from .collection import CollectionError, Metadata, Person
from .network import validate_url
from .pipeline_store import coverage, save_candidate
from .resolution import Candidate, search_status


class CollectionRequest(BaseModel):
    paper_limit:int=Field(default=10,ge=1,le=100)
    full_collection:bool=False


class CSVImport(BaseModel):
    csv_text:str=Field(min_length=1,max_length=10_000_000)


class PDFCandidate(BaseModel):
    url:str=Field(min_length=1,max_length=2000)
    version:Literal['analyst-supplied','proceedings','arxiv']='analyst-supplied'


class CandidateDecision(BaseModel):
    action:Literal['confirm','reject']
    note:str=Field(default='',max_length=2000)


def queue(con,eid,track,limit=10,payload=None):
    jid=str(uuid.uuid4())
    con.execute("INSERT INTO jobs(id,edition_id,status,message,updated,paper_limit,track_id) VALUES(?,?,'queued','Waiting for worker',?,?,?)",(jid,eid,time.time(),limit,track))
    if payload is not None:con.execute('INSERT INTO job_payloads VALUES(?,?)',(jid,json.dumps(payload)))
    return jid


def register_pipeline(app,collection,get):
    @app.get('/api/coverage')
    def inventory_status(c=Depends(collection)):
        with storage.connect(c) as con:
            rows=[{'id':r['id'],**coverage(con,r['id'])} for r in con.execute('SELECT id FROM editions')]
        return {'editions':rows,'inventory_complete':bool(rows) and all(r['inventory_complete'] for r in rows),'search_provider':search_status()}

    @app.post('/api/conferences/{id}/collect')
    def collect(id:str,body:CollectionRequest,c=Depends(collection)):
        with storage.connect(c) as con:
            con.execute('BEGIN IMMEDIATE')
            get(con,'editions',id)
            if con.execute("SELECT 1 FROM jobs WHERE edition_id=? AND status IN ('queued','running')",(id,)).fetchone():raise HTTPException(409,'A collection job for this edition is already queued or running.')
            track=con.execute('SELECT id FROM tracks WHERE edition_id=? ORDER BY id LIMIT 1',(id,)).fetchone()['id']
            jid=queue(con,id,track,None if body.full_collection else body.paper_limit)
        return {'job_id':jid}

    @app.post('/api/conferences/{id}/inventory/csv')
    def import_csv(id:str,body:CSVImport,c=Depends(collection)):
        try:records=parse_csv(body.csv_text.encode())
        except CollectionError as error:raise HTTPException(422,str(error)) from None
        with storage.connect(c) as con:
            edition=get(con,'editions',id)
            tracks={r['name']:r['id'] for r in con.execute('SELECT * FROM tracks WHERE edition_id=?',(id,))}
            if any(r.year!=edition['year'] or r.track not in tracks for r in records):raise HTTPException(422,'Every CSV row must match this edition year and one existing track. Import workshops separately.')
            if len({r.track for r in records})!=1:raise HTTPException(422,'Import one track at a time.')
            jid=queue(con,id,tracks[records[0].track],None,{'records':[r.model_dump() for r in records],'official_count':None,'url':edition['source_url']})
        return {'job_id':jid,'inventory_records':len(records),'official_count':None,'message':'CSV is analyst-supplied membership evidence; full official inventory completeness is unknown.'}

    @app.post('/api/papers/{id}/pdf-candidates')
    def supply_candidate(id:str,body:PDFCandidate,c=Depends(collection)):
        try:validate_url(body.url,resolve=False)
        except CollectionError as error:raise HTTPException(422,str(error)) from None
        with storage.connect(c) as con:
            paper=get(con,'papers',id)
            authors=[r['name'] for r in con.execute('SELECT a.name FROM authors a JOIN authorship au ON au.author_id=a.id WHERE au.paper_id=? ORDER BY au.position',(id,))]
            save_candidate(con,id,Candidate(body.url,paper['title'],authors,body.version),'Analyst-supplied PDF URL; confirm source/version and paper identity before download.')
        return {'ok':True,'message':'Candidate queued for review. No download occurred.'}

    @app.get('/api/pdf-candidates')
    def candidates(c=Depends(collection)):
        with storage.connect(c) as con:
            return [dict(r) for r in con.execute("SELECT c.*,p.title paper_title FROM pdf_candidates c JOIN papers p ON p.id=c.paper_id WHERE c.status='pending' ORDER BY c.created")]

    @app.post('/api/pdf-candidates/{id}/review')
    def review_candidate(id:str,body:CandidateDecision,c=Depends(collection)):
        with storage.connect(c) as con:
            con.execute('BEGIN IMMEDIATE')
            candidate=get(con,'pdf_candidates',id)
            paper=get(con,'papers',candidate['paper_id'])
            if candidate['status']!='pending':raise HTTPException(409,'Candidate has already been reviewed.')
            status='confirmed' if body.action=='confirm' else 'rejected'
            con.execute('UPDATE pdf_candidates SET status=?,reviewed=? WHERE id=?',(status,time.time(),id))
            con.execute('INSERT INTO review_history VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),paper['id'],'pdf_'+body.action,paper['title'],paper['title'],body.note+' Candidate: '+candidate['url']+' ['+candidate['version']+']',time.time()))
            jid=None
            if body.action=='confirm':
                membership=con.execute('SELECT * FROM paper_editions WHERE paper_id=? ORDER BY retrieved DESC LIMIT 1',(paper['id'],)).fetchone()
                edition=get(con,'editions',membership['edition_id'])
                people=[Person(name=r['name']) for r in con.execute('SELECT a.name FROM authors a JOIN authorship au ON a.id=au.author_id WHERE au.paper_id=? ORDER BY au.position',(paper['id'],))]
                record=Metadata(title=paper['title'],abstract=paper['abstract'],authors=people,source_url=paper['canonical_url'] or membership['official_url'])
                jid=queue(con,edition['id'],membership['track_id'],1,{'records':[],'official_count':edition['official_count'],'url':edition['source_url']})
                con.execute('INSERT INTO job_papers VALUES(?,?,?,?,?,?,?,?)',(jid,paper['id'],0,record.model_dump_json(),'resolve','pending',None,time.time()))
        return {'ok':True,'status':status,'job_id':jid}

    @app.get('/api/papers/{id}/pages')
    def pages(id:str,c=Depends(collection)):
        with storage.connect(c) as con:
            get(con,'papers',id)
            return [dict(r) for r in con.execute('SELECT pg.page,pg.text,pg.download_id,d.version FROM pdf_pages pg JOIN downloads d ON d.id=pg.download_id WHERE pg.paper_id=? ORDER BY pg.download_id,pg.page',(id,))]
