import copy
import socket
import unittest
from unittest.mock import patch

from disaster_crawler import discover
from disaster_crawler.osm import OSMProvider
from disaster_crawler.website import (Page, WebsiteError, WebsiteSession, checked_url,
                                      enrich_leads, extract_contacts, public_addresses)
from test_osm import ELEMENTS, request


def leads():
    elements = copy.deepcopy(ELEMENTS)
    for element in elements:
        element["tags"].pop("phone", None)
        element["tags"].pop("contact:phone", None)
        element["tags"]["website"] = "https://facility.example.org/"
        element["tags"].pop("contact:website", None)
    return discover(request(), OSMProvider(transport=lambda *_: {"elements": elements}))["leads"]


class FakeSession(WebsiteSession):
    def __init__(self, pages):
        self.time = 0
        self.calls = []
        self.pages = pages
        super().__init__(transport=self.transport_fake, clock=lambda: self.time, sleep=self.advance)

    def advance(self, seconds):
        self.time += seconds

    def transport_fake(self, url, deadline):
        self.calls.append(url)
        value = self.pages.get(url, (404, "", {}))
        if isinstance(value, Exception):
            raise value
        status, body, headers = value
        return Page(url, status, headers, body, "2026-11-08T00:00:00+00:00")


class ExtractionTests(unittest.TestCase):
    def test_reception_tel_and_fax_exclusion(self):
        contacts, _ = extract_contacts('<p>Reception: <a href="tel:+16195550101;ext=20">619-555-0101 ext. 20</a></p>'
                                       '<p>Fax: <a href="tel:+16195550102">619-555-0102</a></p>', "US")
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["number"], "+16195550101")
        self.assertEqual(contacts[0]["extension"], "20")
        self.assertEqual(contacts[0]["role"], "reception")

    def test_labeled_visible_text_and_extensions(self):
        contacts, _ = extract_contacts("<p>Main phone: (619) 555-0101 x12</p><p>Reception: +34 912 345 678</p>", "US")
        self.assertEqual(len(contacts), 2)
        self.assertEqual(contacts[0]["extension"], "12")
        self.assertEqual(contacts[1]["number"], "+34912345678")

    def test_scripts_hidden_content_and_unlabeled_digits_are_ignored(self):
        contacts, _ = extract_contacts('<script>Phone: 6195550101</script><style>Phone: 6195550102</style>'
                                       '<div hidden>Phone: 6195550103</div><p>Order 6195550104</p>'
                                       '<input hidden><p>Phone: 6195550105</p>', "US")
        self.assertEqual([p["number"] for p in contacts], ["+16195550105"])

    def test_role_is_not_inferred_from_another_number(self):
        contacts, _ = extract_contacts('<p>Reception: 619-555-0101 Fax: 619-555-0102</p>'
                                       '<p><a href="tel:6195550103">Call us</a></p>', "US")
        self.assertEqual(len(contacts), 2)
        self.assertEqual(contacts[1]["role"], "general")

    def test_reception_phone_and_welcome_desk_labels(self):
        contacts, _ = extract_contacts('<p>Reception phone: 6195550101</p>'
                                       '<p>To contact our Welcome Desk, please call 619.692.2077.</p>', "US")
        self.assertEqual([p["role"] for p in contacts], ["reception", "reception"])

    def test_previous_reception_label_does_not_label_following_phone(self):
        contacts, _ = extract_contacts('<p>Reception: 619-555-0101 Phone: 619-555-0102</p>', "US")
        self.assertEqual([p["role"] for p in contacts], ["reception", "general"])


