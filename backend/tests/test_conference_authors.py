import csv
import io
import pytest
from fastapi.testclient import TestClient
from endless_tuna.main import app
from endless_tuna import db
from endless_tuna.pipeline_store import index_pages


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    with TestClient(app) as client:yield client


def test_extraction_search_export_and_isolation(client):
    with db.connect() as con:
        con.execute("UPDATE downloads SET source_url='https://example.org/paper.pdf' WHERE id='harbor-0-pdf'")
        index_pages(con,'harbor-0','harbor-0-pdf',['Mira Chen: Tidal Research Institute; Northstar Lab\nAlex Rivera: Open Coast Research Center'])
    initial=client.get('/api/conferences/harbor/authors').json()
    assert initial['total']==6
    assert initial['coverage']['with_institutions']==0  # legacy metadata is not PDF evidence
    extracted=client.post('/api/conferences/harbor/authors/extract').json()
    assert len(extracted['results'])==1 and extracted['next_after'] is None
    assert extracted['results'][0]['las_requests']==0
    result=client.get('/api/conferences/harbor/authors?q=Northstar&page_size=1').json()
    assert result['total']==1 and result['items'][0]['author']=='Mira Chen'
    assert result['items'][0]['page']==1
    all_rows=client.get('/api/conferences/harbor/authors?page_size=1').json()
    assert all_rows['total']==7 and len(all_rows['items'])==1
    assert all_rows['coverage']['with_institutions']==2
    response=client.get('/api/conferences/harbor/authors.csv')
    rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(rows)==7 and all(r['collection']=='demo' for r in rows)
    assert sum(r['institution']=='' for r in rows)==4
    filtered=list(csv.DictReader(io.StringIO(client.get('/api/conferences/harbor/authors.csv?q=Northstar').content.decode('utf-8-sig'))))
    assert len(filtered)==1 and filtered[0]['excerpt'] and filtered[0]['method']=='deterministic_pdf'
    assert client.get('/api/conferences/harbor/authors?status=missing').json()['total']==4
    assert client.get('/api/conferences/harbor/authors?q=%25').json()['total']==0
    client.post('/api/conferences/harbor/authors/extract')
    assert client.get('/api/conferences/harbor/authors').json()['total']==7
    for path in ('authors','authors.csv','authors.pdf','authors/extract'):
        response=(client.post if path.endswith('extract') else client.get)('/api/conferences/harbor/'+path,headers={'X-Collection':'real'})
        assert response.status_code==404


def test_csv_protects_formulas_and_membership_and_missing_roster(client):
    with db.connect() as con:
        con.execute("UPDATE authors SET name='=HYPERLINK(\"bad\")' WHERE id='a1'")
        con.execute("INSERT INTO paper_editions SELECT paper_id,'summit','summit-main',official_url,inventory_url,retrieved FROM paper_editions WHERE paper_id='harbor-0'")
        con.execute("DELETE FROM affiliations WHERE paper_id='harbor-2'")
        con.execute("DELETE FROM authorship WHERE paper_id='harbor-2'")
    rows=list(csv.DictReader(io.StringIO(client.get('/api/conferences/summit/authors.csv').content.decode('utf-8-sig'))))
    assert any(r['paper_id']=='harbor-0' for r in rows)
    assert all(r['author'].startswith("'=") for r in rows if 'HYPERLINK' in r['author'])
    assert client.get('/api/conferences/harbor/authors').json()['coverage']['papers_without_authors']==1
    assert client.get('/api/conferences/harbor/authors?status=rejected').status_code==422


def test_bounded_batches_continue_after_paper_failure(client,monkeypatch):
    from endless_tuna import conference_authors
    from endless_tuna.enrichment import EnrichmentError
    with db.connect() as con:
        for n in range(12):
            pid=f'fixture-{n:02}'
            con.execute("INSERT INTO papers(id,edition_id,track_id,title,abstract) VALUES(?,'harbor','harbor-main',?,'')",(pid,pid))
            con.execute("INSERT INTO paper_editions VALUES(?,'harbor','harbor-main','https://example.org/paper','https://example.org/list',0)",(pid,))
            con.execute("INSERT INTO downloads(id,paper_id,status,path) VALUES(?,?,'available','harbor-0.pdf')",(pid,pid))
    calls=[]
    def extract(collection,pid,use_las):
        assert collection=='demo' and use_las is False
        calls.append(pid)
        if pid=='fixture-03':raise EnrichmentError('Paper is already running.')
        return {'status':'no_evidence'}
    monkeypatch.setattr(conference_authors,'enrich_paper',extract)
    first=client.post('/api/conferences/harbor/authors/extract').json()
    assert len(first['results'])==10 and first['next_after']
    assert first['results'][3]['status']=='failed'
    second=client.post('/api/conferences/harbor/authors/extract',params={'after':first['next_after']}).json()
    assert len(second['results'])==3 and second['next_after'] is None
    assert len(calls)==len(set(calls))==13


