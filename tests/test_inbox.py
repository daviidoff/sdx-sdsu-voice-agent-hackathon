import pytest
from fastapi.testclient import TestClient
from app.backend import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOCODING_ENABLED', '0')
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('DAYTONA_API_KEY', raising=False)
    with TestClient(create_app(tmp_path / 'inbox.sqlite')) as client:
        yield client


def start(client):
    return '/api/calls/' + client.post('/api/calls', json={'mode': 'elevenlabs', 'scenario_id': 'dashboard'}).json()['id']


def zone(client, id='a', text='TEST: await operator guidance.', level='warning'):
    response = client.post('/api/dashboard/zones', json={'id': id, 'label': id, 'area': 'Test Area',
        'level': level, 'instruction': text})
    assert response.status_code == 200


def test_message_receipt_retry_read_reply_and_call_isolation(client):
    path, other = start(client), start(client)
    payload = {'text': 'Please clarify the instruction.', 'request_id': 'message-1'}
    receipt = client.post(path + '/operator-messages', json=payload).json()
    assert receipt['status'] == 'received'
    assert client.post(path + '/operator-messages', json=payload).json() == receipt
    assert len(client.get(path + '/operator-messages').json()['messages']) == 1
    assert client.get(other + '/operator-messages').json()['messages'] == []
    assert client.post(path + '/operator-messages', json={**payload, 'text': 'Changed'}).status_code == 409
    assert client.post(path + '/operator-messages', json={**payload, 'text': '  '}).status_code == 422
    assert client.post(path + '/steering', json={'text': '  '}).status_code == 422
    assert not client.get(path + '/operator-messages').json()['messages'][0]['read_by_operator']
    client.post(path + '/inbox/read', json={'through_event_id': int(receipt['message_id'])})
    assert client.get(path + '/operator-messages').json()['messages'][0]['read_by_operator']
    # A racing read only acknowledges the messages actually displayed.
    second = client.post(path + '/operator-messages', json={'text': 'New question', 'request_id': 'message-2'}).json()
    client.post(path + '/inbox/read', json={'through_event_id': int(receipt['message_id'])})
    assert not client.get(path + '/operator-messages').json()['messages'][-1]['read_by_operator']
    reply = client.post(path + '/steering', json={'text': 'Checking with coordinator.'}).json()['events'][-1]
    assert client.get(path + '/operator-messages').json()['replies'][0]['id'] == reply['id']
    assert reply['type'] == 'steering.queued'
    assert client.post(other + '/steering/' + reply['id'] + '/ack', json={}).status_code == 404
    client.post(path + '/steering/' + reply['id'] + '/ack', json={})
    assert client.get(path).json()['events'][-1]['type'] == 'steering.acknowledged'
    client.post(path + '/end')
    assert client.post(path + '/steering', json={'text': 'Too late'}).status_code == 409
    assert client.post(path + '/operator-messages', json=payload).status_code == 409
    assert client.post(path + '/inbox/read', json={'through_event_id': int(second['message_id'])}).status_code == 200
    assert len(client.get(path + '/operator-messages').json()['messages']) == 2


def test_identical_overlaps_provide_guidance_without_escalation(client):
    zone(client)
    zone(client, 'b')
    path = start(client)
    result = client.post(path + '/resolve', json={'location': 'Test Area'}).json()
    assert result['action'] == 'warning'
    assert result['match_status'] == 'overlap_agreement'
    assert result['matching_zone_ids'] == ['a', 'b']
    assert client.get(path + '/operator-messages').json()['messages'] == []


def test_conflict_escalates_once_and_operator_selects_versioned_guidance(client):
    zone(client)
    # Same action with different text still conflicts.
    zone(client, 'b', text='TEST: different guidance.')
    path = start(client)
    for _ in range(2):
        result = client.post(path + '/resolve', json={'location': 'Test Area'}).json()
        assert result['action'] == 'unknown'
        assert result['operator_receipt']['status'] == 'received'
    assert len(client.get(path + '/operator-messages').json()['messages']) == 1
    call = client.get(path).json()
    assert client.post(path + '/operator-instruction', json={'zone_id': 'b', 'revision': -1}).status_code == 409
    assert client.post(path + '/operator-instruction', json={'zone_id': 'elsewhere', 'revision': call['revision']}).status_code == 422
    selected = client.post(path + '/operator-instruction', json={'zone_id': 'b', 'revision': call['revision']}).json()
    assert selected['instruction']['match_status'] == 'operator_resolved'
    assert selected['instruction']['text'] == 'TEST: different guidance.'
    rechecked = client.post(path + '/resolve', json={'location': 'Test Area'}).json()
    assert rechecked['match_status'] == 'operator_resolved'
    # Updating either zone revokes the call-scoped choice and creates a new request.
    zone(client, text='TEST: new conflicting guidance.')
    updated = client.get(path).json()
    assert updated['instruction']['action'] == 'unknown'
    assert len(client.get(path + '/operator-messages').json()['messages']) == 2
    client.post(path + '/operator-instruction', json={'zone_id': 'b', 'revision': updated['revision']})
    client.post(path + '/resolve', json={'location': 'Different area'})
    returned = client.post(path + '/resolve', json={'location': 'Test Area'}).json()
    assert returned['action'] == 'unknown'
    assert len(client.get(path + '/operator-messages').json()['messages']) == 3


def test_inbox_and_read_state_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    database = tmp_path / 'persistent.sqlite'
    with TestClient(create_app(database)) as client:
        path = start(client)
        receipt = client.post(path + '/operator-messages', json={'text': 'Question', 'request_id': '1'}).json()
        client.post(path + '/inbox/read', json={'through_event_id': int(receipt['message_id'])})
        client.post(path + '/steering', json={'text': 'Answer'})
    with TestClient(create_app(database)) as client:
        thread = client.get(path + '/operator-messages').json()
        assert thread['messages'][0]['read_by_operator']
        assert thread['replies'][0]['payload']['text'] == 'Answer'
