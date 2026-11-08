# Disaster-response crawler

Discover public facility contacts from **OpenStreetMap through Overpass**, with no search-provider account, API key, or third-party Python dependency. Python 3.11+. The worker can publish reports to the dashboard’s existing SQLite backend. Supabase and outbound calling remain separate integrations.

## Run live, without an account

From the repository root:

```sh
cd crawler
python3 -m disaster_crawler --provider osm --request examples/osm-request.json --output out/osm-result.json
```

The example searches a small rectangle in central San Diego. Edit `bounds` (`[west, south, east, north]`) to select another area, and change its single `locations` label. Bounds are required; the label is descriptive and is **not geocoded**. Set `sources` to `["osm"]`, or omit it when using `--provider osm` and the CLI supplies it. Use `country_code` for phone formatting.

Supported categories: `care_home`, `disability_support`, `health_clinic`, `shelter`, `accessible_transport`, and `community_organization`.

Preview the exact Overpass query without making a network request:

```sh
python3 -m disaster_crawler --provider osm --request examples/osm-request.json --plan
```

**Live check, November 8, 2026:** one public Overpass query returned 37 leads and 13 unambiguous formatted phone contacts in the example area. This is one observed result, not a coverage or future availability guarantee. Listings and numbers were not verified by calling.

On this Mac, the Python installation had no configured CA bundle. The live check used the system trust bundle with certificate verification enabled:

```sh
SSL_CERT_FILE=/etc/ssl/cert.pem python3 -m disaster_crawler --provider osm --request examples/osm-request.json --output out/osm-result.json
```

Use that path only where the system bundle exists. Other installations should use their configured trusted CA bundle. `osm_tls_certificate_error` distinguishes this setup issue from API errors.

## Find missing numbers on facility websites

No Apify or other account is needed. Enable the website pass with:

```sh
python3 -m disaster_crawler --provider osm --request examples/osm-request.json --enrich-websites --max-websites 10 --output out/osm-enriched-result.json
```

Or put `"enrich_websites": true` and `"max_websites": 10` in the request JSON (also works through the Daytona launcher). Mock records never trigger website requests. The pass only visits leads with no normalized phone candidates and a listed website; existing contacts and conflicts are preserved.

It reads the listed HTML page, can fall back to that host’s homepage, and follows contact/about/location links on that host (including its `www` variant), up to three pages per facility. It extracts `tel:` links and phone-labeled visible text. Fax and emergency-labeled numbers are excluded. Each candidate records its exact final `source_url`, nearby `excerpt`, `extraction_method`, retrieval timestamp in evidence, and `role`: `reception`, `main`, or `general`. Reception is assigned only when the local label says reception/front desk/welcome desk/switchboard. It is a website label, not a verified call outcome. Multiple different numbers stay flagged for review.

Website-derived contacts carry `website_contact_scope_unverified`: a central organization website can publish a switchboard for several branches. The facility's original OSM source remains intact; new website evidence is appended. An explicitly labeled reception candidate does not establish that the number belongs to the exact branch.

Per-lead `website_enrichment` shows visited pages, errors, or skip reasons. The report-level summary gives sites attempted, leads with new candidates, HTTP requests, and unresolved contacts. A missing number is not an execution failure; inaccessible or budget-skipped websites make the overall run partial.

Fetching is sequential, respects robots.txt, waits at least one second per host (longer for advertised crawl limits), and caches pages and robots policies within the job. Limits: 10 facilities by default (maximum 20), three pages per facility, 80 HTTP requests including redirects/robots, 1 MB per response, four hops per fetch, and a 25-second per-facility network-work deadline. OS DNS resolution can exceed that deadline. HTTP/HTTPS on standard ports only; private/reserved DNS addresses, cross-host redirects beyond `www`, and HTTPS downgrades are blocked. Connections are pinned to validated DNS addresses and TLS hostname verification stays enabled. No credentials, cookies, forms, scripts, or model instructions are executed.

Live validation checked nine facility records using 14 HTTP requests and found one additional public contact on the San Diego LGBT Community Center’s contact page. The other records remained unresolved due to network, HTTP, or redirect failures. This check preceded the homepage fallback refinement; that fallback is covered by synthetic tests. This earlier check preceded the German extraction and transport fixes described below.

