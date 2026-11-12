"""Offline conference discovery and proceedings collection; all records fictional."""
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db, discovery, worker
from endless_tuna.main import app
from endless_tuna.adapters import adapter_for
from endless_tuna.collection import CollectionError
from endless_tuna.proceedings import PMLR, RSS2025

VOLUME = 'https://proceedings.mlr.press/v270/'
PAPER = VOLUME+'fixture25a.html'
DIRECTORY = b'''<ul><li><a href="v270">Volume 270</a> Proceedings of CoRL 2024</li>
<li><a href="v999">Volume 999</a> Fixture Quantum Learning 2023</li>
<li><a href="v270/">Volume 270</a> Proceedings of CoRL 2024</li>
<li><a href="https://evil.example/v555">Volume 555</a> Not official 2024</li>
<li><a href="v555?token=secret">Volume 555</a> Credential URL</li></ul>'''
INVENTORY = b'''<h2>Volume 270: Fictional robotics event, 6-9 November 2024</h2>
<h3>Oral</h3><div class="paper"><p class="title">Fictional sample robot</p><span class="authors">Untrusted listing names</span>
<a href="fixture25a.html">abs</a></div><div class="paper"><p class="title">Fictional sensor study</p><a href="fixture25b.html">abs</a></div>'''
DETAIL = b'''<meta name="citation_title" content="Fictional sample robot"><meta name="citation_author" content="Zed Fixture">
<meta name="citation_author" content="Alex Fixture"><meta name="citation_publication_date" content="2025/01/12">
<meta name="citation_pdf_url" content="https://files.example/fixture.pdf"><meta name="citation_doi" content="10.0000/fixture">
<div id="abstract">Fictional robotics abstract.</div>'''
RSS = 'https://www.roboticsproceedings.org/rss21/'
RSS_LIST = b'''<div class="content"><a href="p001.html">Fictional field robot</a><a href="p001.html">Fictional field robot</a>
<a href="../rss20/p002.html">Wrong edition</a><a href="https://evil.example/rss21/p003.html">Wrong host</a></div>'''
RSS_DETAIL = b'''<meta name="citation_title" content="Fictional field robot"><meta name="citation_author" content="Mira Fixture">
<meta name="citation_pdf_url" content="http://www.roboticsproceedings.org/rss21/p001.pdf">
<div class="content"><p><b>Abstract:</b></p><p style="text-align: justify">Fictional RSS abstract.</p></div>'''


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA', tmp_path)
    monkeypatch.setattr(discovery, '_cache', {'rows': [], 'fetched_at': None, 'attempted_at': 0, 'warning': None})
    with TestClient(app) as client: yield client


def test_starter_search_is_local_and_does_not_create_records(client, monkeypatch):
    def forbidden(*a, **k): raise AssertionError('Starter search must not fetch')
    monkeypatch.setattr(discovery, 'fetch_bytes', forbidden)
    r = client.get('/api/discovery/conferences?q=robotics&year=2024').json()
    assert r['total'] == 1 and r['items'][0]['source_url'] == VOLUME
    assert r['items'][0]['support'] == 'collector_available'
    assert r['items'][0]['inspection_status'] == r['items'][0]['pdf_status'] == 'not_checked'
    with db.connect('real') as con:
        assert con.execute('SELECT count(*) FROM editions').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    assert client.get('/api/discovery/conferences?q=unfindable').json()['total'] == 0


def test_live_directory_cache_filters_pagination_and_literal_terms(client, monkeypatch):
    calls=[]
    def fetch(url, **kwargs): calls.append(url); return DIRECTORY, url
    monkeypatch.setattr(discovery, 'fetch_bytes', fetch)
    result=client.get('/api/discovery/conferences?directory=official&q=quantum&year=2023').json()
    assert result['total'] == 1
    assert result['items'][0]['origin'] == 'Official PMLR directory'
    assert result['fetched_at'] and result['warning'] is None
    assert client.get('/api/discovery/conferences?directory=official&q=conference%20robot').json()['total'] == 1
    result=client.get('/api/discovery/conferences?directory=official&publisher=PMLR&page_size=1&page=999').json()
    assert result['page'] == result['pages'] and len(result['items']) == 1
    assert len(calls) == 1
    assert client.get('/api/discovery/conferences?q=unfindable%20OR%20*').json()['total'] == 0
    assert client.get('/api/discovery/conferences?publisher=unknown').status_code == 422
    assert client.get('/api/discovery/conferences?page_size=1000').status_code == 422


