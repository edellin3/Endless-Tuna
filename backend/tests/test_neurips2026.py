import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db, worker
from endless_tuna.main import app
from endless_tuna.collection import CollectionError
from endless_tuna.neurips2026 import NeurIPS2026, LISTING, parse_program
from endless_tuna.adapters import adapter_for

FEED='https://neurips.cc/static/virtual/data/neurips-2026-orals-posters.json'
ABSTRACTS='https://neurips.cc/static/virtual/data/neurips-2026-abstracts.json'
PAGE=b'''<script>start("/static/virtual/data/neurips-2026-orals-posters.json",true,"/static/virtual/data/neurips-2026-abstracts.json",false)</script>'''


def poster(event, note, title='Fictional robot paper', group='https://openreview.net/group?id=NeurIPS.cc/2026/Conference'):
    return {'id':event,'eventtype':'Poster','visible':True,'decision':'Accept (poster)',
            'name':title,'authors':[{'fullname':'Fixture First','institution':'Profile institution, not paper-time evidence'},{'fullname':'Fixture Second'}],
            'sourceurl':group,'paper_url':'https://openreview.net/forum?id='+note,'paper_pdf_url':None,
            'virtualsite_url':f'/virtual/2026/poster/{event}','eventmedia':[]}


def data(rows):return json.dumps({'count':len(rows),'next':None,'previous':None,'results':rows}).encode()


def transport(rows, denied=False, calls=None):
    def fetch(url,**kwargs):
        if calls is not None:calls.append(url)
        if url==LISTING:return PAGE,'https://neurips.cc/virtual/2026/loc/sydney/papers.html'
        if url==FEED:return data(rows),url
        if url==ABSTRACTS:return json.dumps({str(r['id']):'Fictional abstract on robots.' for r in rows}).encode(),url
        if denied and url.startswith('https://openreview.net/pdf?'):raise CollectionError('Source returned HTTP 403. Check source access or retry.')
        if url.startswith('https://export.arxiv.org/api/query?'):return b'<feed xmlns="http://www.w3.org/2005/Atom"/>',url
        pytest.fail('Unexpected mocked request '+url)
    return fetch


@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    monkeypatch.delenv('TUNA_SEARCH_ENDPOINT',raising=False)
    with TestClient(app) as client:yield client


def test_official_script_feed_abstracts_authors_tracks_and_duplicate_presentations():
    one=poster(1,'FictionalA')
    duplicate=copy.deepcopy(one);duplicate['id']=2
    oral=copy.deepcopy(one);oral['eventtype']='Oral'
    dataset=poster(3,'FictionalB',group='https://openreview.net/group?id=NeurIPS.cc/2026/Evaluations_and_Datasets_Track')
    inventory=adapter_for(LISTING).inventory(LISTING,transport([one,duplicate,oral,dataset]))
    assert inventory.official_count==2 and len(inventory.records)==2
    assert {r.track for r in inventory.records}=={'Main Conference','Evaluations and Datasets'}
    assert all([a.name for a in r.authors]==['Fixture First','Fixture Second'] for r in inventory.records)
    assert all(not a.organizations for r in inventory.records for a in r.authors)
    assert all(r.abstract=='Fictional abstract on robots.' and r.inventory_url==FEED for r in inventory.records)
    assert all(r.version.startswith('openreview:') and r.pdf_url.startswith('https://openreview.net/pdf?id=') for r in inventory.records)


@pytest.mark.parametrize('change',['count','pagination','empty','wrong_script','wrong_redirect'])
def test_changed_or_incomplete_official_sources_are_not_called_complete(change):
    row=poster(1,'FictionalA');fetch=transport([row])
    def changed(url,**kwargs):
        raw,final=fetch(url,**kwargs)
        if url==FEED:
            body=json.loads(raw)
            if change=='count':body['count']=2
            if change=='pagination':body['next']='https://neurips.cc/next'
            if change=='empty':body['results']=[];body['count']=0
            raw=json.dumps(body).encode()
        if url==LISTING and change=='wrong_script':raw=b'<script src="https://untrusted.example/feed.json"></script>'
        if url==LISTING and change=='wrong_redirect':final='https://untrusted.example/papers.html'
        return raw,final
    with pytest.raises(CollectionError):NeurIPS2026().inventory(LISTING,changed)


