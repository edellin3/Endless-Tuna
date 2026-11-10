import time
import uuid
import json
from typing import Literal
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from . import db as storage
from .enrichment import AssertionInput,EnrichmentError,insert_assertion,enrich_paper,assertions,component,contains
from .identity import propose,review_identity,corroboration,supported_proposals


class EnrichRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    use_las:bool=False


class AssertionReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['confirm','reject','correct']
    note:str=Field(min_length=1,max_length=2000)
    replacement:AssertionInput|None=None


class IdentityProposal(BaseModel):
    model_config=ConfigDict(extra='forbid')
    left_author_id:str
    right_author_id:str
    source_url:str=Field(min_length=1,max_length=2000)
    excerpt:str=Field(min_length=3,max_length=1800)
    assertion_ids:list[str]=Field(default_factory=list,max_length=20)


class IdentityReview(BaseModel):
    action:Literal['confirm','reject','undo']
    note:str=Field(min_length=1,max_length=2000)


def review_assertion(con,ident,body):
    row=con.execute('SELECT * FROM author_assertions WHERE id=?',(ident,)).fetchone()
    if not row:raise EnrichmentError('Assertion not found.')
    if row['status']=='superseded':raise EnrichmentError('This assertion was superseded. Review its replacement.')
    replacement=None
    if body.action=='correct':
        if not body.replacement:raise EnrichmentError('A correction requires a replacement assertion and supporting evidence.')
        replacement,_=insert_assertion(con,row['author_id'],body.replacement,method='analyst_correction',supersedes=ident)
        status='superseded';message='Original assertion preserved. Corrected assertion needs separate verification.'
    elif body.action=='confirm':
        if row['kind']=='orcid' and row['method'] not in ('deterministic_pdf','las'):
            papers=con.execute('SELECT p.title,p.canonical_url FROM papers p JOIN authorship au ON au.paper_id=p.id WHERE au.author_id=?',(row['author_id'],)).fetchall()
            from_paper=row['paper_id'] and con.execute('SELECT 1 FROM paper_editions WHERE paper_id=? AND official_url=? UNION ALL SELECT 1 FROM downloads WHERE paper_id=? AND source_url=?',(row['paper_id'],row['source_url'],row['paper_id'],row['source_url'])).fetchone()
            if not from_paper and not any(contains(row['excerpt'],p['title']) for p in papers):
                raise EnrichmentError('ORCID verification requires known-publication corroboration. A name and valid checksum alone do not prove ownership.')
        if row['kind'] in ('organization_country','organization_city') and not con.execute("SELECT 1 FROM author_assertions WHERE author_id=? AND paper_id=? AND organization_id=? AND kind='affiliation' AND status='verified'",(row['author_id'],row['paper_id'],row['organization_id'])).fetchone():
            raise EnrichmentError('Verify the supporting paper-time affiliation before verifying its location.')
        status='verified';message='Assertion verified by analyst against the supplied evidence.'
    else:status='rejected';message='Assertion rejected; original evidence and review history retained.'
    con.execute('UPDATE author_assertions SET status=? WHERE id=?',(status,ident))
    con.execute('INSERT INTO assertion_reviews VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),ident,body.action,row['status'],status,body.note,replacement,time.time()))
    return {'ok':True,'status':status,'replacement_id':replacement,'message':message}


def register_enrichment(app,collection,get):
    @app.post('/api/papers/{id}/enrich')
    def enrich(id:str,body:EnrichRequest,c=Depends(collection)):
        try:return enrich_paper(c,id,body.use_las)
        except EnrichmentError as error:raise HTTPException(409,str(error)) from None

    @app.get('/api/papers/{id}/enrichment')
    def paper_enrichment(id:str,c=Depends(collection)):
        with storage.connect(c) as con:
            get(con,'papers',id)
            state=con.execute('SELECT * FROM enrichment_state WHERE paper_id=?',(id,)).fetchone()
            authors=[r[0] for r in con.execute('SELECT author_id FROM authorship WHERE paper_id=? ORDER BY position',(id,))]
            return {'state':dict(state) if state else {'status':'not_started','attempts':0},'assertions':[a for a in assertions(con,authors) if a['paper_id']==id] if authors else [],'runs':[dict(r) for r in con.execute('SELECT * FROM enrichment_runs WHERE paper_id=? ORDER BY started DESC',(id,))]}

    @app.post('/api/authors/{id}/assertions',status_code=201)
    def add_assertion(id:str,body:AssertionInput,c=Depends(collection)):
        try:
            with storage.connect(c) as con:
                get(con,'authors',id)
                ident,created=insert_assertion(con,id,body)
                status=con.execute('SELECT status FROM author_assertions WHERE id=?',(ident,)).fetchone()['status']
            return {'id':ident,'status':status,'message':'Assertion recorded with evidence. It is not verified until explicitly confirmed.' if created else 'Matching assertion already exists. Its review status was preserved.'}
        except EnrichmentError as error:raise HTTPException(422,str(error)) from None

    @app.get('/api/assertions')
    def assertion_queue(status:Literal['pending','all']='pending',c=Depends(collection)):
        with storage.connect(c) as con:
            ids=[r[0] for r in con.execute('SELECT id FROM authors')]
            rows=assertions(con,ids) if ids else []
            return rows if status=='all' else [r for r in rows if r['status'] in ('extracted','needs_review')]

    @app.post('/api/assertions/{id}/review')
    def assertion_review(id:str,body:AssertionReview,c=Depends(collection)):
        try:
            with storage.connect(c) as con:
                con.execute('BEGIN IMMEDIATE')
                return review_assertion(con,id,body)
        except EnrichmentError as error:raise HTTPException(422,str(error)) from None

    @app.get('/api/author-filters')
    def author_filters(c=Depends(collection)):
        from .enrichment_views import directory
        with storage.connect(c) as con:
            rows=directory(con)
            return {'organizations':sorted({org for a in rows for org in a['organizations']}),'countries':sorted({country for a in rows for country in a['verified_countries']})}

    @app.post('/api/identity/proposals',status_code=201)
    def identity_proposal(body:IdentityProposal,c=Depends(collection)):
        try:
            with storage.connect(c) as con:
                con.execute('BEGIN IMMEDIATE')
                ident=propose(con,body.left_author_id,body.right_author_id,body.source_url,body.excerpt,body.assertion_ids)
            return {'id':ident,'status':'pending','message':'Proposal saved. Author identities remain separate until evidence is confirmed.'}
        except EnrichmentError as error:raise HTTPException(422,str(error)) from None

    @app.post('/api/identity/discover')
    def suggest_identities(c=Depends(collection)):
        with storage.connect(c) as con:
            con.execute('BEGIN IMMEDIATE')
            created=supported_proposals(con)
        return {'ok':True,'proposed':len(created),'message':'Only matching verified ORCIDs generate suggestions. No names were merged automatically.'}

    @app.get('/api/identity/proposals')
    def identity_proposals(c=Depends(collection)):
        with storage.connect(c) as con:
            rows=[dict(r) for r in con.execute('SELECT p.*,a.name left_name,b.name right_name FROM identity_proposals p JOIN authors a ON a.id=p.left_author_id JOIN authors b ON b.id=p.right_author_id ORDER BY p.created DESC')]
            for row in rows:
                row['can_confirm'],row['eligibility']=corroboration(con,row['left_author_id'],row['right_author_id'],row['excerpt']) if row['status']=='pending' else (False,'')
                row['history']=[dict(r) for r in con.execute('SELECT * FROM identity_history WHERE proposal_id=? ORDER BY created',(row['id'],))]
                row['supporting_assertions']=[dict(r) for r in con.execute('SELECT * FROM author_assertions WHERE id IN ('+','.join('?' for _ in json.loads(row['assertion_ids']))+')',json.loads(row['assertion_ids']))] if json.loads(row['assertion_ids']) else []
            return rows

    @app.post('/api/identity/proposals/{id}/review')
    def identity_review(id:str,body:IdentityReview,c=Depends(collection)):
        try:
            with storage.connect(c) as con:
                con.execute('BEGIN IMMEDIATE')
                message=review_identity(con,id,body.action,body.note)
            return {'ok':True,'message':message}
        except EnrichmentError as error:raise HTTPException(422,str(error)) from None
