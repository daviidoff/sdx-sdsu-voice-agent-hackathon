"""Run one real Daytona computation and delete its sandbox.

Usage: .venv/bin/python scripts/smoke_daytona.py
Requires DAYTONA_API_KEY in the environment or project .env. Never falls back to
local mode. Prints only a sanitized JSON outcome, never provider errors or keys.
"""
from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import json
import logging
import os
from pathlib import Path
import sys
from uuid import uuid4
import warnings

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import workers  # noqa: E402


async def smoke() -> tuple[dict, int]:
    outcome = {"status": "failed", "provider": "daytona", "sandbox_id": None,
               "protocol_count": 0, "summary": "Daytona smoke did not complete."}
    call_id = "daytona-smoke-" + uuid4().hex
    failure = None
    cleanup_failed = False
    try:
        result = await workers.run_case_job(call_id, {
            "location": "Synthetic test zone A",
            "people_count": 6,
            "can_evacuate": False,
            "transport_needed": True,
            "mobility_needs": "Two people use wheelchairs.",
            "wheelchair_users": 2,
        }, {"id": "synthetic-smoke-order", "version": 1, "zone_id": "synthetic-a"})
        sandbox_id = result.get("sandbox_id")
        # Provider IDs are identifiers, not arbitrary remote content.
        if isinstance(sandbox_id, str) and len(sandbox_id) <= 200 and all(
            char.isalnum() or char in "-_" for char in sandbox_id
        ):
            outcome["sandbox_id"] = sandbox_id
        protocols = result.get("protocols", [])
        outcome["protocol_count"] = len(protocols) if isinstance(protocols, list) else 0
        candidate = result.get("proposed_candidate") or {}
        if not (
            result.get("provider") == "daytona"
            and outcome["sandbox_id"]
            and result.get("status") == "proposal_ready"
            and {item.get("id") for item in protocols} == {"intake", "mobility", "transport"}
            and candidate.get("passenger_capacity", 0) >= 6
            and candidate.get("wheelchair_capacity", 0) >= 2
            and result.get("dispatch_status") == "not_dispatched"
        ):
            raise RuntimeError("Unexpected synthetic assessment result")
    except Exception as exc:
        # Class name gives a useful failure category without exposing provider
        # response bodies, request headers, paths, or credential-bearing URLs.
        failure = type(exc).__name__
    finally:
        try:
            await workers.close_case(call_id)
        except Exception:
            cleanup_failed = True
        try:
            # Retry any case cleanup failure and always close SDK connections.
            await workers.close_all()
            cleanup_failed = False
        except Exception:
            cleanup_failed = True
    if cleanup_failed:
        outcome["summary"] = "Sandbox cleanup could not be verified; inspect Daytona before retrying."
    elif failure:
        outcome["summary"] = f"Daytona smoke failed ({failure}); tracked sandbox cleanup completed."
    else:
        outcome.update(status="passed", summary="Real Daytona protocol lookup and capacity assessment passed; sandbox deleted.")
    return outcome, 0 if outcome["status"] == "passed" else 1


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("DAYTONA_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"status": "failed", "provider": "daytona", "sandbox_id": None,
                          "protocol_count": 0,
                          "summary": "DAYTONA_API_KEY is missing; no cloud request was made."}))
        return 2
    os.environ["DAYTONA_API_KEY"] = api_key
    # Third-party diagnostics can contain request details; the only stdout/stderr
    # this smoke command exposes is the bounded, explicitly selected result below.
    logging.disable(logging.CRITICAL)
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result, code = asyncio.run(smoke())
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
