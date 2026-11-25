# Connected operator dashboard

Run `./scripts/run-demo.sh` from the repository root and open
[the dashboard](http://127.0.0.1:8000/dashboard/). Open [the voice caller](http://127.0.0.1:8000/) to start
an ElevenLabs browser session against the same backend. For frontend development, `npm ci && npm run dev` serves
`http://127.0.0.1:5174/dashboard/` and proxies `/api` to port 8000; open the phone separately on port 8000.

Calls, transcripts, confirmed facts, and background results come from the durable voice API. The feed
refreshes every second and shows connection errors without silently switching to a fake feed.
Operator messages are queued by the backend and delivered by the active phone window. Published
area instructions are versioned and persisted. See `../docs/demo-api.md` for the contract.

Facilities combine the team's shared `data/` records with persisted crawler discoveries. Incidents and candidate routes still come from the shared records. Existing
records are labeled demonstrations. Unknown caller coordinates remain absent from the map.
There is no connected crew dispatch service. `src/data/fake.ts` remains historical demo source and is
not imported by the live dashboard.

Validation: `npm run build`, `npm run lint`, and the root Python dashboard integration tests.

Crawler reports are published directly by the worker using `--publish-url http://127.0.0.1:8000`. Click a map marker or Contacts entry to inspect
phone candidates, address, exact source pages, timestamps, and review flags. **Fit contacts** fits the newest imported area. Discovery records remain unverified and do not trigger calls.
The backend uses the existing SQLite database, not Supabase. See `../crawler/README.md` for commands.

Draw a zone with **Zone**, then click or tap the map to add polygon corners.
Use **Undo** to remove the last corner. After at least three corners, choose **Finish** or click
the first point to close the polygon. **Cancel** or Escape discards the drawing. Finishing opens an instruction editor. Complete the name and guidance; valid edits save automatically after a brief pause and apply to matching callers. **Areas** lists saved instructions and in-progress edits. Save failures stay visible with a retry action. Closing the panel does not cancel a pending save.

## San Diego contact workflow

Open **Contacts → Search**, select published instruction areas from the list or map (or use
**Select all areas**), choose live OSM/web research or offline San Diego fixtures, then click
**Contact · search**. Selection highlights appear only in Contacts; instruction boundaries
remain the shared source of truth. Areas without published map boundaries cannot be searched.
Search jobs and each search/website worker persist their status. Results are filtered to the
union of selected polygons, with overlapping results deduplicated. Each search preserves the
instruction IDs, versions and boundaries it used. Errors display provider codes and a retry
action; retries use the currently selected published areas. Berlin remains a saved validation example and is excluded from this incident view.

Under **Contacts → Contacts**, inspect a facility's sources and select its phone candidate.
**Approve mock call** queues an operator-approved simulation. **Act as receiver** opens an incoming
mock call with microphone or typed reception role-play using the dedicated ElevenLabs outreach
agent. **Run scripted mock** exercises the workflow offline with clearly labeled scripted dialogue;
bulk approval runs at most three scripted conversations concurrently. Nothing dials a real number.

**Reports** shows who reported what, the source conversation, timestamps, quotes and assistance
needs. Reception self-confirmation and operator verification are distinct. Needs remain for review;
there are no dispatch commitments or extra people/need markers on the map. Correcting a report
preserves its history and invalidates its old verification. The structured downstream feed is
`GET /api/contacts/needs`, also included as `reported_needs` in the shared dashboard/voice context (all current reports are explicitly `mock: true`).

Run `.venv/bin/python scripts/configure_outreach.py` once with the existing ElevenLabs API key.
This provisions a separate reception agent, preserving the inbound agent. Its IDs are saved in
`.runtime/outreach-agent.json`; alternatively set `ELEVENLABS_OUTREACH_AGENT_ID`. Never put keys in
frontend variables. Start/restart the backend to load new routes, then rebuild the frontend.

Validation: `tests/test_contacts.py`, `frontend/tests/contacts.test.mjs`, and
`.venv/bin/python scripts/smoke_contacts.py --base-url http://127.0.0.1:8002`. The last command uses
real ElevenLabs speech output and a typed, explicitly mock receptionist; it does not validate
physical microphone capture. Run an offline contact search before this smoke check.

### Wildfire simulation on OpenStreetMap

Choose **Add fire**, draw the ignition area, then choose **Finish** and **Start simulation**.
SQLite stores the ignition area. The dashboard derives the spreading footprint
from simulated wind, fuel and ground distance in metres. The drawn polygon seeds the simulation grid directly. Two charcoal tones mark its burned interior. The red margin and coral teeth
mark its advancing side and fade as the simulation cools. After burnout, playback repeats from the drawn ignition. A refresh resumes the current cycle in the same tab.
Click the current footprint to edit or replay the fire. Operator instruction zones supply caller guidance.

Streets uses OSM Shortbread vector tiles. MapLibre renders the incident GeoJSON between
land cover and the reference layers for water, buildings, streets and labels. Aerial adds
USGS imagery to the same style. Leaflet handles navigation, drawing, markers and instruction
zones. The map uses raster tiles and the same fire geometry when the vector renderer is
unavailable. Set `VITE_OSM_STYLE_URL` to use another compatible style and tile service.
The browser requests visible tiles directly and displays attribution for the map sources.
[OSM tile policy](https://operations.osmfoundation.org/policies/vector/) · [MapLibre layer ordering](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/#addlayer)

### Crew simulation

Open **Crews → Simulate AI crews** to spawn four clearly labeled demo vehicles spread roughly 5–6 km apart around the current map center. Drag a crew marker to reposition it; dropping cancels its current simulated route and restarts its patrol at the new location. Available crews follow slow, synthetic patrol loops. Select a crew and choose a mapped contact under **Route destination**, then **Set simulated route**. For a call that ended with an outstanding assistance report, choose its last confirmed location and select **Dispatch simulated crew**. The scripted dispatcher accepts, the route appears, and the marker moves to the destination. Cancel a route or resume patrol after arrival; **Stop simulation** removes the session's crews and routes. Simulation resets on page reload.

Destination routes use the existing OSRM lookup, with an explicitly labeled straight-line simulation if unavailable. Patrol paths are illustrative, and routes do not account for disaster conditions. Radio exchanges are scripted; simulation does not contact crews, steer live calls, or confirm real assistance.

## Workspace controls

Drag a panel by its header or resize from the lower-right corner. The focused header and resize
handle also support arrow keys. Close panels with **×** and reopen them from the workspace toolbar;
**Map only** clears the map and **Reset layout** restores the default arrangement. On smaller screens,
the active panel becomes a bottom sheet. Contacts, Calls and Areas switch the overview; selecting a
record opens its details. **Inbox** sits at the right end of the toolbar with an unread count and opens as a movable panel.

UI regression check: `.venv/bin/python scripts/smoke_workspace_ui.py` from the repository root.
It checks panel interactions, mobile sizes, serialized autosave, close-during-save and failed-save retry
using intercepted browser fixtures, without changing the live backend.