class FetchPolicyTests(unittest.TestCase):
    def test_private_and_mixed_dns_answers_rejected(self):
        for addresses in (["127.0.0.1"], ["169.254.169.254"], ["10.0.0.1"], ["93.184.216.34", "192.168.0.1"], ["::1"]):
            info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]
            with self.subTest(addresses=addresses), patch("socket.getaddrinfo", return_value=info), self.assertRaises(WebsiteError):
                public_addresses("facility.example.org", 443)

    def test_public_dns_addresses_accepted(self):
        info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch("socket.getaddrinfo", return_value=info):
            self.assertEqual(public_addresses("facility.example.org", 443), ["93.184.216.34"])

    def test_invalid_urls_blocked(self):
        for url in ("file:///etc/passwd", "http://localhost", "https://user:pass@example.org", "https://example.org:22", "https://example.org/\n"):
            with self.subTest(url=url), self.assertRaises(WebsiteError):
                checked_url(url)

    def test_robots_disallow_prevents_page_fetch(self):
        session = FakeSession({"https://facility.example.org/robots.txt": (200, "User-agent: *\nDisallow: /", {})})
        with self.assertRaisesRegex(WebsiteError, "robots_disallowed"):
            session.get_page("https://facility.example.org/", "https://facility.example.org/", 25)
        self.assertEqual(len(session.calls), 1)

    def test_cross_host_redirect_is_not_followed(self):
        session = FakeSession({"https://facility.example.org/": (302, "", {"location": "http://127.0.0.1/admin"})})
        with self.assertRaisesRegex(WebsiteError, "cross_host_redirect"):
            session.get_page("https://facility.example.org/", "https://facility.example.org/", 25)
        self.assertFalse(any("127.0.0.1" in call for call in session.calls))

    def test_www_redirect_checks_new_robots(self):
        session = FakeSession({"https://facility.example.org/": (301, "", {"location": "https://www.facility.example.org/"}),
                               "https://www.facility.example.org/robots.txt": (200, "User-agent: *\nDisallow: /", {})})
        with self.assertRaisesRegex(WebsiteError, "robots_disallowed"):
            session.get_page("https://facility.example.org/", "https://facility.example.org/", 25)
        self.assertNotIn("https://www.facility.example.org/", session.calls)

    def test_crawl_delay_and_cache(self):
        session = FakeSession({"https://facility.example.org/robots.txt": (200, "User-agent: *\nCrawl-delay: 3", {}),
                               "https://facility.example.org/": (200, "hello", {})})
        page = session.get_page("https://facility.example.org/", "https://facility.example.org/", 25)
        again = session.get_page(page.url, page.url, 25)
        self.assertEqual(session.time, 3)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(page.retrieved_at, again.retrieved_at)

    def test_rate_limit_is_not_retried(self):
        session = FakeSession({"https://facility.example.org/robots.txt": (429, "", {})})
        for _ in range(2):
            with self.assertRaisesRegex(WebsiteError, "429"):
                session.get_page("https://facility.example.org/", "https://facility.example.org/", 25)
        self.assertEqual(len(session.calls), 1)


class EnrichmentTests(unittest.TestCase):
    def test_follows_contact_link_and_attaches_source(self):
        records = leads()[:1]
        session = FakeSession({"https://facility.example.org/": (200, '<a href="/contact">Contact us</a>', {}),
                               "https://facility.example.org/contact": (200, '<p>Reception: <a href="tel:6195550101">Call</a></p>', {})})
        summary = enrich_leads(records, "US", session=session)
        self.assertEqual(summary["leads_enriched"], 1)
        self.assertEqual(records[0]["phone"]["number"], "+16195550101")
        self.assertEqual(records[0]["phone"]["role"], "reception")
        self.assertEqual(records[0]["phone"]["source_url"], "https://facility.example.org/contact")
        self.assertEqual(records[0]["evidence"][-1]["retrieved_at"], "2026-11-08T00:00:00+00:00")
        self.assertNotIn("missing_or_unrecognized_phone", records[0]["flags"])
        self.assertIn("website_contact_scope_unverified", records[0]["flags"])
        self.assertFalse(records[0]["handoff"]["dial_allowed"])

    def test_distinct_numbers_remain_review_candidates(self):
        records = leads()[:1]
        session = FakeSession({"https://facility.example.org/": (200, '<p>Phone: 6195550101</p><p>Reception: 6195550102</p>', {})})
        enrich_leads(records, "US", session=session)
        self.assertIsNone(records[0]["phone"])
        self.assertIn("phone_conflict", records[0]["flags"])

    def test_existing_contacts_and_mock_data_never_fetched(self):
        records = leads()[:2]
        records[0]["phone_candidates"] = [{"number": "+16195550101", "extension": None, "raw": "6195550101", "verification": "format_only"}]
        records[1]["is_mock"] = True
        session = FakeSession({})
        summary = enrich_leads(records, "US", session=session)
        self.assertEqual(summary["websites_attempted"], 0)
        self.assertEqual(session.calls, [])

    def test_websites_budget_and_failure_preserve_leads(self):
        records = leads()
        session = FakeSession({"https://facility.example.org/": (403, "", {})})
        summary = enrich_leads(records, "US", max_websites=1, session=session)
        self.assertEqual(len(records), 3)
        self.assertEqual(summary["websites_attempted"], 1)
        self.assertTrue(summary["incomplete"])
        self.assertTrue(any(r["website_enrichment"].get("reason") == "website_budget" for r in records))

    def test_shared_site_is_cached_but_branch_identity_is_not_assumed(self):
        records = leads()
        session = FakeSession({"https://facility.example.org/": (200, '<p>Main phone: 6195550101</p>', {})})
        enrich_leads(records, "US", session=session)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(len(records), 3)
        self.assertTrue(all("shared_phone_across_facilities" in r["flags"] for r in records))

    def test_missing_deep_page_can_fall_back_to_homepage(self):
        records = leads()[:1]
        records[0]["website"] = "https://facility.example.org/old-location"
        session = FakeSession({"https://facility.example.org/": (200, '<p>Main phone: 6195550101</p>', {})})
        summary = enrich_leads(records, "US", session=session)
        self.assertEqual(summary["leads_enriched"], 1)
        self.assertEqual(records[0]["phone"]["source_url"], "https://facility.example.org/")
        self.assertEqual(records[0]["website_enrichment"]["errors"][0]["code"], "website_http_404")


