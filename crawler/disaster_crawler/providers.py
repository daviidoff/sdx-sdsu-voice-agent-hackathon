"""Mock fixtures and an opt-in Apify REST adapter. No arbitrary URL fetching."""

import copy
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .models import ProviderError, SearchResult


class MockProvider:
    mode = "mock"

    def __init__(self, fixture_path=None):
        path = fixture_path or Path(__file__).parent / "fixtures" / "facilities.json"
        self.fixture = json.loads(Path(path).read_text())

    def search(self, task, request):
        if task.location != self.fixture["location"]:
            raise ProviderError("mock_location_not_available")
        if task.source not in ("maps", "web"):
            raise ProviderError("mock_source_not_available")
        rows = [r for r in self.fixture["records"]
                if r["source"] == task.source and task.category in r["categories"]]
        limit = request.max_results_per_task
        return SearchResult(copy.deepcopy(rows[:limit]), limit_reached=len(rows) >= limit)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ApifyProvider:
    mode = "live"
    ACTORS = {"maps": "compass~crawler-google-places", "web": "apify~google-search-scraper"}
    TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}

    def __init__(self, token=None, *, transport=None, sleep=time.sleep, clock=time.monotonic):
        self.token = token or os.environ.get("APIFY_TOKEN")
        if not self.token:
            raise ValueError("APIFY_TOKEN is required for --provider apify")
        self.transport = transport or self._http
        self.sleep = sleep
        self.clock = clock

    def _http(self, method, path, body, timeout):
        # Origin is fixed; credentials never appear in query strings or output.
        request = Request("https://api.apify.com/v2/" + path,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"}, method=method)
        with build_opener(NoRedirects()).open(request, timeout=timeout) as response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ProviderError("response_too_large")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError("invalid_provider_json") from exc

    def _request(self, method, path, body=None, *, deadline):
        # Starting an Actor is not retried: a lost POST response can hide a running job.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise ProviderError("task_timeout")
            try:
                return self.transport(method, path, body, min(20, remaining))
            except HTTPError as exc:
                retryable = exc.code in (429, 500, 502, 503, 504)
                code = f"apify_http_{exc.code}"
                exc.close()
            except (URLError, socket.timeout, TimeoutError):
                retryable, code = True, "apify_network_error"
            if not retryable or attempt == attempts - 1:
                raise ProviderError(code)
            self.sleep(min(2 ** attempt, max(0, deadline - self.clock())))

    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
            raise ProviderError("invalid_provider_identifier")
        return value

    def search(self, task, request):
        deadline = self.clock() + request.task_timeout_seconds
        if task.source == "maps":
            payload = {"searchStringsArray": [task.query], "locationQuery": task.location,
                       "maxCrawledPlacesPerSearch": request.max_results_per_task,
                       "language": "en", "maxReviews": 0, "maxImages": 0,
                       "scrapeContacts": False}
        else:
            payload = {"queries": f"{task.query} {task.location} contact",
                       "maxPagesPerQuery": 1, "countryCode": request.country_code.lower()}
        params = urlencode({"timeout": request.task_timeout_seconds,
                            "maxTotalChargeUsd": request.max_charge_usd_per_task})
        run_id = None
        terminal = False
        try:
            run = self._request("POST", f"acts/{self.ACTORS[task.source]}/runs?{params}",
                                payload, deadline=deadline)["data"]
            run_id = self._identifier(run["id"])
            while run.get("status") not in self.TERMINAL:
                self.sleep(min(2, max(0, deadline - self.clock())))
                run = self._request("GET", f"actor-runs/{run_id}", deadline=deadline)["data"]
            terminal = True
            if run["status"] != "SUCCEEDED":
                raise ProviderError("apify_run_" + run["status"].lower(), run_id)
            dataset = self._identifier(run["defaultDatasetId"])
            # A single task is intentionally bounded. Fetch one extra item to detect clipping.
            limit = request.max_results_per_task
            rows = self._request("GET", f"datasets/{dataset}/items?format=json&clean=true&limit={limit + 1}",
                                 deadline=deadline)
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ProviderError("invalid_dataset_shape", run_id)
            if task.source == "web":
                organic = []
                for row in rows:
                    items = row.get("organicResults", [])
                    if not isinstance(items, list) or any(not isinstance(r, dict) for r in items):
                        raise ProviderError("invalid_search_results", run_id)
                    organic.extend({"title": r.get("title"), "url": r.get("url"),
                                    "description": r.get("description"), "source": "web"} for r in items)
                rows = organic
            return SearchResult(rows[:limit], run_id, run.get("buildId"), len(rows) >= limit)
        except Exception as exc:
            error = exc if isinstance(exc, ProviderError) else ProviderError("invalid_provider_response")
            error.run_id = run_id
            if run_id and not terminal:
                try:
                    self._request("POST", f"actor-runs/{run_id}/abort", deadline=self.clock() + 10)
                except Exception:
                    error.cleanup_failed = True
            elif run_id is None:
                # Includes a POST accepted by Apify whose response never arrived.
                error.code += "_start_state_unknown"
            raise error from None
