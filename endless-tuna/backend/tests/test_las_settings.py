import json
import httpx
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db, las_settings
from endless_tuna.main import app
from endless_tuna.las import LASClient, LASConfig


@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    with TestClient(app) as client:yield client


def test_settings_open_is_local_and_secret_free(session,monkeypatch):
    monkeypatch.setenv('LAS_API_KEY','do-not-expose-server-key')
    monkeypatch.setenv('LAS_MODEL','test/model')
    data=session.get('/api/settings').json()
    assert data['las']['credentials_configured'] is True
    assert data['las']['status']=='configured_unverified'
    assert 'do-not-expose-server-key' not in str(data)


def test_explicit_discovery_selection_and_test(session,monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'gateway/model-a'}]})
        assert b'gateway/model-a' in request.content
        return httpx.Response(200,json={'choices':[{'message':{'content':'OK'}}]})
    def factory():
        model=las_settings.read_setting('las_selected_model')
        return LASClient(LASConfig('https://gateway.invalid/v1','mock-key',model),transport=httpx.MockTransport(handler))
    monkeypatch.setattr(las_settings,'configured_client',factory)
    session.get('/api/settings')
    assert not calls
    assert session.post('/api/las/test').json()['code']=='missing_configuration'
    assert not calls
    assert session.post('/api/las/discover').json()['models']==['gateway/model-a']
    assert len(calls)==1
    assert session.post('/api/las/model',json={'model':'invented'}).json()['code']=='invalid_model'
    assert session.post('/api/las/model',json={'model':'gateway/model-a'}).json()['ok']
    assert len(calls)==1
    assert session.get('/api/settings').json()['las']['model']=='gateway/model-a'
    assert session.post('/api/las/test').json()['code']=='model_verified'
    assert len(calls)==2
    assert session.post('/api/las/test',headers={'Origin':'https://other.invalid'}).status_code==403
    assert len(calls)==2


def test_missing_las_does_not_break_browsing_or_exports(session):
    assert session.post('/api/las/discover').json()['code']=='missing_configuration'
    assert session.post('/api/papers/harbor-0/extract').json()['code']=='missing_configuration'
    assert session.get('/api/papers/harbor-0').status_code==200
    assert session.get('/api/papers?q=robotics').json()
    assert session.get('/api/conferences/harbor/export').status_code==200
    assert session.get('/api/papers/harbor-0/pdf').status_code==200


def test_extraction_validates_evidence_and_preserves_stored_record(session,monkeypatch):
    with db.connect() as con:con.execute('INSERT INTO pdf_text VALUES(?,?,?)',('harbor-0','The exact source sentence.',1))
    def factory():
        return LASClient(LASConfig('https://gateway.invalid/v1','mock-key','gateway/model-a'),transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':'{"title":"Proposal","abstract":"Proposed abstract","evidence_quote":"invented"}'}}]})))
    monkeypatch.setattr(las_settings,'configured_client',factory)
    response=session.post('/api/papers/harbor-0/extract').json()
    assert response['code']=='malformed_response'
    assert session.get('/api/papers/harbor-0').json()['title']=='Learning to navigate together'


def test_local_pdf_parse_without_las(session):
    assert session.post('/api/papers/harbor-0/pdf/parse').json()['pages']==1
    assert session.get('/api/papers/harbor-0').json()['parsed_pdf_pages']==1
    assert session.post('/api/papers/harbor-1/pdf/parse').status_code==404
    assert session.post('/api/papers/harbor-0/extract').json()['code']=='missing_configuration'


def test_valid_extraction_is_only_a_proposal(session,monkeypatch):
    with db.connect() as con:
        con.execute('INSERT INTO pdf_text VALUES(?,?,?)',('harbor-0','The exact source sentence.',1))
    proposal={'title':'Proposed title','abstract':'Proposed abstract','evidence_quote':'The exact source sentence.'}
    def factory():
        return LASClient(LASConfig('https://gateway.invalid/v1','mock-key','gateway/model-a'),transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(proposal)}}]})))
    monkeypatch.setattr(las_settings,'configured_client',factory)
    result=session.post('/api/papers/harbor-0/extract').json()
    assert result['ok'] and result['proposal']==proposal
    assert session.get('/api/papers/harbor-0').json()['title']=='Learning to navigate together'
