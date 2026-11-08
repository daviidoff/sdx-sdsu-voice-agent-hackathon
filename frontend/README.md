# Connected operator dashboard

Run `./scripts/run-demo.sh` from the repository root and open
[the dashboard](http://127.0.0.1:8000/dashboard/). Use **Open voice caller** to start an ElevenLabs
browser session against the same backend. For frontend development, `npm ci && npm run dev` serves
`http://127.0.0.1:5174/dashboard/` and proxies `/api` to port 8000; open the phone separately on port 8000.

Calls, transcripts, confirmed facts, and background results come from the durable voice API. The feed
refreshes every second and shows connection errors without silently switching to a fake feed.
Operator messages are queued by the backend and delivered by the active phone window. Published
area instructions are versioned and persisted. See `../docs/demo-api.md` for the contract.

Facilities, incidents, and candidate routes come from the team's shared `data/` records. Existing
records are labeled demonstrations. Unknown caller coordinates remain absent from the map.
There is no connected crew dispatch service. `src/data/fake.ts` remains historical demo source and is
not imported by the live dashboard.

Validation: `npm run build`, `npm run lint`, and the root Python dashboard integration tests.
