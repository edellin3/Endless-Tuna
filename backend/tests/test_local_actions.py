"""Origin validation must permit the real dev proxy and reject foreign actions."""
import pytest
from fastapi.testclient import TestClient
from endless_tuna import db
from endless_tuna.main import app


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    with TestClient(app) as client:yield client


@pytest.mark.parametrize('host',['127.0.0.1:5173','localhost:5173','127.0.0.1:8041'])
def test_browser_facing_host_allows_local_actions(client,host):
    response=client.post('/api/intake/preview',headers={'Host':host,'Origin':'http://'+host,'Sec-Fetch-Site':'same-origin'},json={'url':'http://localhost/'})
    assert response.status_code==200
    assert response.json()['ok'] is False  # Input rejected, but origin check passed; no external traffic.


@pytest.mark.parametrize('headers',[
    {'Host':'127.0.0.1:5173','Origin':'https://foreign.invalid','Sec-Fetch-Site':'cross-site'},
    {'Host':'127.0.0.1:8041','Origin':'http://127.0.0.1:5173','Sec-Fetch-Site':'same-origin'},
    {'Host':'127.0.0.1:5173','Origin':'http://127.0.0.1:5173','Sec-Fetch-Site':'cross-site'},
])
def test_rewritten_or_foreign_origins_remain_blocked(client,headers):
    assert client.post('/api/intake/preview',headers=headers,json={'url':'http://localhost/'}).status_code==403
