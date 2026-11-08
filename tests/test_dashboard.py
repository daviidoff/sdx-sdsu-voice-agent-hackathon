import json
import time
from fastapi.testclient import TestClient
import pytest
from app.backend import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('DAYTONA_API_KEY', raising=False)
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    (tmp_path / 'facilities.json').write_text(json.dumps([{'id': 'team-1', 'name': 'Team shelter', 'simulated': True}]))
    with TestClient(create_app(tmp_path / 'dashboard.sqlite')) as client:
        yield client


def start(client):
    response = client.post('/api/calls', json={'mode': 'elevenlabs', 'scenario_id': 'dashboard'})
    assert response.status_code == 200
    return '/api/calls/' + response.json()['id']


def publish(client, **changes):
    response = client.post('/api/dashboard/zones', json={
        'id': 'team-zone', 'label': 'Team area', 'area': 'Mission Valley', 'level': 'shelter',
        'instruction': 'Test operator instruction: await a coordinator update.', **changes})
    assert response.status_code == 200
    return response.json()


def test_snapshot_has_only_stored_calls_and_team_records(client):
    initial = client.get('/api/dashboard/snapshot').json()
    assert initial['calls'] == [] and initial['zones'] == []
    assert initial['facilities'] == [{'id': 'team-1', 'name': 'Team shelter', 'simulated': True}]
    path = start(client)
    client.post(path + '/transcript', json={'role': 'user', 'text': 'We are four people.', 'segment_id': '1'})
    client.post(path + '/assessment', json={'people_count': 4})
    client.post(path + '/transcript', json={'role': 'user', 'text': 'We are five people.', 'segment_id': '1', 'replace': True})
    client.post(path + '/assessment', json={'people_count': 5})
    snapshot = client.get('/api/dashboard/snapshot').json()
    assert len(snapshot['calls']) == 1
    call = snapshot['calls'][0]
    assert call['assessment']['people_count'] == 5
    transcript = [e for e in call['events'] if e['type'] == 'transcript']
    assert len(transcript) == 1 and transcript[0]['payload']['text'] == 'We are five people.'
    client.post(path + '/end')
    assert client.get('/api/dashboard/snapshot').json()['calls'][0]['status'] == 'ended'


def test_published_dashboard_instructions_flow_to_matching_voice_calls(client):
    path, other = start(client), start(client)
    # Old demo orders never leak into a dashboard call.
    assert client.post(path + '/resolve', json={'location': 'North Ridge'}).json()['action'] == 'unknown'
    client.post(path + '/resolve', json={'location': 'Mission Valley'})
    client.post(other + '/resolve', json={'location': 'Other area'})
    first = publish(client)
    call = client.get(path).json()
    assert first['version'] == call['instruction']['version'] == 1
    assert call['instruction']['source'] == 'dashboard'
    assert call['events'][-1]['type'] == 'instruction.updated'
    assert client.get(other).json()['instruction']['action'] == 'unknown'
    assert publish(client, instruction='Updated test instruction')['version'] == 2
    assert client.get(path).json()['instruction']['text'] == 'Updated test instruction'
    # Editing an area revokes an order that no longer matches.
    publish(client, area='Different area')
    assert client.get(path).json()['instruction']['action'] == 'unknown'


def test_duplicate_areas_do_not_select_an_arbitrary_order(client):
    path = start(client)
    publish(client)
    publish(client, id='second-zone', level='evacuate')
    assert client.post(path + '/resolve', json={'location': 'Mission Valley'}).json()['action'] == 'unknown'


def test_steering_queued_acknowledged_and_visible_in_snapshot(client):
    path = start(client)
    queued = client.post(path + '/steering', json={'text': 'Ask about medication'}).json()['events'][-1]
    assert queued['type'] == 'steering.queued'
    client.post(path + '/steering/' + queued['id'] + '/ack', json={'status': 'context_delivered'})
    events = client.get('/api/dashboard/snapshot').json()['calls'][0]['events']
    assert events[-1]['type'] == 'steering.acknowledged'
    assert not any(e['type'] == 'transcript' for e in events)
    client.post(path + '/end')
    assert client.post(path + '/steering', json={'text': 'Too late'}).status_code == 409


def test_dashboard_jobs_never_fall_back_to_synthetic_vehicle_fleet(client):
    path = start(client)
    client.post(path + '/assessment', json={'location': 'Mission Valley', 'transport_needed': True, 'people_count': 3})
    for _ in range(100):
        events = client.get(path).json()['events']
        completed = [e for e in events if e['type'] == 'job.completed']
        if completed:
            break
        time.sleep(.01)
    result = completed[-1]['payload']['result']
    assert result['proposed_candidate'] is None
    assert result['synthetic_resources'] is False
    assert result['dispatch_status'] == 'not_dispatched'


def test_shared_data_is_read_live_and_malformed_data_reports_error(client, tmp_path):
    (tmp_path / 'facilities.json').write_text('[{"id":"new","name":"New team record"}]')
    assert client.get('/api/dashboard/context').json()['facilities'][0]['id'] == 'new'
    (tmp_path / 'facilities.json').write_text('broken')
    assert client.get('/api/dashboard/snapshot').status_code == 503


def test_dashboard_zone_persists_on_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    database = tmp_path / 'persistent.sqlite'
    with TestClient(create_app(database)) as client:
        publish(client)
    with TestClient(create_app(database)) as client:
        assert client.get('/api/dashboard/snapshot').json()['zones'][0]['version'] == 1


def test_demo_instruction_changes_never_override_dashboard_call(client):
    path = start(client)
    publish(client, area='North Ridge')
    client.post(path + '/resolve', json={'location': 'North Ridge'})
    original = client.get(path).json()['instruction']
    client.post('/api/instructions', json={'zone_id': 'north-ridge', 'action': 'evacuate', 'text': 'Separate demonstration fixture'})
    assert client.get(path).json()['instruction'] == original