if __name__ == "__main__":
    unittest.main()

class GermanAndTransportRegressionTests(unittest.TestCase):
    def test_german_formats_labels_and_exclusions(self):
        from disaster_crawler.normalize import phone_candidate
        for raw in ['030 / 449 60 62', '030–4496062', '+49 (0)30 4496062', '0049 (0)30 4496062']:
            self.assertEqual(phone_candidate(raw, 'DE')['number'], '+49304496062')
        self.assertIsNone(phone_candidate('112', 'DE'))
        self.assertIsNone(phone_candidate('0304496062', 'US'))
        phones, _ = extract_contacts('<p>Anmeldung: 030 / 449 60 62<br>Telefax: 030 / 449 60 63</p>'
                                     '<p>Zentrale: 030 – 4496064</p><p>Notfalltelefon: 0304496065</p>', 'DE')
        self.assertEqual([(p['number'], p['role']) for p in phones], [('+49304496062', 'reception'), ('+49304496064', 'main')])

    def test_regulator_phone_in_imprint_is_not_facility_phone(self):
        phones, _ = extract_contacts('<p>Kassenärztliche Vereinigung Berlin<br>Masurenallee 6<br>Tel.: 030 / 31003-0</p>'
                                     '<p>Telefon: 030 / 4642003</p>', 'DE')
        self.assertEqual([p['number'] for p in phones], ['+49304642003'])

    def test_german_contact_link(self):
        records = leads()[:1]
        session = FakeSession({'https://facility.example.org/': (200, '<a href="/kontakt">Kontakt</a>', {}),
                               'https://facility.example.org/kontakt': (200, '<p>Empfang: 030 / 4496062</p>', {})})
        enrich_leads(records, 'DE', session=session)
        self.assertEqual(records[0]['phone']['number'], '+49304496062')
        self.assertEqual(records[0]['phone']['source_url'], 'https://facility.example.org/kontakt')

    def test_https_host_and_final_read_closed_socket(self):
        from disaster_crawler.website import fetch_once
        from unittest.mock import MagicMock
        sock = MagicMock()
        response = MagicMock(status=200)
        response.getheaders.return_value = [('Content-Type', 'text/html'), ('Content-Length', '5')]
        response.headers.get_content_charset.return_value = 'utf-8'
        response.isclosed.side_effect = [False, True]
        response.read1.return_value = 'hello'.encode()
        conn = MagicMock(); conn.getresponse.return_value = response
        context = MagicMock(); context.wrap_socket.return_value = sock
        with patch('disaster_crawler.website.public_addresses', return_value=['93.184.216.34']), \
             patch('disaster_crawler.website.socket.create_connection', return_value=sock), \
             patch('disaster_crawler.website.tls_context', return_value=context), \
             patch('disaster_crawler.website.http.client.HTTPConnection', return_value=conn):
            import time
            self.assertEqual(fetch_once('https://facility.example.org/', time.monotonic()+25).body, 'hello')
        self.assertEqual(conn.request.call_args.kwargs['headers']['Host'], 'facility.example.org')
        self.assertEqual(sock.settimeout.call_count, 1)
        context.wrap_socket.assert_called_once_with(sock, server_hostname='facility.example.org')
