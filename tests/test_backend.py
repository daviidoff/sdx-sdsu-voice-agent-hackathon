import asyncio
import json
import threading
import time

from fastapi.testclient import TestClient
import pytest

from app.backend import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    with TestClient(create_app(tmp_path / "test.sqlite3")) as value:
        yield value


def start(client, **kwargs):
    response = client.post("/api/calls", json=kwargs)
    assert response.status_code == 200
    return response.json()


def test_location_required_before_guidance(client):
    call = start(client)
    assert call["instruction"] is None
    assert call["assessment"] == {}
    assert "evacuate" not in call["events"][-1]["payload"]["text"].lower()
    response = client.post(f"/api/calls/{call['id']}/messages", json={"text": "I am in North Ridge"})
    assert response.status_code == 200
    call = response.json()
    assert call["instruction"] is None
    assert call["pending_location"] == "I am in North Ridge"
    call = client.post(f"/api/calls/{call['id']}/messages", json={"text": "yes"}).json()
    assert call["instruction"]["action"] == "evacuate"
    assert call["assessment"]["location"] == "I am in North Ridge"
    assert call["instruction"]["simulation"] is True


@pytest.mark.parametrize("location", ["123 Unknown Road", "North Ridge or River Park", "North Ridgeline", "not in North Ridge", "maybe North Ridge", "leaving North Ridge", "Lake View or River Park", "not in Lake View", "near Lake View", "Lake View and North Ridge"])
def test_unknown_or_ambiguous_location_never_guesses(client, location):
    call = start(client)
    result = client.post(f"/api/calls/{call['id']}/resolve", json={"location": location}).json()
    assert result["action"] == "unknown"
    assert result["version"] is None


def test_instruction_editor_lists_three_distinct_editable_fixtures(client):
    response = client.get("/api/instructions")
    assert response.status_code == 200
    instructions = response.json()["instructions"]
    assert [(item["zone_id"], item["name"]) for item in instructions] == [("north-ridge", "North Ridge"), ("river-park", "River Park"), ("lake-view", "Lake View")]
    assert len({item["text"] for item in instructions}) == 3
    for item in instructions:
        assert item["id"] == item["zone_id"]
        assert item["source"] == "synthetic-responder-fixture"
        assert item["version"] == 1
        assert item["simulation"] is True
        assert item["authorized_by"] == "demo-operator"


@pytest.mark.parametrize("scenario_id", ["wildfire-north", "river-park", "lake-view", "unknown-location"])
def test_live_call_never_assumes_scenario_location(client, scenario_id):
    call = start(client, mode="elevenlabs", scenario_id=scenario_id)
    assert call["assessment"] == {}
    assert call["instruction"] is None
    assert not any(item["type"] == "instruction.updated" for item in call["events"])


def test_lake_view_instruction_edit_publishes_only_to_matching_live_call(client):
    lake = start(client, mode="elevenlabs", scenario_id="unknown-location")
    river = start(client, mode="elevenlabs", scenario_id="unknown-location")
    lake_path, river_path = f"/api/calls/{lake['id']}", f"/api/calls/{river['id']}"
    resolved = client.post(lake_path + "/resolve", json={"location": "I'm currently in Lake View"}).json()
    assert resolved["zone_id"] == "lake-view"
    assert resolved["action"] == "evacuate"
    client.post(river_path + "/resolve", json={"location": "River Park"})
    edited = client.post("/api/instructions", json={"zone_id": "lake-view", "action": "shelter", "text": "DEMO: Updated Lake View shelter instruction"}).json()
    assert edited["version"] == 2
    assert edited["name"] == "Lake View"
    updated = client.get(lake_path).json()
    assert updated["instruction"] == edited
    assert updated["events"][-1]["type"] == "instruction.updated"
    assert updated["events"][-1]["payload"] == edited
    assert client.get(river_path).json()["instruction"]["version"] == 1
    listed = client.get("/api/instructions").json()["instructions"]
    assert next(item for item in listed if item["zone_id"] == "lake-view") == edited


