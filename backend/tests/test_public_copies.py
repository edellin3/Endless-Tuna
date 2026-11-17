import json
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db,worker
from endless_tuna.main import app
from endless_tuna.collection import Metadata,Person,CollectionError
from endless_tuna.resolution import resolve,cvf_candidates,Candidate
from endless_tuna.pipeline_store import upsert_paper
from tests.acceptance_fixture import fixture_pdf

SOURCE='https://openaccess.thecvf.com/WACV2026?day=all'
PDF='https://openaccess.thecvf.com/content/WACV2026/papers/Fixture_Study_WACV_2026_paper.pdf'
CATALOG=f'''<dt class="ptitle"><a href="/content/WACV2026/html/Fixture_Study_WACV_2026_paper.html">Fictional study</a></dt><dd><input name="query_author" value="Mira Chen"><input name="query_author" value="Alex Rivera"></dd><dd><a href="{PDF}">pdf</a><a href="/content/WACV2026/supplemental/fixture.pdf">supp</a></dd>'''.encode()

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    monkeypatch.setattr('endless_tuna.resolution.time.sleep',lambda _:None)
    with TestClient(app) as client:yield client

def record():return Metadata(title='Fictional study',authors=[Person(name='Mira Chen'),Person(name='Alex Rivera')],year=2026,source_url='https://wacv.thecvf.com/virtual/2026/poster/1')

def test_cvf_uses_exact_title_and_complete_authors_and_cached_catalog(client):
    calls=[]
    def fetch(url,**kwargs):calls.append(url);assert url==SOURCE;return CATALOG,url
    selected,_,_=resolve(record(),'real',fetch,wide=True)
    assert selected.url==PDF and selected.version=='cvf:WACV2026'
    assert cvf_candidates(record(),'real',fetch)[0].url==PDF and calls==[SOURCE]

def test_cvf_incomplete_authors_require_review_and_cannot_select_supplement(client):
    r=record().model_copy(update={'authors':[Person(name='Mira Chen')]})
    def fetch(url,**kwargs):
        if url==SOURCE:return CATALOG,url
        if 'arxiv.org' in url:return b'<feed xmlns="http://www.w3.org/2005/Atom"/>',url
        if 'openalex.org' in url:return b'{"results":[]}',url
        raise AssertionError(url)
    selected,candidates,error=resolve(r,'real',fetch,wide=True)
    assert selected is None and [c.url for c in candidates]==[PDF] and 'Ambiguous' in error
    with pytest.raises(CollectionError):cvf_candidates(record(),'demo',lambda *a,**k:(CATALOG.replace(b'/papers/',b'/supplemental/'),SOURCE))