This is an HTML crawler. JavaScript-only contacts, PDFs, unlinked contact pages, cross-domain sites, and blocked pages may remain unresolved; it does not bypass access controls. Structured JSON-LD extraction and browser rendering are not implemented.

## Returned data

Each lead includes a name, address when mapped, latitude/longitude, public phone candidates, website, OSM source link, categories, evidence, and review flags. `phone` and `contact:phone` are both retained; multiple or conflicting numbers remain candidates rather than silently selecting one. `phone.verification = format_only` does not establish ownership or reachability.

OSM nodes have point coordinates. Ways and relations use their bounding-box center and are flagged `approximate_coordinates`; these are not entrances or confirmed positions of people. `retrieved_at` records when the response arrived. The source's update time remains unknown.

Missing phone numbers stay missing. Category matches reflect OSM tags, not confirmed services. In particular, an accessible taxi stand is only a possible transport contact, and a community center is not necessarily an active disaster shelter. Source tags are included in evidence for review. Ordinary outdoor `amenity=shelter` structures are intentionally excluded from the social-shelter search.

Results preserve the existing JSON shape and [TypeScript contract](contracts/discovery.ts), adding the `osm` source and attribution metadata. OSM IDs are namespaced as `osm:node/123`, `osm:way/123`, or `osm:relation/123`. Repeated category matches merge by element ID. Separate OSM elements representing the same building may still need manual reconciliation; a shared phone does not merge branches.

Every lead remains `needs_review` and `not_contacted`, with safety and capacity unknown. Draft reception questions are included; the calling backend must independently authorize any outreach. The crawler does not call anyone or determine evacuation instructions.

## Limits and public-service behavior

One discovery job performs **one HTTP request** for all scheduled categories, then processes category results locally. Thread-pool concurrency does not multiply public Overpass requests. Requests are limited to a box at most one degree wide and tall, a 25-second server computation timeout (shorter if the request deadline requires it), 16 MiB server memory, 5 MB response, and 1,000 processed elements. The query requests one extra element to detect clipping.

`max_tasks` controls scheduled categories; `max_results_per_task` caps each category's records, and `max_leads` caps the merged report. Truncation and partial Overpass runtime errors are visible. A valid empty response means only that no matching elements were returned. Unknown population coverage remains explicit.

On a 429, 504, or network failure, the job reports the failure without automatic retries or switching servers. All workers share that failure, avoiding a retry burst. There is no persistent cache or cross-process global limiter yet. For recurring or larger deployments, add a shared cache/queue or operate an Overpass instance/regional OSM extract; do not run an army of workers against the public endpoint. See [Overpass public-service guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).

