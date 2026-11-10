import json
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db
from endless_tuna.main import app
from endless_tuna.collection import parse_metadata, parse_pdf, CollectionError, public_url
from endless_tuna.worker import tick


def test_citation_adapter_and_json_validation():
    raw=b'<meta name="citation_title" content="Source title"><meta name="citation_author" content="Same Name"><meta name="citation_pdf_url" content="paper.pdf">'
    record=parse_metadata(raw,'https://example.org/source')[0]
    assert record.title=='Source title' and record.authors[0].name=='Same Name'
    assert record.pdf_url=='https://example.org/paper.pdf'
    with pytest.raises(CollectionError):parse_metadata(b'{"papers":[{"title":null}]}','https://example.org/source')
    with pytest.raises(CollectionError):parse_metadata(b'<html>No metadata</html>','https://example.org/source')
    with pytest.raises(CollectionError):parse_pdf(b'<html>not PDF</html>')


@pytest.mark.parametrize('parser_failure',[False,True])
def test_adapter_downloads_and_parses_pdf_without_las(tmp_path,monkeypatch,parser_failure):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setattr('endless_tuna.worker.public_url',lambda url:url)
    if parser_failure:
        def cannot_parse(_):raise CollectionError('PDF text parser could not process this file')
        monkeypatch.setattr('endless_tuna.worker.parse_pdf_pages',cannot_parse)
    with TestClient(app) as client:
        sample=(tmp_path/'demo-pdfs'/'harbor-0.pdf').read_bytes()
        manifest={'papers':[{'title':'Collected deterministic title','abstract':'Robotics abstract','authors':[{'name':'Same Name','organizations':['Test lab']},{'name':'Same Name'}],'pdf_url':'https://example.org/paper.pdf'}]}
        def fetch(url,**kwargs):
            return (sample if url.endswith('.pdf') else json.dumps(manifest).encode()),url
        monkeypatch.setattr('endless_tuna.worker.fetch_bytes',fetch)
        h={'X-Collection':'real'}
        created=client.post('/api/conferences',headers=h,json={'name':'Adapter test','year':2026,'track':'Main','source_url':'https://example.org/metadata','adapter':'metadata'}).json()
        assert tick('real')
        job=client.get('/api/jobs',headers=h).json()[0]
        assert job['status']==('partial' if parser_failure else 'complete') and job['progress']==100
        papers=client.get('/api/papers?q=Robotics',headers=h).json()
        assert len(papers)==1
        pid=papers[0]['id']
        detail=client.get('/api/papers/'+pid,headers=h).json()
        assert detail['parsed_pdf_pages']==(None if parser_failure else 1) and len(detail['authors'])==2
        assert detail['authors'][0]['id']!=detail['authors'][1]['id']
        assert client.get('/api/papers/'+pid+'/pdf',headers=h).status_code==(404 if parser_failure else 200)
        with db.connect('real') as con:
            parsed=con.execute('SELECT text FROM pdf_text WHERE paper_id=?',(pid,)).fetchone()
            assert (parsed is None) if parser_failure else ('DEMO DATA' in parsed['text'])
            # Reprocessing is idempotent and leaves the stored records available.
            con.execute("UPDATE jobs SET status='queued',cursor=0 WHERE id=?",(created['job_id'],))
        assert tick('real')
        assert len(client.get('/api/papers',headers=h).json())==1


@pytest.mark.parametrize('url',['http://127.0.0.1/file','http://localhost/file','file:///tmp/file','https://user:secret@example.org/file','https://example.org/file?token=secret'])
def test_source_url_guard(url):
    with pytest.raises(CollectionError):public_url(url)
