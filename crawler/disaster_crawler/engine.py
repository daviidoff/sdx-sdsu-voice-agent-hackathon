from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import json
import uuid

from .models import CATEGORIES, ProviderError, SearchTask
from .normalize import merge_leads, normalize, stable_id


def now():
    return datetime.now(timezone.utc).isoformat()


def plan(request):
    tasks = []
    for location in dict.fromkeys(request.locations):
        for category in dict.fromkeys(request.categories):
            for source in dict.fromkeys(request.sources):
                key = json.dumps([request.incident_id, location, category, source])
                tasks.append(SearchTask(stable_id(key), location, category, source, CATEGORIES[category]))
    return tasks[:request.max_tasks], tasks[request.max_tasks:]


def discover(request, provider, on_progress=None):
    started = now()
    tasks, skipped = plan(request)
    if hasattr(provider, "prepare"):
        provider.prepare(request, tasks)

    def execute(task):
        report = {**asdict(task), "started_at": now(), "status": "running"}
        leads = []
        if on_progress:
            on_progress({"kind": "search", "id": task.task_id, "label": task.category, "status": "running"})
        try:
            result = provider.search(task, request)
            invalid = 0
            for row in result.records[:request.max_results_per_task]:
                lead = normalize(row, task, request, result.retrieved_at or now(), provider.mode, result.run_id) if isinstance(row, dict) else None
                if lead:
                    leads.append(lead)
                else:
                    invalid += 1
            report.update(status="succeeded", provider_run_id=result.run_id,
                          provider_build_id=result.build_id, records_received=len(result.records),
                          invalid_records=invalid, limit_reached=result.limit_reached, warnings=result.warnings)
        except ProviderError as exc:
            report.update(status="failed", error_code=exc.code, provider_run_id=exc.run_id,
                          cleanup_failed=exc.cleanup_failed)
        except Exception:
            # External payloads/errors may contain credentials or personal data.
            report.update(status="failed", error_code="unexpected_provider_error")
        report["finished_at"] = now()
        if on_progress:
            on_progress({"kind": "search", "id": task.task_id, "label": task.category, "status": report["status"], "records": len(leads), "error_code": report.get("error_code")})
        return report, leads

    with ThreadPoolExecutor(max_workers=request.concurrency) as pool:
        results = list(pool.map(execute, tasks))
    reports = [r for r, _ in results]
    all_leads = merge_leads([lead for _, leads in results for lead in leads])
    leads = all_leads[:request.max_leads]
    enrichment = None
    if request.enrich_websites:
        from .website import enrich_leads
        enrichment = enrich_leads(leads, request.country_code, max_websites=request.max_websites, on_progress=on_progress)
    failures = sum(r["status"] == "failed" for r in reports)
    clipped = len(all_leads) > len(leads)
    partial = bool(failures or skipped or clipped or any(r.get("limit_reached") or r.get("invalid_records") or r.get("warnings") for r in reports))
    partial = partial or bool(enrichment and enrichment["incomplete"])
    return {
        "schema_version": "1.0", "run_id": str(uuid.uuid4()),
        "request_key": stable_id(json.dumps(request.to_dict(), sort_keys=True)),
        "incident_id": request.incident_id, "mode": provider.mode,
        "attributions": [provider.attribution] if hasattr(provider, "attribution") else [],
        "status": "failed" if failures == len(tasks) else "partial" if partial else "completed",
        "started_at": started, "finished_at": now(), "request": request.to_dict(),
        "summary": {"tasks_planned": len(tasks) + len(skipped), "tasks_executed": len(tasks),
                    "tasks_failed": failures, "tasks_skipped": len(skipped),
                    "leads_found": len(all_leads), "leads_returned": len(leads),
                    "leads_omitted": len(all_leads) - len(leads),
                    "leads_with_phone": sum(bool(lead["phone"]) for lead in leads)},
        "coverage": {"population_coverage": "unknown", "exhaustive": False,
                     "note": "Completion means the bounded searches finished, not that every facility or person was found."},
        "tasks": reports,
        "skipped_tasks": [{**asdict(t), "reason": "max_tasks"} for t in skipped],
        "leads": leads,
        "website_enrichment": enrichment,
    }
