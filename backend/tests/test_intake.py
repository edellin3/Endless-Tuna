"""Link-first title collection and explicit PDF retrieval. Offline fixtures only."""
import json
import time
import pytest
from fastapi.testclient import TestClient
from endless_tuna.main import app
from endless_tuna import db,intake,worker
from endless_tuna.collection import CollectionError,Metadata,Person
from endless_tuna.resolution import openalex_candidates,resolve
from tests.test_discovery import INVENTORY,DETAIL,VOLUME,DIRECTORY

REAL={'X-Collection':'real'}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    monkeypatch.delenv('TUNA_SEARCH_ENDPOINT',raising=False)
    with TestClient(app) as client:yield client


def preview(client,monkeypatch,source=VOLUME):
    monkeypatch.setattr(intake,'fetch_bytes',lambda url,**k:(INVENTORY,url))
    value=client.post('/api/intake/preview',headers=REAL,json={'url':source})
    assert value.status_code==200,value.text
    assert value.json()['ok'],value.text
    return value.json()


def start(client,value,all=True):
    response=client.post('/api/intake/start',headers=REAL,json={'preview_id':value['preview_id'],'name':'Fictional source fixture','year':2024,'full_collection':all})
    assert response.status_code==201,response.text
    return response.json()


def test_supported_link_detects_metadata_preview_and_no_collection(client,monkeypatch):
    result=preview(client,monkeypatch)
    assert result['year']==2024 and result['listed_count']==2 and result['adapter']=='pmlr-volume'
    assert result['titles']==['Fictional sample robot','Fictional sensor study']
    assert client.get('/api/papers',headers=REAL).json()==[]
    assert client.get('/api/jobs',headers=REAL).json()==[]
    assert len(client.get('/api/papers').json())==9
    assert not list(db.DATA.glob('real-pdfs/*.pdf'))


def test_titles_only_then_explicit_pdf_stage(client,monkeypatch):
    result=preview(client,monkeypatch);created=start(client,result)
    def forbidden(*a,**k):raise AssertionError('Title-only job must not fetch any paper pages or PDFs')
    monkeypatch.setattr(worker,'fetch_bytes',forbidden)
    assert worker.tick('real',created['job_id'])
    detail=client.get('/api/conferences/'+created['id'],headers=REAL).json()
    assert len(detail['papers'])==2 and detail['coverage']['inventory_complete'] and detail['coverage']['pdfs']==0
    job=client.get('/api/jobs',headers=REAL).json()[0]
    assert job['kind']=='inventory' and job['status']=='complete' and job['stages'][0]['completed']==2
    status=client.get('/api/conferences/'+created['id']+'/workflow',headers=REAL).json()
    assert status['coverage']['missing_pdfs']==2
    from tests.acceptance_fixture import fixture_pdf
    raw=fixture_pdf();calls=[]
    def fetch(url,**k):
        calls.append(url)
        if url.startswith(VOLUME):return DETAIL,url
        return raw,url
    monkeypatch.setattr(worker,'fetch_bytes',fetch)
    queued=client.post('/api/conferences/'+created['id']+'/pdfs',headers=REAL,json={'paper_limit':1})
    assert queued.status_code==200,queued.text
    assert queued.json()['selected_papers']==1
    assert worker.tick('real',queued.json()['job_id'])
    detail=client.get('/api/conferences/'+created['id'],headers=REAL).json()
    assert detail['coverage']['pdfs']==1 and detail['coverage']['inventory_complete']
    assert len(detail['papers'])==2 and VOLUME not in calls
    assert len(client.get('/api/papers').json())==9


def test_scope_defaults_expiry_isolation_and_duplicates(client,monkeypatch):
    result=preview(client,monkeypatch)
    request={'preview_id':result['preview_id'],'name':'Fictional fixture','year':2024}
    assert client.post('/api/intake/start',json=request).status_code==422
    assert client.post('/api/intake/start',headers=REAL,json={**request,'year':2025}).status_code==422
    first=client.post('/api/intake/start',headers=REAL,json=request).json()
    second=client.post('/api/intake/start',headers=REAL,json=request).json()
    assert second['existing'] and second['id']==first['id']
    with db.connect('real') as con:
        assert con.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
        assert con.execute('SELECT paper_limit FROM jobs').fetchone()[0]==10
        con.execute('UPDATE intake_previews SET created=0')
    assert client.post('/api/intake/start',headers=REAL,json=request).status_code==410
    assert client.post('/api/conferences/'+first['id']+'/pdfs',headers=REAL,json={}).status_code==409