def test_public_copy_job_never_requests_openreview_and_continues_after_missing_copy(client,monkeypatch):
    edition=client.post('/api/conferences',headers={'X-Collection':'real'},json={'name':'Fictional edition','year':2026,'track':'Main','source_url':'https://example.org/papers','adapter':'metadata'}).json()
    with db.connect('real') as con:
        con.execute("UPDATE jobs SET status='cancelled' WHERE edition_id=?",(edition['id'],))
        track=con.execute('SELECT id FROM tracks WHERE edition_id=?',(edition['id'],)).fetchone()[0]
        for n in range(3):
            r=record().model_copy(update={'title':f'Fictional {n}','source_url':f'https://example.org/paper/{n}','pdf_url':f'https://openreview.net/pdf?id=fixture{n}'})
            pid=upsert_paper(con,edition['id'],track,r,'https://example.org/papers')
            con.execute("INSERT INTO job_papers VALUES(?,?,?,?,'resolve','pending',NULL,1)",(edition['job_id'],pid,n,r.model_dump_json()))
    def find(r,*args,**kwargs):
        assert r.pdf_url is None
        if r.title.endswith('0'):return None,[],'No public copy found.'
        if not kwargs.get('excluded_urls'):return Candidate('https://denied.example/paper.pdf',r.title,[p.name for p in r.authors],'arxiv:fixture'),[],None
        return Candidate('https://files.example/paper.pdf',r.title,[p.name for p in r.authors],'arxiv:fixture'),[],None
    calls=[]
    def fetch(url,**kwargs):
        calls.append(url);assert 'openreview.net' not in url
        if 'denied.example' in url:raise CollectionError('Source returned HTTP 403.')
        return fixture_pdf(),url
    monkeypatch.setattr(worker,'resolve',find);monkeypatch.setattr(worker,'fetch_bytes',fetch)
    queued=client.post('/api/conferences/'+edition['id']+'/pdfs',headers={'X-Collection':'real'},json={'public_alternatives':True}).json()
    assert queued['selected_papers']==3 and worker.tick('real',queued['job_id'])
    assert calls.count('https://denied.example/paper.pdf')==1
    with db.connect('real') as con:
        assert json.loads(con.execute('SELECT records FROM job_payloads WHERE job_id=?',(queued['job_id'],)).fetchone()[0])['public_alternatives'] is True
        assert con.execute("SELECT COUNT(*) FROM job_papers WHERE job_id=? AND status='done'",(queued['job_id'],)).fetchone()[0]==2
        assert con.execute("SELECT COUNT(*) FROM job_papers WHERE job_id=? AND status='pending'",(queued['job_id'],)).fetchone()[0]==0


def test_queue_reuses_the_latest_durable_metadata_snapshot(client):
    from endless_tuna.pipeline_api import queue
    e=client.post('/api/conferences',headers={'X-Collection':'real'},json={'name':'Fictional edition','year':2026,'track':'Main','source_url':'https://example.org/papers','adapter':'metadata'}).json()
    with db.connect('real') as con:
        con.execute("UPDATE jobs SET status='cancelled'")
        track=con.execute('SELECT id FROM tracks WHERE edition_id=?',(e['id'],)).fetchone()[0]
        r=record().model_copy(update={'source_url':'https://example.org/paper','abstract':'older snapshot'})
        pid=upsert_paper(con,e['id'],track,r,'https://example.org/papers')
        for timestamp,abstract in [(1,'older snapshot'),(2,'newest snapshot')]:
            jid=queue(con,e['id'],track)
            con.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(jid,))
            con.execute("INSERT INTO job_papers VALUES(?,?,0,?,'resolve','pending',NULL,?)",(jid,pid,r.model_copy(update={'abstract':abstract}).model_dump_json(),timestamp))
    response=client.post('/api/conferences/'+e['id']+'/pdfs',headers={'X-Collection':'real'},json={'public_alternatives':True,'full_collection':True}).json()
    with db.connect('real') as con:
        saved=json.loads(con.execute('SELECT metadata FROM job_papers WHERE job_id=?',(response['job_id'],)).fetchone()[0])
        assert saved['abstract']=='newest snapshot' and saved['authors']==r.model_dump()['authors']


def test_worker_main_survives_busy_database_but_surfaces_other_sql_errors(monkeypatch):
    import sqlite3,sys
    monkeypatch.setattr(sys,'argv',['worker','--once','--collection','real'])
    monkeypatch.setattr(worker.storage,'initialize',lambda _:None)
    monkeypatch.setattr(worker.signal,'signal',lambda *args:None)
    busy=sqlite3.OperationalError('database is locked');busy.sqlite_errorcode=sqlite3.SQLITE_BUSY
    def locked(*args):raise busy
    monkeypatch.setattr(worker,'tick',locked)
    worker.main()
    error=sqlite3.OperationalError('missing table');error.sqlite_errorcode=sqlite3.SQLITE_ERROR
    def broken(*args):raise error
    monkeypatch.setattr(worker,'tick',broken)
    with pytest.raises(sqlite3.OperationalError,match='missing table'):worker.main()