def test_location_correction_requires_confirmation(client):
    call = start(client)
    base = f"/api/calls/{call['id']}"
    client.post(base + "/messages", json={"text": "North Ridge"})
    client.post(base + "/messages", json={"text": "yes"})
    corrected = client.post(base + "/messages", json={"text": "Actually I'm in River Park"}).json()
    assert corrected["instruction"] is None
    assert corrected["pending_location"] == "Actually I'm in River Park"
    client.post("/api/instructions", json={"zone_id": "north-ridge", "action": "evacuate", "text": "DEMO: old zone update"})
    assert client.get(base).json()["instruction"] is None
    confirmed = client.post(base + "/messages", json={"text": "yes"}).json()
    assert confirmed["instruction"]["action"] == "shelter"


def test_order_versions_only_update_affected_active_calls(client):
    north, river = start(client), start(client)
    client.post(f"/api/calls/{north['id']}/resolve", json={"location": "North Ridge"})
    client.post(f"/api/calls/{river['id']}/resolve", json={"location": "River Park"})
    response = client.post("/api/instructions", json={"zone_id": "north-ridge", "action": "shelter", "text": "DEMO: Changed order"})
    assert response.json()["version"] == 2
    north = client.get(f"/api/calls/{north['id']}").json()
    river = client.get(f"/api/calls/{river['id']}").json()
    assert north["instruction"]["action"] == "shelter"
    assert north["instruction"]["version"] == 2
    assert river["instruction"]["version"] == 1


def test_ended_call_is_immutable(client):
    call = start(client)
    base = f"/api/calls/{call['id']}"
    ended = client.post(base + "/end").json()
    for suffix, payload in [
        ("/messages", {"text": "North Ridge"}),
        ("/transcript", {"role": "user", "text": "new"}),
        ("/assessment", {"people_count": 3}),
        ("/resolve", {"location": "North Ridge"}),
        ("/steering", {"text": "new"}),
    ]:
        assert client.post(base + suffix, json=payload).status_code == 409
    assert client.post(base + "/end").json() == ended
    assert client.get(base).json() == ended


def test_transcript_deduplicates_and_sse_replays(client):
    call = start(client, mode="elevenlabs")
    base = f"/api/calls/{call['id']}"
    payload = {"role": "user", "text": "Hello", "segment_id": "segment-1"}
    client.post(base + "/transcript", json=payload)
    updated = client.post(base + "/transcript", json=payload).json()
    transcripts = [event for event in updated["events"] if event["type"] == "transcript"]
    assert len(transcripts) == 1
    client.post(base + "/end")
    response = client.get(base + "/events", headers={"Last-Event-ID": transcripts[0]["id"]})
    data = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [event["type"] for event in data] == ["call.ended"]


def test_transcript_correction_updates_original_and_notifies_without_duplicate(client):
    call = start(client, mode="elevenlabs")
    base = f"/api/calls/{call['id']}"
    original = {"role": "agent", "text": "The uncorrected transcript", "segment_id": "segment-1"}
    initial = client.post(base + "/transcript", json=original).json()
    original_event = initial["events"][-1]
    correction = {**original, "text": "The corrected transcript", "replace": True}
    corrected = client.post(base + "/transcript", json=correction).json()
    transcripts = [item for item in corrected["events"] if item["type"] == "transcript"]
    assert len(transcripts) == 1
    assert transcripts[0]["id"] == original_event["id"]
    assert transcripts[0]["payload"]["text"] == "The corrected transcript"
    notification = corrected["events"][-1]
    assert notification["type"] == "transcript.corrected"
    assert notification["payload"] == {"segment_id": "segment-1", "original_event_id": original_event["id"]}
    assert client.post(base + "/transcript", json=correction).json() == corrected