Display **© OpenStreetMap contributors** with the returned copyright link. OSM data is licensed under ODbL; preserve the attribution and [license information](https://www.openstreetmap.org/copyright) with exported results.

## Offline mock demo and tests

```sh
python3 -m disaster_crawler --request examples/demo-request.json --output out/demo-result.json
python3 -m unittest discover -s tests -v
```

Mock remains the CLI default. Its fixture covers the exact label `San Diego, California, USA` and legacy `maps`/`web` source tasks. The demo yields 11 fictional leads with missing numbers, conflicting numbers, closed listings, shared switchboards, and out-of-area results. The [sample mock report](examples/demo-result.json) supports dashboard development without network access. The OSM provider tests inject synthetic Overpass responses; routine tests never query the public API.

CLI exit codes: 0 for completed/partial with a report, 1 when all tasks failed, 2 for input/configuration errors. Always inspect JSON `status`, `tasks`, and `coverage`, even on exit 0. The CLI writes the output atomically.

## Daytona

The same account-free OSM provider can run inside Daytona. Daytona itself still requires the team's Daytona credentials:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements-daytona.txt
# Supply DAYTONA_API_KEY securely in the environment.
.venv/bin/python scripts/run_daytona.py --provider osm --request examples/osm-request.json
```

The launcher uploads only the Python worker and fixture, runs the job, retrieves `out/daytona-result.json`, and requests sandbox deletion in `finally`. No Apify token is required or passed in OSM mode. The optional SDK is pinned to Daytona 2.0.0a8, v2 only; the package signatures and mocked lifecycle are tested. Actual Daytona account execution remains unverified. Container packaging is also included but has not been runtime-tested.

## Dashboard/backend handoff

Python callers can use `discover(DiscoveryRequest.from_dict(payload), OSMProvider())`; import `OSMProvider` from `disaster_crawler.osm`. Library callers must set `sources: ["osm"]` explicitly. Run discovery in a background job. The root FastAPI app now owns durable ingestion; the worker does not access database files directly. This remains a local unauthenticated demo.

The backend creates `discovery_runs` and `discovery_facilities` in its existing SQLite database. `POST /api/discovery/import` validates and stores the complete report; `GET /api/discovery/runs` lists recent runs and `GET /api/discovery/runs/{run_id}` returns the full evidence. Repeating the same run is idempotent; reusing a run ID with different content returns 409. Facility keys include incident, mode, and lead ID. An older run cannot overwrite a newer projection. Team fixtures and call records are preserved. Imports never authorize calls or assert safety/capacity.

From the repository root, discover and publish automatically:

```sh
PYTHONPATH=crawler .venv/bin/python -m disaster_crawler \
  --provider osm --request crawler/examples/berlin-arkonaplatz-request.json \
  --enrich-websites --max-websites 20 --output crawler/out/berlin-result.json \
  --publish-url http://127.0.0.1:8000
```

To import an existing report without crawling again, use **Import crawler results** in the dashboard, or:

```sh
curl --fail-with-body http://127.0.0.1:8000/api/discovery/import \
  -H 'Content-Type: application/json' \
  --data-binary @crawler/out/berlin-arkonaplatz-fixed-result.json
```

The snapshot includes persisted discovered facilities alongside team contacts. Map markers and the Contacts list open details with normalized numbers, original formatting, evidence, source links, OSM tags, timestamps, and unresolved errors. The map initially fits the latest discovery area; **Show discovered facilities** returns to it. Multiple numbers remain review candidates. Existing reviewed decisions are not implemented yet; add them in a separate operator-owned record rather than overwriting discovery evidence.

German extraction follows Kontakt/Impressum/Über uns/Standort links, recognizes Telefon, Empfang, Rezeption, Anmeldung and Zentrale, excludes fax/emergency/regulator contacts, and normalizes `030`, `0049`, `+49 (0)` and slash/dash separators. General numbers are not labeled reception. TLS verification stays enabled with a system CA-bundle fallback when Python lacks a default store. The pinned HTTPS transport uses the correct Host header and stops reading when the response closes, fixing self-redirects and closed-socket errors.

Berlin validation reprocessed the saved live OSM response (preserving original retrieval times) and fetched websites live: **35 facilities, 19 with phone candidates, 18 with a single unambiguous number**, five additional contacts from 11 website attempts. One facility has conflicting website numbers. One expired certificate and one cross-domain redirect remain unresolved; four other checked sites yielded no extracted phone. This does not establish reachability or current facility capacity. The report is `out/berlin-arkonaplatz-fixed-result.json`. Browser validation confirmed the persisted markers and source-linked phone detail panel.

Use [contracts/discovery.ts](contracts/discovery.ts) for ingestion. Store reports by `run_id` and incident-level suggestions by `(incident_id, mode, lead_id)`. Preserve evidence and prior reviewed decisions. `request_key` is a correlation hash, not an idempotency lock: running the CLI again makes another request. The backend owns authorization, durable jobs, global limits, cancellation, review state, and duplicate-call prevention. The Contacts workspace now supplies durable local searches, polygon selection, approval, browser mock calls, and attributed assistance reports; see `../frontend/README.md`. Real outbound telephone calling remains unimplemented.

The earlier Apify adapter remains optional for compatibility, but it is not needed for this workflow. Only explicitly choosing `--provider apify` uses it or requires `APIFY_TOKEN`. The legacy `max_charge_usd_per_task` request field is ignored by OSM. The optional website-enrichment pass handles published contact pages after OSM discovery. General internet searching and official-directory lookup remain separate future providers.

See [the updated crawler plan](../docs/crawler-plan.md) for implementation decisions and remaining integration work.