def test_homepage_suggestions_do_not_claim_inventory(client,monkeypatch):
    raw=b'<title>Fixture Conference 2024</title><nav><a href="/accepted">Accepted papers</a></nav>'
    monkeypatch.setattr(intake,'fetch_bytes',lambda url,**k:(raw,url))
    result=client.post('/api/intake/preview',headers=REAL,json={'url':'https://conference.example/'}).json()
    assert not result['ok'] and result['suggestions']==[{'label':'Accepted papers','url':'https://conference.example/accepted'}]
    assert client.get('/api/papers',headers=REAL).json()==[]


def test_corl_homepage_suggests_real_proceedings_not_guessed_papers(client,monkeypatch):
    def fetch(url,**k):return (DIRECTORY if url=='https://proceedings.mlr.press/' else b'<h1>CoRL 2024</h1>'),url
    monkeypatch.setattr(intake,'fetch_bytes',fetch)
    result=client.post('/api/intake/preview',headers=REAL,json={'url':'https://2024.corl.org/'}).json()
    assert not result['ok'] and result['suggestions'][0]['url']==VOLUME
    assert 'titles' not in result


def test_generic_list_and_direct_pdf_are_real_links_not_navigation(client,monkeypatch):
    raw=b'<h1>Fictional Conference 2024</h1><nav><a href="/about">About</a></nav><article data-paper="1"><h2><a href="https://files.example/fixture.pdf">Fictional research title</a></h2></article>'
    monkeypatch.setattr(intake,'fetch_bytes',lambda url,**k:(raw,url))
    result=client.post('/api/intake/preview',headers=REAL,json={'url':'https://conference.example/accepted'}).json()
    assert result['ok'] and result['official_count'] is None and result['listed_count']==1
    assert result['adapter']=='linked-paper-list' and result['year']==2024
    created=start(client,result)
    monkeypatch.setattr(worker,'fetch_bytes',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No fetching during list save')))
    assert worker.tick('real',created['job_id'])
    assert not client.get('/api/conferences/'+created['id'],headers=REAL).json()['coverage']['inventory_complete']


@pytest.mark.parametrize('url',['http://localhost/','https://user:password@example.org/','http://169.254.169.254/latest'])
def test_invalid_links_never_fetch(client,monkeypatch,url):
    def fail(*a,**k):raise AssertionError('Invalid URL fetched')
    monkeypatch.setattr(intake,'fetch_bytes',fail)
    assert not client.post('/api/intake/preview',headers=REAL,json={'url':url}).json()['ok']


def oa_payload(title='Fictional research title',names=('First Fixture','Second Fixture'),url='https://repository.example/paper.pdf'):
    return json.dumps({'results':[{'id':'https://openalex.org/W123','title':title,'authorships':[{'raw_author_name':n} for n in names],'locations':[{'is_oa':True,'pdf_url':url,'version':'acceptedVersion'},{'is_oa':False,'pdf_url':'https://closed.example/paper.pdf'}]}]}).encode()


def test_openalex_metadata_matching_cache_and_private_url_rejection(client):
    record=Metadata(title='Fictional research title',authors=[Person(name='First Fixture'),Person(name='Second Fixture')])
    calls=[]
    def fetch(url,**k):calls.append(url);return oa_payload(),url
    assert len(openalex_candidates(record,'real',fetch))==1
    assert len(openalex_candidates(record,'real',fetch))==1 and len(calls)==1
    with db.connect('real') as con:con.execute('DELETE FROM resolution_cache')
    rows=openalex_candidates(record,'real',lambda url,**k:(oa_payload(url='http://127.0.0.1/private.pdf'),url))
    assert rows==[]


def test_wider_search_accepts_only_complete_title_and_author_evidence(client,monkeypatch):
    record=Metadata(title='Fictional research title',authors=[Person(name='First Fixture'),Person(name='Second Fixture')])
    def fetch(url,**k):return (b'<feed xmlns="http://www.w3.org/2005/Atom"/>' if 'arxiv' in url else oa_payload()),url
    selected,candidates,error=resolve(record,'real',fetch,wide=True)
    assert selected and selected.url=='https://repository.example/paper.pdf' and selected.version.startswith('openalex:')
    with db.connect('real') as con:con.execute('DELETE FROM resolution_cache')
    def partial(url,**k):return (b'<feed xmlns="http://www.w3.org/2005/Atom"/>' if 'arxiv' in url else oa_payload(names=('First Fixture',))),url
    monkeypatch.setattr('endless_tuna.resolution.time.sleep',lambda _:None)
    selected,candidates,error=resolve(record,'real',partial,wide=True)
    assert selected is None and len(candidates)==1
    assert 'Ambiguous' in error


def test_markdown_link_input_is_supported(client,monkeypatch):
    result=preview(client,monkeypatch,source=f'[{VOLUME}]({VOLUME})')
    assert result['source_url']==VOLUME


def test_blocked_official_pdf_falls_through_to_open_access_copy(client,monkeypatch):
    result=preview(client,monkeypatch);created=start(client,result)
    worker.tick('real',created['job_id'])
    from tests.acceptance_fixture import fixture_pdf
    raw=fixture_pdf();calls=[]
    record_title='Fictional sample robot'
    monkeypatch.setattr('endless_tuna.resolution.time.sleep',lambda _:None)
    def fetch(url,**kwargs):
        calls.append(url)
        if url.startswith(VOLUME):return DETAIL,url
        if url=='https://files.example/fixture.pdf':raise CollectionError('Source returned HTTP 403.')
        if 'export.arxiv.org' in url:return b'<feed xmlns="http://www.w3.org/2005/Atom"/>',url
        if url.startswith('https://api.openalex.org/works?'):
            return oa_payload(title=record_title,names=('Zed Fixture','Alex Fixture')),url
        if url=='https://repository.example/paper.pdf':return raw,url
        raise AssertionError(url)
    monkeypatch.setattr(worker,'fetch_bytes',fetch)
    # Select one known paper deterministically through its saved snapshot.
    with db.connect('real') as con:
        target=con.execute('SELECT id FROM papers WHERE title=?',(record_title,)).fetchone()[0]
        other=con.execute('SELECT id FROM papers WHERE title!=?',(record_title,)).fetchone()[0]
        con.execute("INSERT INTO downloads(id,paper_id,status,path,parse_status) VALUES('ignore-other',?,'available','ignore.pdf','indexed')",(other,))
        folder=db.DATA/'real-pdfs';folder.mkdir(exist_ok=True);(folder/'ignore.pdf').write_bytes(raw)
    queued=client.post('/api/conferences/'+created['id']+'/pdfs',headers=REAL,json={}).json()
    worker.tick('real',queued['job_id'])
    paper=client.get('/api/papers/'+target,headers=REAL).json()
    assert any(d['status']=='available' and d['source_url']=='https://repository.example/paper.pdf' and d['version'].startswith('openalex:') for d in paper['downloads'])
    assert calls.count('https://files.example/fixture.pdf')==1


def test_inaccessible_copies_remain_retryable_without_losing_titles(client,monkeypatch):
    result=preview(client,monkeypatch);created=start(client,result)
    worker.tick('real',created['job_id'])
    def fetch(url,**kwargs):
        if url.startswith(VOLUME):return DETAIL,url
        if url.startswith('https://api.openalex.org/works?'):return b'{"results":[]}',url
        if 'export.arxiv.org' in url:return b'<feed xmlns="http://www.w3.org/2005/Atom"/>',url
        raise CollectionError('Source returned HTTP 403.')
    monkeypatch.setattr(worker,'fetch_bytes',fetch)
    monkeypatch.setattr('endless_tuna.resolution.time.sleep',lambda _:None)
    queued=client.post('/api/conferences/'+created['id']+'/pdfs',headers=REAL,json={}).json()
    worker.tick('real',queued['job_id'])
    jobs=client.get('/api/jobs',headers=REAL).json();job=next(j for j in jobs if j['id']==queued['job_id'])
    assert job['status']=='partial' and len(job['failures'])==2
    assert all('403' in f['error'] for f in job['failures'])
    assert len(client.get('/api/papers',headers=REAL).json())==2
    assert client.post('/api/jobs/'+queued['job_id']+'/retry',headers=REAL,json={}).status_code==200
