"""Dashboard integration: shared team records and durable operator zones."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

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
    return context


def transport_resources():
    # Only explicitly supplied capacity records; never invent vehicles from facilities.
    vehicles = team_records('resources')
    return {'vehicles': vehicles, 'source': 'data/resources.json', 'version': 1,
            'synthetic': any(v.get('simulated', False) for v in vehicles)}


class DashboardZone(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    area: str = Field(min_length=1, max_length=200)
    level: Literal['evacuate', 'warning', 'shelter', 'unknown']
    polygon: list[tuple[float, float]] = Field(default_factory=list, max_length=1000)
    instruction: str = Field(min_length=1, max_length=10000)

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


def instruction_for(db, location):
    normalized = ' '.join(location.casefold().strip(' .').split())
    matches = [z for z in zones(db) if normalized == ' '.join(z['area'].casefold().strip(' .').split())]
    if len(matches) != 1:
        return {'zone_id': None, 'action': 'unknown', 'version': None,
                'text': 'No unambiguous published dashboard instruction matches this confirmed location. Ask the operator; do not infer an order or a safe route.',
                'source': 'dashboard'}
    zone = matches[0]
    return {'zone_id': zone['id'], 'action': zone['level'], 'text': zone['instruction'],
            'version': zone['version'], 'effective_at': zone['updated_at'], 'source': 'dashboard'}
