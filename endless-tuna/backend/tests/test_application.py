import time
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db
from endless_tuna.main import app
from endless_tuna.worker import tick

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA', tmp_path)
    with TestClient(app) as c:
        yield c

def create(client, collection='real'):
    r=client.post('/api/conferences',headers={'X-Collection':collection},json={'name':'Fictional Test Conference','year':2026,'track':'Research','source_url':'https://example.org/papers','adapter':'metadata'})
    assert r.status_code==201
    return r.json()

def test_demo_isolation_and_reset(client):
    assert len(client.get('/api/papers').json())==9
    assert client.get('/api/papers',headers={'X-Collection':'real'}).json()==[]
    added=create(client)
    assert len(client.get('/api/conferences',headers={'X-Collection':'real'}).json())==1
    assert client.post('/api/demo/reset',headers={'X-Collection':'real'}).status_code==403
    assert client.post('/api/demo/reset').status_code==200
    assert client.get('/api/conferences/'+added['id'],headers={'X-Collection':'real'}).status_code==200
    assert len(client.get('/api/papers').json())==9

def test_fts_filters_and_counts(client):
    conferences=client.get('/api/conferences?q=robotics&pdf=yes&year=2025').json()
    assert len(conferences)==2
    assert all(c['matching_count']==1 and c['total_count']==3 for c in conferences)
    assert client.get('/api/conferences?q=unfindableword').json()==[]
    assert client.get('/api/conferences?q=%22%20OR%20*').status_code==200
    papers=client.get('/api/papers?q=robotics').json()
    assert papers and all(p['match_reasons'] for p in papers)
    assert any(r['kind']=='conference' for p in papers for r in p['match_reasons'])
    assert len(client.get('/api/conferences?organization=Northstar%20Lab').json())==3

def test_ordered_people_and_paper_affiliations(client):
    people=client.get('/api/authors?q=Alex%20Rivera').json()
    assert len(people)==2 and people[0]['id']!=people[1]['id']
    paper=client.get('/api/papers/harbor-0').json()
    assert [a['position'] for a in paper['authors']]==[1,2]
    assert paper['authors'][1]['organizations'][0]['name']=='Northstar Lab'
    assert paper['evidence'][0]['url'].startswith('https://example.org/')

def test_review_updates_fts_and_audit(client):
    r=client.post('/api/papers/harbor-1/review',json={'action':'correct','title':'Unique corrected title','note':'Checked fictional listing'})
    assert r.status_code==200
    paper=client.get('/api/papers/harbor-1').json()
    assert paper['review_status']=='confirmed'
    assert paper['history'][0]['old_title']=='Soft grippers for delicate ocean sampling'
    assert client.get('/api/papers?q=Unique').json()[0]['id']=='harbor-1'
    client.post('/api/papers/harbor-1/review',json={'action':'reject'})
    assert client.get('/api/papers/harbor-1').json()['review_status']=='rejected'

def test_pdf_and_exports(client):
    r=client.get('/api/papers/harbor-0/pdf')
    assert r.status_code==200 and r.content.startswith(b'%PDF-1.4')
    assert client.get('/api/papers/harbor-1/pdf').status_code==404
    with db.connect() as con:
        con.execute("UPDATE downloads SET path='../real.sqlite3' WHERE paper_id='harbor-0'")
    assert client.get('/api/papers/harbor-0/pdf').status_code==404
    assert client.get('/api/conferences/harbor/export?format=json&pdf=yes').json()['papers']==[]
    with db.connect() as con:con.execute("UPDATE downloads SET path='harbor-0.pdf' WHERE paper_id='harbor-0'")
    r=client.get('/api/conferences/harbor/export?format=json&pdf=yes')
    assert len(r.json()['papers'])==1 and r.json()['collection']=='demo'
    client.post('/api/papers/harbor-1/review',json={'action':'correct','title':'=FORMULA()'})
    assert "'=FORMULA()" in client.get('/api/conferences/harbor/export').text

def test_durable_worker_and_job_actions(client,monkeypatch):
    from endless_tuna.collection import CollectionError
    def unsupported(*args,**kwargs):
        raise CollectionError('LAS configuration required for unsupported metadata source')
    monkeypatch.setattr('endless_tuna.worker.fetch_bytes',unsupported)
    added=create(client); jid=added['job_id']; h={'X-Collection':'real'}
    assert tick('real')
    job=client.get('/api/jobs',headers=h).json()[0]
    assert job['status']=='failed' and job['progress']==0 and job['attempts']==1
    assert 'LAS' in job['message']
    assert client.post(f'/api/jobs/{jid}/resume',headers=h,json={}).status_code==200
    assert tick('real')
    assert client.get('/api/jobs',headers=h).json()[0]['attempts']==2
    assert client.post(f'/api/jobs/{jid}/retry',headers=h,json={}).status_code==200
    assert client.post(f'/api/jobs/{jid}/cancel',headers=h,json={}).status_code==200
    assert not tick('real')
    assert client.post(f'/api/jobs/{jid}/cancel',headers=h,json={}).status_code==409
    client.post(f'/api/jobs/{jid}/resume',headers=h,json={})
    with db.connect('real') as con:
        con.execute("UPDATE jobs SET status='running',lease_until=? WHERE id=?",(time.time()-10,jid))
    assert tick('real')
    assert client.get('/api/papers',headers=h).json()==[]

def test_validation_and_diagnostics(client):
    assert client.get('/api/conferences',headers={'X-Collection':'other'}).status_code==400
    assert client.get('/api/papers/missing').status_code==404
    assert client.post('/api/conferences',json={'name':'  ','year':2026,'track':'x','source_url':'file:///tmp/file'}).status_code==422
    settings=client.get('/api/settings').json()
    assert settings['las']['inference_enabled'] is False
    assert 'LAS_BASE_URL' not in str(settings)

def test_organization_search_is_preserved_in_detail_export(client):
    params='organization=Northstar%20Lab'
    assert len(client.get('/api/papers?edition=harbor&'+params).json())==1
    assert len(client.get('/api/conferences/harbor/export?format=json&'+params).json()['papers'])==1

def test_worker_stops_when_cancelled_during_step(client,monkeypatch):
    added=create(client)
    def cancel(*args,**kwargs):
        with db.connect('real') as con:
            con.execute("UPDATE jobs SET status='cancelled',lease_token=NULL WHERE id=?",(added['job_id'],))
        return b'{"papers":[{"title":"Test title"}]}', 'https://example.org/papers'
    monkeypatch.setattr('endless_tuna.worker.fetch_bytes',cancel)
    assert tick('real')
    job=client.get('/api/jobs',headers={'X-Collection':'real'}).json()[0]
    assert job['status']=='cancelled' and job['progress']==0

def test_migrations_idempotent(client):
    db.initialize('demo')
    db.initialize('real')
    assert len(client.get('/api/papers').json())==9
    with db.connect() as con:
        assert con.execute('SELECT count(*) FROM migrations').fetchone()[0]==7
        assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
