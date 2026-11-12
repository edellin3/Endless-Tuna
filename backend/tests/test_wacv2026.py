"""Fictional fixtures matching inspected WACV HTML/JSON. All traffic is mocked."""
import copy
import json
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db,worker,intake,discovery
from endless_tuna.main import app
from endless_tuna.adapters import adapter_for
from endless_tuna.collection import CollectionError
from endless_tuna.wacv2026 import HOME,INDEX,LISTING,FEED,GROUP,WACV2026,parse_program

PAGE=b'''<script>start("/static/virtual/data/wacv-2026-orals-posters.json",false,"/static/virtual/data/wacv-2026-abstracts.json",true)</script><noscript><ul><li><a href="/virtual/2026/poster/20">Fictional navigation paper</a></li><li><a href="/virtual/2026/poster/10">Fictional visual study</a></li></ul></noscript>'''
HOME_PAGE=b'<a href="/virtual/2026/index.html">Conference Site</a>'
INDEX_PAGE=b'<a href="/virtual/2026/papers.html">Papers</a>'
REAL={'X-Collection':'real'}


def poster(id,title='Fictional visual study'):
    return {'id':id,'sourceid':id+100,'eventtype':'Poster','visible':True,'decision':'Accept Poster','sourceurl':GROUP,
            'name':title,'abstract':'Fictional evidence-backed abstract.','authors':[{'fullname':'Zed Fixture','institution':'Profile data must not become affiliation evidence'},{'fullname':'Alex Fixture'}],
            'paper_pdf_url':None,'url':'https://project.example/','eventmedia':[{'name':'Slides','type':'PDF','uri':'https://files.example/slides.pdf','visible':True},{'name':'Poster','uri':'https://files.example/poster.pdf'}]}


def rows():
    oral=poster(99);oral.update(eventtype='Oral',sourceid=-110,related_events_ids=[10])
    return [poster(20,'Fictional navigation paper'),oral,poster(10)]


def feed(items=None):
    items=items if items is not None else rows()
    return json.dumps({'results':items,'count':len(items),'next':None,'previous':None}).encode()


def fetch(url,**kwargs):
    lookup={HOME:HOME_PAGE,INDEX:INDEX_PAGE,LISTING:PAGE,FEED:feed()}
    if url.rstrip('/') not in lookup:raise AssertionError('Unexpected source request: '+url)
    return lookup[url.rstrip('/')],url


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    with TestClient(app) as client:yield client


@pytest.mark.parametrize('url',[HOME,HOME+'/',INDEX,LISTING])
def test_all_entry_points_reach_same_official_inventory(url):
    adapter=adapter_for(url)
    assert isinstance(adapter,WACV2026)
    inv=adapter.inventory(url,fetch)
    assert inv.url==LISTING and inv.official_count==2
    assert [r.identifiers['wacv-program-event'] for r in inv.records]==['10','20']
    assert [a.name for a in inv.records[0].authors]==['Zed Fixture','Alex Fixture']
    assert all(a.organizations==[] for r in inv.records for a in r.authors)
    assert inv.records[0].identifiers['wacv-oral-event']=='99'
    assert all(r.pdf_url is None and r.year==2026 and r.inventory_url==FEED for r in inv.records)
    assert inv.records[0].abstract=='Fictional evidence-backed abstract.'


def test_equal_titles_never_merge_distinct_official_paper_ids():
    items=rows();items[0]['name']=items[2]['name']
    inv=parse_program(feed(items),PAGE)
    assert inv.official_count==2 and len({r.source_url for r in inv.records})==2


@pytest.mark.parametrize('mutation',[
    lambda data:data.update(next='https://example.org/page2'),
    lambda data:data.update(count=999),
    lambda data:data['results'][0].update(sourceurl='workshop'),
    lambda data:data['results'][0].update(id=True),
    lambda data:data['results'][0].update(sourceid=110),
    lambda data:data['results'][1].update(related_events_ids=[777]),
    lambda data:data['results'][0].update(paper_pdf_url='http://127.0.0.1/private.pdf'),
    lambda data:data['results'][0].update(paper_pdf_url='https://wacv.thecvf.com/media/slides.pdf'),
])
def test_changed_incomplete_or_unsafe_feeds_fail_truthfully(mutation):
    data=json.loads(feed());mutation(data)
    with pytest.raises(CollectionError):parse_program(json.dumps(data).encode(),PAGE)


def test_page_and_feed_membership_must_agree():
    with pytest.raises(CollectionError):parse_program(feed(),PAGE.replace(b'/poster/20',b'/poster/21'))
    with pytest.raises(CollectionError):parse_program(feed(),b'<h1>Login</h1>')