def test_transcript_correction_arriving_first_creates_transcript(client):
    call = start(client, mode="elevenlabs")
    corrected = client.post(f"/api/calls/{call['id']}/transcript", json={"role": "user", "text": "Final transcript", "segment_id": "segment-first", "replace": True}).json()
    assert corrected["events"][-1]["type"] == "transcript"
    assert corrected["events"][-1]["payload"]["text"] == "Final transcript"
    assert not any(item["type"] == "transcript.corrected" for item in corrected["events"])


def test_empty_transcript_only_allowed_for_correction(client):
    call = start(client, mode="elevenlabs")
    path = f"/api/calls/{call['id']}/transcript"
    payload = {"role": "agent", "text": "", "segment_id": "interrupted"}
    assert client.post(path, json=payload).status_code == 422
    client.post(path, json={**payload, "text": "Words that were interrupted"})
    result = client.post(path, json={**payload, "replace": True})
    assert result.status_code == 200
    transcripts = [item for item in result.json()["events"] if item["type"] == "transcript"]
    assert len(transcripts) == 1
    assert transcripts[0]["payload"]["text"] == ""
    assert result.json()["events"][-1]["type"] == "transcript.corrected"


def test_steering_acknowledgement_is_idempotent_and_does_not_claim_heard(client):
    call = start(client, mode="elevenlabs")
    base = f"/api/calls/{call['id']}"
    steered = client.post(base + "/steering", json={"text": "Ask about stairs"}).json()
    queued = steered["events"][-1]
    assert queued["type"] == "steering.queued"
    for _ in range(2):
        response = client.post(base + f"/steering/{queued['id']}/ack", json={"status": "context_delivered"})
        assert response.status_code == 200
    acknowledgements = [item for item in response.json()["events"] if item["type"] == "steering.acknowledged"]
    assert len(acknowledgements) == 1
    assert acknowledgements[0]["payload"]["status"] == "context_delivered"


def test_simulation_steering_records_answer_and_resumes_intake(client):
    call = start(client)
    base = f"/api/calls/{call['id']}"
    client.post(base + "/messages", json={"text": "North Ridge"})
    client.post(base + "/messages", json={"text": "yes"})
    steered = client.post(base + "/steering", json={"text": "What color is your front door?"}).json()
    assert steered["pending_operator_question"]["text"] == "What color is your front door?"
    assert any(item["type"] == "steering.simulated" and item["payload"]["status"] == "simulation_applied" for item in steered["events"])
    assert steered["events"][-1]["payload"]["text"] == "Demo responder asks: What color is your front door?"
    answered = client.post(base + "/messages", json={"text": "Blue"}).json()
    assert "pending_operator_question" not in answered
    assert "mobility_needs" not in answered["assessment"]
    assert "can_evacuate" not in answered["assessment"]
    assert answered["events"][-2]["type"] == "operator.followup"
    assert answered["events"][-2]["payload"]["answer"] == "Blue"
    assert "able to leave" in answered["events"][-1]["payload"]["text"]


def test_location_correction_takes_priority_over_operator_question(client):
    call = start(client)
    base = f"/api/calls/{call['id']}"
    client.post(base + "/messages", json={"text": "North Ridge"})
    client.post(base + "/messages", json={"text": "yes"})
    client.post(base + "/steering", json={"text": "What color is your door?"})
    corrected = client.post(base + "/messages", json={"text": "Actually I'm in River Park"}).json()
    assert corrected["pending_location"] == "Actually I'm in River Park"
    assert corrected["pending_operator_question"]["text"] == "What color is your door?"
    assert corrected["instruction"] is None
    client.post("/api/instructions", json={"zone_id": "north-ridge", "action": "evacuate", "text": "DEMO: updated north order"})
    assert client.get(base).json()["instruction"] is None
    confirmed = client.post(base + "/messages", json={"text": "yes"}).json()
    assert confirmed["instruction"]["action"] == "shelter"
    assert "pending_operator_question" in confirmed
    assert "Demo responder asks: What color is your door?" in confirmed["events"][-1]["payload"]["text"]


