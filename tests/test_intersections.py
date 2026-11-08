import copy

from fastapi.testclient import TestClient
import httpx
import pytest

from app.backend import create_app
from app.intersections import parse_intersection, crossing_candidates


QUERY = 'Pacific Beach Drive at Everts Street, Pacific Beach, San Diego'
POINT = {'lat': 32.7925867, 'lon': -117.2463902}
ROAD = {'type': 'Feature', 'properties': {'name': 'Pacific Beach Drive', 'osm_key': 'highway',
    'city': 'San Diego', 'district': 'Pacific Beach', 'osm_type': 'W', 'osm_id': 123},
    'geometry': {'type': 'Point', 'coordinates': [-117.2413628, 32.7934703]}}
ROADS = [{'tags': {'name': 'Pacific Beach Drive'}, 'nodes': [1, 2], 'geometry': [POINT, POINT]},
         {'tags': {'name': 'Everts Street'}, 'nodes': [1, 3], 'geometry': [POINT, POINT]}]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('GEOCODING_ENABLED', '1')
    monkeypatch.delenv('DAYTONA_API_KEY', raising=False)
    async def features(query, focus):
        return [ROAD]
    async def roads(anchors):
        return copy.deepcopy(ROADS)
    monkeypatch.setattr('app.intersections.fetch_features', features)
    monkeypatch.setattr('app.intersections.fetch_crossing_roads', roads)
    with TestClient(create_app(tmp_path / 'test.sqlite')) as client:
        client.post('/api/dashboard/zones', json={'id': 'pb', 'label': 'PB shelter', 'area': 'PB',
            'level': 'shelter', 'instruction': 'TEST: shelter in place',
            'polygon': [[32.78, -117.26], [32.81, -117.26], [32.81, -117.23], [32.78, -117.23]]})
        yield client


def start(client):
    return '/api/calls/' + client.post('/api/calls', json={'mode': 'elevenlabs', 'scenario_id': 'dashboard'}).json()['id']


def test_intersection_resolves_to_shared_node_and_shelter(client):
    path = start(client)
    result = client.post(path + '/resolve', json={'location': QUERY}).json()
    assert result['action'] == 'shelter'
    assert result['location_resolution']['lat'] == POINT['lat']
    assert result['location_resolution']['precision'] == 'intersection'
    assert result['location_resolution']['source_url'].endswith('/node/1')
    assert client.get('/api/dashboard/snapshot').json()['calls'][0]['assessment']['location_resolution']['lng'] == POINT['lon']


def test_misheard_street_requires_confirmation_then_updates_pin_and_instruction(client):
    path = start(client)
    client.post(path + '/resolve', json={'location': QUERY})
    result = client.post(path + '/resolve', json={'location': QUERY.replace('Everts', 'Everest')}).json()
    assert result['action'] == 'unknown'
    assert result['location_resolution']['status'] == 'needs_confirmation'
    assert 'lat' not in result['location_resolution']
    assert 'Everts Street' in result['text']
    confirmed = client.post(path + '/resolve', json={'location': QUERY}).json()
    assert confirmed['action'] == 'shelter'


def test_crossing_without_shared_nodes_is_not_an_intersection():
    roads = copy.deepcopy(ROADS)
    roads[1]['nodes'] = [8, 9]
    assert crossing_candidates(roads, 'pacific beach drive', 'everts street', 'San Diego') == ([], [])


def test_separate_intersections_remain_ambiguous(client, monkeypatch):
    async def roads(anchors):
        other = {'lat': 32.798, 'lon': -117.246}
        return [*ROADS, {'tags': {'name': 'Pacific Beach Drive'}, 'nodes': [4], 'geometry': [other]},
                {'tags': {'name': 'Everts Street'}, 'nodes': [4], 'geometry': [other]}]
    monkeypatch.setattr('app.intersections.fetch_crossing_roads', roads)
    result = client.post(start(client) + '/resolve', json={'location': QUERY}).json()
    assert result['action'] == 'unknown' and result['location_resolution']['status'] == 'ambiguous'


def test_divided_road_nodes_form_one_junction(client, monkeypatch):
    async def roads(anchors):
        other = {'lat': POINT['lat'] + .00001, 'lon': POINT['lon']}
        return [*ROADS, {'tags': {'name': 'Pacific Beach Drive'}, 'nodes': [4], 'geometry': [other]},
                {'tags': {'name': 'Everts Street'}, 'nodes': [4], 'geometry': [other]}]
    monkeypatch.setattr('app.intersections.fetch_crossing_roads', roads)
    assert client.post(start(client) + '/resolve', json={'location': QUERY}).json()['action'] == 'shelter'


def test_provider_failure_is_not_reported_as_no_instruction(client, monkeypatch):
    async def unavailable(anchors):
        raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr('app.intersections.fetch_crossing_roads', unavailable)
    result = client.post(start(client) + '/resolve', json={'location': QUERY}).json()
    assert result['location_resolution']['status'] == 'unavailable'
    assert 'Intersection lookup unavailable' in result['text']
    assert 'no published dashboard instruction' not in result['text'].lower()


def test_failed_named_place_lookup_is_retried(client, monkeypatch):
    requests = []
    async def features(query, focus):
        requests.append(query)
        return []
    monkeypatch.setattr('app.geography.fetch_features', features)
    path = start(client)
    for _ in range(2):
        client.post(path + '/resolve', json={'location': 'Unmapped place, San Diego'})
    assert len(requests) == 2


def test_intersection_parser_accepts_abbreviations_but_not_business_names():
    assert parse_intersection('Pacific Beach Dr & Everts St, San Diego') == ('pacific beach drive', 'everts street', 'San Diego')
    assert parse_intersection('Tavern at the Beach, San Diego') is None
