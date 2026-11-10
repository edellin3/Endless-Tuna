import csv
import io
import json
import hashlib
import time
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db
from endless_tuna.main import app
from endless_tuna.adapters import NeurIPS2024,adapter_for,parse_csv
from endless_tuna.collection import Metadata,Person,CollectionError,parse_pdf_pages
from endless_tuna.resolution import Candidate,strong_match,parse_arxiv,resolve
from endless_tuna.network import fetch_bytes,PublicTransport,validate_url
from endless_tuna.worker import tick,owned,LostLease

FIXTURES=Path(__file__).parent/'fixtures'
SOURCE='https://papers.nips.cc/paper_files/paper/2024'


@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setenv('TUNA_DOWNLOAD_CONCURRENCY','1')
    monkeypatch.delenv('TUNA_SEARCH_ENDPOINT',raising=False)
    with TestClient(app) as client:yield client


def create(client,url='https://example.org/inventory.json'):
    r=client.post('/api/conferences',headers={'X-Collection':'real'},json={'name':'Fixture edition','year':2024,'track':'Main Conference','source_url':url,'adapter':'auto'})
    assert r.status_code==201,r.text
    return r.json()


def test_official_adapter_inventory_detail_and_workshop_separation():
    adapter=adapter_for(SOURCE)
    inventory=adapter.inventory(SOURCE,lambda *a,**k:((FIXTURES/'neurips_inventory.html').read_bytes(),SOURCE))
    assert inventory.official_count==2
    assert len(inventory.records)==2
    record=inventory.records[0]
    url=record.source_url
    hydrated=adapter.hydrate(record,lambda *a,**k:((FIXTURES/'neurips_paper.html').read_bytes(),url))
    assert hydrated.title=='Fixture optimization for robots'
    assert [a.name for a in hydrated.authors]==['Mira Chen','Alex Rivera']
    assert hydrated.identifiers['doi']=='10.0000/fictional-fixture'
    assert hydrated.abstract.startswith('Fictional abstract')
    assert hydrated.pdf_url.endswith('-Paper-Conference.pdf')
    with pytest.raises(CollectionError):adapter_for('https://unrecognized.example/conference')
    with pytest.raises(CollectionError):adapter_for('https://papers.nips.cc/paper_files/paper/2024/workshops')


def test_csv_preserves_author_order_and_requires_membership_evidence():
    out=io.StringIO();writer=csv.writer(out);writer.writerow(['title','authors','official_url','inventory_url','year','track','pdf_url','doi'])
    writer.writerow(['Fictional CSV title',json.dumps(['Second alphabetically','First alphabetically']),'https://example.org/paper','https://example.org/inventory',2024,'Main Conference','https://example.org/paper.pdf','10.0000/fixture'])
    result=parse_csv(out.getvalue().encode())[0]
    assert [a.name for a in result.authors]==['Second alphabetically','First alphabetically']
    assert result.inventory_url=='https://example.org/inventory' and result.year==2024
    with pytest.raises(CollectionError):parse_csv(b'title,authors\nOnly a title,[]')


def test_arxiv_matching_exact_title_and_full_author_evidence():
    record=Metadata(title='Fixture optimization for robots',authors=[Person(name='Mira Chen'),Person(name='Alex Rivera')])
    candidate=parse_arxiv((FIXTURES/'arxiv.xml').read_bytes())[0]
    assert candidate.version=='arxiv:0000.00000v2' and strong_match(record,candidate)
    assert not strong_match(record,Candidate(candidate.url,'Fixture optimization for robot',candidate.authors,candidate.version))
    assert not strong_match(record,Candidate(candidate.url,record.title,['Mira Chen'],candidate.version))


