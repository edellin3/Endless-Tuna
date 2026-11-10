import io
import json
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from endless_tuna import db
from endless_tuna.main import app
from endless_tuna.pipeline_store import index_pages,upsert_paper
from endless_tuna.collection import Metadata,Person
from endless_tuna.enrichment import insert_assertion,AssertionInput
from endless_tuna.enrichment_api import review_assertion,AssertionReview


@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    with TestClient(app) as client:yield client


def test_case_phrases_terms_punctuation_and_metadata(session):
    assert [p['id'] for p in session.get('/api/papers?q=ROBOTICS').json()]==[p['id'] for p in session.get('/api/papers?q=robotics').json()]
    phrase=session.get('/api/papers',params={'q':'"shared navigation"'}).json()
    assert phrase and all('shared navigation' in p['abstract'] for p in phrase)
    assert session.get('/api/papers',params={'q':'"navigation shared"'}).json()==[]
    # Terms can match across conference metadata and paper text, always with AND semantics.
    result=session.get('/api/papers',params={'q':'Harbor "delicate ocean"'}).json()
    assert [p['id'] for p in result]==['harbor-1']
    assert {'conference','title'}<={r['kind'] for r in result[0]['match_reasons']}
    for q in ['robotics ) OR *','"unterminated phrase','title:robotics','NEAR(foo bar)','""','---:()']:
        assert session.get('/api/search/conferences',params={'q':q}).status_code==200
    assert session.get('/api/papers?q=Harbor').json()
    assert session.get('/api/papers?q=Harbor%20unfindableword').json()==[]
    assert session.get('/api/papers?q=Harbor%20ocean').json()==session.get('/api/papers?q=Harbor-ocean').json()


def test_terms_across_pages_versioned_reasons_and_stable_pages(session):
    with db.connect() as con:index_pages(con,'harbor-0','harbor-0-pdf',['Uniquequokka appears here.','Remotezebra appears on a different page.'])
    result=session.get('/api/search/papers',params={'q':'uniquequokka remotezebra','page_size':1}).json()
    assert result['total']==1 and result['items'][0]['id']=='harbor-0'
    assert {int(p['page']) for p in result['items'][0]['matching_pages']}=={1,2}
    ids=[]
    for page in range(1,4):
        result=session.get('/api/search/conferences',params={'page':page,'page_size':1}).json()
        ids.extend(r['id'] for r in result['items'])
    assert len(ids)==len(set(ids))==3
    again=[r['id'] for r in session.get('/api/conferences').json()]
    assert ids==again
    empty=session.get('/api/search/conferences',params={'page':999,'page_size':1}).json()
    assert empty['items']==[] and empty['total']==3


def test_metadata_index_updates_and_duplicate_memberships(session):
    with db.connect() as con:
        con.execute("UPDATE series SET name='Searchable Seastar Symposium' WHERE id='harbor'")
        con.execute("UPDATE editions SET description='Transparent coral evidence' WHERE id='harbor'")
        con.execute("UPDATE tracks SET name='Special Reef Track' WHERE id='harbor-main'")
        con.execute("INSERT INTO tracks VALUES('another-harbor-track','harbor','Additional Track')")
        con.execute("INSERT INTO paper_editions VALUES('harbor-0','harbor','another-harbor-track','https://example.org/paper','https://example.org/inventory',0)")
    result=session.get('/api/search/conferences',params={'q':'seastar "Reef Track"'}).json()
    assert result['total']==1 and result['items'][0]['matching_count']==3
    assert len(session.get('/api/papers?edition=harbor&q=coral').json())==3


def test_verified_country_filter_excludes_unverified_locations(session):
    with db.connect() as con:
        aff,_=insert_assertion(con,'a1',AssertionInput(kind='affiliation',value='Tidal Research Institute',paper_id='harbor-0',source_url='https://example.org/evidence',excerpt='Mira Chen: Tidal Research Institute, Canada.'))
        loc,_=insert_assertion(con,'a1',AssertionInput(kind='organization_country',value='Canada',organization='Tidal Research Institute',paper_id='harbor-0',source_url='https://example.org/evidence',excerpt='Tidal Research Institute, Canada.'))
    assert session.get('/api/search/conferences?country=Canada').json()['total']==0
    with db.connect() as con:
        review_assertion(con,aff,AssertionReview(action='confirm',note='Fixture evidence verified.'))
        review_assertion(con,loc,AssertionReview(action='confirm',note='Fixture country verified.'))
    result=session.get('/api/search/papers?country=Canada&year=2025&pdf=yes&review=confirmed').json()
    assert result['total']==1 and result['items'][0]['id']=='harbor-0'
    assert 'Canada' in session.get('/api/filters').json()['countries']


