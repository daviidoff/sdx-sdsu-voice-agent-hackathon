"""Dashboard integration: shared team records and durable operator zones."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from app.geography import point_in_polygon, normalize

ROOT = Path(__file__).resolve().parents[1]


def team_records(name):
    path = Path(os.getenv('TEAM_DATA_DIR', str(ROOT / 'data'))) / f'{name}.json'
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text())
        records = value if isinstance(value, list) else [value]
        if not all(isinstance(item, dict) for item in records):
            raise ValueError('Expected records')
        return records
    except (OSError, ValueError) as exc:
        raise HTTPException(503, f'Team dataset {name} is unavailable or invalid') from exc


def team_context(db=None):
    context = {name: team_records(name) for name in ('facilities', 'incidents', 'routes')}
    if db is not None:
        from app.discovery import facilities
        context['facilities'].extend(facilities(db))
        from app.contacts import reported_needs
        context['reported_needs'] = reported_needs(db)
    return context


def transport_resources():
    # Only explicitly supplied capacity records; never invent vehicles from facilities.
    vehicles = team_records('resources')
    return {'vehicles': vehicles, 'source': 'data/resources.json', 'version': 1,
            'synthetic': any(v.get('simulated', False) for v in vehicles)}


class DashboardZone(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    area: str = Field(default='', max_length=200)
    level: Literal['evacuate', 'warning', 'shelter', 'unknown']
    polygon: list[tuple[float, float]] = Field(default_factory=list, max_length=1000)
    instruction: str = Field(min_length=1, max_length=10000)

    @model_validator(mode='after')
    def has_matching_scope(self):
        self.area = self.area.strip()
        if not self.polygon and not self.area:
            raise ValueError('A named area or drawn polygon is required')
        return self

    @field_validator('polygon')
    @classmethod
    def valid_polygon(cls, value):
        if value and len(value) < 3:
            raise ValueError('A polygon needs at least three points')
        if any(not (-90 <= lat <= 90 and -180 <= lng <= 180) for lat, lng in value):
            raise ValueError('Invalid coordinates')
        return value


def zones(db):
    return [json.loads(row['data']) for row in db.execute('SELECT data FROM dashboard_zones ORDER BY rowid')]


def instruction_for(db, location, resolution=None):
    normalized = normalize(location)
    available = zones(db)
    point = (resolution['lat'], resolution['lng']) if resolution and resolution.get('status') == 'resolved' else None
    # Polygon zones are geographic. Text matching is reserved for named-only zones.
    matches = [z for z in available if
        (bool(z.get('polygon')) and point is not None and point_in_polygon(point, z['polygon'])) or
        (not z.get('polygon') and normalized == normalize(z.get('area', '')))]
    # Shared boundaries are harmless only when the full published guidance agrees.
    agreeing = len(matches) > 1 and len({(z['level'], z['instruction'].strip()) for z in matches}) == 1
    if len(matches) != 1 and not agreeing:
        reason = 'overlapping_zones' if len(matches) > 1 else 'unlocated' if point is None else 'outside_zones'
        return {'zone_id': None, 'action': 'unknown', 'version': None,
                'text': 'Published zones overlap at this location; ask the operator to resolve the conflicting instructions.' if len(matches) > 1 else
                    'No published dashboard instruction matches the resolved location.' if point else
                    'The current location could not be mapped, so its published instruction has not been determined. '
                    + ((resolution or {}).get('message') or 'Ask for a precise location or operator assistance; do not infer an order or safe route.'),
                'source': 'dashboard', 'match_status': reason,
                'location_resolution': resolution,
                'matching_zone_ids': [z['id'] for z in matches],
                'matching_zones': [{'id': z['id'], 'label': z['label'], 'action': z['level'],
                                    'text': z['instruction'], 'version': z['version']} for z in matches]}
    zone = matches[0]
    return {'zone_id': zone['id'], 'action': zone['level'], 'text': zone['instruction'],
            'version': zone['version'], 'effective_at': zone['updated_at'], 'source': 'dashboard',
            'match_method': 'polygon' if zone.get('polygon') else 'area_name',
            'location_resolution': resolution,
            'matching_zone_ids': [z['id'] for z in matches],
            'match_status': 'overlap_agreement' if agreeing else 'matched'}
