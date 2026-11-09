"""Dashboard integration: shared team records and durable operator zones."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from app.geography import footprint_relation, normalize

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
    current = resolution and (not resolution.get('query') or normalize(resolution['query']) == normalized)
    point = resolution if current and resolution.get('status') == 'resolved' else None
    candidates = ([point] if point else resolution.get('candidates', [])
                  if current and resolution.get('status') == 'ambiguous' else [])
    named = [z for z in available if not z.get('polygon') and normalized == normalize(z.get('area', ''))]
    candidate_matches, partial = [], []
    for candidate in candidates:
        matched = list(named)
        for zone in available:
            if not zone.get('polygon'):
                continue
            relation = footprint_relation(candidate, zone['polygon'])
            if relation == 'inside':
                matched.append(zone)
            elif relation == 'partial':
                partial.append(zone)
        candidate_matches.append(matched)
    matches = list({z['id']: z for group in candidate_matches for z in group}.values()) if candidates else named
    signatures = {(z['level'], z['instruction'].strip()) for z in matches}
    complete = all(candidate_matches) if candidates else bool(named)
    # A fully covered location remains covered when an additional zone with the
    # identical guidance cuts through it. Only a different partial instruction
    # creates geographic uncertainty about what guidance applies.
    if complete and len(signatures) == 1 and partial and all(
            (z['level'], z['instruction'].strip()) in signatures for z in partial):
        matches = list({z['id']: z for z in [*matches, *partial]}.values())
        partial = []
    # Location ambiguity does not imply instruction ambiguity: all sourced
    # candidates can be wholly covered by the same published guidance. Preserve
    # candidate uncertainty; never choose one of their pins as the caller.
    consensus = bool(not point and candidates and complete and len(signatures) == 1 and not partial)
    agreeing = len(matches) > 1 and len(signatures) == 1
    if partial or not complete or not matches or len(signatures) > 1:
        all_matches = list({z['id']: z for z in [*matches, *partial]}.values())
        reason = ('location_spans_zones' if partial else 'candidate_disagreement' if candidates and not point
                  else 'overlapping_zones' if len(signatures) > 1 else 'unlocated' if point is None else 'outside_zones')
        if partial:
            message = 'The mapped place footprint crosses a published zone boundary. Confirm a more precise location or ask the operator; do not claim there is no instruction.'
        elif candidates and not point:
            message = 'The possible mapped locations do not all have the same published instruction. Confirm which location the caller means or ask the operator; do not claim there are no instructions.'
        elif len(signatures) > 1:
            message = 'Published zones overlap at this location; ask the operator to resolve the conflicting instructions.'
        elif point:
            message = 'No published dashboard instruction matches the resolved location.'
        else:
            message = ('The current location could not be mapped, so its published instruction has not been determined. '
                       + ((resolution or {}).get('message') or 'Ask for a precise location or operator assistance; do not infer an order or safe route.'))
        return {'zone_id': None, 'action': 'unknown', 'version': None, 'text': message,
                'source': 'dashboard', 'match_status': reason, 'location_resolution': resolution,
                'matching_zone_ids': [z['id'] for z in all_matches],
                'matching_zones': [{'id': z['id'], 'label': z['label'], 'action': z['level'],
                                    'text': z['instruction'], 'version': z['version']} for z in all_matches]}
    zone = matches[0]
    result = {'zone_id': zone['id'], 'action': zone['level'], 'text': zone['instruction'],
              'version': zone['version'], 'effective_at': zone['updated_at'], 'source': 'dashboard',
              'match_method': 'candidate_consensus' if consensus else 'polygon' if zone.get('polygon') else 'area_name',
              'location_resolution': resolution, 'matching_zone_ids': [z['id'] for z in matches],
              'match_status': 'candidate_agreement' if consensus else 'overlap_agreement' if agreeing else 'matched'}
    if consensus:
        result.update(location_precision='candidate_area', location_confirmation_required=True,
                      location_note='All mapped candidates and their available footprints have this published instruction. Relay it now; the exact caller position is still unconfirmed. Ask for a precise location if needed for assistance.')
    return result