def test_pdf_matches_csv_filters_preserves_unicode_and_paginates(client):
    from pypdf import PdfReader
    with db.connect() as con:
        con.execute("UPDATE authors SET name='Zoë 张 <Analyst> & Co' WHERE id='a1'")
    response=client.get('/api/conferences/harbor/authors.pdf?q=Zoë')
    assert response.status_code==200 and response.headers['content-type']=='application/pdf'
    assert 'attachment' in response.headers['content-disposition']
    assert response.content.startswith(b'%PDF-')
    report=PdfReader(io.BytesIO(response.content))
    text='\n'.join(page.extract_text() for page in report.pages)
    assert 'Zoë 张 <Analyst> & Co' in text
    assert 'Alex Rivera' not in text and '2 matching author-institution rows' in text
    assert 'Not extracted' in text and 'FICTIONAL DEMO DATA' in text
    assert '1. Zoë' in text and '2. Zoë' in text
    empty=client.get('/api/conferences/harbor/authors.pdf?q=absent')
    assert 'No matching author records' in PdfReader(io.BytesIO(empty.content)).pages[0].extract_text()


def test_pdf_long_evidence_remains_readable_across_pages(client):
    from pypdf import PdfReader
    from endless_tuna.enrichment import insert_assertion,AssertionInput
    with db.connect() as con:
        quote='Mira Chen: Northstar Lab. '+('Long retained evidence sentence. '*140)+' Evidence end.'
        insert_assertion(con,'a1',AssertionInput(kind='affiliation',value='Northstar Lab',paper_id='harbor-0',source_url='https://example.org/evidence',excerpt=quote))
    response=client.get('/api/conferences/harbor/authors.pdf?q=Northstar')
    report=PdfReader(io.BytesIO(response.content))
    text='\n'.join(page.extract_text() for page in report.pages)
    assert len(report.pages)>1 and 'Evidence end.' in text
    assert 'https://example.org/evidence' in text and 'Northstar Lab' in text
    assert 'needs_review (unverified)' in text


def test_conference_name_search_is_scoped_to_names_years_and_collection(client):
    result=client.get('/api/author-conferences?q=Harbor%202025').json()
    assert result['total']==1
    assert result['items'][0]['id']=='harbor'
    assert result['items'][0]['papers']==3 and result['items'][0]['author_records']==6
    assert client.get('/api/author-conferences?q=2025').json()['total']==2
    assert client.get('/api/author-conferences?q=grippers').json()['total']==0
    assert client.get('/api/author-conferences?q=%25').json()['total']==0
    assert client.get('/api/author-conferences?q=Harbor',headers={'X-Collection':'real'}).json()['total']==0
    assert client.get('/api/author-conferences').json()['items']==[]


def test_compile_entire_dataset_and_explicit_ai_option(client,monkeypatch):
    from endless_tuna import conference_authors
    calls=[]
    def extract(collection,pid,use_las):
        calls.append((collection,pid,use_las))
        return {'status':'no_evidence'}
    monkeypatch.setattr(conference_authors,'enrich_paper',extract)
    response=client.post('/api/conferences/harbor/authors/extract',json={'all_papers':True}).json()
    assert len(response['results'])==3
    assert {pid for _,pid,_ in calls}=={'harbor-0','harbor-1','harbor-2'}
    assert all(not ai for _,_,ai in calls)
    calls.clear()
    client.post('/api/conferences/harbor/authors/extract',json={'all_papers':True,'use_las':True})
    assert len(calls)==3 and all(ai for _,_,ai in calls)
    assert client.post('/api/conferences/harbor/authors/extract',json={'unknown':True}).status_code==422
