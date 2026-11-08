"""Background-worker behavior without credentials or external network calls."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import workers


@pytest.fixture(autouse=True)
def isolated_worker(monkeypatch):
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.delenv("DAYTONA_SNAPSHOT", raising=False)
    monkeypatch.delenv("DAYTONA_JOB_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(workers, "_client", None)
    monkeypatch.setattr(workers, "_sandboxes", {})
    monkeypatch.setattr(workers, "_locks", {})
    monkeypatch.setattr(workers, "_incomplete", set())


def test_empty_python_trust_store_gets_verified_certifi_bundle(monkeypatch):
    import certifi

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(workers.ssl, "create_default_context", lambda: SimpleNamespace(
        cert_store_stats=lambda: {"x509_ca": 0}))
    workers._ensure_tls_roots()
    assert workers.os.environ["SSL_CERT_FILE"] == certifi.where()


def test_explicit_tls_trust_store_is_preserved(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/explicit/company-ca.pem")
    workers._ensure_tls_roots()
    assert workers.os.environ["SSL_CERT_FILE"] == "/explicit/company-ca.pem"


def job(facts, instruction=None):
    return asyncio.run(workers.run_case_job("test-call", facts, instruction))


def test_missing_group_size_never_becomes_one_person_proposal():
    result = job({"location": "Demo zone A", "transport_needed": True})
    assert result["provider"] == "local-demo"
    assert result["sandbox_id"] is None
    assert result["status"] == "needs_more_information"
    assert "people_count" in result["missing_fields"]
    assert result["proposed_candidate"] is None
    assert result["dispatch_status"] == "not_dispatched"


@pytest.mark.parametrize("mobility", ["WHEELCHAIR", "Two people use wheelchairs."])
def test_accessible_group_proposal_meets_both_capacity_constraints(mobility):
    result = job({"location": "Demo zone A", "people_count": 6,
                  "can_evacuate": False, "mobility_needs": mobility,
                  "wheelchair_users": 2}, {"id": "order-a", "version": 3})
    candidate = result["proposed_candidate"]
    assert candidate["passenger_capacity"] >= 6
    assert candidate["wheelchair_capacity"] >= 2
    assert len(candidate["vehicle_ids"]) == 2
    assert candidate["status"] == "proposal_only"
    assert candidate["requires_confirmation"] is True
    assert candidate["resource_source"] == "synthetic-demo-fixture"
    assert result["instruction_reference"] == {"id": "order-a", "version": 3}
    assert {p["id"] for p in result["protocols"]} == {"intake", "mobility", "transport"}
    assert all(p["version"] and p["source"] for p in result["protocols"])


def test_unknown_wheelchair_count_is_explicitly_assumed_and_requires_confirmation():
    result = job({"location": "Demo zone A", "people_count": 3,
                  "transport_needed": True, "mobility_needs": "wheelchair"})
    assert result["status"] == "needs_more_information"
    assert "wheelchair_users" in result["missing_fields"]
    assert any("unconfirmed" in assumption for assumption in result["assumptions"])
    assert result["proposed_candidate"]["wheelchair_capacity"] >= 1
    assert result["dispatch_status"] == "not_dispatched"


def test_insufficient_capacity_preserves_unmet_need():
    result = job({"location": "Demo zone A", "people_count": 99, "transport_needed": True})
    assert result["status"] == "unmet_needs"
    assert result["proposed_candidate"] is None
    assert any("cannot satisfy" in need for need in result["unmet_needs"])


def test_independent_caller_does_not_generate_transport_or_route():
    result = job({"location": "Demo zone A", "people_count": 2, "can_evacuate": True})
    assert result["status"] == "assessment_complete"
    assert result["proposed_candidate"] is None
    assert "route" not in result
    assert "evacuation_instruction" not in result
    assert result["dispatch_status"] == "not_dispatched"


@pytest.mark.parametrize("answer", ["none", "No", "No mobility needs.", "  NONE  "])
def test_explicit_no_mobility_needs_does_not_create_unmet_mobility_need(answer):
    result = job({"location": "Demo zone A", "people_count": 2,
                  "can_evacuate": True, "mobility_needs": answer})
    assert result["status"] == "assessment_complete"
    assert result["unmet_needs"] == []
    assert {p["id"] for p in result["protocols"]} == {"intake"}


@pytest.mark.parametrize("answer", ["no wheelchair", "No wheelchair; needs a walker",
                                    "wheelchair not needed", "doesn't need a wheelchair",
                                    "No wheelchairs", "Wheelchairs are not needed"])
def test_negated_wheelchair_does_not_invent_wheelchair_user(answer):
    result = job({"location": "Demo zone A", "people_count": 2,
                  "transport_needed": True, "mobility_needs": answer})
    assert "wheelchair_users" not in result["missing_fields"]
    assert result["assumptions"] == []
    assert result["proposed_candidate"]["vehicle_ids"] == ["demo-van-a"]


def test_configured_provider_failure_never_silently_falls_back(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "fake-unit-test-key")
    remote = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    monkeypatch.setattr(workers, "_remote_job", remote)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        job({"people_count": 2})
    assert remote.await_count == 1


def test_daytona_adapter_reuses_one_sandbox_and_deletes_after_work(monkeypatch):
    import daytona

    monkeypatch.setenv("DAYTONA_API_KEY", "fake-unit-test-key")
    fs = SimpleNamespace(create_folder=AsyncMock(), upload_file=AsyncMock(),
                         find_files=AsyncMock(return_value=[object()]))
    process = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(
        exit_code=0, result=json.dumps({"status": "proposal_ready"}))))
    sandbox = SimpleNamespace(id="mock-sandbox", fs=fs, process=process, delete=AsyncMock())
    client = SimpleNamespace(create=AsyncMock(return_value=sandbox), close=AsyncMock())
    monkeypatch.setattr(daytona, "AsyncDaytona", lambda: client)

    async def scenario():
        for _ in range(2):
            result = await workers.run_case_job("../../call;$(malicious)", {
                "location": "Demo zone A", "people_count": 2, "transport_needed": True}, None)
            assert result["provider"] == "daytona"
            assert result["sandbox_id"] == "mock-sandbox"
        assert client.create.await_count == 1
        params = client.create.call_args.args[0]
        assert params.name.startswith("disaster-")
        assert "malicious" not in params.name and "/" not in params.name
        assert params.auto_stop_interval == 0
        assert process.exec.await_count == 2
        assert fs.find_files.await_count == 2
        assert all("malicious" not in call.args[0] for call in process.exec.call_args_list)
        assert any(call.args[1].endswith("/mobility.json") for call in fs.upload_file.call_args_list)
        sandbox.delete.assert_not_awaited()
        await workers.close_case("../../call;$(malicious)")
        sandbox.delete.assert_awaited_once_with(timeout=20, wait=True)
        assert not workers._sandboxes
        await workers.close_all()
        client.close.assert_awaited_once()

    asyncio.run(scenario())


def test_failed_sandbox_process_is_not_reported_as_success(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "fake-unit-test-key")
    sandbox = SimpleNamespace(
        fs=SimpleNamespace(upload_file=AsyncMock(), find_files=AsyncMock(return_value=[])),
        process=SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(exit_code=1, result="bad output"))))
    monkeypatch.setattr(workers, "_prepare", AsyncMock(return_value=sandbox))
    with pytest.raises(RuntimeError, match="exit code 1"):
        job({"people_count": 2, "transport_needed": True})
