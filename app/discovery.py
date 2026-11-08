"""Durable crawler reports and dashboard projections in the shared demo database."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

router = APIRouter(prefix='/api/discovery', tags=['discovery'])


class Record(BaseModel):
    model_config = ConfigDict(extra='allow')


class Point(Record):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Phone(Record):
    number: str = Field(pattern=r'^\+[1-9][0-9]{7,14}$')
    extension: str | None = Field(default=None, pattern=r'^\d{1,8}$')


class Lead(Record):
    lead_id: str = Field(min_length=1, max_length=200)
    incident_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    categories: list[str] = Field(max_length=20)
    address: str | None = None
    coordinates: Point | None = None
    phone: Phone | None = None
    phone_candidates: list[Phone] = Field(max_length=100)
    evidence: list[dict] = Field(max_length=200)
    flags: list[str] = Field(default_factory=list, max_length=100)
    is_mock: bool


class Report(Record):
    schema_version: Literal['1.0']
    run_id: str = Field(min_length=1, max_length=200)
    incident_id: str = Field(min_length=1, max_length=200)
    mode: Literal['live', 'mock']
    status: Literal['completed', 'partial', 'failed']
    started_at: datetime
    finished_at: datetime
    leads: list[Lead] = Field(max_length=1000)

    @model_validator(mode='after')
    def consistent(self):
        if not self.started_at.tzinfo or not self.finished_at.tzinfo or self.finished_at < self.started_at:
            raise ValueError('Report requires ordered, timezone-aware timestamps')
        if len({lead.lead_id for lead in self.leads}) != len(self.leads):
            raise ValueError('Duplicate lead IDs')
        for lead in self.leads:
            if lead.incident_id != self.incident_id or lead.is_mock != (self.mode == 'mock'):
                raise ValueError('Lead incident/mode must match its report')
            if lead.phone and not any((p.number, p.extension) == (lead.phone.number, lead.phone.extension) for p in lead.phone_candidates):
                raise ValueError('Selected phone must be an evidenced candidate')
        return self


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS discovery_runs (
          run_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, observed_at TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS discovery_facilities (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, observed_at TEXT NOT NULL, data TEXT NOT NULL);
    ''')


def facilities(db):
    return [json.loads(row['data']) for row in db.execute('SELECT data FROM discovery_facilities ORDER BY rowid')]


def save_report(db, report: Report):
    raw = report.model_dump(mode='json')
    serialized = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(serialized.encode()) > 10_000_000:
        raise HTTPException(413, 'Discovery report exceeds 10 MB')
    existing = db.execute('SELECT data FROM discovery_runs WHERE run_id=?', (report.run_id,)).fetchone()
    if existing:
        if existing['data'] != serialized:
            raise HTTPException(409, 'Run ID already belongs to a different report')
        return {'run_id': report.run_id, 'imported': 0, 'unchanged': len(report.leads), 'duplicate': True}
    # Start time prevents a slower, older run overwriting a newer discovery.
    observed_at = report.started_at.astimezone(timezone.utc).isoformat()
    imported = 0
    with db:
        db.execute('INSERT INTO discovery_runs VALUES (?,?,?,?)', (report.run_id, report.incident_id, observed_at, serialized))
        for lead in raw['leads']:
            key = json.dumps([report.incident_id, report.mode, lead['lead_id']])
            identifier = 'discovery-' + hashlib.sha256(key.encode()).hexdigest()[:24]
            point = lead.get('coordinates') or {}
            phone = lead.get('phone')
            contact = phone['number'] + ((' ext. ' + phone['extension']) if phone.get('extension') else '') if phone else ''
            item = {'id': identifier, 'name': lead['name'], 'type': next(iter(lead['categories']), 'facility'),
                    'area': ', '.join(raw.get('request', {}).get('locations', [])), 'address': lead.get('address'),
                    'latitude': point.get('lat'), 'longitude': point.get('lng'), 'contact': contact,
                    'simulated': lead['is_mock'], 'source': 'crawler', 'incident_id': report.incident_id,
                    'run_id': report.run_id, 'updated_at': raw['finished_at'],
                    'discovery': {**lead, 'review_status': 'needs_review', 'contact_status': 'not_contacted',
                                  'safety_status': 'unknown', 'capacity_status': 'unknown',
                                  'handoff': {'status': 'draft', 'dial_allowed': False}},
                    'attributions': raw.get('attributions', [])}
            result = db.execute('''INSERT INTO discovery_facilities VALUES (?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id, observed_at=excluded.observed_at, data=excluded.data
                WHERE excluded.observed_at > discovery_facilities.observed_at''',
                (identifier, report.run_id, observed_at, json.dumps(item, ensure_ascii=False, allow_nan=False)))
            imported += result.rowcount
    return {'run_id': report.run_id, 'imported': imported, 'unchanged': len(report.leads) - imported, 'duplicate': False}


@router.post('/import')
async def import_report(report: Report, request: Request):
    return save_report(request.app.state.db, report)


@router.get('/runs')
async def runs(request: Request):
    rows = request.app.state.db.execute('SELECT data FROM discovery_runs ORDER BY observed_at DESC LIMIT 100')
    return [{key: report.get(key) for key in ('run_id', 'incident_id', 'mode', 'status', 'started_at', 'finished_at', 'summary', 'website_enrichment', 'attributions')}
            for report in (json.loads(row['data']) for row in rows)]


@router.get('/runs/{run_id}')
async def run(run_id: str, request: Request):
    row = request.app.state.db.execute('SELECT data FROM discovery_runs WHERE run_id=?', (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Discovery run not found')
    return json.loads(row['data'])