def test_expired_instruction_is_unknown(client):
    row = client.app.state.db.execute("SELECT data FROM instructions WHERE zone_id='north-ridge'").fetchone()
    order = json.loads(row["data"])
    order["expires_at"] = "2000-01-01T00:00:00+00:00"
    client.app.state.db.execute("UPDATE instructions SET data=? WHERE zone_id='north-ridge'", (json.dumps(order),))
    client.app.state.db.commit()
    call = start(client)
    result = client.post(f"/api/calls/{call['id']}/resolve", json={"location": "North Ridge"}).json()
    assert result["action"] == "unknown"


def test_confirmed_wheelchair_count_is_saved_and_validated(client):
    call = start(client)
    path = f"/api/calls/{call['id']}/assessment"
    assert client.post(path, json={"wheelchair_users": -1}).status_code == 422
    assert client.post(path, json={"wheelchair_users": 10001}).status_code == 422
    saved = client.post(path, json={"people_count": 3, "wheelchair_users": 1}).json()
    assert saved["assessment"]["wheelchair_users"] == 1
    saved = client.post(path, json={"wheelchair_users": 0}).json()
    assert saved["assessment"]["wheelchair_users"] == 0


def test_repeated_identical_assessment_does_not_invalidate_pending_job(client, monkeypatch):
    import app.workers
    release = threading.Event()

    async def worker(call_id, assessment, instruction):
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "proposal_only"}

    monkeypatch.setattr(app.workers, "run_case_job", worker)
    call = start(client)
    base = f"/api/calls/{call['id']}"
    initial = client.post(base + "/assessment", json={"transport_needed": True}).json()
    repeated = client.post(base + "/assessment", json={"transport_needed": True}).json()
    assert repeated["revision"] == initial["revision"]
    release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        events = client.get(base).json()["events"]
        if any(item["type"] == "job.completed" for item in events):
            break
        time.sleep(0.01)
    assert sum(item["type"] == "job.started" for item in events) == 1
    assert sum(item["type"] == "job.completed" for item in events) == 1
    assert not any(item["type"] == "job.discarded" for item in events)


def test_background_result_does_not_overwrite_new_instruction(client, monkeypatch):
    import app.workers
    release = threading.Event()

    async def worker(call_id, assessment, instruction):
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"instruction_version": instruction.get("version")}

    monkeypatch.setattr(app.workers, "run_case_job", worker)
    call = start(client)
    base = f"/api/calls/{call['id']}"
    client.post(base + "/resolve", json={"location": "North Ridge"})
    client.post(base + "/assessment", json={"can_evacuate": False})
    client.post("/api/instructions", json={"zone_id": "north-ridge", "action": "shelter", "text": "DEMO: updated"})
    release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        events = client.get(base).json()["events"]
        if any(event["type"] == "job.discarded" for event in events) and any(event["type"] == "job.completed" for event in events):
            break
        time.sleep(0.01)
    assert any(event["type"] == "job.discarded" for event in events)
    completed = [event for event in events if event["type"] == "job.completed"]
    assert len(completed) == 1
    assert completed[0]["payload"]["result"]["instruction_version"] == 2
    current_revision = client.get(base).json()["revision"]
    assert completed[0]["payload"]["revision"] == current_revision
    discarded = next(event for event in events if event["type"] == "job.discarded")
    assert discarded["payload"]["revision"] < current_revision
    assert discarded["payload"]["current_revision"] == current_revision
    started_revisions = {event["payload"]["revision"] for event in events if event["type"] == "job.started"}
    assert started_revisions == {discarded["payload"]["revision"], current_revision}


def test_sqlite_survives_app_restart(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    with TestClient(create_app(path)) as first:
        call = start(first)
        first.post(f"/api/calls/{call['id']}/resolve", json={"location": "River Park"})
    with TestClient(create_app(path)) as second:
        persisted = second.get(f"/api/calls/{call['id']}").json()
        assert persisted["instruction"]["action"] == "shelter"
        assert persisted["assessment"]["location"] == "River Park"
