"""Local, synthetic incident API shared by the demo and voice integrations."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from app.dashboard import DashboardZone, team_context, transport_resources, zones, instruction_for
from app.geography import initialize as initialize_geography, resolve_place
from app.discovery import initialize as initialize_discovery, router as discovery_router
from app.contacts import initialize as initialize_contacts, overview as contact_overview, router as contact_router


SCENARIOS = [
    {"id": "dashboard", "name": "Live dashboard", "description": "Use shared team records and published operator instructions.", "location": "", "zone_id": None},
    {"id": "wildfire-north", "name": "North Ridge wildfire", "description": "Synthetic evacuation and transport intake.", "location": "North Ridge", "zone_id": "north-ridge"},
    {"id": "river-park", "name": "River Park shelter", "description": "Synthetic shelter-in-place instruction.", "location": "River Park", "zone_id": "river-park"},
    {"id": "lake-view", "name": "Lake View evacuation", "description": "Synthetic evacuation with accessible-transport intake.", "location": "Lake View", "zone_id": "lake-view"},
    {"id": "unknown-location", "name": "Unknown location", "description": "No matching instruction; request clarification.", "location": "Unknown", "zone_id": None},
]

ZONE_NAMES = {"north-ridge": "North Ridge", "river-park": "River Park", "lake-view": "Lake View"}
KNOWN_AREAS = "North Ridge, River Park, and Lake View"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StartCall(BaseModel):
    mode: Literal["simulation", "elevenlabs"] = "simulation"
    scenario_id: str = "wildfire-north"


class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class Transcript(TextInput):
    text: str = Field(max_length=10000)
    role: Literal["user", "agent"]
    segment_id: str | None = Field(default=None, max_length=200)
    replace: bool = False

    @model_validator(mode="after")
    def require_text_unless_correction(self):
        if not self.replace and not self.text:
            raise ValueError("Transcript text is required unless replacing an interrupted segment")
        return self


class Assessment(BaseModel):
    location: str | None = Field(default=None, max_length=1000)
    can_evacuate: bool | None = None
    people_count: int | None = Field(default=None, ge=1, le=10000)
    wheelchair_users: int | None = Field(default=None, ge=0, le=10000)
    mobility_needs: str | None = Field(default=None, max_length=2000)
    transport_needed: bool | None = None


class Location(BaseModel):
    location: str = Field(min_length=1, max_length=1000)


class InstructionInput(BaseModel):
    zone_id: Literal["north-ridge", "river-park", "lake-view"]
    action: Literal["evacuate", "shelter", "unknown"]
    text: str = Field(min_length=1, max_length=10000)


class SteeringAcknowledgement(BaseModel):
    status: Literal["context_delivered"] = "context_delivered"


class OperatorMessage(TextInput):
    request_id: str = Field(min_length=1, max_length=200)


class InboxRead(BaseModel):
    through_event_id: int = Field(ge=0)


class OperatorInstruction(BaseModel):
    zone_id: str
    revision: int


def zone_for(location: str) -> str | None:
    # Fixture matching only: do not pretend to geocode arbitrary addresses.
    normalized = " ".join(re.sub(r"[^a-z0-9 ]", " ", location.lower()).split())
    prefix = r"(?:actually )?(?:(?:i am|i m|we are|we re) )?(?:currently )?(?:(?:located )?(?:in|at) )?"
    matches = [zone for zone, name in ZONE_NAMES.items() if re.fullmatch(prefix + name.lower() + r"(?: area)?", normalized)]
    return matches[0] if len(matches) == 1 else None


def create_app(db_path: str | Path | None = None) -> FastAPI:
    database = str(db_path or os.getenv("DEMO_DB_PATH", os.getenv("DATABASE_PATH", "data/voice-agent.sqlite3")))

    @asynccontextmanager
    async def lifespan(api: FastAPI):
        if database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(database, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS dashboard_zones (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS instructions (zone_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_call ON events(call_id, id);
        """)
        initialize_discovery(db)
        initialize_contacts(db)
        api.state.contact_semaphore = asyncio.Semaphore(3)
        initialize_geography(db)
        api.state.db = db
        api.state.jobs = set()
        for zone, action, text in [
            ("north-ridge", "evacuate", "DEMO: The simulated responder order for North Ridge is to evacuate. No route has been approved in this fixture."),
            ("river-park", "shelter", "DEMO: The simulated responder order for River Park is to shelter in place and await updated instructions."),
            ("lake-view", "evacuate", "DEMO: Lake View is under a simulated evacuation order. Report the number of people and accessible-transport needs to the demo responder. No route or vehicle assignment has been approved."),
        ]:
            instruction = {"zone_id": zone, "action": action, "text": text, "version": 1, "effective_at": now(), "expires_at": None, "authorized_by": "demo-operator", "simulation": True}
            db.execute("INSERT OR IGNORE INTO instructions VALUES (?, ?)", (zone, json.dumps(instruction)))
            # Add editor metadata to existing fixtures without replacing edits or
            # resetting instruction versions when the application restarts.
            stored = json.loads(db.execute("SELECT data FROM instructions WHERE zone_id = ?", (zone,)).fetchone()["data"])
            stored.update(id=zone, name=ZONE_NAMES[zone], source="synthetic-responder-fixture")
            db.execute("UPDATE instructions SET data = ? WHERE zone_id = ?", (json.dumps(stored), zone))
        db.commit()
        yield
        for task in api.state.jobs:
            task.cancel()
        if api.state.jobs:
            await asyncio.gather(*api.state.jobs, return_exceptions=True)
        try:
            from app.workers import close_all
            await close_all()
        except ImportError:
            pass
        finally:
            db.close()

    api = FastAPI(title="Disaster response demo API", lifespan=lifespan)
    api.include_router(discovery_router)
    api.include_router(contact_router)
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000").split(",")
    api.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in origins if origin.strip()], allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "Last-Event-ID"])

    def db():
        return api.state.db

    def read_call(call_id: str, writable=False):
        row = db().execute("SELECT data FROM calls WHERE id = ?", (call_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Call not found")
        call = json.loads(row["data"])
        if writable and call["status"] == "ended":
            raise HTTPException(409, "Call has ended")
        return call

    def save(call):
        db().execute("INSERT OR REPLACE INTO calls VALUES (?, ?)", (call["id"], json.dumps(call)))
        db().commit()

    def event(call_id, event_type, payload):
        created = now()
        cursor = db().execute("INSERT INTO events(call_id, type, payload, created_at) VALUES (?, ?, ?, ?)", (call_id, event_type, json.dumps(payload), created))
        db().commit()
        return {"id": str(cursor.lastrowid), "call_id": call_id, "type": event_type, "payload": payload, "created_at": created}

    def events(call_id, after=0):
        rows = db().execute("SELECT * FROM events WHERE call_id = ? AND id > ? ORDER BY id", (call_id, after)).fetchall()
        return [{"id": str(row["id"]), "call_id": row["call_id"], "type": row["type"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]} for row in rows]

    def full(call_id):
        return {**read_call(call_id), "events": events(call_id)}

    def send_to_operator(call, text, request_id, source="agent"):
        previous = next((e for e in events(call['id']) if e['type'] == 'operator.requested'
                         and e['payload'].get('request_id') == request_id), None)
        if previous and previous['payload']['text'] != text:
            raise HTTPException(409, 'Request ID already used for a different message')
        receipt = previous or event(call['id'], 'operator.requested', {
            'text': text, 'request_id': request_id, 'source': source,
            'location': call['assessment'].get('location'), 'status': 'received'})
        return {'status': 'received', 'message_id': receipt['id'], 'thread_id': call['id'],
                'notice': 'Saved in the operator inbox. This does not mean an operator has read it or that help is assigned.'}

    def dashboard_instruction(call):
        location = call['assessment'].get('location') or ''
        instruction = instruction_for(db(), location, call['assessment'].get('location_resolution'))
        if instruction.get('match_status') == 'overlapping_zones':
            signature = json.dumps([location, instruction['matching_zones']], sort_keys=True)
            override = call.get('operator_instruction')
            if override and override['signature'] == signature:
                chosen = next(z for z in instruction['matching_zones'] if z['id'] == override['zone_id'])
                call.pop('zone_conflict_request', None)
                return {**instruction, 'zone_id': chosen['id'], 'action': chosen['action'],
                        'text': chosen['text'], 'version': chosen['version'],
                        'match_status': 'operator_resolved', 'authorized_by': 'operator'}
            call.pop('operator_instruction', None)
            pending = call.get('zone_conflict_request')
            if not pending or pending['signature'] != signature:
                pending = {'signature': signature, 'request_id': 'zone-conflict:' + str(uuid4())}
                call['zone_conflict_request'] = pending
            instruction['operator_receipt'] = send_to_operator(call,
                'Conflicting instructions at ' + location + '. Please select the applicable instruction.\n' +
                '\n'.join(f"{z['label']} (v{z['version']}): {z['text']}" for z in instruction['matching_zones']),
                pending['request_id'], source='backend')
        else:
            call.pop('operator_instruction', None)
            call.pop('zone_conflict_request', None)
        return instruction

    api.state.store = SimpleNamespace(get_call=read_call, get_events=events, append_event=event, full_call=full)

    def say(call_id, text):
        event(call_id, "transcript", {"role": "agent", "text": text, "simulation": True})

    def intake_question(call):
        assessment = call["assessment"]
        if call.get("pending_location"):
            return "First, is the location you gave where you are now? Please answer yes or no."
        if not assessment.get("location") or not call.get("instruction") or call["instruction"]["action"] == "unknown":
            return f"Where are you currently located? The demo recognizes {KNOWN_AREAS}."
        if assessment.get("can_evacuate") is None:
            return "If evacuation is needed, are you able to leave on your own?"
        if not assessment.get("people_count"):
            return "How many people are with you, including yourself?"
        return "Does anyone need mobility assistance, accessible transport, or other help?"

    def lookup(location):
        zone = zone_for(location)
        row = db().execute("SELECT data FROM instructions WHERE zone_id = ?", (zone,)).fetchone() if zone else None
        instruction = json.loads(row["data"]) if row else None
        if instruction and instruction.get("expires_at"):
            try:
                expired = datetime.fromisoformat(instruction["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
            except (ValueError, TypeError):
                expired = True
            if expired:
                instruction = None
        return instruction or {"zone_id": zone, "action": "unknown", "text": "No current approved demo instruction matches this location. Confirm the location with the responder; do not infer an evacuation order or route.", "version": None, "simulation": True}

    def resolve(call, location):
        call["assessment"]["location"] = location
        call["assessment"]["location_confirmed_at"] = now()
        call["revision"] += 1
        call["instruction"] = instruction_for(db(), location, call["assessment"].get("location_resolution")) if call["scenario_id"] == "dashboard" else lookup(location)
        save(call)
        event(call["id"], "assessment.updated", call["assessment"])
        event(call["id"], "instruction.updated", call["instruction"])
        return call["instruction"]

    async def locate_dashboard(call_id, location, *, historical=False):
        call = read_call(call_id, writable=not historical)
        request_id = str(uuid4())
        if historical:
            expected_location = call["assessment"].get("location")
        else:
            if call['assessment'].get('location') != location:
                call.pop('operator_instruction', None)
                call.pop('zone_conflict_request', None)
            call["assessment"]["location"] = location
            call["assessment"]["location_confirmed_at"] = now()
            call["assessment"]["location_resolution"] = {"status": "pending", "query": location, "request_id": request_id}
            call["revision"] += 1
            call["instruction"] = instruction_for(db(), location)
            save(call)
            event(call_id, "assessment.updated", call["assessment"])
            event(call_id, "instruction.updated", call["instruction"])
        resolution = await resolve_place(db(), location, team_context(db())["facilities"], zones(db()))
        current = read_call(call_id)
        if historical:
            # Enrich map metadata explicitly, retaining the instruction and events
            # actually seen during the ended conversation.
            if current["status"] != "ended" or current["assessment"].get("location") != expected_location:
                raise HTTPException(409, "Call state changed while resolving its location")
            current["assessment"]["location_resolution"] = {**resolution, "enriched_after_call": True}
            current["current_spatial_instruction"] = instruction_for(db(), location, resolution)
            save(current)
            return current["current_spatial_instruction"]
        if current["status"] == "ended" or current["assessment"].get("location_resolution", {}).get("request_id") != request_id:
            # A later location, cleared location, or call end wins over a delayed response.
            return current.get("instruction") or {}
        current["assessment"]["location_resolution"] = resolution
        current["instruction"] = dashboard_instruction(current)
        current["revision"] += 1
        save(current)
        event(call_id, "assessment.updated", current["assessment"])
        event(call_id, "instruction.updated", current["instruction"])
        return current["instruction"]

    def launch_job(call):
        if call["status"] == "ended" or not (call["assessment"].get("transport_needed") or call["assessment"].get("can_evacuate") is False):
            return
        signature = json.dumps([call["assessment"], call["instruction"]], sort_keys=True)
        if call.get("last_job_signature") == signature:
            return
        call["last_job_signature"] = signature
        save(call)
        job_id = str(uuid4())
        revision = call["revision"]
        assessment = dict(call["assessment"])
        instruction = dict(call["instruction"] or {})
        event(call["id"], "job.started", {"job_id": job_id, "revision": revision, "status": "pending", "simulation": True})

        async def work():
            try:
                from app.workers import run_case_job
                if call["scenario_id"] == "dashboard":
                    result = await run_case_job(call["id"], assessment, instruction, resources=transport_resources())
                else:
                    result = await run_case_job(call["id"], assessment, instruction)
                current = read_call(call["id"])
                if current["status"] == "ended":
                    return
                if current["revision"] != revision:
                    event(call["id"], "job.discarded", {"job_id": job_id, "revision": revision, "current_revision": current["revision"], "reason": "Call information or instructions changed"})
                    return
                event(call["id"], "job.completed", {"job_id": job_id, "revision": revision, "result": result, "simulation": True})
            except asyncio.CancelledError:
                raise
            except Exception:
                current = read_call(call["id"])
                if current["status"] != "ended":
                    event(call["id"], "job.failed", {"job_id": job_id, "revision": revision, "message": "Background analysis unavailable; assistance remains unconfirmed.", "simulation": True})

        task = asyncio.create_task(work(), name=call["id"])
        api.state.jobs.add(task)
        task.add_done_callback(api.state.jobs.discard)

    @api.get("/api/config")
    async def config():
        agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")
        return {"elevenlabs_agent_id": agent_id, "voice_configured": bool(agent_id), "daytona_configured": bool(os.getenv("DAYTONA_API_KEY")), "simulation": True}

    @api.get("/api/scenarios")
    async def scenarios():
        return {"scenarios": SCENARIOS}

    @api.get("/api/instructions")
    async def list_instructions():
        return {"instructions": [json.loads(db().execute("SELECT data FROM instructions WHERE zone_id = ?", (zone,)).fetchone()["data"]) for zone in ZONE_NAMES]}

    @api.get("/api/calls")
    async def list_calls():
        return {"calls": [json.loads(row["data"]) for row in db().execute("SELECT data FROM calls ORDER BY rowid DESC").fetchall()]}

    @api.post("/api/calls")
    async def start_call(body: StartCall):
        if body.scenario_id == "dashboard" and body.mode != "elevenlabs":
            raise HTTPException(422, "Use ElevenLabs voice for dashboard calls; choose a demo scenario for simulation")
        if body.scenario_id not in {item["id"] for item in SCENARIOS}:
            raise HTTPException(422, "Unknown scenario")
        call = {"id": str(uuid4()), "status": "active", "mode": body.mode, "scenario_id": body.scenario_id, "assessment": {}, "instruction": None, "revision": 0, "created_at": now(), "simulation": True}
        save(call)
        event(call["id"], "call.started", {"mode": body.mode, "simulation": True})
        if body.mode == "simulation":
            say(call["id"], "This is a disaster response simulation. Where are you currently located? Please name the area or address.")
        return full(call["id"])

    @api.get("/api/calls/{call_id}")
    async def get_call(call_id: str):
        return full(call_id)

    @api.get("/api/calls/{call_id}/events")
    async def stream_events(call_id: str, request: Request, last_event_id: str | None = Header(default=None)):
        read_call(call_id)
        try:
            after = max(0, int(last_event_id or "0"))
        except ValueError:
            raise HTTPException(400, "Invalid Last-Event-ID")

        async def stream():
            cursor = after
            while not await request.is_disconnected():
                for item in events(call_id, cursor):
                    cursor = int(item["id"])
                    yield f"id: {cursor}\ndata: {json.dumps(item)}\n\n"
                if read_call(call_id)["status"] == "ended":
                    break
                yield ": keepalive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @api.post("/api/calls/{call_id}/messages")
    async def message(call_id: str, body: TextInput):
        call = read_call(call_id, writable=True)
        if call["mode"] != "simulation":
            raise HTTPException(409, "Use the transcript endpoint for live voice")
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "Message is empty")
        event(call_id, "transcript", {"role": "user", "text": text, "simulation": True})
        assessment = call["assessment"]
        named_zone = zone_for(text)
        current_zone = zone_for(assessment.get("location") or "")
        if call.get("pending_location"):
            answer = text.lower().strip(" .!")
            if answer in {"yes", "yes i am", "yes we are", "correct", "that is correct"}:
                location = call.pop("pending_location")
                instruction = resolve(call, location)
                followup = ("Demo responder asks: " + call["pending_operator_question"]["text"]) if call.get("pending_operator_question") else intake_question(call)
                say(call_id, instruction["text"] + " " + followup)
                launch_job(call)
            elif answer in {"no", "incorrect", "not there"}:
                call.pop("pending_location", None)
                save(call)
                say(call_id, f"Please tell me your current area. The demo recognizes {KNOWN_AREAS}.")
            elif named_zone:
                call["pending_location"] = text
                save(call)
                say(call_id, f"You said {text}. Is that where you are now? Please answer yes or no.")
            else:
                say(call_id, "Please confirm whether that is your current location with yes or no.")
        elif named_zone and (not current_zone or named_zone != current_zone):
            call["pending_location"] = text
            call["revision"] += 1
            # Stop relying on the old order as soon as a correction is offered.
            call["instruction"] = None
            assessment.pop("location", None)
            assessment.pop("location_confirmed_at", None)
            save(call)
            event(call_id, "assessment.updated", assessment)
            event(call_id, "instruction.updated", None)
            say(call_id, f"You said {text}. Is that where you are now? Please answer yes or no.")
        elif call.get("pending_operator_question"):
            question = call.pop("pending_operator_question")
            save(call)
            event(call_id, "operator.followup", {"question_id": question["id"], "question": question["text"], "answer": text, "simulation": True})
            say(call_id, "I recorded your answer for the demo responder. " + intake_question(call))
        elif not assessment.get("location") or not call["instruction"] or call["instruction"]["action"] == "unknown":
            instruction = lookup(text)
            if instruction["action"] == "unknown":
                say(call_id, f"I could not match that to a current demo instruction. The demo recognizes {KNOWN_AREAS}. Please clarify your current location.")
            else:
                call["pending_location"] = text
                save(call)
                say(call_id, f"You said {text}. Is that where you are now? Please answer yes or no.")
        elif assessment.get("can_evacuate") is None:
            lower = text.lower()
            if re.search(r"\b(no|cannot|can't|unable|need help|no car|no transport)\b", lower):
                assessment["can_evacuate"] = False
                if re.search(r"\b(car|transport|ride|vehicle)\b", lower):
                    assessment["transport_needed"] = True
            elif re.search(r"\b(yes|can|able)\b", lower):
                assessment["can_evacuate"] = True
                assessment["transport_needed"] = False
            else:
                say(call_id, "Can you leave on your own if needed? Please answer yes or no, and describe any obstacle.")
                return full(call_id)
            assessment["evacuation_details"] = text
            call["revision"] += 1
            save(call)
            event(call_id, "assessment.updated", assessment)
            say(call_id, "How many people are with you, including yourself?")
            launch_job(call)
        elif not assessment.get("people_count"):
            numbers = re.findall(r"\b\d+\b", text)
            words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
            count = int(numbers[0]) if len(numbers) == 1 else words.get(text.lower().strip(" ."))
            if not count or count > 10000:
                say(call_id, "Please give the total number of people, including yourself.")
                return full(call_id)
            assessment["people_count"] = count
            call["revision"] += 1
            save(call)
            event(call_id, "assessment.updated", assessment)
            say(call_id, "Does anyone need mobility assistance, accessible transport, or other help?")
            launch_job(call)
        else:
            assessment["mobility_needs"] = text
            assessment["assistance_status"] = "requested" if assessment.get("transport_needed") or text.lower() not in {"no", "none", "no."} else "not_requested"
            call["revision"] += 1
            save(call)
            event(call_id, "assessment.updated", assessment)
            say(call_id, "I have recorded that for the demo responders. No transport or rescue has been dispatched or confirmed. Please tell me if your situation changes.")
            launch_job(call)
        return full(call_id)

    @api.post("/api/calls/{call_id}/transcript")
    async def append_transcript(call_id: str, body: Transcript):
        read_call(call_id, writable=True)
        duplicate = next((item for item in events(call_id) if body.segment_id and item["type"] == "transcript" and item["payload"].get("segment_id") == body.segment_id and item["payload"].get("role") == body.role), None)
        if duplicate and body.replace and duplicate["payload"]["text"] != body.text:
            corrected = {**duplicate["payload"], "text": body.text}
            db().execute("UPDATE events SET payload = ? WHERE id = ? AND call_id = ?", (json.dumps(corrected), int(duplicate["id"]), call_id))
            event(call_id, "transcript.corrected", {"segment_id": body.segment_id, "original_event_id": duplicate["id"]})
        if not duplicate:
            event(call_id, "transcript", {**body.model_dump(exclude={"replace"}), "simulation": True})
        return full(call_id)

    @api.post("/api/calls/{call_id}/assessment")
    async def update_assessment(call_id: str, body: Assessment):
        call = read_call(call_id, writable=True)
        changes = body.model_dump(exclude_unset=True)
        if all(key in call["assessment"] and call["assessment"][key] == value for key, value in changes.items()):
            return full(call_id)
        call["assessment"].update(changes)
        call["revision"] += 1
        if "location" in changes:
            call.pop('operator_instruction', None)
            call.pop('zone_conflict_request', None)
            # A corrected location invalidates its old coordinate evidence immediately.
            call["assessment"].pop("location_resolution", None)
            call["assessment"].pop("location_confirmed_at", None)
            call["instruction"] = None
        save(call)
        if "location" in changes and call["scenario_id"] == "dashboard" and changes["location"]:
            await locate_dashboard(call_id, changes["location"])
            call = read_call(call_id)
        else:
            if "location" in changes:
                call["instruction"] = lookup(changes["location"]) if changes["location"] else None
                save(call)
                event(call_id, "instruction.updated", call["instruction"])
            event(call_id, "assessment.updated", call["assessment"])
        launch_job(call)
        return full(call_id)

    @api.post("/api/calls/{call_id}/resolve")
    async def resolve_location(call_id: str, body: Location):
        call = read_call(call_id, writable=True)
        result = await locate_dashboard(call_id, body.location) if call["scenario_id"] == "dashboard" else resolve(call, body.location)
        launch_job(read_call(call_id))
        return {**result, "dashboard_context": team_context(db())} if call["scenario_id"] == "dashboard" else result

    @api.post("/api/calls/{call_id}/steering")
    async def steering(call_id: str, body: TextInput):
        call = read_call(call_id, writable=True)
        if not body.text.strip():
            raise HTTPException(422, 'Message is empty')
        question = {"id": str(uuid4()), "text": body.text.strip()}
        event(call_id, "steering.queued", {**question, "status": "queued", "simulation": True})
        if call["mode"] == "simulation":
            call["pending_operator_question"] = question
            save(call)
            event(call_id, "steering.simulated", {**question, "status": "simulation_applied", "simulation": True})
            suffix = " " + intake_question(call) if call.get("pending_location") else ""
            say(call_id, "Demo responder asks: " + body.text + suffix)
        return full(call_id)

    @api.post('/api/calls/{call_id}/operator-messages')
    async def operator_message(call_id: str, body: OperatorMessage):
        call = read_call(call_id, writable=True)
        if not body.text.strip():
            raise HTTPException(422, 'Message is empty')
        return send_to_operator(call, body.text.strip(), body.request_id)

    @api.get('/api/calls/{call_id}/operator-messages')
    async def operator_messages(call_id: str):
        call = read_call(call_id)
        history = events(call_id)
        through = max((e['payload']['through_event_id'] for e in history if e['type'] == 'operator.read'), default=0)
        return {'thread_id': call_id, 'call_status': call['status'],
                'current_instruction': call.get('instruction'),
                'messages': [{**e, 'read_by_operator': int(e['id']) <= through} for e in history
                             if e['type'] == 'operator.requested'],
                'replies': [e for e in history if e['type'] == 'steering.queued'],
                'notice': 'Replies include history. Use current_instruction for applicable guidance; past replies may be superseded. Receipt or context delivery does not prove the caller heard them.'}

    @api.post('/api/calls/{call_id}/inbox/read')
    async def mark_inbox_read(call_id: str, body: InboxRead):
        read_call(call_id)
        history = events(call_id)
        through = max((int(e['id']) for e in history if e['type'] == 'operator.requested'
                       and int(e['id']) <= body.through_event_id), default=0)
        previous = max((e['payload']['through_event_id'] for e in history if e['type'] == 'operator.read'), default=0)
        if through > previous:
            event(call_id, 'operator.read', {'through_event_id': through})
        return {'through_event_id': max(through, previous)}

    @api.post('/api/calls/{call_id}/operator-instruction')
    async def select_operator_instruction(call_id: str, body: OperatorInstruction):
        call = read_call(call_id, writable=True)
        instruction = instruction_for(db(), call['assessment'].get('location') or '',
                                      call['assessment'].get('location_resolution'))
        if call['revision'] != body.revision or instruction.get('match_status') != 'overlapping_zones':
            raise HTTPException(409, 'Call or instructions changed. Refresh before choosing guidance.')
        chosen = next((z for z in instruction['matching_zones'] if z['id'] == body.zone_id), None)
        if not chosen:
            raise HTTPException(422, 'Choose an instruction that matches this location')
        call['operator_instruction'] = {'zone_id': body.zone_id, 'signature': json.dumps([
            call['assessment']['location'], instruction['matching_zones']], sort_keys=True)}
        call['instruction'] = dashboard_instruction(call)
        call['revision'] += 1
        save(call)
        event(call_id, 'instruction.updated', call['instruction'])
        event(call_id, 'steering.queued', {'id': str(uuid4()), 'status': 'queued',
            'instruction': call['instruction'],
            'text': 'Operator selected the applicable instruction for this call: ' + chosen['text']})
        launch_job(call)
        return full(call_id)

    @api.post("/api/calls/{call_id}/steering/{event_id}/ack")
    async def acknowledge_steering(call_id: str, event_id: str, body: SteeringAcknowledgement):
        read_call(call_id, writable=True)
        call_events = events(call_id)
        queued = next((item for item in call_events if item["type"] == "steering.queued" and (item["id"] == event_id or item["payload"].get("id") == event_id)), None)
        if queued is None:
            raise HTTPException(404, "Steering event not found")
        if not any(item["type"] == "steering.acknowledged" and item["payload"].get("event_id") == queued["id"] for item in call_events):
            event(call_id, "steering.acknowledged", {"event_id": queued["id"], "status": body.status, "simulation": True})
        return full(call_id)

    @api.post("/api/calls/{call_id}/end")
    async def end(call_id: str):
        call = read_call(call_id)
        if call["status"] != "ended":
            call["status"] = "ended"
            call["ended_at"] = now()
            call["revision"] += 1
            save(call)
            event(call_id, "call.ended", {"status": "ended"})
            pending = [task for task in api.state.jobs if task.get_name() == call_id]
            for task in pending:
                task.cancel()

            async def cleanup():
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                try:
                    from app.workers import close_case
                    await close_case(call_id)
                except ImportError:
                    pass
                except Exception:
                    logging.exception("Sandbox cleanup failed for ended call %s", call_id)

            cleanup_task = asyncio.create_task(cleanup(), name="cleanup:" + call_id)
            api.state.jobs.add(cleanup_task)
            cleanup_task.add_done_callback(api.state.jobs.discard)
        return full(call_id)

    @api.post("/api/instructions")
    async def publish_instruction(body: InstructionInput):
        previous = json.loads(db().execute("SELECT data FROM instructions WHERE zone_id = ?", (body.zone_id,)).fetchone()["data"])
        instruction = {**previous, **body.model_dump(), "version": previous["version"] + 1, "effective_at": now(), "expires_at": None, "authorized_by": "demo-operator", "simulation": True}
        db().execute("UPDATE instructions SET data = ? WHERE zone_id = ?", (json.dumps(instruction), body.zone_id))
        db().commit()
        for row in db().execute("SELECT data FROM calls").fetchall():
            call = json.loads(row["data"])
            if call["status"] == "ended" or call["scenario_id"] == "dashboard" or call.get("pending_location") or zone_for(call["assessment"].get("location") or "") != body.zone_id:
                continue
            call["instruction"] = instruction
            call["revision"] += 1
            save(call)
            event(call["id"], "instruction.updated", instruction)
            if call["mode"] == "simulation":
                say(call["id"], "Updated demo responder instruction: " + body.text)
            launch_job(call)
        return instruction

    @api.get("/api/dashboard/snapshot")
    async def dashboard_snapshot():
        return {"calls": [full(row["id"]) for row in db().execute("SELECT id FROM calls ORDER BY rowid DESC")],
                "zones": zones(db()), **team_context(db()), "contact_workflow": contact_overview(db()), "source": "voice-backend", "updated_at": now()}

    @api.post("/api/dashboard/calls/{call_id}/geolocate")
    async def refresh_call_location(call_id: str):
        call = read_call(call_id)
        if call["scenario_id"] != "dashboard" or not call["assessment"].get("location"):
            raise HTTPException(409, "A dashboard call with a confirmed location is required")
        await locate_dashboard(call_id, call["assessment"]["location"], historical=call["status"] == "ended")
        if call["status"] != "ended":
            launch_job(read_call(call_id))
        return full(call_id)

    @api.get("/api/dashboard/context")
    async def dashboard_context():
        return {**team_context(db()), "zones": zones(db()),
                "notice": "Records retain their source and simulation labels. Candidate routes are not approved travel instructions; facility listings do not confirm availability."}

    @api.post("/api/dashboard/zones")
    async def publish_zone(body: DashboardZone):
        previous = next((z for z in zones(db()) if z["id"] == body.id), None)
        zone = {**body.model_dump(), "version": (previous or {}).get("version", 0) + 1, "updated_at": now()}
        db().execute("INSERT OR REPLACE INTO dashboard_zones VALUES (?, ?)", (body.id, json.dumps(zone)))
        db().commit()
        refresh_dashboard_instructions()
        return zone

    @api.delete("/api/dashboard/zones/{zone_id}")
    async def delete_zone(zone_id: str):
        deleted = db().execute("DELETE FROM dashboard_zones WHERE id = ?", (zone_id,))
        db().commit()
        if deleted.rowcount == 0:
            raise HTTPException(404, "Published instruction not found")
        refresh_dashboard_instructions()
        return {"deleted": zone_id}

    def refresh_dashboard_instructions():
        # Refresh all dashboard calls, including those whose old area no longer matches.
        for row in db().execute("SELECT data FROM calls").fetchall():
            call = json.loads(row["data"])
            location = call["assessment"].get("location")
            if call["status"] == "ended" or call["scenario_id"] != "dashboard" or not location:
                continue
            instruction = dashboard_instruction(call)
            if instruction == call.get("instruction"):
                continue
            call["instruction"] = instruction
            call["revision"] += 1
            save(call)
            event(call["id"], "instruction.updated", instruction)
            launch_job(call)

    return api


app = create_app()
