import asyncio
import threading
from fastapi.testclient import TestClient
import pytest
from app.backend import create_app
from app.geography import point_in_polygon

AIRPORT = {'type': 'Feature', 'properties': {'osm_type': 'W', 'osm_id': 209694794,
    'osm_key': 'aeroway', 'osm_value': 'aerodrome', 'type': 'house',
    'name': 'San Diego International Airport', 'city': 'San Diego', 'state': 'California', 'country': 'United States'},
    'geometry': {'type': 'Point', 'coordinates': [-117.1922464, 32.7333608]}}
POLYGON = [[32.748590, -117.221031], [32.748590, -117.117347], [32.713355, -117.117347], [32.713355, -117.221031]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('TEAM_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('GEOCODING_ENABLED', '1')
    monkeypatch.delenv('DAYTONA_API_KEY', raising=False)
    async def lookup(query, focus):
        return [AIRPORT] if 'San Diego' in query else []
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    with TestClient(create_app(tmp_path / 'geo.sqlite')) as client:
        yield client


def start(client):
    return '/api/calls/' + client.post('/api/calls', json={'mode': 'elevenlabs', 'scenario_id': 'dashboard'}).json()['id']


def publish(client, **changes):
    response = client.post('/api/dashboard/zones', json={'id': 'downtown', 'label': 'Downtown',
        'area': 'Downtown', 'level': 'evacuate', 'polygon': POLYGON,
        'instruction': 'TEST: Follow the operator-approved airport evacuation instruction.', **changes})
    assert response.status_code == 200
    return response.json()


def test_airport_place_reference_matches_drawn_zone_not_area_label(client):
    publish(client)
    path = start(client)
    instruction = client.post(path + '/resolve', json={'location': 'San Diego Airport'}).json()
    assert instruction['action'] == 'evacuate' and instruction['zone_id'] == 'downtown'
    assert instruction['match_method'] == 'polygon'
    call = client.get(path).json()
    location = call['assessment']['location_resolution']
    assert (location['lat'], location['lng']) == (32.7333608, -117.1922464)
    assert location['precision'] == 'place_reference'
    assert location['source_url'] == 'https://www.openstreetmap.org/way/209694794'
    assert call['assessment']['location'] == 'San Diego Airport'


def test_polygon_boundary_counts_as_inside_and_outside_does_not():
    assert point_in_polygon((32.7333608, -117.1922464), POLYGON)
    assert point_in_polygon(POLYGON[0], POLYGON)
    assert point_in_polygon((32.73, -117.221031), POLYGON)
    assert not point_in_polygon((33, -117), POLYGON)
    assert not point_in_polygon((32, -117), [])


def test_updated_polygon_recomputes_active_instruction_and_invalidates_old_result(client):
    path = start(client)
    client.post(path + '/resolve', json={'location': 'San Diego Airport'})
    assert client.get(path).json()['instruction']['action'] == 'unknown'
    publish(client)
    first = client.get(path).json()
    assert first['instruction']['action'] == 'evacuate'
    publish(client, polygon=[[34, -118], [34.1, -118], [34.1, -117.9]])
    moved = client.get(path).json()
    assert moved['instruction']['action'] == 'unknown'
    assert moved['revision'] > first['revision']
    assert next(e for e in reversed(moved['events']) if e['type'] == 'instruction.updated')['payload'] == moved['instruction']


def test_unknown_correction_clears_previous_coordinate_and_polygon_instruction(client):
    publish(client)
    path = start(client)
    client.post(path + '/resolve', json={'location': 'San Diego Airport'})
    changed = client.post(path + '/assessment', json={'location': 'Unidentified new address'}).json()
    assert changed['assessment']['location_resolution']['status'] == 'unresolved'
    assert 'lat' not in changed['assessment']['location_resolution']
    assert changed['instruction']['action'] == 'unknown'
    cleared = client.post(path + '/assessment', json={'location': None}).json()
    assert 'location_resolution' not in cleared['assessment']
    assert cleared['instruction'] is None


def test_generic_airport_and_city_centroid_never_locate_caller(client, monkeypatch):
    path = start(client)
    result = client.post(path + '/resolve', json={'location': 'the airport'}).json()
    assert result['location_resolution']['status'] == 'ambiguous'
    async def city(query, focus):
        return [{'properties': {'name': 'San Diego', 'osm_key': 'place', 'osm_value': 'city', 'type': 'city'},
                 'geometry': {'type': 'Point', 'coordinates': [-117.16, 32.72]}}]
    monkeypatch.setattr('app.geography.fetch_features', city)
    result = client.post(path + '/resolve', json={'location': 'San Diego'}).json()
    assert result['location_resolution']['status'] == 'unresolved'
    assert result['action'] == 'unknown'


def test_overlapping_polygon_orders_are_explicitly_ambiguous(client):
    publish(client)
    publish(client, id='second-zone', level='shelter')
    result = client.post(start(client) + '/resolve', json={'location': 'San Diego Airport'}).json()
    assert result['action'] == 'unknown' and result['match_status'] == 'overlapping_zones'
    assert set(result['matching_zone_ids']) == {'downtown', 'second-zone'}


def test_cache_reused_and_polling_never_queries_geocoder(client, monkeypatch):
    count = 0
    async def lookup(query, focus):
        nonlocal count
        count += 1
        return [AIRPORT]
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    path = start(client)
    first = client.post(path + '/resolve', json={'location': 'San Diego Airport'}).json()
    again = client.post(path + '/resolve', json={'location': 'San Diego Airport'}).json()
    for _ in range(3):
        client.get('/api/dashboard/snapshot')
    assert count == 1
    assert first['location_resolution']['resolved_at'] == again['location_resolution']['resolved_at']


def test_historical_enrichment_retains_original_instruction_and_event_history(client):
    publish(client)
    path = start(client)
    client.post(path + '/assessment', json={'location': 'San Diego Airport'})
    ended = client.post(path + '/end').json()
    updated = client.post('/api/dashboard/calls/' + ended['id'] + '/geolocate').json()
    assert updated['instruction'] == ended['instruction']
    assert updated['events'] == ended['events'] and updated['ended_at'] == ended['ended_at']
    assert updated['assessment']['location_resolution']['enriched_after_call'] is True
    assert updated['current_spatial_instruction']['zone_id'] == 'downtown'


def test_delayed_old_lookup_cannot_overwrite_location_correction(client, monkeypatch):
    entered = threading.Event()
    async def lookup(query, focus):
        if query == 'San Diego Airport':
            entered.set()
            await asyncio.sleep(.15)
            return [AIRPORT]
        return []
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    path = start(client)
    pending = threading.Thread(target=lambda: client.post(path + '/resolve', json={'location': 'San Diego Airport'}))
    pending.start()
    assert entered.wait(1)
    client.post(path + '/resolve', json={'location': 'Different confirmed address'})
    pending.join(2)
    current = client.get(path).json()
    assert current['assessment']['location'] == 'Different confirmed address'
    assert current['assessment']['location_resolution']['status'] == 'unresolved'
    assert current['instruction']['action'] == 'unknown'


def test_named_airport_wins_over_other_airports_matching_only_city(client, monkeypatch):
    other = {**AIRPORT, 'properties': {**AIRPORT['properties'], 'name': 'Brown Field Municipal Airport', 'osm_id': 101603157},
             'geometry': {'type': 'Point', 'coordinates': [-116.9795582, 32.5727262]}}
    async def lookup(query, focus):
        return [AIRPORT, other]
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    publish(client)
    result = client.post(start(client) + '/resolve', json={'location': 'San Diego Airport'}).json()
    assert result['zone_id'] == 'downtown'
    assert result['location_resolution']['place_name'] == 'San Diego International Airport'


def test_city_qualified_landmark_wins_over_business_name_extensions(client, monkeypatch):
    cove = {**AIRPORT, 'properties': {**AIRPORT['properties'], 'name': 'La Jolla Cove', 'osm_type': 'R', 'osm_id': 7102574, 'osm_key': 'natural', 'osm_value': 'beach'},
            'geometry': {'type': 'Point', 'coordinates': [-117.272987, 32.8504469]}}
    hotel = {**cove, 'properties': {**cove['properties'], 'name': 'La Jolla Cove Hotel & Suites', 'osm_id': 672728232}}
    async def lookup(query, focus):
        return [AIRPORT] if 'Airport' in query else [hotel, cove]
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    publish(client)
    path = start(client)
    first = client.post(path + '/resolve', json={'location': 'San Diego Airport'}).json()
    outside = client.post(path + '/resolve', json={'location': 'La Jolla Cove, San Diego'}).json()
    returned = client.post(path + '/resolve', json={'location': 'San Diego Airport'}).json()
    assert first['action'] == returned['action'] == 'evacuate'
    assert outside['action'] == 'unknown' and outside['match_status'] == 'outside_zones'
    assert outside['location_resolution']['place_name'] == 'La Jolla Cove'
    assert client.get(path).json()['assessment']['location_resolution']['place_name'] == 'San Diego International Airport'


def test_multiple_exact_named_places_share_order_but_remain_location_ambiguous(client, monkeypatch):
    other = {**AIRPORT, 'properties': {**AIRPORT['properties'], 'osm_id': 999}}
    async def lookup(query, focus):
        return [AIRPORT, other]
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    publish(client)
    result = client.post(start(client) + '/resolve', json={'location': 'San Diego International Airport, San Diego'}).json()
    assert result['action'] == 'evacuate' and result['match_method'] == 'candidate_consensus'
    assert result['location_resolution']['status'] == 'ambiguous'

# Real Photon references for the user-reported Crown Point/Pacific Beach case.
CROWN_POINT = [
    {'properties': {'osm_type': 'W', 'osm_id': 38088908, 'osm_key': 'leisure', 'osm_value': 'park',
                    'name': 'Crown Point', 'district': 'Pacific Beach', 'city': 'San Diego',
                    'extent': [-117.2346059, 32.7896345, -117.2317212, 32.782422]},
     'geometry': {'type': 'Point', 'coordinates': [-117.2329712, 32.7860198]}},
    {'properties': {'osm_type': 'N', 'osm_id': 13125562301, 'osm_key': 'amenity', 'osm_value': 'parking',
                    'name': 'Crown Point', 'district': 'Pacific Beach', 'city': 'San Diego'},
     'geometry': {'type': 'Point', 'coordinates': [-117.233055, 32.7848077]}},
]
SHELTER_POLYGON = [[32.81324715804999, -117.26380749550778], [32.81238152593336, -117.21675801953992],
                   [32.75292129095983, -117.1934049949719], [32.76302656020649, -117.2480098612412]]


def test_crown_point_candidates_share_shelter_instruction_without_inventing_caller_pin(client, monkeypatch):
    async def lookup(query, focus):
        return CROWN_POINT
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    zone = publish(client, id='pacific-beach', level='shelter', polygon=SHELTER_POLYGON, instruction='Shelter in place.')
    path = start(client)
    result = client.post(path + '/resolve', json={'location': 'Crown Point, Pacific Beach'}).json()
    assert result['zone_id'] == zone['id'] and result['action'] == 'shelter'
    assert result['match_method'] == 'candidate_consensus'
    assert result['location_confirmation_required'] is True
    location = result['location_resolution']
    assert location['status'] == 'ambiguous' and 'lat' not in location
    assert len(location['candidates']) == 2
    assert location['uncertainty_bounds'] == CROWN_POINT[0]['properties']['extent']
    # Changing a live published instruction recomputes agreement, including the
    # case where a conflicting zone covers only part of a candidate footprint.
    publish(client, id='conflicting-patch', level='evacuate',
            polygon=[[32.788, -117.234], [32.789, -117.234], [32.789, -117.233], [32.788, -117.233]])
    updated = client.get(path).json()['instruction']
    assert updated['action'] == 'unknown' and updated['match_status'] == 'location_spans_zones'


def test_candidates_on_different_sides_of_zone_remain_unknown(client, monkeypatch):
    other = {**CROWN_POINT[1], 'geometry': {'type': 'Point', 'coordinates': [-117.1, 32.73]}}
    async def lookup(query, focus):
        return [CROWN_POINT[0], other]
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    publish(client, level='shelter', polygon=SHELTER_POLYGON)
    result = client.post(start(client) + '/resolve', json={'location': 'Crown Point, Pacific Beach'}).json()
    assert result['action'] == 'unknown' and result['match_status'] == 'candidate_disagreement'
    publish(client, id='different-order', level='evacuate',
            polygon=[[32.72, -117.11], [32.74, -117.11], [32.74, -117.09], [32.72, -117.09]])
    result = client.post(start(client) + '/resolve', json={'location': 'Crown Point, Pacific Beach'}).json()
    assert result['action'] == 'unknown' and result['match_status'] == 'candidate_disagreement'
    assert set(result['matching_zone_ids']) == {'downtown', 'different-order'}


def test_candidate_footprints_cannot_cross_a_concave_zone_notch():
    from app.geography import footprint_relation
    candidate = {'lat': 1, 'lng': 1, 'bounds': [.5, 3.5, 3.5, .5]}
    # Every extent corner is inside, but the notch intrudes into its middle.
    polygon = [(0, 0), (0, 4), (4, 4), (4, 3), (2, 3), (2, 2), (4, 2), (4, 0)]
    assert footprint_relation(candidate, polygon) == 'partial'
    assert footprint_relation(candidate, [(0, 0), (0, 4), (4, 4), (4, 0)]) == 'inside'
    assert footprint_relation(candidate, [(5, 5), (5, 6), (6, 6)]) == 'outside'


def test_stale_resolution_cannot_apply_instruction_for_new_location(client):
    from app.dashboard import instruction_for
    from app.geography import initialize
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE dashboard_zones (data TEXT)')
    initialize(db)
    result = instruction_for(db, 'New location', {'status': 'resolved', 'query': 'Old location', 'lat': 1, 'lng': 1})
    assert result['match_status'] == 'unlocated'


def test_ambiguous_hospital_clarification_resolves_operator_area_in_next_turn(client, monkeypatch):
    """The tool must expose both hospitals before asking, then accept the city answer."""
    hospitals = [
        {'type': 'Feature', 'properties': {'osm_type': 'W', 'osm_id': 570070336,
          'osm_key': 'amenity', 'name': 'Scripps Mercy Hospital', 'city': 'San Diego'},
         'geometry': {'type': 'Point', 'coordinates': [-117.160071, 32.7513283]}},
        {'type': 'Feature', 'properties': {'osm_type': 'W', 'osm_id': 569998588,
          'osm_key': 'amenity', 'name': 'Scripps Mercy Hospital Chula Vista', 'city': 'Chula Vista'},
         'geometry': {'type': 'Point', 'coordinates': [-117.0839903, 32.6336784]}},
    ]
    async def lookup(query, focus):
        return hospitals
    monkeypatch.setattr('app.geography.fetch_features', lookup)
    publish(client, id='hospital-area', polygon=[[32.74,-117.17],[32.76,-117.17],[32.76,-117.15],[32.74,-117.15]],
            instruction='Operator instruction: evacuate this hospital area.')
    path = start(client)
    proposal = client.post(path+'/location-proposal', json={'location':'Mercy Hospital'}).json()
    reported = proposal['reported_zone']
    assert reported['resolution']['status'] == 'ambiguous'
    assert len(reported['resolution']['candidates']) == 2
    assert reported['instruction']['action'] == 'unknown'
    assert proposal['instruction'] is None
    # The model cannot choose a candidate itself in the initial turn.
    assert client.post(path+'/resolve', json={'location':'Scripps Mercy Hospital, San Diego'}).status_code == 409
    client.post(path+'/transcript', json={'role':'user','text':'The one in San Diego.'})
    result = client.post(path+'/resolve', json={'location':'Scripps Mercy Hospital, San Diego'})
    assert result.status_code == 200
    assert result.json()['zone_id'] == 'hospital-area'
    assert result.json()['text'] == 'Operator instruction: evacuate this hospital area.'
    assert client.get(path).json().get('pending_location') is None
    # Rechecks use the latest operator revision, not the provisional result.
    publish(client, id='hospital-area', level='shelter',
            polygon=[[32.74,-117.17],[32.76,-117.17],[32.76,-117.15],[32.74,-117.15]],
            instruction='Operator update: shelter in place.')
    refreshed = client.post(path+'/resolve', json={'location':'Scripps Mercy Hospital, San Diego'}).json()
    assert refreshed['action'] == 'shelter' and refreshed['version'] == 2
