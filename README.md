# SDX SDSU Voice Agent Hackathon

Voice agent project for the SDX SDSU hackathon.

## Start here

Read the [disaster response brainstorm and project handoff](docs/disaster-response-brainstorm.md) for the selected direction, wildfire research, general disaster scope, ElevenLabs and Daytona roles, proposed demo, and open implementation questions.

## Local browser-call demo

The voice demo lives alongside the independent `crawler/` work. It provides a browser phone interface, a central mock incident API, live transcripts and structured intake, operator steering, versioned instructions, and asynchronous protocol/transport analysis. There is no telephone carrier or real 911 connection.

Run from this directory (Python 3.11+ and Node.js 22+):

```bash
./scripts/run-demo.sh
```

Open [localhost:8000](http://localhost:8000). The main view is a phone screen for a live browser call to the configured ElevenLabs agent. Press the call button, allow microphone access, and speak naturally. It requires provider configuration; there is no scripted walkthrough in the phone interface. The displayed 911 number is a simulated phone interface, not a connection to emergency services. API documentation is at [localhost:8000/docs](http://localhost:8000/docs).

Open **Debug window** from the phone screen (or [localhost:8000/?debug=1](http://localhost:8000/?debug=1)) to inspect transcripts, collected facts, background results, and event delivery. Send agent steering or edit the three prefilled areas there. North Ridge, River Park, and Lake View have separate instruction records; the agent selects one only after confirming your spoken location. The debug window is a test console for the team's future dashboard, which can use the same HTTP commands and SSE event stream. See [the API handoff](docs/demo-api.md).

### Enable ElevenLabs voice

Copy `.env.example` to `.env` and set `ELEVENLABS_API_KEY` locally. Never put API keys in frontend code or Git. Then create a dedicated, authenticated demo agent:

```bash
.venv/bin/python scripts/configure_elevenlabs.py --dry-run
.venv/bin/python scripts/configure_elevenlabs.py
```

The first command previews the configuration without contacting ElevenLabs. The second creates six client tools and one new private agent; it does not modify existing agents. Add the printed `ELEVENLABS_AGENT_ID` to `.env` and restart the server. Then press the phone call button and allow microphone access. Browser sign-in alone does not supply application API credentials.

If using an existing agent, configure the prompt and six client tools described by the dry-run output. Their names and parameter names must match exactly. Public agents can connect with an agent ID alone; private agents require the server API key to mint a short-lived signed URL. The key never reaches the browser. The circular call control is our UI connected through the official ElevenLabs JavaScript SDK.

No public tunnel is needed for this browser demo: client tools call the local backend from the browser. Live microphone audio goes directly to ElevenLabs. Context updates are non-interrupting and do not prove the caller has heard a changed instruction.

### Enable Daytona

Set `DAYTONA_API_KEY` in `.env` and restart. Each call with background work gets a separate sandbox containing the versioned files in `protocols/`. It searches those files and runs the same compatibility calculation used by the local mock. The voice session does not wait for the job to finish. Ending the call cleans up the sandbox; it also has a finite lifetime as a fallback.

Without a key, the worker explicitly reports `local-demo`. A configured Daytona failure is reported as a failed job and is not disguised as a successful local run. Candidate transport is synthetic and never dispatched. Optional settings: `DAYTONA_SNAPSHOT`, `DAYTONA_TARGET`, `DAYTONA_API_URL`, and `DAYTONA_JOB_TIMEOUT_SECONDS` (default 90).

### Development and verification

```bash
.venv/bin/python -m pytest tests -q
cd web
npm test
npm run build
```

For frontend iteration, run the API and `npm run dev` in `web/`; Vite proxies `/api` to port 8000. The production frontend is served by FastAPI after building. Local records are in the ignored `data/` directory. Environment and build output are also ignored.

This backend is deliberately bound to loopback and has no multi-user authentication. Keep it local. A shared deployment needs authentication and an operator authority model before exposing these mutation endpoints.

Live integration checks (use configured provider credits):

```bash
.venv/bin/python scripts/smoke_daytona.py
.venv/bin/python scripts/smoke_elevenlabs.py
.venv/bin/python scripts/smoke_areas.py --exercise-updates
```

The first runs a real synthetic Daytona case and cleans up its sandbox. The second connects to the real ElevenLabs conversation, uses synthetic typed inputs, routes client tools through the local backend, receives synthesized audio, and checks the background result. The third checks all three location instructions through real model tool calls and generated audio, plus a midcall instruction/steering update; it restores the original instruction text and action afterward. These typed-input checks do not substitute for a microphone test. The ignored `.runtime/` directory contains the sanitized latest test result. The temporary `scripts/credential_setup.py` form is only for local key setup and should be stopped afterward.

The current local demo keys were approved and configured on November 8, 2026, with seven-day expiry. The ElevenLabs key is restricted to agent access with a 10,000-credit cap; the Daytona key permits sandbox creation/deletion and the provider's implicit sandbox access. No keys are committed. Refresh the credentials when they expire before a later demonstration.


## Connected dashboard (November 8 integration)

### Manual clinic outreach demo

After a contact search, select a discovered clinic in **Contacts** or on the map.
Choose **Open clinic caller** to open the same phone screen as the inbound 911 demo in a new tab.
Press **Respond as clinic** and allow microphone access. You play clinic reception;
a separate ElevenLabs outreach agent asks about the current situation first, then patients
or others needing assistance, counts, transport and supply needs. It retrieves the current
published instruction for the listed clinic location before explaining exercise guidance.
Confirm the address during the conversation. Missing or conflicting instructions require
coordinator clarification. Transcripts and attributed needs remain under the selected facility.

This is a browser conversation: no institution is dialed, no phone candidate is required,
and discovery does not start calls automatically. Bulk/scripted call controls are hidden.
The inbound voice caller remains a separate agent. To configure or update the dedicated
outreach agent, run `.venv/bin/python scripts/configure_outreach.py --update-existing`.

Validation: backend and frontend tests plus the production frontend build pass. A real
ElevenLabs test with synthetic typed clinic replies received audio, saved a two-person
transport need, and fetched and explained the published exercise guidance. Browser microphone
capture has not been verified in this pass. For the provider check, use an isolated local
backend with an offline contact search and run `scripts/smoke_contacts.py --base-url <url>`.

### Dashboard integration

The dashboard from GitHub `main` (`a83428b`) is integrated with the voice backend.
`./scripts/run-demo.sh` builds both interfaces. Open `/dashboard/` for the operator dashboard and `/` for the voice caller.
The phone interface always uses dashboard context. The debug inspector links to the dashboard for zone management; the old synthetic-area editor and fixture-mode URL switch have been removed.

The dashboard reads persisted calls, corrected transcripts, confirmed intake, background-job results,
and steering acknowledgements from `/api/dashboard/snapshot` every second. Operator messages use
`POST /api/calls/{id}/steering`; the active phone window receives them over SSE and forwards them to
ElevenLabs. Call end is distinct from assistance resolution. No scripted callers, crews, fire forecasts,
or automatic dispatch acceptance are loaded by the connected dashboard.

Publish instructions using **Publish area instruction**. These are durable, versioned records shared
with the voice agent. Caller-confirmed place names are resolved to evidence-backed map references; published polygons
are matched against those coordinates. Zones without a polygon use the confirmed area name. Ambiguous
locations keep their candidate points and sourced bounds visible. If every candidate and available footprint has the same published instruction, the agent can relay it while retaining location uncertainty. Overlapping zones with identical action and instruction text share that guidance;
conflicting instructions create a durable operator inbox request. Place references are approximate, not device GPS. Publishing a new
version refreshes matching active dashboard calls and invalidates stale background analysis.

Team facilities, incidents, and candidate routes are read live from `data/*.json` (override with
`TEAM_DATA_DIR`). Those committed records currently describe **simulated** incidents/facilities/routes;
integration does not turn them into verified real-world data. Calls with unresolved locations stay in the list without an invented map position. Place lookups use
team coordinate records or cached Photon/OpenStreetMap results. Set `GEOCODING_ENABLED=0` for offline
operation or `PHOTON_URL` for a different Photon service. Dashboard calls never use the synthetic vehicle
fleet: optionally supply `data/resources.json` as an array of capacity records with `id`,
`passenger_capacity`, `wheelchair_capacity`, and `simulated`. An absent file means no known vehicles.
The old fixture scenarios retain their separate demo fleet.

Cross streets such as `Pacific Beach Drive at Everts Street, Pacific Beach, San Diego` are
matched to shared OpenStreetMap road nodes. The demo fetches a bounded street map extract
(`GEOCODING_OSM_MAP_URL` overrides the endpoint), with size/time limits and a ten-minute road cache.
Similar spellings produce a clarification request, never an automatic location correction.
Failed location lookups are retried on recheck; resolved places retain their coordinate cache.
The selected caller shows an explicit map notice while coordinates are pending or unresolved,
and coordinates belonging to a previous location are rejected by the dashboard feed.

Validation: backend integration tests cover snapshots, transcript corrections, persisted instructions,
ambiguous areas, steering acknowledgements, and absence of fictional transport proposals. A real
ElevenLabs typed-input test on an isolated database produced audio, invoked `confirm_location` and
`update_assessment`, displayed the facts in the dashboard, and spoke a dashboard reference and operator
question. This does not verify microphone capture or telephone service.

For a repeatable isolated provider check, run the server with
`DEMO_DB_PATH=.runtime/dashboard-integration.sqlite` on port 8010, publish a clearly labeled test
instruction for **Integration Test Area** containing **ORCHID**, then run
`.venv/bin/python scripts/smoke_dashboard.py`. The sanitized result is `.runtime/smoke-dashboard.json`.
Keep both local interfaces on the same backend. This integration does not introduce remote authentication.


### Airport-call fixes and revalidation

Ended-call durations use the recorded end time, and the dashboard distinguishes transport requests
from unknown mobility needs. The conversation view has independent scrolling and optional backend
activity. **Recheck location & zone** repeats the geographic lookup. On ended calls it adds map metadata
and a separately labeled current instruction without changing the original transcript or instruction.

New ElevenLabs calls use the updated conversational policy: pause intake for caller interruptions,
accept explicit present-location statements, recheck after corrections or challenges to old guidance,
and resume unanswered intake questions only after addressing the caller's concern. Assessment and
instruction updates are forwarded as current backend context. Provider contextual updates are
non-interrupting. Explicit operator replies additionally send an operator-attributed response trigger, so the agent need not wait for caller speech. Operator messages are excluded from caller transcripts and cannot supply new caller facts. Delivery or a response request does not prove the caller heard it.

`npm test --prefix frontend` covers durations, unknown facts, coordinate mapping, stable transcript
corrections, and unchanged polling. `npm test --prefix web` covers stale context and changed facts.
The real-provider `scripts/smoke_voice_flexibility.py` tests interruption, location correction, recheck,
pause, and resume using typed inputs/generated audio; microphone ASR requires a separate spoken test.

### Operator inbox

Click **Inbox** in the dashboard header to see unread agent requests, the caller/agent transcript,
and operator reply history. Replies use the existing live voice context channel, with separate
queued, context-delivered, and response-requested states. Ended calls retain their history and cannot receive replies.
Messages and read state persist in SQLite. The agent's `message_operator` tool returns a saved
receipt; the prompt prohibits claiming an escalation succeeded without that receipt. Saving a
message does not mean an operator read it or accepted an assistance request.

Conflicting zones create one request per unresolved conflict. The operator can select a published
instruction for that call directly in the inbox. The choice is invalidated by a changed location
or conflicting zone version; the agent never chooses an order by severity or recency itself.

After changes, rebuild both clients, restart the backend, refresh the phone page, and start a new
call. `scripts/configure_elevenlabs.py --update-existing` attaches the inbox client tools to the
recorded dedicated agent while preserving existing tools. `scripts/smoke_inbox.py --base-url
http://127.0.0.1:8013` exercises the real provider on an isolated test backend, using typed inputs
and generated audio. It must not be pointed at a real incident database.

## Text-only behavior evaluation

See [the evaluation runner](evaluation/README.md), [research and test cases](test%20cases.md), and [findings and remaining reliability issues](docs/evaluation-findings.md). The runner tests the deployed model and real dashboard with isolated synthetic data, without transcription or audio.

### Hospital clarification voice regression

Location lookup now completes inside `propose_location` so its tool response includes
map candidates. For ambiguous names, ask which hospital/city the caller means; pass
their clarified place directly to `confirm_location` and relay the current operator
area instruction before continuing intake. A clarification does not require another
proposal and yes/no loop. Unknown locations never inherit the previous area's order.

Run `.venv/bin/python -m scripts.smoke_hospital_browser --repeat 3` after building both
clients and applying `scripts/configure_elevenlabs.py --update-existing`. This uses
Chromium and the production voice page, generated speech through its microphone
stream, real ElevenLabs ASR/LLM/TTS, real geocoding, and an isolated copy of the zones
from port 8000. It verifies hospital clarification, spoken instructions, an operator
update, and a correction to the other campus. Reports, dashboard screenshots, and
agent WAV recordings are saved under `.runtime/hospital-browser-*`. Physical
microphone hardware and a human listening test are separate from this check.
