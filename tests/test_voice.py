from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from app.voice import router


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_unconfigured_voice_is_explicit(monkeypatch):
    monkeypatch.delenv('ELEVENLABS_AGENT_ID', raising=False)
    assert client().get('/api/voice/session?call_id=demo').status_code == 503


def test_public_agent_returns_no_credential(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_AGENT_ID', 'agent_demo')
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    result = client().get('/api/voice/session?call_id=demo')
    assert result.json() == {'agent_id': 'agent_demo'}
    assert result.headers['cache-control'] == 'no-store'


def test_private_agent_key_stays_server_side(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_AGENT_ID', 'agent_demo')
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-secret-not-for-browser')

    class Provider:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            assert kwargs['headers'] == {'xi-api-key': 'test-secret-not-for-browser'}
            assert kwargs['params'] == {'agent_id': 'agent_demo'}
            return httpx.Response(200, json={'signed_url': 'wss://example.invalid/one-time'}, request=httpx.Request('GET', url))

    monkeypatch.setattr('app.voice.httpx.AsyncClient', Provider)
    result = client().get('/api/voice/session?call_id=demo')
    assert result.json() == {'signed_url': 'wss://example.invalid/one-time'}
    assert 'test-secret' not in result.text


def test_provider_failure_does_not_leak_response(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_AGENT_ID', 'agent_demo')
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'secret')

    class Provider:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            return httpx.Response(401, text='sensitive provider details', request=httpx.Request('GET', url))

    monkeypatch.setattr('app.voice.httpx.AsyncClient', Provider)
    result = client().get('/api/voice/session?call_id=demo')
    assert result.status_code == 502
    assert 'sensitive' not in result.text
