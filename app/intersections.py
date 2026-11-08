"""Resolve cross streets from shared OSM nodes, never from street centroids."""
import json
import os
import re
import time
from difflib import SequenceMatcher

import httpx

from app.geography import _candidate, _distance, _point, _unresolved, fetch_features, normalize, stamp


SUFFIXES = {'st': 'street', 'dr': 'drive', 'ave': 'avenue', 'rd': 'road',
            'blvd': 'boulevard', 'ln': 'lane', 'ct': 'court', 'pl': 'place'}
_road_cache = {}


def street_name(value):
    return ' '.join(SUFFIXES.get(token, token) for token in normalize(value).split())


def parse_intersection(query):
    address, _, context = query.partition(',')
    parts = re.split(r'\s+(?:at|and|crossing|cross|corner of)\s+|\s*[&@/]\s*', address, flags=re.I)
    endings = set(SUFFIXES.values()) | {'way', 'parkway', 'terrace'}
    if len(parts) != 2 or any(not street_name(p).split() or street_name(p).split()[-1] not in endings for p in parts):
        return None
    return street_name(parts[0]), street_name(parts[1]), context.strip()


async def fetch_crossing_roads(anchors):
    # A small, bounded map extract for the verified street, cached independently
    # of the spoken cross-street spelling. No city-wide scans or polling lookups.
    bounds = [f['properties'].get('extent') or [*f['geometry']['coordinates'], *f['geometry']['coordinates']] for f in anchors]
    west = min(b[0] for b in bounds) - .0003
    east = max(b[2] for b in bounds) + .0003
    south = min(min(b[1], b[3]) for b in bounds) - .0003
    north = max(max(b[1], b[3]) for b in bounds) + .0003
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90) or (east-west)*(north-south) > .0005:
        raise ValueError('Street area too large; a more precise location is required')
    bbox = ','.join(str(v) for v in (west, south, east, north))
    url = os.getenv('GEOCODING_OSM_MAP_URL', 'https://www.openstreetmap.org/api/0.6/map.json')
    key = (url, bbox)
    cached = _road_cache.get(key)
    if cached and time.monotonic() - cached[0] < 600:
        return cached[1]
    async with httpx.AsyncClient(timeout=6) as client:
        async with client.stream('GET', url, params={'bbox': bbox}, headers={'User-Agent': 'EmergencyOS-demo/0.1'}) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 12_000_000:
                    raise ValueError('Map extract too large')
    elements = json.loads(content)['elements']
    nodes = {e['id']: e for e in elements if e['type'] == 'node'}
    roads = [{**e, 'geometry': [nodes.get(node) for node in e.get('nodes', [])]}
             for e in elements if e['type'] == 'way' and e.get('tags', {}).get('highway') and e['tags'].get('name')]
    if len(_road_cache) >= 16:
        _road_cache.pop(next(iter(_road_cache)))
    _road_cache[key] = (time.monotonic(), roads)
    return roads


def crossing_candidates(roads, first, second, context):
    first_nodes = set()
    for road in roads:
        if street_name(road.get('tags', {}).get('name', '')) == first:
            first_nodes.update(road.get('nodes', []))
    exact, suggestions = {}, {}
    for road in roads:
        name = road.get('tags', {}).get('name', '')
        normalized = street_name(name)
        if not normalized or normalized == first:
            continue
        matches = normalized == second
        # Similar spelling is a question for the caller, never confirmed coordinates.
        similar = normalized.split()[-1:] == second.split()[-1:] and SequenceMatcher(
            None, normalized.rsplit(' ', 1)[0], second.rsplit(' ', 1)[0]).ratio() >= .75
        if not matches and not similar:
            continue
        for node, geometry in zip(road.get('nodes', []), road.get('geometry', [])):
            if node not in first_nodes or not geometry:
                continue
            point = _point(geometry.get('lat'), geometry.get('lon'))
            if point is None:
                continue
            candidate = {'lat': point[0], 'lng': point[1], 'source': 'openstreetmap-intersection',
                         'source_url': f'https://www.openstreetmap.org/node/{node}',
                         'precision': 'intersection', 'display_name': f'{first.title()} at {name}, {context}',
                         'attribution': '© OpenStreetMap contributors'}
            (exact if matches else suggestions)[node] = candidate
    return list(exact.values()), list(suggestions.values())


async def resolve_intersection(query, parsed, focus):
    first, second, context = parsed
    if not context:
        return _unresolved(query, message='Confirm the city for this intersection before locating the caller.')
    try:
        features = await fetch_features(f'{first}, {context}', focus)
        anchors = [f for f in features if f.get('properties', {}).get('osm_key') == 'highway'
                   and street_name(f['properties'].get('name', '')) == first
                   and _candidate(f, f'{first}, {context}')]
        if not anchors:
            return _unresolved(query, message='The first street could not be verified in that city. Confirm the street name and city.')
        points = [(f['geometry']['coordinates'][1], f['geometry']['coordinates'][0]) for f in anchors]
        if any(_distance(points[0], point) > 5 for point in points[1:]):
            return _unresolved(query, 'ambiguous', message='Multiple streets match. Confirm the neighborhood or a nearby address.')
        roads = await fetch_crossing_roads(anchors)
        exact, suggestions = crossing_candidates(roads, first, second, context)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return _unresolved(query, 'unavailable', message='Intersection lookup unavailable. Ask for an exact nearby address or operator assistance; do not claim there is no published instruction.')
    # Divided roads can represent one junction as several nodes a few metres apart.
    # Keep an actual sourced node as the approximate reference, not an invented pin.
    if exact and all(_distance((exact[0]['lat'], exact[0]['lng']), (c['lat'], c['lng'])) <= .015 for c in exact):
        return {'status': 'resolved', 'query': query, 'resolved_at': stamp(), **exact[0]}
    if len(exact) > 1:
        return _unresolved(query, 'ambiguous', candidates=exact[:5], message='These streets intersect more than once. Confirm a nearby address.')
    if suggestions:
        names = list(dict.fromkeys(c['display_name'] for c in suggestions))
        return _unresolved(query, 'needs_confirmation', suggestions=names[:3],
                           message='Ask the caller whether they mean ' + ' or '.join(names[:3])
                           + '. Repeat the location lookup only after confirmation. Do not apply its coordinates or instructions yet.')
    return _unresolved(query, message='No shared junction was found for those street names. Confirm the spelling of both streets or an exact nearby address.')