def test_ambiguous_arxiv_versions_are_not_auto_accepted(session):
    raw=(FIXTURES/'arxiv.xml').read_text()
    entry=raw.split('<entry>')[1].split('</entry>')[0]
    ambiguous=raw.replace('</feed>','<entry>'+entry.replace('v2','v3')+'</entry></feed>').encode()
    record=Metadata(title='Fixture optimization for robots',authors=[Person(name='Mira Chen'),Person(name='Alex Rivera')])
    selected,candidates,reason=resolve(record,'real',lambda *a,**k:(ambiguous,'https://export.arxiv.org/api/query'))
    assert selected is None and len(candidates)==2 and 'Ambiguous' in reason
    # The cached resolution avoids another API request.
    selected,_,_=resolve(record,'real',lambda *a,**k:pytest.fail('Cache should prevent another request'))
    assert selected is None


@pytest.mark.parametrize('raw',[b'<html>Not a PDF</html>',b'%PDF-1.4\ninvalid truncated PDF'])
def test_invalid_pdf_response(raw):
    with pytest.raises(CollectionError):parse_pdf_pages(raw)


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr('endless_tuna.network.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    monkeypatch.setattr('endless_tuna.network.limiter.wait',lambda _:None)


def test_redirect_to_private_rejected_before_second_request(public_dns):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(302,headers={'Location':'http://169.254.169.254/latest/meta-data/'})
    with pytest.raises(CollectionError):fetch_bytes('https://example.org/paper',transport=httpx.MockTransport(handler))
    assert len(calls)==1


def test_public_redirect_retry_and_size_limits(public_dns):
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        if len(calls)==1:return httpx.Response(503)
        if str(request.url).endswith('/paper'):return httpx.Response(302,headers={'Location':'/download'})
        return httpx.Response(200,content=b'%PDF-fixture')
    raw,url=fetch_bytes('https://example.org/paper',transport=httpx.MockTransport(handler),sleep=lambda _:None)
    assert raw==b'%PDF-fixture' and url.endswith('/download') and len(calls)==3
    with pytest.raises(CollectionError):fetch_bytes('https://example.org/file',limit=3,transport=httpx.MockTransport(lambda _:httpx.Response(200,content=b'toolarge')))


def test_pinned_transport_retains_host_and_tls_name(public_dns):
    seen=[]
    transport=PublicTransport()
    transport.inner=httpx.MockTransport(lambda request:(seen.append(request) or httpx.Response(200,content=b'ok')))
    response=transport.handle_request(httpx.Request('GET','https://example.org/paper'))
    assert response.status_code==200
    assert seen[0].url.host=='93.184.216.34'
    assert seen[0].headers['host']=='example.org'
    assert seen[0].extensions['sni_hostname']=='example.org'


@pytest.mark.parametrize('url',['file:///tmp/a','http://localhost/a','http://127.0.0.1/a','http://[::1]/a','http://10.1.2.3/a','http://169.254.169.254/a','https://user:secret@example.org/a'])
def test_network_boundaries(url):
    with pytest.raises(CollectionError):validate_url(url)


def manifest_fetch(session,monkeypatch,*,fail_second=False):
    sample=(db.DATA/'demo-pdfs'/'harbor-0.pdf').read_bytes()
    records=[{'title':'Fixture metadata '+str(i),'source_url':f'https://example.org/paper/{i}','authors':[{'name':'Same Name'},{'name':'Same Name'}],'pdf_url':f'https://example.org/file/{i}.pdf'} for i in range(2)]
    calls=[]
    def fetch(url,**kwargs):
        calls.append(url)
        if url.endswith('.json'):return json.dumps({'papers':records}).encode(),url
        if fail_second and url.endswith('/1.pdf'):return b'<html>denied</html>',url
        return sample,url
    monkeypatch.setattr('endless_tuna.worker.fetch_bytes',fetch)
    return calls,sample


def test_duplicate_runs_share_canonical_records_files_and_memberships(session,monkeypatch):
    calls,sample=manifest_fetch(session,monkeypatch)
    first=create(session);assert tick('real',first['job_id'])
    second=create(session);assert tick('real',second['job_id'])
    h={'X-Collection':'real'}
    assert len(session.get('/api/papers',headers=h).json())==2
    assert len(session.get('/api/papers?edition='+second['id'],headers=h).json())==2
    assert len(list((db.DATA/'real-pdfs').glob('*.pdf')))==1  # content-addressed identical fixture bytes
    with db.connect('real') as con:
        assert con.execute('SELECT COUNT(*) FROM paper_editions').fetchone()[0]==4
        download=con.execute('SELECT * FROM downloads LIMIT 1').fetchone()
        assert download['sha256']==hashlib.sha256(sample).hexdigest() and download['size_bytes']==len(sample) and download['retrieved']>0
        assert download['version']=='proceedings'
        assert con.execute('SELECT COUNT(*) FROM pdf_pages').fetchone()[0]==2
    # Word appears only in the fixture PDF body, not its inventory title/abstract.
    found=session.get('/api/papers?q=Illustrative',headers=h).json()
    assert len(found)==2 and found[0]['matching_pages'][0]['page']==1
    assert sum(url.endswith('.pdf') for url in calls)==2  # no duplicate transfers across memberships


def test_one_invalid_pdf_does_not_abort_conference(session,monkeypatch):
    manifest_fetch(session,monkeypatch,fail_second=True)
    created=create(session);tick('real',created['job_id'])
    job=session.get('/api/jobs',headers={'X-Collection':'real'}).json()[0]
    assert job['status']=='partial' and len(job['failures'])==1
    assert len(session.get('/api/papers',headers={'X-Collection':'real'}).json())==2
    assert job['stages'][-1]['completed']==1


def test_cancel_resume_and_expired_lease_recovery(session,monkeypatch):
    calls,sample=manifest_fetch(session,monkeypatch)
    created=create(session);jid=created['job_id'];h={'X-Collection':'real'}
    from endless_tuna import worker
    original=worker.process_paper
    processed=[]
    def interrupt(collection,job,token,item,adapter):
        original(collection,job,token,item,adapter)
        processed.append(item['paper_id'])
        if len(processed)==1:
            with db.connect(collection) as con:con.execute("UPDATE jobs SET status='cancelled',lease_token=NULL WHERE id=?",(jid,))
    monkeypatch.setattr(worker,'process_paper',interrupt)
    assert tick('real',jid)
    with db.connect('real') as con:assert con.execute("SELECT COUNT(*) FROM job_papers WHERE status='done'").fetchone()[0]==1
    assert session.post(f'/api/jobs/{jid}/resume',headers=h,json={}).status_code==200
    with db.connect('real') as con:con.execute("UPDATE jobs SET status='running',lease_until=? WHERE id=?",(time.time()-1,jid))
    monkeypatch.setattr(worker,'process_paper',original)
    assert tick('real',jid)
    job=session.get('/api/jobs',headers=h).json()[0]
    assert job['status']=='complete' and job['attempts']==2
    assert sum(url.endswith('.json') for url in calls)==1  # immutable inventory snapshot reused
    assert sum(url.endswith('.pdf') for url in calls)==2
    with db.connect('real') as con:
        with pytest.raises(LostLease):owned(con,jid,'old-owner-token')


def test_manual_candidate_review_and_unsupported_urls(session):
    h={'X-Collection':'real'}
    assert session.post('/api/conferences',headers=h,json={'name':'Unsupported','year':2024,'track':'Main','source_url':'https://arbitrary.example/accepted'}).status_code==422
    r=session.post('/api/papers/harbor-0/pdf-candidates',json={'url':'http://127.0.0.1/p.pdf'})
    assert r.status_code==422
    assert session.post('/api/papers/harbor-0/pdf-candidates',json={'url':'https://example.org/new.pdf','version':'arxiv'}).json()['ok']
    candidates=session.get('/api/pdf-candidates').json()
    assert len(candidates)==1
    decision=session.post('/api/pdf-candidates/'+candidates[0]['id']+'/review',json={'action':'confirm','note':'Inspected version and author evidence'})
    assert decision.json()['job_id']
    assert session.get('/api/pdf-candidates').json()==[]
    assert session.get('/api/papers/harbor-0').json()['history'][0]['action']=='pdf_confirm'


def test_non_latin_and_duplicate_author_names_do_not_create_false_matches():
    record=Metadata(title='研究題名',authors=[Person(name='王明'),Person(name='王明')])
    assert not strong_match(record,Candidate('https://arxiv.org/pdf/1','別の題名',['別人','別人'],'arxiv'))
    assert not strong_match(record,Candidate('https://arxiv.org/pdf/1','研究題名',['王明'],'arxiv'))
    assert strong_match(record,Candidate('https://arxiv.org/pdf/1','研究題名',['王明','王明'],'arxiv'))


def test_scanned_pdf_is_available_but_needs_ocr(session,monkeypatch):
    from pypdf import PdfWriter
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);stream=io.BytesIO();writer.write(stream);raw=stream.getvalue()
    records=[{'title':'Scanned fixture','source_url':'https://example.org/scanned','pdf_url':'https://example.org/scanned.pdf','authors':[{'name':'Fictional Person'}]}]
    monkeypatch.setattr('endless_tuna.worker.fetch_bytes',lambda url,**k:(json.dumps({'papers':records}).encode() if url.endswith('.json') else raw,url))
    created=create(session);assert tick('real',created['job_id'])
    detail=session.get('/api/conferences/'+created['id'],headers={'X-Collection':'real'}).json()
    assert detail['coverage']['pdfs']==1 and detail['coverage']['ocr_required']==1 and detail['coverage']['fulltext']==0


