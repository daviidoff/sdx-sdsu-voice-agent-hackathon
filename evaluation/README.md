# Headless text evaluation

This runs the **configured deployed agent** in text-only mode, sends scripted caller messages, executes its client tools against an isolated instance of the real backend, and records the actual responses. It covers all 55 IDs in [test cases.md](../test%20cases.md), with 10 additional named zone/movement variants (65 runs per suite). The phone, microphone, transcription, and speech synthesis are bypassed.

The model is currently hosted behind ElevenLabs, so the runner uses its [text-only chat interface](https://elevenlabs.io/docs/eleven-agents/guides/chat-mode). This is a hosted model test, not a test of audio quality. No provider agent settings are changed. If an audio event arrives despite the text-only override, the run stops and records a failure to establish the text-only session; audio is never saved.

## Run

From the repository root:

```sh
.venv/bin/python -m pip install -r evaluation/requirements.txt
.venv/bin/python -m playwright install chromium
npm --prefix frontend run build

# List all case IDs and variants without contacting a provider.
.venv/bin/python -m evaluation.run --list

# One movement case, including the actual React dashboard in Chromium.
.venv/bin/python -m evaluation.run --case TC-55:base --dashboard

# All 65 conversations, with responses printed as they arrive.
.venv/bin/python -m evaluation.run --dashboard

# Repeat every movement variant five times.
.venv/bin/python -m evaluation.run --case TC-55 --repeat 5 --dashboard

# Entire coverage report with no provider calls (every case is not_run).
.venv/bin/python -m evaluation.run --catalog-only

# Offline framework/contract validation, no generated agent answers.
.venv/bin/python -m pytest tests/test_evaluation.py -q
```

The existing `.env` supplies `ELEVENLABS_API_KEY` and `ELEVENLABS_AGENT_ID`; environment variables take precedence. The agent must permit the `conversation.text_only` override. The runner checks provider access but never enables permissions or changes the model. Real text conversations consume provider usage. `--case`, `--limit`, and `--turn-timeout` bound a run.

For independent parallel processes, use `--shard-count 4 --shard-index 0` through `3`, each with a different `--output` directory. Never use a shared output directory for simultaneous runs. Merge completed outputs with:

```sh
.venv/bin/python -m evaluation.merge --output .runtime/evaluations/combined \
  .runtime/evaluations/suite-shard-0 .runtime/evaluations/suite-shard-1 \
  .runtime/evaluations/suite-shard-2 .runtime/evaluations/suite-shard-3
```

## Inspect responses

The CLI prints each caller turn and the real agent response. Every completed case updates:

- `report.html`: searchable conversations, failed assertions, tool arguments/results, capability gaps, human-review rubric, final state, and dashboard screenshots.
- `results.json`: machine-readable case/variant/repetition IDs, provider conversation ID, full transcript, tool trace, per-turn stored state, checks, timings, and configuration hashes.
- PNG screenshots: final dashboard state and each step of movement cases.

Outputs default to an ignored `.runtime/evaluations/<UTC timestamp>/` folder. Open `report.html` locally; it is self-contained except linked screenshots. Reports contain only synthetic caller data. API keys, signed URLs, and audio are excluded. A backend tool failure includes its exception class, not an exception message that might contain credentials.

## What the result means

| Status | Meaning |
| --- | --- |
| `failed` | At least one explicit automated assertion failed. Read the turn and actual value. |
| `blocked` | A required capability/configuration is absent, or the run was interrupted. Partial responses remain available. This never counts as a pass. |
| `review` | Executed automated assertions passed, but the semantic rubric still needs review. This is not certified protocol compliance or a full scenario pass. |
| `not_run` | Inventory only; no conversation executed. |

Exit status: `1` for observed assertion failures; `2` for blocked cases/setup if no assertion failed; `0` for an inventory or completed checks awaiting review. A zero exit status is deliberately **not** a safety approval.

The framework does not fill expected facts into model context or silently fall back to the scripted demo conversation. The caller messages in `cases.py` are disclosed in order; expected fields and response patterns are only read by the evaluator. These are fixed, volunteered-fact scripts, not a full adaptive caller simulator. Timing of questions and ambiguity still need review. Regex checks are explicit, limited assertions, not a comprehensive semantic judge.

Current cases retain the requested separate read-back confirmation policy. The deployed prompt may accept clear first-person location statements as confirmation; failures expose that policy disagreement. The runner does not rewrite the model prompt or loosen expectations to hide it.

## Isolation and fidelity

Each case owns a temporary SQLite database, synthetic facility coordinates, and four independently defined zone polygons. Online geocoding and Daytona are disabled in the runner process; it cannot touch the normal `data/` files or dispatch real assistance. A synthetic boundary shared by A/B must produce ambiguous guidance. Local workers execute the real calculation without cloud jobs.

The tool bridge follows the browser's three client tool endpoints and compact assessment response. A frozen copy of the actual `web/src/voice-context.ts` filter runs through Node for instruction/assessment/job contextual updates and stale-event checks. Operator changes are explicitly injected. The runner records hashes of source files and the deployed configuration so drift can be investigated. Start/end configuration changes produce a visible report warning: those runs are exploratory, not a stable regression baseline. The timing is a headless approximation of browser callbacks, not a measurement of audio interruption.

With `--dashboard`, a frozen copy of the **built production React dashboard** runs in Chromium. Its normal polling requests are bridged to the isolated FastAPI TestClient; React, selection, rendering, and Leaflet run unchanged. The runner selects the Calls tab explicitly, waits for current location/instruction text and marker count to converge, checks browser errors, exercises reload, and saves screenshots. External basemap tiles are blocked. This checks the actual dashboard rendering path; it does not claim live network/SSE recovery, independent geocoding accuracy, or pixel-perfect marker positioning. The dashboard currently polls rather than consuming SSE.

Some Markdown requirements need product capabilities that do not exist yet: medical escalation acceptance, missing-person/supply/resource-offer records, multiple-incident scoping, and complete order expiry/revocation semantics. The conversations still run and their responses are available, with those gaps reported. Additional fault variants (e.g. after-commit lost acknowledgements, real reconnects, provider cancellations, withdrawn transcript reconciliation) remain explicitly incomplete rather than inferred from one successful request.

## Extend

Add data in `cases.py`: `say` turns, independent `expect` assertions, injected actions, semantic `review`, and known `gaps`. Use `variant` for separately scored variations. Assertions support exact facts, unknown preservation, zone/version, required/forbidden response patterns, stored reason patterns, event presence, and cross-call isolation. Add evaluator tests when adding a new assertion or fault type. Keep `test cases.md` as the product specification; do not change it merely to make the agent pass.
