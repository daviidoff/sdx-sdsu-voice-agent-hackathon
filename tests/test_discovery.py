import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient
from app.backend import create_app
from crawler.disaster_crawler import DiscoveryRequest, discover
from crawler.disaster_crawler.osm import OSMProvider


def report():
    request = DiscoveryRequest.from_dict({'incident_id': 'berlin-test', 'locations': ['Berlin'], 'categories': ['health_clinic'], 'sources': ['osm'], 'country_code': 'DE', 'bounds': [13.39, 52.53, 13.42, 52.55]})
    return discover(request, OSMProvider(transport=lambda *_: {'elements': [{'type': 'node', 'id': 123, 'lat': 52.537, 'lon': 13.402, 'tags': {'name': 'Berlin clinic', 'amenity': 'doctors', 'phone': '030 / 449 60 62'}}]}))


def test_import_round_trip_persistence_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    (tmp_path / 'facilities.json').write_text(json.dumps([{'id': 'team', 'name': 'Team facility'}]))
    database = tmp_path / 'db.sqlite'
    data = report()
    with TestClient(create_app(database)) as client:
        assert client.post('/api/discovery/import', json=data).json()['imported'] == 1
        assert client.post('/api/discovery/import', json=data).json()['duplicate'] is True
        rows = client.get('/api/dashboard/snapshot').json()['facilities']
        assert len(rows) == 2
        item = rows[1]
        assert item['contact'] == '+49304496062'
        assert item['latitude'] == 52.537
        assert item['discovery']['evidence'][0]['source_url'] == 'https://www.openstreetmap.org/node/123'
        assert item['discovery']['handoff']['dial_allowed'] is False
        assert client.get('/api/dashboard/context').json()['facilities'] == rows
        stored = client.get('/api/discovery/runs/' + data['run_id']).json()
        assert stored['leads'][0]['evidence'] == data['leads'][0]['evidence']
        changed = copy.deepcopy(data); changed['leads'][0]['name'] = 'Changed'
        assert client.post('/api/discovery/import', json=changed).status_code == 409
    with TestClient(create_app(database)) as client:
        assert len(client.get('/api/dashboard/snapshot').json()['facilities']) == 2
        assert len(client.get('/api/discovery/runs').json()) == 1


def test_stale_results_and_incident_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    newer = report(); older = copy.deepcopy(newer)
    older.update(run_id='older', started_at='2026-01-01T00:00:00+00:00', finished_at='2026-01-01T00:00:01+00:00')
    older['leads'][0]['name'] = 'Stale name'
    with TestClient(create_app(tmp_path / 'db')) as client:
        assert client.post('/api/discovery/import', json=newer).status_code == 200
        assert client.post('/api/discovery/import', json=older).json()['imported'] == 0
        assert client.get('/api/dashboard/snapshot').json()['facilities'][0]['name'] == 'Berlin clinic'
        second = copy.deepcopy(newer); second['run_id'] = 'second'; second['incident_id'] = 'other'
        second['leads'][0]['incident_id'] = 'other'
        assert client.post('/api/discovery/import', json=second).json()['imported'] == 1
        assert len(client.get('/api/dashboard/snapshot').json()['facilities']) == 2


def test_invalid_report_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    with TestClient(create_app(tmp_path / 'db')) as client:
        for mutate in [lambda d: d['leads'][0].update(incident_id='wrong'),
                       lambda d: d['leads'][0].update(coordinates={'lat': 100, 'lng': 13}),
                       lambda d: d['leads'][0].update(is_mock=True),
                       lambda d: d['leads'][0].update(phone={'number': '+493012345678'}),
                       lambda d: d.update(started_at='2026-01-01T00:00:00')]:
            data = report(); mutate(data)
            assert client.post('/api/discovery/import', json=data).status_code == 422
        assert client.get('/api/discovery/runs').json() == []
        assert client.get('/api/dashboard/snapshot').json()['facilities'] == []
