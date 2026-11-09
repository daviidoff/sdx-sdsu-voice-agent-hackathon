"""Evidence-backed place references, separate from caller-confirmed location text.

Photon public demo: https://github.com/komoot/photon#demo-server
API: https://github.com/komoot/photon/blob/master/docs/api-v1.md
Only confirmed-location requests trigger lookups, never dashboard polling. Results
are cached in SQLite; one process makes at most one request a second. Use a private
PHOTON_URL for larger deployments, or GEOCODING_ENABLED=0 for offline operation.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import time
import httpx

_last_request = 0.0
_request_lock = None
_lock_loop = None


def stamp():
    return datetime.now(timezone.utc).isoformat()


def normalize(value):
    return ' '.join(re.findall(r'[\w]+', str(value).casefold()))


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS geocode_cache (cache_key TEXT PRIMARY KEY, data TEXT NOT NULL, created_at REAL NOT NULL)')


def point_in_polygon(point, polygon):
    """Boundary-inclusive ray casting in latitude/longitude space."""
    lat, lng = point
    inside = False
    for i, (ay, ax) in enumerate(polygon):
        by, bx = polygon[i - 1]
        cross = (lng - ax) * (by - ay) - (lat - ay) * (bx - ax)
        if abs(cross) < 1e-10 and min(ax, bx) - 1e-10 <= lng <= max(ax, bx) + 1e-10 and min(ay, by) - 1e-10 <= lat <= max(ay, by) + 1e-10:
            return True
        if (ay > lat) != (by > lat) and lng < (bx - ax) * (lat - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def _point(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
        return (lat, lng) if math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180 else None
    except (TypeError, ValueError):
        return None


def candidate_bounds(candidate):
    """OSM/Photon extent in [west, north, east, south] order, never inferred size."""
    bounds = candidate.get('bounds')
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return None
    try:
        west, north, east, south = map(float, bounds)
    except (ValueError, TypeError):
        return None
    if not all(map(math.isfinite, (west, north, east, south))) or not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        return None
    return [west, north, east, south]


def uncertainty_bounds(candidates):
    """Envelope of sourced candidate references/footprints, not caller accuracy."""
    bounds = []
    for candidate in candidates:
        point = _point(candidate.get('lat'), candidate.get('lng'))
        if point:
            bounds.append([point[1], point[0], point[1], point[0]])
        if extent := candidate_bounds(candidate):
            bounds.append(extent)
    return [min(b[0] for b in bounds), max(b[1] for b in bounds),
            max(b[2] for b in bounds), min(b[3] for b in bounds)] if bounds else None


def _segments_intersect(a, b, c, d, proper=False):
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    values = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    if values[0]*values[1] < -1e-20 and values[2]*values[3] < -1e-20:
        return True
    if proper:
        return False
    for value, p, q, r in ((values[0], a, b, c), (values[1], a, b, d),
                           (values[2], c, d, a), (values[3], c, d, b)):
        if abs(value) < 1e-10 and min(p[0], q[0])-1e-10 <= r[0] <= max(p[0], q[0])+1e-10 and min(p[1], q[1])-1e-10 <= r[1] <= max(p[1], q[1])+1e-10:
            return True
    return False


def footprint_relation(candidate, polygon):
    """Return inside/partial/outside for a sourced footprint (point if no extent).

    A bounding box deliberately overestimates a feature's shape. A zone that only
    intersects that envelope cannot establish an instruction for the whole place.
    Checking edges and interior zone vertices also catches concave-zone notches.
    """
    point = _point(candidate.get('lat'), candidate.get('lng'))
    if not polygon or point is None:
        return 'outside'
    bounds = candidate_bounds(candidate)
    if not bounds:
        return 'inside' if point_in_polygon(point, polygon) else 'outside'
    west, north, east, south = bounds
    # Include the provider's reference when an imperfect extent omits it.
    west, north, east, south = min(west, point[1]), max(north, point[0]), max(east, point[1]), min(south, point[0])
    corners = [(south, west), (south, east), (north, east), (north, west)]
    pairs = [(corners[i-1], corners[i]) for i in range(4)]
    edges = [(polygon[i-1], polygon[i]) for i in range(len(polygon))]
    contained = [point_in_polygon(c, polygon) for c in corners]
    interior_vertex = any(south < lat < north and west < lng < east for lat, lng in polygon)
    crosses = any(_segments_intersect(a, b, c, d, proper=True) for a, b in pairs for c, d in edges)
    if all(contained) and not interior_vertex and not crosses:
        return 'inside'
    touches = any(_segments_intersect(a, b, c, d) for a, b in pairs for c, d in edges)
    return 'partial' if any(contained) or interior_vertex or touches else 'outside'


def _focus(zones):
    points = [point for zone in zones for point in zone.get('polygon', [])]
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _distance(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lng2-lng1)/2)**2
    return 12742 * math.asin(min(1, math.sqrt(value)))


def _unresolved(query, status='unresolved', **kwargs):
    return {'status': status, 'query': query, 'resolved_at': stamp(), **kwargs}


async def fetch_features(query, focus):
    global _last_request, _request_lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock_loop is not loop:
        _request_lock, _lock_loop = asyncio.Lock(), loop
    params = {'q': query, 'limit': 8, 'lang': 'en'}
    if focus:
        params.update(lat=focus[0], lon=focus[1], zoom=10)
    # A place category avoids mistaking an airport car park for the airport.
    if 'airport' in normalize(query).split():
        params['osm_tag'] = 'aeroway:aerodrome'
    async with _request_lock:
        await asyncio.sleep(max(0, 1.05 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(os.getenv('PHOTON_URL', 'https://photon.komoot.io/api/'), params=params,
                headers={'User-Agent': 'RelayDisasterDashboard/0.1 (https://github.com/daviidoff/sdx-sdsu-voice-agent-hackathon)'})
            response.raise_for_status()
            return response.json()['features']


def _candidate(feature, query):
    props = feature.get('properties') or {}
    geometry = feature.get('geometry') or {}
    coordinates = geometry.get('coordinates') or []
    point = _point(coordinates[1], coordinates[0]) if geometry.get('type') == 'Point' and len(coordinates) >= 2 else None
    if point is None:
        return None
    # A city/region centroid is not sufficiently precise to place a caller in an evacuation zone.
    if props.get('osm_key') == 'place' or props.get('type') in {'city', 'county', 'state', 'country'}:
        return None
    name = str(props.get('name') or '')
    street = ' '.join(str(props.get(k) or '') for k in ('housenumber', 'street'))
    searchable = normalize(name + ' ' + street + ' ' + ' '.join(str(props.get(k) or '') for k in ('city', 'district', 'state', 'country', 'postcode')))
    tokens = set(normalize(query).split()) - {'the', 'at', 'in'}
    if not tokens.issubset(set(searchable.split())):
        return None
    osm_type = {'N': 'node', 'W': 'way', 'R': 'relation'}.get(props.get('osm_type'))
    source_url = f"https://www.openstreetmap.org/{osm_type}/{props['osm_id']}" if osm_type and props.get('osm_id') else None
    return {'_exact_name_match': normalize(name) == normalize(query.split(',')[0]),
            '_name_match': tokens.issubset(set(normalize(name).split())), 'lat': point[0], 'lng': point[1], 'display_name': ', '.join(dict.fromkeys(str(props[k]) for k in ('name', 'city', 'state', 'country') if props.get(k))),
            'source': 'photon-openstreetmap', 'source_url': source_url, 'precision': 'place_reference',
            'attribution': '© OpenStreetMap contributors', 'place_name': name,
            'bounds': props.get('extent')}


async def resolve_place(db, query, facilities, zones):
    normalized = normalize(query)
    # Require a named place/address, not a generic category even with a map bias.
    specific = set(normalized.split()) - {'the', 'a', 'at', 'in', 'airport', 'international', 'zoo', 'hospital', 'school', 'station'}
    if not specific:
        return _unresolved(query, 'ambiguous', message='Confirm the named place and city before locating the caller.')
    local = []
    for item in facilities:
        names = [item.get('name', ''), item.get('address', ''), *(item.get('aliases') or [])]
        if normalized not in [normalize(name) for name in names if name]:
            continue
        point = _point(item.get('lat', item.get('latitude')), item.get('lng', item.get('longitude')))
        if point:
            local.append({'lat': point[0], 'lng': point[1], 'display_name': item.get('name', query), 'source': 'team-record',
                          'source_id': item.get('id'), 'source_url': item.get('source_url'), 'precision': 'place_reference'})
    if len(local) == 1:
        return {'status': 'resolved', 'query': query, 'resolved_at': stamp(), **local[0]}
    if len(local) > 1:
        return _unresolved(query, 'ambiguous', candidates=local, uncertainty_bounds=uncertainty_bounds(local))
    if os.getenv('GEOCODING_ENABLED', '1') == '0':
        return _unresolved(query, message='No local coordinate record; online geocoding is disabled.')
    focus = _focus(zones)
    cache_key = hashlib.sha256(json.dumps([4, normalized, focus, os.getenv('PHOTON_URL', ''), os.getenv('GEOCODING_OSM_MAP_URL', '')], sort_keys=True).encode()).hexdigest()
    cached = db.execute('SELECT data,created_at FROM geocode_cache WHERE cache_key=?', (cache_key,)).fetchone()
    if cached and time.time() - cached['created_at'] < 86400:
        result = json.loads(cached['data'])
        if result.get('status') == 'resolved':
            return result
    # A caller's recheck must actually retry a failed lookup. Do not cache failures
    # for a day, or repeatedly present the same failure as a fresh lookup.
    from app.intersections import parse_intersection, resolve_intersection
    intersection = parse_intersection(query)
    if intersection:
        result = await resolve_intersection(query, intersection, focus)
        if result['status'] == 'resolved':
            db.execute('INSERT OR REPLACE INTO geocode_cache VALUES (?,?,?)', (cache_key, json.dumps(result), time.time()))
            db.commit()
        return result
    try:
        features = await fetch_features(query, focus)
        candidates = [candidate for f in features if (candidate := _candidate(f, query))]
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return _unresolved(query, 'unavailable', message='Place lookup unavailable. Ask for a precise named location or operator map pin; do not infer coordinates.')
    # Prefer matching named places near the incident, but never turn a generic
    # category or an unrelated city-name-only hit into a caller position.
    if focus:
        nearby = [c for c in candidates if _distance(focus, (c['lat'], c['lng'])) < 100]
        if nearby:
            candidates = nearby
    # Prefer the named landmark over unrelated facilities that only match its city.
    # e.g. 'San Diego Airport' names SAN, not every aerodrome in San Diego county.
    exact = [c for c in candidates if c.get('_exact_name_match')]
    named = [c for c in candidates if c.get('_name_match')]
    if exact or named:
        candidates = exact or named
    for candidate in candidates:
        candidate.pop('_name_match', None)
        candidate.pop('_exact_name_match', None)
    unique = {c.get('source_url') or (c['lat'], c['lng']): c for c in candidates}
    candidates = list(unique.values())
    if len(candidates) == 1:
        result = {'status': 'resolved', 'query': query, 'resolved_at': stamp(), **candidates[0]}
    else:
        result = _unresolved(query, 'ambiguous' if candidates else 'unresolved', candidates=candidates, uncertainty_bounds=uncertainty_bounds(candidates),
            message='More precise caller location or an operator pin is required.' if candidates else 'No matching named place was found.')
    db.execute('INSERT OR REPLACE INTO geocode_cache VALUES (?,?,?)', (cache_key, json.dumps(result), time.time()))
    db.commit()
    return result
