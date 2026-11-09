from fastapi.testclient import TestClient
from app.backend import create_app
from app.contacts import put
from tests.test_contacts import search, publish_zone, POLYGON


def test_demo_call_without_phone_is_manual_and_reusable(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    with TestClient(create_app(tmp_path/'db')) as client:
        f = next(f for f in search(client) if f['type'] == 'health_clinic' and not f['contact'])
        info = client.get(f"/api/contacts/{f['id']}/demo-call")
        assert info.status_code == 200 and info.json()['name'] == f['name']
        assert set(info.json()) == {'id', 'name', 'voice_configured'}
        assert client.get('/api/contacts/overview').json()['sessions'] == []
        response = client.post(f"/api/contacts/{f['id']}/demo-call", json={})
        assert response.status_code == 200
        s = response.json()
        assert s['phone'] == '' and s['mock'] and s['mode'] == 'browser_mock'
        assert s['status'] == 'approved' and not s['transcript']
        assert client.get(f"/api/contacts/sessions/{s['id']}").json()['status'] == 'approved'
        assert client.post(f"/api/contacts/{f['id']}/demo-call", json={}).json()['id'] == s['id']
        s['status'] = 'connected'; put(client.app.state.db, 'contact_sessions', s)
        assert client.post(f"/api/contacts/{f['id']}/demo-call", json={}).status_code == 409
        client.post(f"/api/contacts/sessions/{s['id']}/end", json={'status': 'completed'})
        assert client.post(f"/api/contacts/{f['id']}/demo-call", json={}).json()['id'] != s['id']
        assert client.post('/api/contacts/missing/demo-call', json={}).status_code == 404


def test_clinic_context_uses_current_instruction_and_blocks_conflicts(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    with TestClient(create_app(tmp_path/'db')) as client:
        f = search(client)[0]
        s = client.post(f"/api/contacts/{f['id']}/demo-call", json={}).json()
        url = f"/api/contacts/sessions/{s['id']}/context"
        context = client.get(url).json()
        assert context['location_confirmation_required'] and context['mock']
        assert context['instruction']['action'] == 'warning'
        assert context['instruction']['text'] == 'Await operator guidance'
        response = client.post('/api/dashboard/zones', json={'id': 'zone1', 'label': 'zone1', 'area': 'zone1',
            'level': 'shelter', 'instruction': 'Exercise: remain inside the clinic.', 'polygon': POLYGON})
        assert response.status_code == 200
        updated = client.get(url).json()['instruction']
        assert updated['action'] == 'shelter' and updated['version'] > context['instruction']['version']
        publish_zone(client, 'conflicting', POLYGON)
        conflict = client.get(url).json()['instruction']
        assert conflict['action'] == 'unknown' and conflict['match_status'] == 'overlapping_zones'
        assert 'matching_zones' not in conflict
        s['facility_snapshot']['latitude'] = None
        s['facility_snapshot']['longitude'] = None
        put(client.app.state.db, 'contact_sessions', s)
        assert client.get(url).json()['instruction']['action'] == 'unknown'
