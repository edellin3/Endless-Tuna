"""One analyst action queues durable title and PDF work; no live network or LAS."""
import json
import threading
import time
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db,intake,worker
from endless_tuna.main import app
from endless_tuna.collection import CollectionError
from tests.test_discovery import VOLUME,INVENTORY,DETAIL
from tests.acceptance_fixture import fixture_pdf

REAL={'X-Collection':'real'}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    monkeypatch.delenv('TUNA_SEARCH_ENDPOINT',raising=False)
    monkeypatch.setattr(intake,'fetch_bytes',lambda url,**kwargs:(INVENTORY,url))
    raw=fixture_pdf()
    monkeypatch.setattr(worker,'fetch_bytes',lambda url,**kwargs:(DETAIL if url.startswith(VOLUME) else raw,url))
    with TestClient(app) as client:yield client


def collect(client,**overrides):
    result=client.post('/api/intake/collect',headers=REAL,json={'url':VOLUME,**overrides})
    assert result.status_code==200,result.text
    assert result.json()['ok'],result.text
    return result.json()


def test_one_action_collects_titles_and_pdfs_without_handoffs(client):
    result=collect(client)
    with db.connect('real') as con:
        job=con.execute('SELECT * FROM jobs').fetchone()
        assert job['kind']=='automatic' and job['paper_limit']==10
        assert json.loads(con.execute('SELECT records FROM job_payloads').fetchone()[0])['records']
    assert worker.tick('real',result['job_id'])
    detail=client.get('/api/conferences/'+result['id'],headers=REAL).json()
    assert len(detail['papers'])==2 and detail['coverage']['pdfs']==2 and detail['coverage']['inventory_complete']
    flow=client.get('/api/conferences/'+result['id']+'/workflow',headers=REAL).json()
    assert flow['jobs'][0]['status']=='complete' and flow['needs_attention']==0
    assert len(client.get('/api/papers').json())==9


def test_titles_are_visible_before_first_pdf_finishes(client,monkeypatch):
    result=collect(client);started=threading.Event();release=threading.Event();raw=fixture_pdf()
    def fetch(url,**kwargs):
        if url.startswith(VOLUME):return DETAIL,url
        started.set();assert release.wait(5)
        return raw,url
    monkeypatch.setattr(worker,'fetch_bytes',fetch)
    task=threading.Thread(target=worker.tick,args=('real',result['job_id']))
    task.start()
    try:
        assert started.wait(5)
        detail=client.get('/api/conferences/'+result['id'],headers=REAL).json()
        assert len(detail['papers'])==2 and detail['coverage']['pdfs']==0
        assert client.get('/api/conferences/'+result['id']+'/workflow',headers=REAL).json()['needs_attention']==0
    finally:release.set();task.join(timeout=10)
    assert not task.is_alive()


def test_double_submission_reuses_active_job_and_completed_pdfs(client):
    first=collect(client);second=collect(client)
    assert first['id']==second['id'] and first['job_id']==second['job_id']
    worker.tick('real',first['job_id'])
    third=collect(client)
    assert third['id']==first['id'] and 'job_id' not in third
    with db.connect('real') as con:
        assert con.execute('SELECT count(*) FROM editions').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM jobs').fetchone()[0]==1


def test_full_conference_scope_requires_explicit_selection(client):
    result=collect(client,full_collection=True)
    with db.connect('real') as con:
        assert con.execute('SELECT paper_limit FROM jobs WHERE id=?',(result['job_id'],)).fetchone()[0] is None


def test_pause_resume_preserves_finished_work_and_ownership(client,monkeypatch):
    result=collect(client);original=worker.process_paper;count=0
    def pause(c,job,token,item,adapter):
        nonlocal count
        original(c,job,token,item,adapter);count+=1
        if count==1:
            with db.connect('real') as con:con.execute("UPDATE jobs SET status='cancelled',lease_token=NULL WHERE id=?",(job['id'],))
    monkeypatch.setattr(worker,'process_paper',pause)
    worker.tick('real',result['job_id'])
    with db.connect('real') as con:
        assert con.execute('SELECT status FROM jobs').fetchone()[0]=='cancelled'
        assert con.execute("SELECT count(*) FROM job_papers WHERE status='done'").fetchone()[0]==1
    assert client.post('/api/jobs/'+result['job_id']+'/resume',headers=REAL,json={}).status_code==200
    monkeypatch.setattr(worker,'process_paper',original)
    worker.tick('real',result['job_id'])
    assert client.get('/api/conferences/'+result['id'],headers=REAL).json()['coverage']['pdfs']==2