def test_active_claim_is_not_stolen(session,monkeypatch):
    created=create(session)
    with db.connect('real') as con:
        con.execute("UPDATE jobs SET status='running',lease_token='active-owner',lease_until=? WHERE id=?",(time.time()+100,created['job_id']))
    assert tick('real',created['job_id']) is False
    with db.connect('real') as con:assert con.execute('SELECT lease_token FROM jobs WHERE id=?',(created['job_id'],)).fetchone()['lease_token']=='active-owner'


def test_csv_import_is_queued_with_unknown_official_completeness(session):
    created=create(session)
    out=io.StringIO();w=csv.writer(out);w.writerow(['title','authors','official_url','inventory_url','year','track']);w.writerow(['Fictional CSV',['Unused'], 'https://example.org/paper','https://example.org/inventory',2024,'Main Conference'])
    # authors must be a JSON array, not Python's string representation.
    bad=session.post('/api/conferences/'+created['id']+'/inventory/csv',headers={'X-Collection':'real'},json={'csv_text':out.getvalue()})
    assert bad.status_code==422
    text=out.getvalue().replace("['Unused']",'["Unused"]')
    # Regenerate with CSV quoting for the JSON field.
    out=io.StringIO();w=csv.writer(out);w.writerow(['title','authors','official_url','inventory_url','year','track']);w.writerow(['Fictional CSV',json.dumps(['Unused']),'https://example.org/paper','https://example.org/inventory',2024,'Main Conference'])
    response=session.post('/api/conferences/'+created['id']+'/inventory/csv',headers={'X-Collection':'real'},json={'csv_text':out.getvalue()})
    assert response.status_code==200 and response.json()['official_count'] is None


