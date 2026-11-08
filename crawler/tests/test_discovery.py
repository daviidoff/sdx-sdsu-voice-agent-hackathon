import json
from pathlib import Path
import threading
import time
import unittest

from disaster_crawler import DiscoveryRequest, discover
from disaster_crawler.engine import plan
from disaster_crawler.models import ProviderError, SearchResult
from disaster_crawler.normalize import coordinates, merge_leads, normalize, phone_candidate, safe_url
from disaster_crawler.providers import MockProvider


ROOT = Path(__file__).resolve().parents[1]


def demo_request(**overrides):
    value = json.loads((ROOT / "examples/demo-request.json").read_text())
    value.update(overrides)
    return DiscoveryRequest.from_dict(value)


class DiscoveryTests(unittest.TestCase):
    def test_demo_preserves_uncertainty_and_conflicting_evidence(self):
        result = discover(demo_request(), MockProvider())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["leads_returned"], 11)
        leads = {x["name"]: x for x in result["leads"]}
        care = leads["DEMO Harbor Care Residence"]
        self.assertEqual(care["phone"]["number"], "+16195550101")
        self.assertEqual(len(care["evidence"]), 3)
        clinic = leads["DEMO Bay Health Clinic"]
        self.assertIsNone(clinic["phone"])
        self.assertIn("phone_conflict", clinic["flags"])
        self.assertEqual(len(clinic["phone_candidates"]), 2)
        for lead in result["leads"]:
            self.assertTrue(lead["is_mock"])
            self.assertEqual(lead["safety_status"], "unknown")
            self.assertFalse(lead["handoff"]["dial_allowed"])

    def test_shared_phone_does_not_merge_branches(self):
        result = discover(demo_request(categories=["accessible_transport"]), MockProvider())
        branches = [x for x in result["leads"] if x["phone"]]
        self.assertEqual(len(branches), 2)
        for lead in branches:
            self.assertIn("shared_phone_across_facilities", lead["flags"])

    def test_closed_and_outside_need_research(self):
        result = discover(demo_request(), MockProvider())
        flagged = [x for x in result["leads"] if x["listed_closed"] or x["area_match"] == "outside"]
        self.assertEqual(len(flagged), 2)
        self.assertTrue(all(x["next_action"] == "research_needed" for x in flagged))

    def test_budget_is_visible_and_deterministic(self):
        request = demo_request(max_tasks=2, max_leads=1)
        result = discover(request, MockProvider())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["summary"]["tasks_skipped"], 10)
        self.assertEqual(len(result["leads"]), 1)
        again = discover(request, MockProvider())
        self.assertEqual(result["request_key"], again["request_key"])
        self.assertEqual(result["leads"][0]["lead_id"], again["leads"][0]["lead_id"])
        self.assertNotEqual(result["run_id"], again["run_id"])

    def test_mock_does_not_invent_results_for_other_locations(self):
        result = discover(demo_request(locations=["Different city"]), MockProvider())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["leads"], [])
        self.assertEqual(result["tasks"][0]["error_code"], "mock_location_not_available")

    def test_one_failed_search_does_not_lose_other_results(self):
        class Provider(MockProvider):
            def search(self, task, request):
                if task.source == "web":
                    raise ProviderError("rate_limited")
                return super().search(task, request)
        result = discover(demo_request(categories=["care_home"]), Provider())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["summary"]["tasks_failed"], 1)
        self.assertGreater(len(result["leads"]), 0)

    def test_actual_parallel_execution_is_bounded(self):
        class Provider:
            mode = "mock"
            active = 0
            peak = 0
            lock = threading.Lock()

            def search(self, task, request):
                with self.lock:
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                time.sleep(0.015)
                with self.lock:
                    self.active -= 1
                return SearchResult([])
        provider = Provider()
        discover(demo_request(concurrency=2), provider)
        self.assertEqual(provider.peak, 2)

    def test_invalid_records_and_clipping_are_visible(self):
        class Provider:
            mode = "mock"

            def search(self, task, request):
                return SearchResult([{}, "bad"], limit_reached=True)
        result = discover(demo_request(max_tasks=1), Provider())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["tasks"][0]["invalid_records"], 2)

    def test_bad_input_rejected(self):
        for override in ({"concurrency": 0}, {"max_tasks": True}, {"categories": ["person"]},
                         {"bounds": [0, 0, float("nan"), 1]}, {"locations": ["\n"]},
                         {"sources": []}, {"country_code": "usa"}, {"max_charge_usd_per_task": -1},
                         {"unknown": "ignored?"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                demo_request(**override)

    def test_duplicates_in_request_do_not_launch_twice(self):
        tasks, _ = plan(demo_request(categories=["care_home", "care_home"], sources=["maps", "maps"]))
        self.assertEqual(len(tasks), 1)


class NormalizationTests(unittest.TestCase):
    def test_phone_formats_extensions_and_country(self):
        self.assertEqual(phone_candidate("(619) 555-0101 x20", "US")["extension"], "20")
        self.assertEqual(phone_candidate("+34 912 345 678", "ES")["number"], "+34912345678")
        self.assertIsNone(phone_candidate("912345678", "ES"))
        self.assertIsNone(phone_candidate("911", "US"))
        self.assertIsNone(phone_candidate("phone 619-555-0101 or 619-555-0102", "US"))

    def test_untrusted_urls_and_coordinates(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "https://user:secret@example.com", "https://example.com/\n"):
            self.assertIsNone(safe_url(url))
        for value in ({"lat": True, "lng": 2}, {"lat": 91, "lng": 2}, {"lat": float("inf"), "lng": 2}):
            self.assertIsNone(coordinates(value))

    def test_web_snippets_never_become_phone_contacts(self):
        request = demo_request()
        task = plan(request)[0][1]
        lead = normalize({"title": "Directory", "phone": "6195550101", "url": "https://example.org"},
                         task, request, "now", "live", "run")
        self.assertIsNone(lead["phone"])
        self.assertIn("research_link_only", merge_leads([lead])[0]["flags"])

    def test_location_conflict_retains_both_sources(self):
        request = demo_request()
        task = plan(request)[0][0]
        row = {"title": "Clinic", "placeId": "123", "location": {"lat": 32.7, "lng": -117.1},
               "phone": "6195550101", "url": "https://example.org"}
        first = normalize(row, task, request, "now", "mock", None)
        row["location"]["lat"] = 34
        second = normalize(row, task, request, "now", "mock", None)
        lead = merge_leads([first, second])[0]
        self.assertEqual(len(lead["evidence"]), 2)
        self.assertIn("coordinates_conflict", lead["flags"])
        self.assertEqual(lead["next_action"], "research_needed")

    def test_different_place_ids_at_same_address_stay_separate(self):
        request = demo_request()
        task = plan(request)[0][0]
        row = {"title": "Clinic", "address": "1 Example Road", "placeId": "one"}
        first = normalize(row, task, request, "now", "mock", None)
        row["placeId"] = "two"
        second = normalize(row, task, request, "now", "mock", None)
        self.assertEqual(len(merge_leads([first, second])), 2)


if __name__ == "__main__":
    unittest.main()
