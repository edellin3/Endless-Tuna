import json
import httpx
import pytest
from pydantic import BaseModel
from endless_tuna.las import LASClient, LASConfig, LASError


KEY = 'mock-credential-never-log'


def client(handler, *, base='https://gateway.invalid/v1/', model='returned/model-id', sleep=lambda _: None):
    return LASClient(LASConfig(base, KEY, model, 90), transport=httpx.MockTransport(handler), sleep=sleep)


@pytest.mark.parametrize('base', ['https://gateway.invalid', 'https://gateway.invalid/', 'https://gateway.invalid/v1', 'https://gateway.invalid/v1/'])
def test_endpoint_normalization_auth_and_discovery(base):
    def handler(request):
        assert str(request.url) == 'https://gateway.invalid/v1/models'
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer ' + KEY
        return httpx.Response(200, json={'data':[{'id':'team/model-1'},{'id':'another-id'}]})
    assert client(handler, base=base).discover_models() == ['team/model-1', 'another-id']


def test_missing_configuration_makes_no_request():
    def unexpected(_): raise AssertionError('No transport call should occur')
    with pytest.raises(LASError) as e:
        LASClient(LASConfig('https://gateway.invalid/v1', ''), transport=httpx.MockTransport(unexpected)).discover_models()
    assert e.value.code == 'missing_configuration'
    with pytest.raises(LASError) as e:
        LASClient(LASConfig('https://gateway.invalid/v1', KEY), transport=httpx.MockTransport(unexpected)).complete([])
    assert e.value.code == 'missing_configuration'


def test_key_fallback_only_when_unset(monkeypatch):
    monkeypatch.setenv('OPENAI_KEY', KEY)
    assert LASConfig.from_env().api_key == KEY
    monkeypatch.setenv('LAS_API_KEY', '')
    assert LASConfig.from_env().api_key == ''
    monkeypatch.setenv('LAS_API_KEY', 'primary-credential')
    assert LASConfig.from_env().api_key == 'primary-credential'
    assert 'primary-credential' not in repr(LASConfig.from_env())


def test_completion_uses_only_ordinary_chat_and_configured_id():
    def handler(request):
        assert str(request.url) == 'https://gateway.invalid/v1/chat/completions'
        assert request.method == 'POST'
        assert request.headers['Authorization'] == 'Bearer ' + KEY
        body = json.loads(request.content)
        assert body == {'model':'returned/model-id','messages':[{'role':'user','content':'Hello'}],'max_tokens':8,'stream':False}
        return httpx.Response(200,json={'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}]})
    assert client(handler).complete([{'role':'user','content':'Hello'}],max_tokens=8) == 'OK'


@pytest.mark.parametrize('status,code', [(401,'authentication_failure'),(403,'access_denied'),(404,'invalid_model'),(429,'rate_limited'),(503,'service_unavailable')])
def test_safe_http_failures_including_html(status,code,caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,text='<html>secret: '+KEY+'</html>',headers={'Content-Type':'text/html'})
    with pytest.raises(LASError) as e:
        client(handler).complete([])
    diagnostic=e.value.diagnostic()
    assert diagnostic['code']==code
    assert KEY not in str(diagnostic) and KEY not in caplog.text
    assert len(calls)==1  # never replay inference
    if status==403:
        assert 'network' in diagnostic['message'] and 'does not establish' in diagnostic['message']


def test_invalid_model_json():
    with pytest.raises(LASError) as e:
        client(lambda _:httpx.Response(400,json={'error':{'code':'model_not_found','message':KEY}})).complete([])
    assert e.value.code=='invalid_model' and KEY not in str(e.value)


def test_bounded_retry_on_discovery_rate_limit():
    calls=[];delays=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,json={'error':{'message':KEY}})
    with pytest.raises(LASError) as e:
        client(handler,sleep=delays.append).discover_models()
    assert e.value.code=='rate_limited' and e.value.retryable
    assert len(calls)==3 and delays==[.25,.5]


@pytest.mark.parametrize('failure,code',[(httpx.ReadTimeout,'timeout'),(httpx.ConnectError,'network_failure')])
def test_timeout_and_network_failure_are_redacted(failure,code):
    calls=[]
    def handler(request):
        calls.append(request)
        raise failure(KEY,request=request)
    with pytest.raises(LASError) as e:
        client(handler).discover_models()
    assert e.value.code==code and KEY not in str(e.value)
    assert len(calls)==3
    calls.clear()
    with pytest.raises(LASError):client(handler).complete([])
    assert len(calls)==1


@pytest.mark.parametrize('payload',[{},[],{'data':[{}]},{'data':[{'id':KEY}]}])
def test_malformed_model_discovery(payload):
    with pytest.raises(LASError) as e:
        client(lambda _:httpx.Response(200,json=payload)).discover_models()
    assert e.value.code=='malformed_response'


def test_malformed_html_success_and_redirect_are_safe():
    with pytest.raises(LASError) as e:
        client(lambda _:httpx.Response(200,text='<html>'+KEY+'</html>')).discover_models()
    assert e.value.code=='malformed_response'
    calls=[]
    def redirect(request):
        calls.append(request)
        return httpx.Response(302,headers={'Location':'https://elsewhere.invalid/'})
    with pytest.raises(LASError):client(redirect).discover_models()
    assert len(calls)==1


def test_application_validates_extracted_json():
    class Result(BaseModel):
        title:str
    def respond(text):return lambda _:httpx.Response(200,json={'choices':[{'message':{'content':text}}]})
    assert client(respond('{"title":"From source"}')).extract_json([],Result).title=='From source'
    for text in ('not json','{"wrong":"field"}'):
        with pytest.raises(LASError) as e:client(respond(text)).extract_json([],Result)
        assert e.value.code=='malformed_response'


@pytest.mark.parametrize('url',['https://user:secret@gateway.invalid/v1','https://gateway.invalid/v1?key=secret','https://gateway.invalid/v1#fragment','file:///tmp/file'])
def test_unsafe_configuration_rejected(url):
    with pytest.raises(LASError):LASConfig(url,KEY).require()