def test_confirmed_manual_pdf_download_preserves_the_canonical_paper(session,monkeypatch):
    sample=(db.DATA/'demo-pdfs'/'harbor-0.pdf').read_bytes()
    monkeypatch.setattr('endless_tuna.worker.fetch_bytes',lambda url,**kwargs:(sample,url))
    session.post('/api/papers/harbor-0/pdf-candidates',json={'url':'https://example.org/alternate.pdf','version':'arxiv'})
    cid=session.get('/api/pdf-candidates').json()[0]['id']
    decision=session.post('/api/pdf-candidates/'+cid+'/review',json={'action':'confirm'}).json()
    assert tick('demo',decision['job_id'])
    assert len(session.get('/api/papers').json())==9
    paper=session.get('/api/papers/harbor-0').json()
    alternate=[d for d in paper['downloads'] if d['source_url']=='https://example.org/alternate.pdf'][0]
    assert alternate['status']=='available' and alternate['version']=='arxiv'
    assert session.get('/api/papers/harbor-0/pdf?download_id='+alternate['id']).content==sample


def test_versioned_fulltext_keeps_both_proceedings_and_arxiv_page_references(session):
    from endless_tuna.pipeline_store import save_download
    from pypdf import PdfWriter
    raw=(db.DATA/'demo-pdfs'/'harbor-0.pdf').read_bytes()
    with db.connect() as con:
        save_download(con,'demo','harbor-0',Candidate('https://example.org/proceedings.pdf','Fixture',[],'proceedings'),raw,'https://example.org/proceedings.pdf')
        save_download(con,'demo','harbor-0',Candidate('https://arxiv.org/pdf/0000.00000v1','Fixture',[],'arxiv:0000.00000v1'),raw,'https://arxiv.org/pdf/0000.00000v1')
    result=session.get('/api/papers?q=Illustrative').json()
    paper=next(p for p in result if p['id']=='harbor-0')
    assert {page['version'] for page in paper['matching_pages']}=={'proceedings','arxiv:0000.00000v1'}


