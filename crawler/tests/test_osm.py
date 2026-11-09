import copy
import errno
import socket
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError

from disaster_crawler import DiscoveryRequest, discover
from disaster_crawler.engine import plan
from disaster_crawler.models import ProviderError
from disaster_crawler.osm import OSMProvider


def request(**overrides):
    data = json.loads((Path(__file__).resolve().parents[1] / "examples/osm-request.json").read_text())
    data.update(overrides)
    return DiscoveryRequest.from_dict(data)


ELEMENTS = [
    {"type": "node", "id": 1, "lat": 32.72, "lon": -117.15, "tags": {
        "name": "Test clinic", "amenity": "clinic", "phone": "+1 619 555 0101",
        "contact:phone": "+1 619 555 0199", "contact:website": "https://example.org",
        "addr:housenumber": "1", "addr:street": "Example St", "addr:city": "San Diego"}},
    {"type": "way", "id": 2, "center": {"lat": 32.73, "lon": -117.14}, "tags": {
        "name": "Test care home", "amenity": "social_facility", "social_facility": "nursing_home",
        "social_facility:for": "senior;disabled", "contact:phone": "+1 619 555 0102 ext. 5"}},
    {"type": "relation", "id": 3, "center": {"lat": 32.74, "lon": -117.13}, "tags": {
        "name": "Test shelter", "amenity": "social_facility", "social_facility": "shelter"}},
]


class OSMTests(unittest.TestCase):
    def test_one_request_for_parallel_tasks_and_public_contacts_preserved(self):
        calls = []

        def transport(query, timeout):
            calls.append(query)
            return {"elements": copy.deepcopy(ELEMENTS)}

        result = discover(request(), OSMProvider(transport=transport))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["summary"]["leads_found"], 3)
        leads = {lead["name"]: lead for lead in result["leads"]}
        clinic = leads["Test clinic"]
        self.assertIsNone(clinic["phone"])
        self.assertIn("phone_conflict", clinic["flags"])
        self.assertEqual(len(clinic["phone_candidates"]), 2)
        self.assertEqual(clinic["evidence"][0]["observed"]["phone_tags"]["contact:phone"], "+1 619 555 0199")
        care = leads["Test care home"]
        self.assertEqual(set(care["categories"]), {"care_home", "disability_support"})
        self.assertEqual(care["phone"]["extension"], "5")
        self.assertIn("approximate_coordinates", care["flags"])
        self.assertEqual(care["source_url"], "https://www.openstreetmap.org/way/2")
        self.assertEqual(care["coordinates"]["lng"], -117.14)
        self.assertEqual(result["attributions"][0]["license"], "ODbL-1.0")
        for lead in result["leads"]:
            self.assertFalse(lead["is_mock"])
            self.assertFalse(lead["handoff"]["dial_allowed"])

    def test_bounding_order_and_task_budget(self):
        provider = OSMProvider()
        req = request(max_tasks=1)
        provider.prepare(req, plan(req)[0])
        query = provider.query()
        self.assertIn("[bbox:32.69,-117.18,32.77,-117.1]", query)
        self.assertIn("nursing_home", query)
        self.assertNotIn("hospital", query)
        self.assertIn("out body center 1001", query)

    def test_requires_explicit_single_area_before_network(self):
        for changes in ({"bounds": None}, {"locations": ["A", "B"]}, {"sources": ["maps"]},
                        {"bounds": [-120, 30, -110, 40]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                discover(request(**changes), OSMProvider(transport=lambda *_: self.fail("network used")))

    def test_rate_limit_is_not_retried_by_each_worker(self):
        calls = []

        def transport(*_):
            calls.append(1)
            raise ProviderError("osm_http_429")

        result = discover(request(), OSMProvider(transport=transport))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(all(t["error_code"] == "osm_http_429" for t in result["tasks"]))

    def test_partial_runtime_response_is_not_reported_complete(self):
        provider = OSMProvider(transport=lambda *_: {"elements": ELEMENTS, "remark": "runtime timeout"})
        result = discover(request(), provider)
        self.assertEqual(result["status"], "partial")
        self.assertIn("osm_query_incomplete", result["tasks"][0]["warnings"])
        self.assertGreater(len(result["leads"]), 0)

    def test_empty_runtime_error_is_failure_not_empty_success(self):
        provider = OSMProvider(transport=lambda *_: {"elements": [], "remark": "runtime timeout"})
        self.assertEqual(discover(request(), provider)["status"], "failed")

    def test_normal_empty_results_remain_unknown_coverage(self):
        result = discover(request(), OSMProvider(transport=lambda *_: {"elements": []}))
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["coverage"]["exhaustive"])
        self.assertEqual(result["leads"], [])

    def test_semicolon_phone_values_are_retained(self):
        element = copy.deepcopy(ELEMENTS[0])
        element["tags"].pop("contact:phone")
        element["tags"]["phone"] = "+1 619 555 0101;+1 619 555 0102"
        result = discover(request(), OSMProvider(transport=lambda *_: {"elements": [element]}))
        self.assertEqual(len(result["leads"][0]["phone_candidates"]), 2)
        self.assertIsNone(result["leads"][0]["phone"])

    def test_malformed_response_fails_once(self):
        result = discover(request(), OSMProvider(transport=lambda *_: {"elements": "bad"}))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["tasks"][0]["error_code"], "osm_invalid_response")

    def test_global_element_limit_and_task_result_limit_report_partial(self):
        provider = OSMProvider(transport=lambda *_: {"elements": ELEMENTS})
        provider.ELEMENT_LIMIT = 1
        result = discover(request(), provider)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["tasks"][0]["limit_reached"])

    def test_disused_listing_is_not_a_ready_contact(self):
        element = copy.deepcopy(ELEMENTS[1])
        element["tags"]["disused"] = "yes"
        result = discover(request(), OSMProvider(transport=lambda *_: {"elements": [element]}))
        self.assertIn("listed_closed", result["leads"][0]["flags"])
        self.assertEqual(result["leads"][0]["next_action"], "research_needed")


if __name__ == "__main__":
    unittest.main()


class OSMTransportTests(unittest.TestCase):
    def test_timeout_is_distinct_from_network_error(self):
        for failure, code in [(TimeoutError(), 'osm_timeout'), (URLError(TimeoutError()), 'osm_timeout'), (URLError(ConnectionRefusedError(errno.ECONNREFUSED, 'refused')), 'osm_connection_refused'), (URLError(socket.gaierror(-2, 'no name')), 'osm_dns_error'), (URLError(OSError('network')), 'osm_network_error')]:
            with patch('disaster_crawler.osm.build_opener') as opener:
                opener.return_value.open.side_effect = failure
                with self.assertRaises(ProviderError) as caught:
                    OSMProvider()._http('bounded query', 1)
                self.assertEqual(caught.exception.code, code)

    def test_configured_endpoint_is_https_without_credentials(self):
        with patch.dict('os.environ', {'OVERPASS_API_URL': 'https://example.org/api/interpreter'}):
            self.assertEqual(OSMProvider().endpoint, 'https://example.org/api/interpreter')
        for url in ('http://example.org/api', 'https://secret@example.org/api', 'https://example.org/api?token=secret'):
            with patch.dict('os.environ', {'OVERPASS_API_URL': url}):
                with self.assertRaises(ValueError): OSMProvider()
