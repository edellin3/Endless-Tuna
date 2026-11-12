"""All tests are offline; production HTTP transport is forbidden."""
import httpx
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for name in ('LAS_API_KEY', 'OPENAI_KEY', 'LAS_MODEL', 'LAS_TIMEOUT_SECONDS'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('LAS_API_BASE_URL', 'https://gateway.invalid/v1')
    def blocked(*args, **kwargs):
        raise AssertionError('Automated tests must inject a mocked transport; live network is forbidden.')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)