def test_large_author_roster_and_missing_name_are_preserved_and_flagged():
    row=poster(1,'FictionalA');row['authors']=[{'fullname':f'Fictional author {i}'} for i in range(337)]
    row['authors'][55]['fullname']=''
    row['sourceurl']=None
    inventory=parse_program(data([row]),{},FEED)
    record=inventory.records[0]
    assert len(record.authors)==337 and record.authors[56].name=='Fictional author 56'
    assert record.authors[55].name=='[Name missing in official source]'
    assert len(record.source_warnings)==2 and 'position 56' in record.source_warnings[0]
    assert 'Unspecified' in record.track


def test_homepage_auto_routes_2026_to_official_listing_and_requires_real_mode(session):
    body={'name':'NeurIPS 2026','year':2026,'track':'Main research track','source_url':'https://neurips.cc/','full_collection':True}
    assert session.post('/api/conferences',json=body).status_code==422
    result=session.post('/api/conferences',headers={'X-Collection':'real'},json=body)
    assert result.status_code==201,result.text
    with db.connect('real') as con:
        edition=con.execute('SELECT * FROM editions').fetchone();job=con.execute('SELECT * FROM jobs').fetchone()
        assert edition['adapter']=='neurips-2026-program' and edition['source_url']==LISTING
        assert job['paper_limit'] is None
    body['year']=2025;body['source_url']=LISTING
    assert session.post('/api/conferences',headers={'X-Collection':'real'},json=body).status_code==422


def test_full_inventory_is_searchable_and_tracks_remain_separate_when_pdf_access_pauses(session,monkeypatch):
    rows=[poster(i,'Fictional'+str(i),'Fictional robot paper '+str(i)) for i in range(1,4)]
    rows[2]['sourceurl']='https://openreview.net/group?id=NeurIPS.cc/2026/Position_Paper_Track'
    calls=[];monkeypatch.setattr(worker,'fetch_bytes',transport(rows,True,calls))
    # Keep this fixture independent of real arXiv pacing; resolution still uses the actual matcher.
    monkeypatch.setattr('endless_tuna.resolution.time.sleep',lambda _:None)
    result=session.post('/api/conferences',headers={'X-Collection':'real'},json={
        'name':'NeurIPS 2026 fixture','year':2026,'track':'All','source_url':LISTING,'full_collection':True}).json()
    assert worker.tick('real')
    with db.connect('real') as con:
        assert con.execute('SELECT COUNT(*) FROM papers').fetchone()[0]==3
        assert con.execute('SELECT inventory_complete FROM editions').fetchone()[0]==1
        job=con.execute('SELECT * FROM jobs').fetchone()
        assert job['status']=='partial' and '403' in job['message'] and 'searchable' in job['message']
        assert con.execute("SELECT COUNT(*) FROM job_papers WHERE status='pending'").fetchone()[0]==1
        assert con.execute('SELECT COUNT(DISTINCT track_id) FROM paper_editions').fetchone()[0]==2
    found=session.get('/api/search/papers?q=robot',headers={'X-Collection':'real'}).json()
    assert found['total']==3
    detail=session.get('/api/conferences/'+result['id']+'?include_papers=false',headers={'X-Collection':'real'}).json()
    assert detail['coverage']['inventory_records']==3 and 'papers' not in detail
    assert len([u for u in calls if u.startswith('https://openreview.net/pdf?')])==2
    # Resume reuses the saved official inventory, without duplicating canonical papers/authors.
    assert session.post('/api/jobs/'+result['job_id']+'/retry',headers={'X-Collection':'real'}).status_code==200
    calls.clear();assert worker.tick('real')
    assert FEED not in calls
    with db.connect('real') as con:
        assert con.execute('SELECT COUNT(*) FROM papers').fetchone()[0]==3
        assert con.execute('SELECT COUNT(*) FROM authors').fetchone()[0]==6
