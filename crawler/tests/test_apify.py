import unittest
from urllib.error import HTTPError, URLError

from disaster_crawler.engine import plan
from disaster_crawler.models import ProviderError
from disaster_crawler.providers import ApifyProvider
from test_discovery import demo_request


class ApifyTests(unittest.TestCase):
    def test_maps_actor_input_polling_and_dataset(self):
        calls = []

        def transport(method, path, body, timeout):
            calls.append((method, path, body))
            if method == "POST":
                return {"data": {"id": "run1", "status": "RUNNING"}}
            if path.startswith("actor-runs/"):
                return {"data": {"status": "SUCCEEDED", "defaultDatasetId": "data1", "buildId": "build1"}}
            return [{"title": "Example clinic", "phone": "6195550101"}]

        provider = ApifyProvider("test-secret", transport=transport, sleep=lambda _: None)
        request = demo_request()
        result = provider.search(plan(request)[0][0], request)
        self.assertEqual(result.run_id, "run1")
        self.assertEqual(result.build_id, "build1")
        self.assertIn("maxTotalChargeUsd=0.5", calls[0][1])
        self.assertEqual(calls[0][2]["maxReviews"], 0)
        self.assertFalse(calls[0][2]["scrapeContacts"])
        self.assertNotIn("test-secret", repr(calls))

    def test_web_results_are_flattened_and_bounded(self):
        def transport(method, path, body, timeout):
            if method == "POST":
                self.assertEqual(body["maxPagesPerQuery"], 1)
                return {"data": {"id": "r", "status": "SUCCEEDED", "defaultDatasetId": "d"}}
            return [{"organicResults": [{"title": "One", "url": "https://example.org"}, {"title": "Two"}]}]
        provider = ApifyProvider("test", transport=transport)
        request = demo_request(max_results_per_task=1)
        result = provider.search(plan(request)[0][1], request)
        self.assertEqual(len(result.records), 1)
        self.assertTrue(result.limit_reached)
        self.assertEqual(result.records[0]["source"], "web")

    def test_timeout_aborts_known_run(self):
        clock = [0]
        calls = []

        def transport(method, path, body, timeout):
            calls.append(path)
            return {"data": {"id": "run", "status": "RUNNING"}}

        def sleep(seconds):
            clock[0] += seconds

        provider = ApifyProvider("test", transport=transport, clock=lambda: clock[0], sleep=sleep)
        request = demo_request(task_timeout_seconds=10)
        with self.assertRaises(ProviderError) as caught:
            provider.search(plan(request)[0][0], request)
        self.assertEqual(caught.exception.code, "task_timeout")
        self.assertEqual(caught.exception.run_id, "run")
        self.assertEqual(calls[-1], "actor-runs/run/abort")

    def test_ambiguous_start_is_not_retried(self):
        calls = []

        def transport(method, path, body, timeout):
            calls.append(method)
            raise URLError("secret must not leak")

        provider = ApifyProvider("test", transport=transport)
        request = demo_request()
        with self.assertRaises(ProviderError) as caught:
            provider.search(plan(request)[0][0], request)
        self.assertEqual(calls, ["POST"])
        self.assertIn("start_state_unknown", caught.exception.code)
        self.assertNotIn("secret", str(caught.exception))

    def test_rate_limited_get_retries_without_restarting_actor(self):
        calls = []

        def transport(method, path, body, timeout):
            calls.append(method)
            if method == "POST":
                return {"data": {"id": "r", "status": "SUCCEEDED", "defaultDatasetId": "d"}}
            if calls.count("GET") == 1:
                raise HTTPError("url", 429, "slow down", {}, None)
            return []

        provider = ApifyProvider("test", transport=transport, sleep=lambda _: None)
        request = demo_request()
        provider.search(plan(request)[0][0], request)
        self.assertEqual(calls, ["POST", "GET", "GET"])

    def test_failed_actor_is_reported_with_run_id(self):
        provider = ApifyProvider("test", transport=lambda *a: {"data": {"id": "r", "status": "FAILED"}})
        request = demo_request()
        with self.assertRaises(ProviderError) as caught:
            provider.search(plan(request)[0][0], request)
        self.assertEqual(caught.exception.code, "apify_run_failed")
        self.assertEqual(caught.exception.run_id, "r")

    def test_cleanup_failure_is_visible(self):
        count = [0]

        def transport(method, path, body, timeout):
            count[0] += 1
            if count[0] == 1:
                return {"data": {"id": "r", "status": "RUNNING"}}
            raise HTTPError("url", 401, "no", {}, None)

        provider = ApifyProvider("test", transport=transport, sleep=lambda _: None)
        request = demo_request()
        with self.assertRaises(ProviderError) as caught:
            provider.search(plan(request)[0][0], request)
        self.assertTrue(caught.exception.cleanup_failed)

    def test_malformed_poll_response_still_aborts_known_run(self):
        calls = []

        def transport(method, path, body, timeout):
            calls.append(path)
            if len(calls) == 1:
                return {"data": {"id": "r", "status": "RUNNING"}}
            return {"data": "unexpected"}

        provider = ApifyProvider("test", transport=transport, sleep=lambda _: None)
        request = demo_request()
        with self.assertRaises(ProviderError) as caught:
            provider.search(plan(request)[0][0], request)
        self.assertEqual(caught.exception.code, "invalid_provider_response")
        self.assertEqual(calls[-1], "actor-runs/r/abort")


if __name__ == "__main__":
    unittest.main()