def test_workbook_scopes_relationships_evidence_and_formula_injection(session):
    with db.connect() as con:
        con.execute("UPDATE papers SET title='  =HYPERLINK(\"malicious\")' WHERE id='harbor-0'")
        con.execute("UPDATE authors SET name='@external author' WHERE id='a1'")
        con.execute("UPDATE organizations SET name='+external organization' WHERE id='Northstar Lab'")
    response=session.post('/api/exports/workbook',json={'scope':'conference','edition_id':'harbor'}).json()
    assert response['included_papers']==3
    download=session.get(response['download_url']);assert download.status_code==200
    wb=load_workbook(io.BytesIO(download.content),read_only=True,data_only=False)
    assert wb.sheetnames==['Conferences','Papers','Paper Authors','Affiliations','Sources','Missing PDFs','Review Queue']
    def records(name):
        data=list(wb[name].values);return [dict(zip(data[0],row)) for row in data[1:]]
    papers=records('Papers');authors=records('Paper Authors');conferences=records('Conferences')
    assert {p['paper_id'] for p in papers}=={'harbor-0','harbor-1','harbor-2'}
    assert all(a['paper_id'] in {p['paper_id'] for p in papers} for a in authors)
    assert all(p['edition_id'] in {c['edition_id'] for c in conferences} for p in papers)
    assert all(s['source_url'] for s in records('Sources') if s['kind']=='membership')
    assert len(records('Missing PDFs'))==2
    for sheet in wb:
        for row in sheet:
            assert all(cell.data_type!='f' for cell in row)
    assert next(p['title'] for p in papers if p['paper_id']=='harbor-0').startswith("'")
    assert next(a['original_author_name'] for a in authors if a['author_id']=='a1').startswith("'")
    filtered=session.post('/api/exports/workbook',json={'scope':'filtered','edition_id':'harbor','filters':{'pdf':'yes'}}).json()
    assert filtered['included_papers']==1
    allrows=session.post('/api/exports/workbook',json={'scope':'all','edition_id':'harbor','filters':{'q':'impossible'}}).json()
    assert allrows['included_papers']==9


def test_zip_scope_manifest_missing_report_and_path_safety(session):
    with db.connect() as con:
        con.execute("UPDATE papers SET title='../../unsafe title' WHERE id='harbor-0'")
        con.execute("UPDATE downloads SET path='../real.sqlite3' WHERE paper_id='harbor-1'")
    report=session.post('/api/exports/pdf-bundles',json={'scope':'conference','edition_id':'harbor','max_bundle_mb':1}).json()
    assert report['selected_papers']==3 and report['included_papers']==1 and report['missing_papers']==2
    part=report['parts'][0];raw=session.get(part['download_url']).content
    assert len(raw)==part['size_bytes'] and len(raw)<=1_000_000
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert 'manifest.json' in archive.namelist() and 'missing-files.csv' in archive.namelist()
        assert all(not name.startswith('/') and '..' not in name.split('/') for name in archive.namelist())
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['scope']['all_result_pages'] is True
        assert {item['paper_id'] for item in manifest['items']}=={'harbor-0','harbor-1','harbor-2'}
        item=next(i for i in manifest['items'] if i['status']=='included')
        assert archive.read(item['archive_name']).startswith(b'%PDF-') and item['sha256']
        assert len(archive.read('missing-files.csv').decode().splitlines())==3


def test_zip_splitting_size_limits_and_oversize_reports(session):
    folder=db.DATA/'demo-pdfs'
    # Existing valid PDF structure plus harmless trailing bytes creates deterministic split fixtures.
    raw=(folder/'harbor-0.pdf').read_bytes()
    for pid in ('harbor-0','harbor-1','harbor-2'):
        (folder/(pid+'-large.pdf')).write_bytes(raw+b'\n%'+b'x'*600000)
        with db.connect() as con:con.execute("UPDATE downloads SET status='available',path=?,sha256=NULL WHERE paper_id=?",(pid+'-large.pdf',pid))
    report=session.post('/api/exports/pdf-bundles',json={'scope':'conference','edition_id':'harbor','max_bundle_mb':1}).json()
    assert len(report['parts'])==3 and report['included_papers']==3
    assert all(p['size_bytes']<=1_000_000 for p in report['parts'])
    combined=[]
    for part in report['parts']:
        with zipfile.ZipFile(io.BytesIO(session.get(part['download_url']).content)) as archive:
            manifest=json.loads(archive.read('manifest.json'));assert manifest['parts']==3
            combined.extend(i['paper_id'] for i in manifest['items'])
    assert len(combined)==len(set(combined))==3
    (folder/'harbor-0-large.pdf').write_bytes(raw+b'\n%'+b'x'*1_100_000)
    oversized=session.post('/api/exports/pdf-bundles',json={'scope':'conference','edition_id':'harbor','max_bundle_mb':1}).json()
    assert oversized['included_papers']==2 and oversized['missing_papers']==1


def test_export_metadata_and_files_survive_new_client_and_expiration(session):
    part=session.post('/api/exports/workbook',json={'scope':'filtered','filters':{'pdf':'yes'}}).json()
    with TestClient(app) as restarted:
        assert restarted.get(part['download_url']).status_code==200
    with db.connect() as con:con.execute('UPDATE export_files SET expires=0 WHERE id=?',(part['id'],))
    assert session.get(part['download_url']).status_code==404
    assert session.get('/api/exports/files/invalid?collection=demo').status_code==404


def test_export_collection_isolation_and_empty_workbook(session):
    real=session.post('/api/exports/workbook',headers={'X-Collection':'real'},json={'scope':'all'}).json()
    assert real['included_papers']==0
    assert session.get(real['download_url']).status_code==200
    assert session.get(real['download_url'].replace('collection=real','collection=demo')).status_code==404
    assert session.post('/api/exports/workbook',json={'scope':'conference'}).status_code==422


def test_invalid_bundle_configuration_is_a_clear_error(session,monkeypatch):
    monkeypatch.setenv('TUNA_ZIP_MAX_MB','invalid')
    response=session.post('/api/exports/pdf-bundles',json={'scope':'all'})
    assert response.status_code==422 and 'TUNA_ZIP_MAX_MB' in response.json()['detail']
