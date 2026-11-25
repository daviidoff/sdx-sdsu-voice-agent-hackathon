#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.txt
(cd frontend && npm ci --silent && npm run build)
if [[ "${1:-}" == "--dashboard-drill" ]]; then
  exec .venv/bin/python -m scripts.dashboard_drill
fi
(cd web && npm ci --silent && npm run build)
if [[ "${1:-}" == "--assistance-call" ]]; then
  exec .venv/bin/python -m scripts.assistance_demo
fi
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
