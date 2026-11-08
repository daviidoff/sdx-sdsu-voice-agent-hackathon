"""Search campaigns, approved mock outreach and attributed assistance reports.

No endpoint dials a telephone number. Browser voice and scripted calls are simulations.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from app.discovery import Report, facilities, save_report
from app.geography import point_in_polygon

router = APIRouter(prefix='/api/contacts', tags=['contact-workflow'])


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize(db):
    for table in ('contact_searches', 'contact_sessions', 'contact_reports', 'contact_reviews'):
        db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    # Explicitly interrupt unfinished work; a restart is never a successful call.
    for job in rows(db, 'contact_searches'):
        if job['status'] in ('queued', 'running'):
            job.update(status='interrupted', error='Server restarted; run the search again.', finished_at=now())
            put(db, 'contact_searches', job)
    for session in rows(db, 'contact_sessions'):
        if session['status'] in ('connecting', 'connected', 'dialing', 'queued'):
            session.update(status='interrupted', ended_at=now())
            put(db, 'contact_sessions', session)
    db.commit()


def rows(db, table):
    return [json.loads(r['data']) for r in db.execute(f'SELECT data FROM {table} ORDER BY rowid DESC')]


def get(db, table, identifier):
    row = db.execute(f'SELECT data FROM {table} WHERE id=?', (identifier,)).fetchone()
    if not row:
        raise HTTPException(404, 'Contact workflow record not found')
    return json.loads(row['data'])


def put(db, table, value):
    db.execute(f'INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (value['id'], json.dumps(value)))
    db.commit()


def overview(db):
    return {'searches': rows(db, 'contact_searches'), 'sessions': rows(db, 'contact_sessions'),
            'reports': rows(db, 'contact_reports'), 'reviews': [v for v in rows(db, 'contact_reviews') if any(r['id'] == v['id'] and r.get('version') == v.get('report_version') for r in rows(db, 'contact_reports'))], 'mock_only': True}


class Search(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(default='San Diego contact search', min_length=1, max_length=150)
    provider: Literal['osm', 'mock'] = 'osm'
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=100)

    @model_validator(mode='after')
    def valid_area(self):
        # This dashboard is scoped to the user's San Diego test incident.
        if any(not (32.45 <= lat <= 33.2 and -117.65 <= lng <= -116.7) for lat, lng in self.polygon):
            raise ValueError('Draw the contact area in San Diego (32.45–33.2 N, 117.65–116.7 W).')
        origin = self.polygon[0]
        area = sum((a[1]-origin[1])*(b[0]-origin[0])-(b[1]-origin[1])*(a[0]-origin[0]) for a,b in zip(self.polygon, self.polygon[1:]+self.polygon[:1]))
        if abs(area) < 1e-10:
            raise ValueError('Draw a nonempty polygon')
        if max(p[0] for p in self.polygon)-min(p[0] for p in self.polygon) > .25 or max(p[1] for p in self.polygon)-min(p[1] for p in self.polygon) > .25:
            raise ValueError('Use an area smaller than 0.25 degrees per side for this bounded search.')
        return self


def launch(app, coroutine, name):
    task = asyncio.create_task(coroutine, name=name)
    app.state.jobs.add(task)
    task.add_done_callback(app.state.jobs.discard)


async def run_search(app, body: Search):
    from crawler.disaster_crawler import DiscoveryRequest, discover
    from crawler.disaster_crawler.models import CATEGORIES
    from crawler.disaster_crawler.providers import MockProvider
    from crawler.disaster_crawler.osm import OSMProvider
    db = app.state.db
    job = get(db, 'contact_searches', body.id)
    job.update(status='running', started_at=now())
    put(db, 'contact_searches', job)
    loop = asyncio.get_running_loop()
    def update(item):
        if job['status'] != 'running':
            return
        job['workers'][item['id']] = {**item, 'updated_at': now()}
        job['updated_at'] = now()
        put(db, 'contact_searches', job)
    def progress(item):
        if not loop.is_closed():
            loop.call_soon_threadsafe(update, item)
    try:
        request = DiscoveryRequest.from_dict({'incident_id': 'san-diego-demo', 'locations': ['San Diego, California, USA'],
            'categories': list(CATEGORIES), 'country_code': 'US', 'sources': ['osm'] if body.provider == 'osm' else ['maps', 'web'],
            'bounds': [min(p[1] for p in body.polygon), min(p[0] for p in body.polygon), max(p[1] for p in body.polygon), max(p[0] for p in body.polygon)],
            'max_tasks': 12, 'max_results_per_task': 50, 'max_leads': 100, 'concurrency': 3, 'task_timeout_seconds': 40,
            'enrich_websites': body.provider == 'osm', 'max_websites': 10})
        result = await asyncio.to_thread(discover, request, OSMProvider() if body.provider == 'osm' else MockProvider(), progress)
        # Overpass uses the polygon's bounding rectangle. Filter final results by the actual polygon.
        outside = [l for l in result['leads'] if not l['coordinates'] or not point_in_polygon((l['coordinates']['lat'], l['coordinates']['lng']), body.polygon)]
        result['leads'] = [l for l in result['leads'] if l not in outside]
        result['summary'].update(leads_returned=len(result['leads']), leads_with_phone=sum(bool(l['phone']) for l in result['leads']), polygon_excluded=len(outside))
        result['request']['search_polygon'] = body.polygon
        save_report(db, Report.model_validate(result))
        ids = [f['id'] for f in facilities(db) if f['run_id'] == result['run_id']]
        job.update(status=result['status'], run_id=result['run_id'], facility_ids=ids, summary=result['summary'],
                   website_enrichment=result.get('website_enrichment'), finished_at=now())
    except asyncio.CancelledError:
        job.update(status='interrupted', finished_at=now())
        raise
    except Exception:
        job.update(status='failed', error='Search failed. Retry the bounded search; existing contacts are retained.', finished_at=now())
    finally:
        put(db, 'contact_searches', job)


@router.post('/searches', status_code=202)
async def search(body: Search, request: Request):
    db = request.app.state.db
    existing = next((j for j in rows(db, 'contact_searches') if j['id'] == body.id), None)
    if existing:
        if existing['request'] != body.model_dump(mode='json'):
            raise HTTPException(409, 'Search ID already used with different parameters')
        return existing
    if any(j['status'] in ('queued', 'running') for j in rows(db, 'contact_searches')):
        raise HTTPException(409, 'A search is already running. Wait for it to finish.')
    job = {'id': body.id, 'label': body.label, 'provider': body.provider, 'polygon': body.polygon, 'request': body.model_dump(mode='json'),
           'status': 'queued', 'created_at': now(), 'workers': {}, 'facility_ids': []}
    put(db, 'contact_searches', job)
    launch(request.app, run_search(request.app, body), 'contact-search-'+body.id)
    return job


@router.get('/overview')
async def get_overview(request: Request):
    return overview(request.app.state.db)


class Approval(BaseModel):
    phone: str = Field(min_length=1, max_length=100)


def facility(db, identifier):
    match = next((f for f in facilities(db) if f['id'] == identifier), None)
    if not match or match.get('incident_id') != 'san-diego-demo':
        raise HTTPException(404, 'Search for this contact in the San Diego incident first')
    return match


@router.post('/{facility_id}/approve')
async def approve(facility_id: str, body: Approval, request: Request):
    db = request.app.state.db
    f = facility(db, facility_id)
    candidates = f['discovery']['phone_candidates']
    def formatted(p): return p['number'] + ((' ext. ' + p['extension']) if p.get('extension') else '')
    matching = {formatted(p) for p in candidates if formatted(p) == body.phone or p['number'] == body.phone}
    if len(matching) != 1 or f['discovery'].get('listed_closed'):
        raise HTTPException(422, 'Select a published candidate for an open listing')
    chosen_phone = next(iter(matching))
    existing = next((s for s in rows(db, 'contact_sessions') if s['facility_id'] == facility_id and s['status'] not in ('completed', 'cancelled', 'failed', 'interrupted')), None)
    if existing:
        if existing['phone'] != chosen_phone:
            raise HTTPException(409, 'Cancel the existing approval before changing its phone')
        return existing
    session = {'id': str(uuid4()), 'facility_id': facility_id, 'facility_name': f['name'], 'incident_id': 'san-diego-demo',
        'phone': chosen_phone, 'facility_snapshot': f, 'status': 'approved', 'mode': None, 'mock': True,
        'approved_at': now(), 'created_at': now(), 'transcript': [], 'identity_status': 'unconfirmed'}
    put(db, 'contact_sessions', session)
    return session


class Utterance(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    role: Literal['agent', 'user']
    text: str = Field(max_length=10000)


class Need(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    location: str | None = Field(default=None, max_length=500)
    people_count: int | None = Field(default=None, ge=1, le=10000)
    urgency: Literal['unknown', 'routine', 'urgent'] = 'unknown'


class ContactReport(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    receptionist_name: str | None = Field(default=None, max_length=200)
    reception_confirmed: bool = False
    needs: list[Need] = Field(default_factory=list, max_length=30)
    source_quote: str = Field(min_length=1, max_length=2000)


def save_contact_report(db, session, body, source='voice_agent'):
    # One current report per conversation, with previous versions retained for provenance.
    previous = next((r for r in rows(db, 'contact_reports') if r['id'] == session['id']), None)
    content = body.model_dump()
    if previous and previous['content'] == content:
        return previous
    record = {'id': session['id'], 'session_id': session['id'], 'facility_id': session['facility_id'],
              'facility_name': session['facility_name'], 'phone': session['phone'], 'incident_id': session['incident_id'],
              'mock': True, 'source': source, 'content': content, 'recorded_at': now(), 'status': 'needs_review',
              'history': (previous.get('history', []) + [{'content': previous['content'], 'recorded_at': previous['recorded_at']}]) if previous else []}
    record['history'] = record['history'][-30:]
    record['version'] = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    put(db, 'contact_reports', record)
    session['identity_status'] = 'self_reported_reception' if body.reception_confirmed else 'unconfirmed'
    put(db, 'contact_sessions', session)
    return record


@router.post('/sessions/{session_id}/report')
async def report(session_id: str, body: ContactReport, request: Request):
    db = request.app.state.db
    session = get(db, 'contact_sessions', session_id)
    if session['status'] not in ('connected', 'completed'):
        raise HTTPException(409, 'A connected conversation is required')
    # A quote must come from the receiver transcript, not agent-generated content.
    user_text = ' '.join(t['text'] for t in session['transcript'] if t['role'] == 'user')
    quote = ' '.join(body.source_quote.casefold().split())
    if not quote or quote not in ' '.join(user_text.casefold().split()):
        raise HTTPException(422, 'Source quote must match the receiver transcript; use their exact words')
    return save_contact_report(db, session, body)


@router.post('/sessions/{session_id}/transcript')
async def transcript(session_id: str, body: Utterance, request: Request):
    db = request.app.state.db
    session = get(db, 'contact_sessions', session_id)
    if session['status'] not in ('connecting', 'connected', 'completed'):
        raise HTTPException(409, 'Conversation is not open')
    entry = next((t for t in session['transcript'] if t['id'] == body.id and t['role'] == body.role), None)
    if entry:
        entry['text'] = body.text
    else:
        if len(session['transcript']) >= 500:
            raise HTTPException(422, 'Transcript limit reached')
        session['transcript'].append({**body.model_dump(), 'at': now()})
    put(db, 'contact_sessions', session)
    return session


@router.post('/sessions/{session_id}/connected')
async def connected(session_id: str, request: Request):
    db = request.app.state.db
    session = get(db, 'contact_sessions', session_id)
    if session['status'] != 'connecting':
        raise HTTPException(409, 'Session is not awaiting a browser connection')
    session.update(status='connected', connected_at=now())
    put(db, 'contact_sessions', session)
    return session


class End(BaseModel):
    status: Literal['completed', 'failed', 'cancelled'] = 'completed'


@router.post('/sessions/{session_id}/end')
async def end(session_id: str, body: End, request: Request):
    db = request.app.state.db
    session = get(db, 'contact_sessions', session_id)
    if session['status'] not in ('completed', 'cancelled', 'failed', 'interrupted'):
        outcome = body.status if session['status'] == 'connected' else ('failed' if body.status == 'completed' else body.status)
        session.update(status=outcome, ended_at=now())
        put(db, 'contact_sessions', session)
    return session


@router.post('/sessions/{session_id}/verify-reception')
async def verify(session_id: str, request: Request):
    db = request.app.state.db
    session = get(db, 'contact_sessions', session_id)
    if session['identity_status'] != 'self_reported_reception':
        raise HTTPException(409, 'The receiver must first confirm reception in the conversation report')
    review = {'id': session_id, 'session_id': session_id, 'facility_id': session['facility_id'], 'verified_at': now(),
              'identity_status': 'operator_verified_in_mock', 'mock': True,
              'report_version': get(db, 'contact_reports', session_id)['version']}
    put(db, 'contact_reviews', review)
    return review


def reported_needs(db):
    verified = {r['id']: r for r in rows(db, 'contact_reviews')}
    return [{**need, 'id': r['id'] + ':' + str(index), 'session_id': r['session_id'], 'facility_id': r['facility_id'],
             'reported_by': r['facility_name'], 'source_quote': r['content']['source_quote'], 'recorded_at': r['recorded_at'],
             'mock': True, 'status': 'needs_review', 'reception_verified': r['id'] in verified and verified[r['id']].get('report_version') == r.get('version')}
            for r in rows(db, 'contact_reports') for index, need in enumerate(r['content']['needs'])]


@router.get('/needs')
async def needs(request: Request):
    return reported_needs(request.app.state.db)

async def scripted_call(app, identifier):
    async with app.state.contact_semaphore:
        db = app.state.db
        s = get(db, 'contact_sessions', identifier)
        if s['status'] != 'queued':
            return
        s.update(status='dialing'); put(db, 'contact_sessions', s)
        await asyncio.sleep(1)
        s = get(db, 'contact_sessions', identifier)
        if s['status'] != 'dialing': return
        s.update(status='connected', connected_at=now()); put(db, 'contact_sessions', s)
        text = 'This is a scripted test. I am the receptionist. Two people need wheelchair transport from our front entrance.'
        for role, line in [('agent', 'This is a simulated outreach call. Are you reception, and does anyone need assistance?'), ('user', text), ('agent', 'I have recorded that as a mock assistance report for operator review. No transport has been dispatched.')]:
            await asyncio.sleep(1)
            s = get(db, 'contact_sessions', identifier)
            if s['status'] != 'connected': return
            s['transcript'].append({'id': str(uuid4()), 'role': role, 'text': line, 'at': now()}); put(db, 'contact_sessions', s)
        save_contact_report(db, s, ContactReport(summary='Scripted demonstration: two people need wheelchair transport.', reception_confirmed=True,
            source_quote=text, needs=[Need(description='Wheelchair transport requested (scripted mock)', location='Front entrance; exact pickup needs confirmation', people_count=2)]), 'scripted_mock')
        s.update(status='completed', ended_at=now()); put(db, 'contact_sessions', s)


@router.post('/sessions/{session_id}/simulate')
async def simulate(session_id: str, request: Request):
    db = request.app.state.db
    session = get(db, 'contact_sessions', session_id)
    if session['status'] != 'approved':
        raise HTTPException(409, 'Approve a new mock call first')
    session.update(status='queued', mode='scripted_mock'); put(db, 'contact_sessions', session)
    launch(request.app, scripted_call(request.app, session_id), 'contact-mock-'+session_id)
    return session


@router.post('/sessions/{session_id}/voice')
async def voice(session_id: str, request: Request, response: Response):
    from app.outreach_agent import agent_id
    db = request.app.state.db
    session = get(db, 'contact_sessions', session_id)
    if session['status'] != 'approved':
        raise HTTPException(409, 'Approve a new mock call first; each session has one receiver')
    session.update(status='connecting', mode='browser_mock'); put(db, 'contact_sessions', session)
    response.headers['Cache-Control'] = 'no-store'
    try:
        identifier = agent_id()
        async with httpx.AsyncClient(timeout=20) as client:
            result = await client.get('https://api.elevenlabs.io/v1/convai/conversation/get-signed-url',
                params={'agent_id': identifier}, headers={'xi-api-key': os.getenv('ELEVENLABS_API_KEY', '')})
            result.raise_for_status()
        return {'signed_url': result.json()['signed_url'], 'session': session,
                'dynamic_variables': {'facility_name': session['facility_name'], 'facility_address': session['facility_snapshot'].get('address') or 'not confirmed'}}
    except (httpx.HTTPError, ValueError, KeyError, RuntimeError):
        session.update(status='failed', ended_at=now()); put(db, 'contact_sessions', session)
        raise HTTPException(503, 'Outreach voice unavailable. Configure the dedicated outreach agent or use a scripted mock call.') from None
