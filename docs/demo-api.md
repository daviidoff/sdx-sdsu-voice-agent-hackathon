# Browser-call demo and dashboard handoff

Implemented direction: local browser calls first; real phone service deferred. The central backend owns durable call state. Dashboard fixtures are replaceable data, and the dashboard does not need to own the voice connection. This implementation is a demo, not an operational emergency service.

## Run and discover

Run `./scripts/run-demo.sh` from the repository root. The interface is on `http://localhost:8000`, interactive API docs on `/docs`, and the machine-readable contract on `/openapi.json`. The main page contains the live voice phone screen; `/?debug=1` opens the separate responder debug console. The deterministic conversation endpoint remains available for automated backend checks but is not exposed as a phone mode. SQLite is local to the server; other components use the API, not the database file. The separate `crawler/` package is not coupled to this mock API.

## HTTP contract

| Method and path | Input / purpose |
| --- | --- |
| `GET /api/config` | Provider configuration booleans and public agent ID; never API keys. |
| `GET /api/scenarios` | Synthetic scenarios and their fixture locations. |
| `POST /api/calls` | `{mode: "simulation" or "elevenlabs", scenario_id}` creates a call. |
| `GET /api/calls` | Existing call summaries. |
| `GET /api/calls/{id}` | Current call, assessment, instruction and complete event history. |
| `GET /api/calls/{id}/events` | SSE feed; reconnect with `Last-Event-ID`. |
| `POST /api/calls/{id}/messages` | `{text}` advances the deterministic mock conversation. |
| `POST /api/calls/{id}/transcript` | `{role: "user" or "agent", text, segment_id?, replace?}` stores live SDK transcript events and corrections. |
| `POST /api/calls/{id}/resolve` | `{location}` resolves a caller-confirmed current location. |
| `POST /api/calls/{id}/assessment` | Merge confirmed intake fields. |
| `POST /api/calls/{id}/steering` | `{text}` queues operator context. |
| `POST /api/calls/{id}/steering/{event_id}/ack` | `{status: "context_delivered"}` records delivery to the voice context, not that the caller heard it. |
| `POST /api/calls/{id}/end` | Ends the call and schedules sandbox cleanup. |
| `GET /api/instructions` | All three editable area instruction records. |
| `POST /api/instructions` | `{zone_id, action, text}` publishes the next instruction version and updates affected active calls. |
| `GET /api/voice/session?call_id=...` | Returns a signed ElevenLabs URL, or the configured public agent ID. |

Scenario IDs include `wildfire-north`, `river-park`, `lake-view`, and `unknown-location`. Instruction zones are `north-ridge`, `river-park`, and `lake-view`; actions are `evacuate`, `shelter`, or `unknown`. Fixture matching is not real geocoding. The caller's current location is separate from the selected scenario.

Assessment fields: `location`, `can_evacuate` (boolean or unknown), `people_count`, `wheelchair_users` (confirmed count, including zero when explicitly confirmed), `mobility_needs`, and `transport_needed`. Ask for the wheelchair-user count when wheelchair use is reported; do not infer it from party size. Preserve unknown values. Assistance requested, a capacity-compatible proposal, responder acceptance, and dispatch are separate facts. This demo implements requests and proposals, not dispatch.

## Event contract

Every SSE message has `{id, call_id, type, payload, created_at}`. The `id` is a monotonically increasing database event ID, serialized as a string; use it to deduplicate delivery. SSE uses the default `message` event. Transcript events have `{role, text}` and optional `segment_id`. Event types include:

- `call.started`, `call.ended`
- `transcript`, `transcript.corrected`, `assessment.updated`, `instruction.updated`
- `steering.queued`, `steering.acknowledged`, `steering.simulated`, `operator.followup`
- `job.started`, `job.completed`, `job.failed`, `job.discarded`

The browser forwards steering, instruction changes, and completed worker results through the active ElevenLabs SDK conversation. A context-delivered acknowledgement does not mean the assistant has spoken it. Disconnected voice clients cannot apply steering. A changed location, fact set, or instruction invalidates an older worker result. Job events include the snapshot `revision`; clients compare it with the current call revision before treating a result as current. Discarded jobs also identify `current_revision`.

Simulation asks for yes/no confirmation of `pending_location` before resolving an instruction. A simulated operator question sets `pending_operator_question`; its answer is recorded separately and normal intake resumes. In live mode the model obtains confirmation before invoking the location tool. Transcript corrections update the original segment and emit `transcript.corrected` referencing its event ID; clients refresh their snapshot rather than appending a duplicate utterance. A fully interrupted segment may be replaced with an empty string.

## Background processing

`app/workers.py` exposes `run_case_job(call_id, assessment, instruction)`. Without a Daytona key it runs the deterministic protocol/transport calculation locally and returns `provider: "local-demo"`. With a key it creates or reuses a private per-call sandbox, uploads the protocol files and facts, searches protocol contents, and runs `protocols/assess.py`. The backend records results outside the sandbox. Cleanup deletes the sandbox after the call ends.

Protocols specify intake questions and processing rules. Live instruction records specify the current operator-approved action. Do not copy changing orders into static protocol snapshots. Synthetic vehicle records are in `protocols/resources.demo.json`; matching capacity produces only a proposal and exposes missing information and assumptions.

## Integration boundaries

Replace the fixture lookup and persistence behind the existing endpoints when the team chooses a shared database. Keep the session IDs, event stream, instruction versions, and stale-result checks. Add authenticated operator identity before using a remotely shared service. The current local browser owns the live SDK session; closing that browser loses live steering even though stored events remain.

Actual phone calling, human voice takeover, real geographic boundary resolution, operational authorizations, and external dispatch are not implemented. This handoff does not assert provider runtime validation without a credentialed call.


## Connected dashboard API

- `GET /api/dashboard/snapshot`: full persisted calls and events, dashboard zones, team facilities,
  incidents, and routes. The dashboard polls once per second; corrected utterances replace their
  original IDs and ended calls remain ended, not resolved. A failed poll displays a stale-data warning.
- `GET /api/dashboard/context`: current team records and published zones for the voice session.
- `POST /api/dashboard/zones`: `{id, label, area, level, polygon?, instruction}` publishes a new version.
  `level` is `evacuate`, `warning`, `shelter`, or `unknown`. `polygon` uses `[latitude, longitude]` points.
  Matching uses the confirmed `area` string only; conflicting area records yield unknown guidance.
- `POST /api/calls` with `{mode:"elevenlabs", scenario_id:"dashboard"}` selects shared dashboard
  instructions and capacity records rather than the separate demonstration fixtures. Resolve returns
  the instruction plus current team context. Simulation mode is rejected for this scenario.

Run the dashboard at `/dashboard/`; Vite development uses port 5174 and proxies `/api` to port 8000.
The phone stays at `/`. Team records retain their source/simulation labels. No Supabase credentials
are needed for this path. The old scripted feed and automatic mock crew dispatch are not active.