def test_directory_failure_preserves_starters_and_last_good_cache(client, monkeypatch):
    monkeypatch.setattr(discovery, 'fetch_bytes', lambda url, **k: (DIRECTORY, url))
    assert client.get('/api/discovery/conferences?directory=official&q=quantum').json()['total'] == 1
    old = discovery._cache['fetched_at']; discovery._cache['attempted_at'] = 0
    def fail(*a, **k): raise CollectionError('Source returned HTTP 403.')
    monkeypatch.setattr(discovery, 'fetch_bytes', fail)
    result = client.get('/api/discovery/conferences?directory=official&q=quantum').json()
    assert result['total'] == 1 and result['fetched_at'] == old and '403' in result['warning']
    discovery._cache.update(rows=[], attempted_at=0, fetched_at=None)
    result=client.get('/api/discovery/conferences?directory=official').json()
    assert result['total'] == 6 and result['warning'] and result['fetched_at'] is None


def test_directory_rejects_external_redirects_and_unrecognized_structure():
    for raw, final in [(DIRECTORY,'https://evil.example/'),(b'<p>No volumes</p>',discovery.DIRECTORY)]:
        with pytest.raises(CollectionError): discovery.parse_directory(raw,final)
    rows=discovery.parse_directory(DIRECTORY,discovery.DIRECTORY)
    assert len(rows)==2 and all('evil' not in r['source_url'] for r in rows)


def test_pmlr_inventory_hydration_preserves_event_year_and_author_order():
    adapter=adapter_for(VOLUME)
    assert isinstance(adapter,PMLR)
    inventory=adapter.inventory(VOLUME,lambda url,**k:(INVENTORY,url))
    assert inventory.official_count==2 and all(r.year==2024 for r in inventory.records)
    assert inventory.records[0].authors==[]  # actual order comes from paper citation tags
    paper=adapter.hydrate(inventory.records[0],lambda url,**k:(DETAIL,url))
    assert paper.year==2024 and [a.name for a in paper.authors]==['Zed Fixture','Alex Fixture']
    assert paper.abstract=='Fictional robotics abstract.' and paper.identifiers['doi']=='10.0000/fixture'
    assert paper.pdf_url=='https://files.example/fixture.pdf'
    with pytest.raises(CollectionError): adapter_for(VOLUME,'csv')
    with pytest.raises(CollectionError): adapter.inventory(VOLUME,lambda url,**k:(INVENTORY,'https://proceedings.mlr.press/v271/'))
    with pytest.raises(CollectionError): adapter.inventory(VOLUME,lambda url,**k:(b'<div class="paper"><p class="title">Missing link</p></div>',url))
    with pytest.raises(CollectionError): adapter.hydrate(inventory.records[0],lambda url,**k:(DETAIL,'https://evil.example/paper'))


def test_rss_scope_and_pdf_canonicalization():
    adapter=adapter_for(RSS)
    assert isinstance(adapter,RSS2025)
    inv=adapter.inventory(RSS,lambda url,**k:(RSS_LIST,url))
    assert inv.official_count==1 and inv.records[0].year==2025
    paper=adapter.hydrate(inv.records[0],lambda url,**k:(RSS_DETAIL,url))
    assert paper.pdf_url==RSS+'p001.pdf' and paper.abstract=='Fictional RSS abstract.'
    assert [a.name for a in paper.authors]==['Mira Fixture']
    with pytest.raises(CollectionError): adapter_for('https://www.roboticsproceedings.org/rss22/')


def test_inspection_does_not_download_pdfs_or_mutate_collections(client, monkeypatch):
    calls=[]
    def fetch(url, **kwargs): calls.append(url); return INVENTORY, url
    monkeypatch.setattr(discovery,'fetch_bytes',fetch)
    result=client.post('/api/discovery/inspect',json={'source_url':VOLUME}).json()
    assert result['ok'] and result['official_count']==2 and result['year']==2024
    assert result['pdf_status']=='not_checked' and len(calls)==1
    assert len(client.get('/api/papers').json())==9
    assert client.get('/api/papers',headers={'X-Collection':'real'}).json()==[]
    assert client.get('/api/jobs',headers={'X-Collection':'real'}).json()==[]
    assert list(db.DATA.glob('real-pdfs/*.pdf'))==[]


@pytest.mark.parametrize('url',['http://127.0.0.1:8000','https://evil.example/conference','https://proceedings.mlr.press/v270/?token=secret','https://example.org/papers.json'])
def test_inspection_rejects_private_unsupported_and_nonofficial_sources(client,monkeypatch,url):
    def fail(*a,**k): raise AssertionError('Rejected source must not fetch')
    monkeypatch.setattr(discovery,'fetch_bytes',fail)
    assert client.post('/api/discovery/inspect',json={'source_url':url}).json()['ok'] is False