def test_official_detail_author_order_and_title_replace_only_unreviewed_inventory(session):
    from endless_tuna.pipeline_store import upsert_paper,hydrate_paper
    from endless_tuna.pipeline_api import queue
    created=create(session)
    initial=Metadata(title='Inventory title',source_url='https://example.org/order-test',authors=[Person(name='Incorrect split'),Person(name='Extra Name'),Person(name='Unused')])
    authoritative=Metadata(title='Official page title',source_url=initial.source_url,authors=[Person(name='Mira Chen'),Person(name='Alex Rivera')])
    with db.connect('real') as con:
        tid=con.execute('SELECT id FROM tracks WHERE edition_id=?',(created['id'],)).fetchone()['id']
        pid=upsert_paper(con,created['id'],tid,initial,'https://example.org/inventory')
        hydrate_paper(con,pid,authoritative)
    detail=session.get('/api/papers/'+pid,headers={'X-Collection':'real'}).json()
    assert detail['title']=='Official page title' and [a['name'] for a in detail['authors']]==['Mira Chen','Alex Rivera']
    session.post('/api/papers/'+pid+'/review',headers={'X-Collection':'real'},json={'action':'correct','title':'Reviewed title'})
    with db.connect('real') as con:hydrate_paper(con,pid,authoritative)
    assert session.get('/api/papers/'+pid,headers={'X-Collection':'real'}).json()['title']=='Reviewed title'


def test_rejected_arxiv_candidate_is_not_automatically_selected_on_retry(session):
    from endless_tuna.pipeline_store import upsert_paper,save_candidate
    created=create(session)
    record=Metadata(title='Fixture optimization for robots',source_url='https://example.org/arxiv-test',authors=[Person(name='Mira Chen'),Person(name='Alex Rivera')])
    candidate=parse_arxiv((FIXTURES/'arxiv.xml').read_bytes())[0]
    with db.connect('real') as con:
        tid=con.execute('SELECT id FROM tracks WHERE edition_id=?',(created['id'],)).fetchone()['id']
        pid=upsert_paper(con,created['id'],tid,record,'https://example.org/inventory')
        save_candidate(con,pid,candidate,'Candidate to reject')
        con.execute("UPDATE pdf_candidates SET status='rejected' WHERE paper_id=?",(pid,))
    selected,candidates,_=resolve(record,'real',lambda *args,**kwargs:((FIXTURES/'arxiv.xml').read_bytes(),'https://export.arxiv.org/api/query'))
    assert selected is None and candidates==[]
