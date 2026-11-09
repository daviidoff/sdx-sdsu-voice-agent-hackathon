"""Fire editing persists independently of live instructions and calls."""
from fastapi.testclient import TestClient
import pytest
from app.backend import create_app

FIRE = {'id': 'demo-fire', 'label': 'Canyon fire', 'polygon': [[32.75, -117.12], [32.76, -117.11], [32.74, -117.10]]}


def test_fire_lifecycle_persistence_and_instruction_isolation(tmp_path):
    database = tmp_path / 'fires.sqlite3'
    with TestClient(create_app(database)) as client:
        before = client.get('/api/dashboard/snapshot').json()
        response = client.post('/api/dashboard/fires', json=FIRE)
        assert response.status_code == 200
        saved = response.json()
        assert saved['simulated'] is True
        assert saved['polygon'] == FIRE['polygon']
        assert saved['updated_at']
        after = client.get('/api/dashboard/snapshot').json()
        assert after['fires'] == [saved]
        assert after['zones'] == before['zones']
        assert after['calls'] == before['calls']
    with TestClient(create_app(database)) as client:
        assert client.get('/api/dashboard/snapshot').json()['fires'] == [saved]
        edited = {**FIRE, 'label': 'Edited canyon fire', 'polygon': [[32.75, -117.12], [32.77, -117.11], [32.74, -117.10]]}
        assert client.post('/api/dashboard/fires', json=edited).status_code == 200
        rows = client.get('/api/dashboard/snapshot').json()['fires']
        assert len(rows) == 1 and rows[0]['polygon'] == edited['polygon']
        assert client.delete('/api/dashboard/fires/demo-fire').status_code == 200
        assert client.get('/api/dashboard/snapshot').json()['fires'] == []
        assert client.delete('/api/dashboard/fires/demo-fire').status_code == 404


@pytest.mark.parametrize('changes', [
    {'polygon': []}, {'polygon': [[0, 0], [1, 1], [2, 2]]},
    {'polygon': [[0, 0], [1, 1], [0, 0]]},
    {'polygon': [[91, 0], [1, 1], [2, 0]]},
    {'polygon': [[0, 0], [3, 3], [0, 2], [2, 0]]},
    {'label': '   '}, {'simulated': False},
])
def test_invalid_fire_is_not_saved(tmp_path, changes):
    with TestClient(create_app(tmp_path / 'fires.sqlite3')) as client:
        assert client.post('/api/dashboard/fires', json={**FIRE, **changes}).status_code == 422
        assert client.get('/api/dashboard/snapshot').json()['fires'] == []