def test_check_failure_is_truthful_and_retryable(client,monkeypatch):
    def fail(*a,**k): raise CollectionError('Source returned HTTP 403.')
    monkeypatch.setattr(discovery,'fetch_bytes',fail)
    result=client.post('/api/discovery/inspect',json={'source_url':VOLUME}).json()
    assert not result['ok'] and result['status']=='unavailable' and '403' in result['message']
    monkeypatch.setattr(discovery,'fetch_bytes',lambda url,**k:(INVENTORY,url))
    assert client.post('/api/discovery/inspect',json={'source_url':VOLUME}).json()['ok']


def test_discovered_source_enters_existing_real_job_pipeline(client,monkeypatch):
    from tests.acceptance_fixture import fixture_pdf
    raw=fixture_pdf()
    def fetch(url,**kwargs):
        if url==VOLUME:return INVENTORY,url
        if url.startswith(VOLUME):return DETAIL,url
        if url=='https://files.example/fixture.pdf':return raw,url
        raise AssertionError('Unexpected fixture request: '+url)
    monkeypatch.setattr(worker,'fetch_bytes',fetch)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    request=dict(name='Fictional PMLR edition',year=2024,track='Published proceedings',source_url=VOLUME,adapter='pmlr-volume',paper_limit=1)
    assert client.post('/api/conferences',json=request).status_code==422
    created=client.post('/api/conferences',headers={'X-Collection':'real'},json=request)
    assert created.status_code==201,created.text
    ids=created.json()
    assert worker.tick('real',ids['job_id'])
    detail=client.get('/api/conferences/'+ids['id'],headers={'X-Collection':'real'}).json()
    assert detail['coverage']['pdfs']==1 and not detail['coverage']['inventory_complete']
    assert len(detail['papers'])==1 and detail['papers'][0]['year']==2024
    assert client.get('/api/discovery/conferences?q=CoRL').json()['items'][0]['existing_edition_id']==ids['id']
    assert len(client.get('/api/papers').json())==9


def test_full_inventory_does_not_claim_full_pdf_coverage(client,monkeypatch):
    from tests.acceptance_fixture import fixture_pdf
    raw=fixture_pdf()
    monkeypatch.delenv('TUNA_SEARCH_ENDPOINT',raising=False)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    def fetch(url,**kwargs):
        if url==VOLUME:return INVENTORY,url
        if url.endswith('fixture25a.html'):return DETAIL,url
        if url.endswith('fixture25b.html'):return DETAIL.replace(b'fixture.pdf',b'missing.pdf').replace(b'Fictional sample robot',b'Fictional sensor study'),url
        if url=='https://files.example/fixture.pdf':return raw,url
        if url=='https://files.example/missing.pdf':raise CollectionError('Source returned HTTP 403.')
        if url.startswith('https://export.arxiv.org/api/query'):return b'<feed xmlns="http://www.w3.org/2005/Atom"/>',url
        raise AssertionError('Unexpected request: '+url)
    monkeypatch.setattr(worker,'fetch_bytes',fetch)
    request=dict(name='Fictional full edition',year=2024,track='Published proceedings',source_url=VOLUME,full_collection=True)
    response=client.post('/api/conferences',headers={'X-Collection':'real'},json=request)
    assert response.status_code==201,response.text
    ids=response.json();assert worker.tick('real',ids['job_id'])
    detail=client.get('/api/conferences/'+ids['id'],headers={'X-Collection':'real'}).json()
    assert len(detail['papers'])==2 and detail['coverage']['inventory_complete']
    assert detail['coverage']['pdfs']==1 and detail['coverage']['official_count']==2
    jobs=client.get('/api/jobs',headers={'X-Collection':'real'}).json()
    assert jobs[0]['status']=='partial' and len(jobs[0]['failures'])==1
    assert '403' in jobs[0]['failures'][0]['error']


def test_mismatched_event_year_fails_without_paper_insertion(client,monkeypatch):
    monkeypatch.setattr(worker,'fetch_bytes',lambda url,**kwargs:(INVENTORY,url))
    response=client.post('/api/conferences',headers={'X-Collection':'real'},json=dict(name='Fictional incorrect event year',year=2025,track='Published proceedings',source_url=VOLUME))
    assert response.status_code==201
    assert worker.tick('real',response.json()['job_id'])
    assert client.get('/api/papers',headers={'X-Collection':'real'}).json()==[]
    job=client.get('/api/jobs',headers={'X-Collection':'real'}).json()[0]
    assert job['status']=='failed' and 'year does not match' in job['message']
