# Emergency OS — Call dashboard

Live call list, OpenStreetMap disaster map, live transcripts, and agent steering. React + Vite + Tailwind + shadcn/ui + Leaflet.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
```

With no Supabase settings it plays a scripted demo with **fake data** (press **Replay** to restart).

## Connect Supabase

Create `frontend/.env.local` (never commit it):

```
VITE_SUPABASE_URL=https://<project>.supabase.co
VITE_SUPABASE_ANON_KEY=<publishable/anon key>
```

Tables the dashboard reads (enable Realtime on `calls` and `transcript_lines`):

| Table | Columns |
|---|---|
| `calls` | `id text pk, caller_name, phone, address, lat float8, lng float8, people int, situation ('can_leave'\|'needs_help'\|'trapped'), mobility, status ('active'\|'instructed'\|'help_assigned'\|'resolved'), started_at timestamptz` |
| `transcript_lines` | `id text pk, call_id text, speaker ('caller'\|'agent'\|'system'), text, created_at timestamptz` |
| `steering` (dashboard writes) | `id bigint generated, call_id text, text, mode ('context'\|'say'), created_at timestamptz default now()` |

The voice agent side should listen for new `steering` rows for its call: `mode = 'context'` → `conversation.sendContextualUpdate(text)`, `mode = 'say'` → `conversation.sendUserMessage(text)`.

## Where things are

- `src/data/fake.ts` — fake calls, transcript script, fire stages, zones, responders, extra facilities. Also loads the team's `../data/facilities`.
- `src/lib/feed.ts` — data source: fake replay or Supabase (same event shapes).
- `src/lib/geo.ts` — which zone a caller is in (code decides the instruction), call priority.
- `src/components/` — `CallList`, `DisasterMap`, `CallDetail`.