def test_unreadable_source_is_actionable_and_creates_no_job(client,monkeypatch):
    monkeypatch.setattr(intake,'fetch_bytes',lambda url,**k:(b'<a href="/papers">Accepted papers</a>',url))
    response=client.post('/api/intake/collect',headers=REAL,json={'url':'https://fixture.example/'})
    assert not response.json()['ok'] and response.json()['suggestions']
    assert client.get('/api/conferences',headers=REAL).json()==[]
    assert client.get('/api/jobs',headers=REAL).json()==[]


def test_missing_year_is_the_only_required_confirmation(client,monkeypatch):
    raw=b'<h1>Fictional Conference</h1><div class="paper"><h2><a href="/paper">Fictional visual study</a></h2></div>'
    monkeypatch.setattr(intake,'fetch_bytes',lambda url,**k:(raw,url))
    result=client.post('/api/intake/collect',headers=REAL,json={'url':'https://fixture.example/accepted'}).json()
    assert result['needs_details'] and result['year'] is None and result['preview_id']
    response=client.post('/api/intake/collect',headers=REAL,json={'url':'https://fixture.example/accepted','preview_id':result['preview_id'],'year':2025,'name':'Fictional Conference'})
    assert response.json()['ok'] and response.json()['job_id']


def test_unresolved_pdfs_preserve_titles_and_report_attention(client,monkeypatch):
    result=collect(client)
    monkeypatch.setattr(worker,'resolve',lambda *a,**k:(None,[],'No free copy found.'))
    worker.tick('real',result['job_id'])
    flow=client.get('/api/conferences/'+result['id']+'/workflow',headers=REAL).json()
    assert flow['needs_attention']==2 and flow['coverage']['inventory_records']==2
    assert flow['jobs'][0]['status']=='partial'
    assert client.post('/api/jobs/'+result['job_id']+'/retry',headers=REAL,json={}).status_code==200
    assert client.get('/api/conferences/'+result['id']+'/workflow',headers=REAL).json()['needs_attention']==0


def test_demo_cannot_start_real_automatic_collection(client):
    assert client.post('/api/intake/collect',json={'url':VOLUME}).status_code==422


def test_program_page_is_kept_separate_from_feed_provenance(client,monkeypatch):
    from tests.test_neurips2026 import PAGE,FEED,ABSTRACTS,poster,data
    from endless_tuna.neurips2026 import LISTING
    def fetch(url,**kwargs):
        if url==LISTING:return PAGE,url
        if url==FEED:return data([poster(10,'FixtureNote')]),url
        if url==ABSTRACTS:return b'{}',url
        raise AssertionError(url)
    monkeypatch.setattr(intake,'fetch_bytes',fetch)
    result=collect(client,url=LISTING)
    with db.connect('real') as con:
        assert con.execute('SELECT source_url FROM editions').fetchone()[0]==LISTING
        record=json.loads(con.execute('SELECT records FROM job_payloads').fetchone()[0])['records'][0]
        assert record['inventory_url']==FEED


def test_continuing_a_sample_keeps_a_previously_complete_title_list(client,monkeypatch):
    first=collect(client,full_collection=True);original=worker.resolve
    monkeypatch.setattr(worker,'resolve',lambda *a,**k:(None,[],'No free copy found.'))
    worker.tick('real',first['job_id'])
    assert client.get('/api/conferences/'+first['id'],headers=REAL).json()['coverage']['inventory_complete']
    monkeypatch.setattr(worker,'resolve',original)
    following=collect(client,paper_limit=1)
    worker.tick('real',following['job_id'])
    detail=client.get('/api/conferences/'+first['id'],headers=REAL).json()
    assert len(detail['papers'])==2 and detail['coverage']['inventory_complete'] and detail['coverage']['pdfs']==1
    flow=client.get('/api/conferences/'+first['id']+'/workflow',headers=REAL).json()
    assert flow['needs_attention']==1  # Historical missing results do not count the newly available file.
