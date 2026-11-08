"""Per-call background computation. No API key means an explicit local demo.

The backend must schedule run_case_job outside the voice request and persist its
result before close_case. Configured Daytona failures propagate without fallback.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import ssl
from typing import Any
from uuid import NAMESPACE_URL, uuid5

_PROTOCOLS = Path(__file__).resolve().parents[1] / "protocols"
_REMOTE = "/home/daytona/disaster-case"
_client: Any = None
_sandboxes: dict[str, Any] = {}
_locks: dict[str, asyncio.Lock] = {}
_incomplete: set[str] = set()


def _key(call_id: str) -> str:
    # A deterministic UUID prevents raw caller-controlled text entering paths or commands.
    if not isinstance(call_id, str) or not call_id or len(call_id) > 512:
        raise ValueError("call_id must be a nonempty string of at most 512 characters")
    return uuid5(NAMESPACE_URL, "disaster-call:" + call_id).hex


def _timeout() -> float:
    value = float(os.getenv("DAYTONA_JOB_TIMEOUT_SECONDS", "90"))
    if not 1 <= value <= 300:
        raise ValueError("DAYTONA_JOB_TIMEOUT_SECONDS must be between 1 and 300")
    return value


async def _get_client():
    global _client
    if _client is None:
        _ensure_tls_roots()
        try:
            from daytona import AsyncDaytona
        except ImportError as exc:
            raise RuntimeError("DAYTONA_API_KEY is set; install daytona==0.231.0") from exc
        _client = AsyncDaytona()
    return _client


def _ensure_tls_roots() -> None:
    """Fill an empty Python CA store without disabling TLS verification.

    Some macOS Python installations have no installed CA bundle. Daytona's
    aiohttp transport uses Python's defaults, unlike httpx's certifi default.
    Preserve an explicitly configured trust store and otherwise use the trusted
    certifi bundle already required by httpx when Python has no loaded CA roots.
    """
    if os.getenv("SSL_CERT_FILE") or os.getenv("SSL_CERT_DIR"):
        return
    if ssl.create_default_context().cert_store_stats().get("x509_ca", 0):
        return
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()


async def _prepare(key: str):
    if key in _sandboxes:
        if key in _incomplete:
            raise RuntimeError("Previous Daytona setup failed; close this case sandbox before retrying")
        return _sandboxes[key]
    from daytona import CreateSandboxFromSnapshotParams
    client = await _get_client()
    sandbox = await client.create(CreateSandboxFromSnapshotParams(
        name=f"disaster-{key}", language="python", public=False,
        snapshot=os.getenv("DAYTONA_SNAPSHOT") or None,
        labels={"app": "disaster-voice-demo", "case_key": key},
        auto_stop_interval=0, auto_delete_interval=0, ttl_minutes=120,
    ), timeout=45)
    # Record immediately, so partial setup is still visible to cleanup.
    _sandboxes[key] = sandbox
    _incomplete.add(key)
    try:
        await sandbox.fs.create_folder(_REMOTE, "700", request_timeout=15)
        for path in sorted(_PROTOCOLS.iterdir()):
            if path.is_file() and path.suffix in {".py", ".json"}:
                await sandbox.fs.upload_file(path.read_bytes(), f"{_REMOTE}/{path.name}", timeout=15)
    except BaseException:
        # Keep the mapping if deletion fails so explicit cleanup can retry it.
        try:
            await sandbox.delete(timeout=15)
        except Exception:
            pass
        else:
            _sandboxes.pop(key, None)
            _incomplete.discard(key)
        raise
    _incomplete.discard(key)
    return sandbox


async def prepare_case(call_id: str) -> dict:
    """Optional background prewarming; never await from a live audio turn."""
    key = _key(call_id)
    if not os.getenv("DAYTONA_API_KEY"):
        return {"provider": "local-demo", "sandbox_id": None}
    async with _locks.setdefault(key, asyncio.Lock()):
        sandbox = await asyncio.wait_for(_prepare(key), timeout=_timeout())
        return {"provider": "daytona", "sandbox_id": sandbox.id}


def _local(payload: dict) -> dict:
    spec = importlib.util.spec_from_file_location("disaster_demo_assessment", _PROTOCOLS / "assess.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.assess(payload, _PROTOCOLS)


async def _remote_job(key: str, payload: dict) -> dict:
    sandbox = await _prepare(key)
    await sandbox.fs.upload_file(json.dumps(payload).encode(), f"{_REMOTE}/input.json", timeout=15)
    # Actual content search in the sandbox gives an inspectable protocol lookup.
    mobility = str(payload["assessment"].get("mobility_needs") or "")
    term = "wheelchair" if "wheelchair" in mobility.lower() else "transport"
    matches = await sandbox.fs.find_files(_REMOTE, term, request_timeout=15)
    execution = await sandbox.process.exec(
        f"python3 {_REMOTE}/assess.py {_REMOTE}/input.json", timeout=20)
    if execution.exit_code != 0:
        raise RuntimeError(f"Daytona assessment process failed with exit code {execution.exit_code}")
    result = json.loads(execution.result)
    result.update(provider="daytona", sandbox_id=sandbox.id,
                  protocol_search={"term": term, "match_count": len(matches)})
    return result


async def run_case_job(call_id: str, assessment: dict, instruction: dict | None, *, resources: dict | None = None) -> dict:
    """Compute a transport proposal; never places calls, dispatches, or invents routes."""
    key = _key(call_id)
    # Snapshot caller dictionaries so an in-flight edit cannot change a job's input.
    payload = json.loads(json.dumps({"assessment": assessment, "instruction": instruction}))
    if resources is not None:
        payload["resources"] = json.loads(json.dumps(resources))
    async with _locks.setdefault(key, asyncio.Lock()):
        if not os.getenv("DAYTONA_API_KEY"):
            result = await asyncio.to_thread(_local, payload)
            result.update(provider="local-demo", sandbox_id=None)
        else:
            result = await asyncio.wait_for(_remote_job(key, payload), timeout=_timeout())
    result["call_id"] = call_id
    return result


async def close_case(call_id: str) -> None:
    """Delete the case sandbox after the backend has persisted required results."""
    key = _key(call_id)
    async with _locks.setdefault(key, asyncio.Lock()):
        sandbox = _sandboxes.get(key)
        if sandbox is not None:
            await asyncio.wait_for(sandbox.delete(timeout=20, wait=True), timeout=25)
            _sandboxes.pop(key, None)
            _incomplete.discard(key)


async def close_all() -> None:
    """Best effort lifespan cleanup; raise a summary if any sandbox remains."""
    global _client
    failed = []
    for key, sandbox in list(_sandboxes.items()):
        try:
            async with _locks.setdefault(key, asyncio.Lock()):
                await asyncio.wait_for(sandbox.delete(timeout=20, wait=True), timeout=25)
                _sandboxes.pop(key, None)
                _incomplete.discard(key)
        except Exception:
            failed.append(sandbox.id)
    if _client is not None:
        await asyncio.wait_for(_client.close(), timeout=10)
        _client = None
    if failed:
        raise RuntimeError("Daytona cleanup failed for sandbox IDs: " + ", ".join(failed))