@pytest.mark.parametrize('url',['https://wacv.thecvf.com/Conferences/2025','https://wacv.thecvf.com/virtual/2026/workshops.html','https://lookalike.example/virtual/2026/papers.html'])
def test_other_editions_workshops_and_hosts_are_not_silently_supported(url):
    with pytest.raises(CollectionError):adapter_for(url)


def test_only_inspected_feed_and_homepage_chain_are_followed():
    for source in [HOME,LISTING]:
        with pytest.raises(CollectionError):WACV2026().inventory(source,lambda url,**k:(b'<a href="https://evil.example/">Papers</a>',url))
    def redirect(url,**k):
        if url==FEED:return feed(),'https://evil.example/feed.json'
        return fetch(url,**k)
    with pytest.raises(CollectionError):WACV2026().inventory(LISTING,redirect)
    with pytest.raises(CollectionError):adapter_for(HOME,'csv')


def test_missing_name_slot_preserves_author_order_with_review_warning():
    items=rows();items[2]['authors'][0]['fullname']=''
    inv=parse_program(feed(items),PAGE)
    assert inv.records[0].authors[0].name=='[Name missing in official source]'
    assert inv.records[0].authors[1].name=='Alex Fixture'
    assert inv.records[0].source_warnings


def test_homepage_intake_saves_titles_then_separate_pdf_job(client,monkeypatch):
    calls=[]
    def track(url,**k):calls.append(url);return fetch(url,**k)
    monkeypatch.setattr(intake,'fetch_bytes',track)
    preview=client.post('/api/intake/preview',headers=REAL,json={'url':HOME}).json()
    assert preview['ok'] and preview['name']=='WACV' and preview['year']==2026 and preview['listed_count']==2
    assert preview['source_url']==LISTING and set(calls)=={HOME,INDEX,LISTING,FEED}
    assert client.get('/api/papers',headers=REAL).json()==[]
    created=client.post('/api/intake/start',headers=REAL,json={'preview_id':preview['preview_id'],'name':'Fictional WACV fixture','year':2026,'full_collection':True}).json()
    def forbidden(*a,**k):raise AssertionError('Title-only worker must not fetch')
    monkeypatch.setattr(worker,'fetch_bytes',forbidden)
    worker.tick('real',created['job_id'])
    detail=client.get('/api/conferences/'+created['id'],headers=REAL).json()
    assert detail['coverage']['inventory_complete'] and detail['coverage']['pdfs']==0 and len(detail['papers'])==2
    assert detail['tracks'][0]['name']=='Main Conference'
    assert len(client.get('/api/papers').json())==9
    assert client.get('/api/authors',headers=REAL).json()[0]['paper_count']==1  # same names are separate identities per paper
    from tests.acceptance_fixture import fixture_pdf
    from endless_tuna.resolution import Candidate
    pdf=fixture_pdf()
    def resolve(record,*a,**k):return Candidate('https://files.example/paper.pdf',record.title,[p.name for p in record.authors],'arxiv:fixture'),[],None
    monkeypatch.setattr(worker,'resolve',resolve)
    monkeypatch.setattr(worker,'fetch_bytes',lambda url,**k:(pdf,url))
    queued=client.post('/api/conferences/'+created['id']+'/pdfs',headers=REAL,json={'paper_limit':1}).json()
    worker.tick('real',queued['job_id'])
    detail=client.get('/api/conferences/'+created['id'],headers=REAL).json()
    assert detail['coverage']['pdfs']==1 and detail['coverage']['inventory_complete'] and len(detail['papers'])==2


def test_advanced_form_accepts_homepage_with_auto_and_guards_real_year(client):
    body={'source_url':HOME,'name':'Fictional WACV fixture','year':2026,'track':'Main'}
    assert client.post('/api/conferences',json=body).status_code==422
    assert client.post('/api/conferences',headers=REAL,json={**body,'year':2025}).status_code==422
    assert client.post('/api/conferences',headers=REAL,json={**body,'adapter':'csv'}).status_code==422
    response=client.post('/api/conferences',headers=REAL,json=body)
    assert response.status_code==201,response.text
    with db.connect('real') as con:
        row=con.execute('SELECT * FROM editions').fetchone();job=con.execute('SELECT * FROM jobs').fetchone()
        assert row['source_url']==LISTING and row['adapter']=='wacv-2026-program' and job['paper_limit']==10


def test_discovery_source_check_uses_wacv_collector(client,monkeypatch):
    monkeypatch.setattr(discovery,'fetch_bytes',fetch)
    result=client.get('/api/discovery/conferences?q=WACV&publisher=CVF').json()
    assert result['total']==1 and result['items'][0]['adapter']=='wacv-2026-program'
    checked=client.post('/api/discovery/inspect',headers=REAL,json={'source_url':HOME}).json()
    assert checked['ok'] and checked['official_count']==2 and checked['year']==2026 and checked['pdf_status']=='not_checked'
