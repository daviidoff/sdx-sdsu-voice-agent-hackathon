"""Small, account-free contact-page crawler. Website text is data, never code."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .normalize import merge_leads, phone_candidate, stable_id
from .tls import tls_context


AGENT = "DisasterResponseDiscovery"
REDIRECTS = {301, 302, 303, 307, 308}


class WebsiteError(Exception):
    pass


def checked_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url) or "\\" in url:
        raise WebsiteError("invalid_website_url")
    try:
        p = urlsplit(url)
        if (p.scheme not in ("http", "https") or not p.hostname or p.username or p.password
                or p.port not in (None, 80 if p.scheme == "http" else 443)):
            raise WebsiteError("unsupported_website_url")
        host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        # IPv6 literals are deliberately unsupported, even when globally routable.
        if not re.fullmatch(r"[a-z0-9.-]+", host) or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise WebsiteError("blocked_website_host")
        return urlunsplit((p.scheme, host, p.path or "/", p.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise WebsiteError("invalid_website_url") from exc


def public_addresses(host, port):
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except OSError as exc:
        raise WebsiteError("website_dns_error") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise WebsiteError("blocked_website_address")
    return addresses


@dataclass
class Page:
    url: str
    status: int
    headers: dict
    body: str
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def fetch_once(url, deadline):
    """Pin the socket to validated DNS, retaining hostname verification for TLS."""
    url = checked_url(url)
    parts = urlsplit(url)
    port = 443 if parts.scheme == "https" else 80
    addresses = public_addresses(parts.hostname, port)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WebsiteError("website_time_limit")
    conn = http.client.HTTPConnection(parts.hostname, port, timeout=min(8, remaining))
    sock = None
    try:
        # Never resolve the hostname a second time after checking the addresses.
        for index, address in enumerate(addresses[:4]):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WebsiteError("website_time_limit")
            try:
                sock = socket.create_connection((address, port), timeout=min(4, remaining))
                break
            except OSError:
                if index == len(addresses[:4]) - 1:
                    raise
        if parts.scheme == "https":
            sock = tls_context().wrap_socket(sock, server_hostname=parts.hostname)
        conn.sock = sock
        target = urlunsplit(("", "", parts.path, parts.query, ""))
        conn.request("GET", target, headers={"Host": parts.hostname, "User-Agent": AGENT + "/0.1", "Accept": "text/html,text/plain;q=0.9",
                                             "Accept-Encoding": "identity", "Connection": "close"})
        response = conn.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        if response.status != 200:
            return Page(url, response.status, headers, "")
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise WebsiteError("unsupported_content_encoding")
        max_bytes = 1_000_000
        if int(headers.get("content-length", "0")) > max_bytes:
            raise WebsiteError("website_page_too_large")
        content_type = headers.get("content-type", "").lower()
        if not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
            raise WebsiteError("unsupported_content_type")
        chunks, size = [], 0
        # read1 may close its socket after the final Content-Length byte.
        while not response.isclosed():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WebsiteError("website_time_limit")
            sock.settimeout(min(8, remaining))
            chunk = response.read1(min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                raise WebsiteError("website_page_too_large")
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            body = b"".join(chunks).decode(charset, errors="replace")
        except LookupError:
            body = b"".join(chunks).decode("utf-8", errors="replace")
        return Page(url, response.status, headers, body)
    except ssl.SSLCertVerificationError:
        raise WebsiteError("website_tls_certificate_error") from None
    except (socket.timeout, TimeoutError):
        raise WebsiteError("website_timeout") from None
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        raise WebsiteError("website_network_error") from None
    finally:
        conn.close()
        if sock:
            sock.close()


class WebsiteSession:
    """Sequential, cached fetching with robots checks and per-host spacing."""
    def __init__(self, *, transport=fetch_once, clock=time.monotonic, sleep=time.sleep, max_requests=80):
        self.transport, self.clock, self.sleep = transport, clock, sleep
        self.max_requests = max_requests
        self.requests = 0
        self.cache, self.robots, self.last_request, self.host_errors = {}, {}, {}, {}

    def _raw(self, url, deadline, delay=1):
        url = checked_url(url)
        if url in self.cache:
            return self.cache[url]
        host = urlsplit(url).hostname
        if host in self.host_errors:
            raise WebsiteError(self.host_errors[host])
        if self.requests >= self.max_requests:
            raise WebsiteError("website_request_budget")
        wait = max(0, self.last_request.get(host, -1e9) + delay - self.clock())
        if self.clock() + wait >= deadline:
            raise WebsiteError("website_time_limit")
        if wait:
            self.sleep(wait)
        self.requests += 1
        self.last_request[host] = self.clock()
        try:
            page = self.transport(url, deadline)
        except WebsiteError as exc:
            self.host_errors[host] = str(exc)
            raise
        if page.status in (429, 503):
            self.host_errors[host] = f"website_http_{page.status}"
            raise WebsiteError(self.host_errors[host])
        self.cache[url] = page
        return page

    @staticmethod
    def allowed_host(url, initial):
        initial_host = urlsplit(initial).hostname
        base = initial_host[4:] if initial_host.startswith("www.") else initial_host
        return urlsplit(url).hostname in {base, "www." + base}

    def _redirect_target(self, page, initial):
        destination = checked_url(urljoin(page.url, page.headers.get("location", "")))
        if not self.allowed_host(destination, initial):
            raise WebsiteError("cross_host_redirect_needs_review")
        if urlsplit(page.url).scheme == "https" and urlsplit(destination).scheme != "https":
            raise WebsiteError("insecure_redirect")
        return destination

    def _policy(self, url, initial, deadline):
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots:
            robot_url = origin + "/robots.txt"
            for _ in range(4):
                response = self._raw(robot_url, deadline)
                if response.status not in REDIRECTS:
                    break
                robot_url = self._redirect_target(response, initial)
            else:
                raise WebsiteError("robots_redirect_limit")
            if response.status not in (200, 404, 410):
                raise WebsiteError("robots_unavailable")
            policy = RobotFileParser()
            policy.parse(response.body.splitlines() if response.status == 200 else ["User-agent: *", "Allow: /"])
            self.robots[origin] = policy
        return self.robots[origin]

    def get_page(self, url, initial, deadline):
        url = checked_url(url)
        for _ in range(4):
            if not self.allowed_host(url, initial):
                raise WebsiteError("cross_host_link_skipped")
            policy = self._policy(url, initial, deadline)
            if not policy.can_fetch(AGENT, url):
                raise WebsiteError("robots_disallowed")
            delay = max(1, policy.crawl_delay(AGENT) or 0)
            rate = policy.request_rate(AGENT)
            if rate and rate.requests > 0:
                delay = max(delay, rate.seconds / rate.requests)
            response = self._raw(url, deadline, delay)
            if response.status not in REDIRECTS:
                if response.status != 200:
                    raise WebsiteError(f"website_http_{response.status}")
                return response
            url = self._redirect_target(response, initial)
        raise WebsiteError("website_redirect_limit")


BLOCKS = {"p", "div", "section", "article", "li", "td", "tr", "address", "header", "footer", "h1", "h2", "h3"}
PHONE_TEXT = re.compile(r"(?<!\w)(?:\+?\d[\d()/ .\u00a0–—‑-]{6,}\d)(?:\s*(?:ext\.?|x|#|durchwahl)\s*\d{1,8})?", re.I)
LABEL = re.compile(r"\b(reception|front desk|welcome desk|switchboard|main (?:phone|line|number)|telefax|fax|emergency|notruf|notfall(?:nummer|telefon)?|phone|telephone|telefon(?:nummer|zentrale)?|tel|call|empfang|rezeption|zentrale|anmeldung|kontakt)\b", re.I)
CONTACT_LINK = re.compile(r"contact|kontakt|impressum|about|über.uns|ueber.uns|location|standort", re.I)


class ContactParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.links = [], []
        self.parts, self.tels = [], []
        self.hidden = []
        self.anchor = None

    def flush(self):
        if self.parts or self.tels:
            self.blocks.append(("".join(self.parts), self.tels))
        self.parts, self.tels = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.hidden:
            if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "wbr"):
                self.hidden.append(tag)
            return
        if tag in ("script", "style", "noscript", "template") or "hidden" in attrs or attrs.get("aria-hidden") == "true":
            if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "wbr"):
                self.hidden.append(tag)
            return
        if tag in BLOCKS:
            self.flush()
        if tag == "br":
            self.parts.append("\n")
        if tag == "a":
            href = attrs.get("href", "")
            self.anchor = [href, []]
            if href.lower().startswith("tel:"):
                self.tels.append((unquote(href[4:]).replace(";ext=", " ext. "), len("".join(self.parts))))

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in self.hidden:
                self.hidden = self.hidden[:len(self.hidden) - 1 - self.hidden[::-1].index(tag)]
            return
        if tag == "a" and self.anchor:
            self.links.append((self.anchor[0], "".join(self.anchor[1])))
            self.anchor = None
        if tag in BLOCKS:
            self.flush()

    def handle_data(self, data):
        if self.hidden:
            return
        self.parts.append(data)
        if self.anchor:
            self.anchor[1].append(data)

    def close(self):
        super().close()
        self.flush()


def extract_contacts(html, country):
    parser = ContactParser()
    parser.feed(html)
    parser.close()
    found = []
    for block, tels in parser.blocks:
        # Imprints often list the regulator's contact alongside the practice.
        # Keep line-break context so these are not presented as facility phones.
        if re.search(r"kassenärztliche vereinigung|ärztekammer|aufsichtsbehörde", block, re.I):
            continue
        entries = [(raw, offset, "tel_link") for raw, offset in tels]
        entries.extend((match.group(), match.start(), "labeled_text") for match in PHONE_TEXT.finditer(block))
        for raw, offset, method in entries:
            prefix = block[max(0, offset - 100):offset]
            previous_numbers = list(PHONE_TEXT.finditer(prefix))
            if previous_numbers:
                prefix = prefix[previous_numbers[-1].end():]
            labels = list(LABEL.finditer(prefix))
            specific = [m for m in labels if m.group().lower() not in ("phone", "telephone", "tel", "call", "telefon", "telefonnummer", "kontakt")]
            label = (specific or labels)[-1].group().lower() if labels else ""
            if label in ("fax", "telefax", "emergency", "notruf", "notfall", "notfallnummer", "notfalltelefon") or (method == "labeled_text" and not label):
                continue
            phone = phone_candidate(raw.strip(), country)
            if not phone:
                continue
            role = "reception" if label in ("reception", "front desk", "welcome desk", "empfang", "rezeption", "anmeldung") else "main" if label.startswith("main ") or label in ("switchboard", "zentrale", "telefonzentrale") else "general"
            excerpt = re.sub(r"\s+", " ", block[max(0, offset - 100):offset + len(raw) + 80]).strip()[:280]
            candidate = {**phone, "role": role, "extraction_method": method, "excerpt": excerpt}
            if not any((p["number"], p["extension"], p["role"]) == (phone["number"], phone["extension"], role) for p in found):
                found.append(candidate)
    return found[:20], parser.links


def enrich_leads(leads, country, *, max_websites=10, session=None, on_progress=None):
    """Mutate only missing-contact leads, retaining field-level source evidence."""
    session = session or WebsiteSession()
    attempted = enriched = 0
    for lead in leads:
        report = {"status": "skipped", "pages": [], "errors": []}
        lead["website_enrichment"] = report
        if lead["phone_candidates"]:
            report["reason"] = "existing_phone_candidates"
            continue
        if lead["is_mock"]:
            report["reason"] = "mock_data"
            continue
        if not lead["website"]:
            report["reason"] = "no_website"
            continue
        if attempted >= max_websites:
            report["reason"] = "website_budget"
            continue
        attempted += 1
        if on_progress:
            on_progress({"kind": "website", "id": lead["lead_id"], "label": lead["name"], "status": "running"})
        deadline = session.clock() + 25
        try:
            initial = checked_url(lead["website"])
            pending, visited = [initial], set()
            parts = urlsplit(initial)
            homepage = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
            if homepage != initial:
                pending.append(homepage)
            while pending and len(visited) < 3:
                url = pending.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                try:
                    page = session.get_page(url, initial, deadline)
                    contacts, links = extract_contacts(page.body, country)
                    retrieved = page.retrieved_at
                    report["pages"].append({"url": page.url, "retrieved_at": retrieved, "candidates_found": len(contacts)})
                    for contact in contacts:
                        contact["source_url"] = page.url
                        lead["phone_candidates"].append(contact)
                        lead["evidence"].append({
                            "evidence_id": stable_id(lead["lead_id"] + page.url + contact["number"] + str(contact["extension"]) + contact["role"]),
                            "source": "website", "source_url": page.url, "retrieved_at": retrieved,
                            "source_updated_at": None, "task_id": "website-" + lead["lead_id"], "provider_run_id": None,
                            "query": "public reception/contact phone", "search_location": "listed facility website",
                            "observed": {"name": lead["name"], "address": None, "coordinates": None,
                                         "phone_raw": contact["raw"], "phone": contact, "listed_closed": False},
                            "excerpt": contact["excerpt"],
                        })
                    if any(c["role"] == "reception" for c in contacts):
                        break
                    for href, label in links:
                        if not CONTACT_LINK.search(unquote(label + " " + href)):
                            continue
                        try:
                            link = checked_url(urljoin(page.url, href))
                            if session.allowed_host(link, initial) and link not in visited and link not in pending:
                                pending.append(link)
                        except WebsiteError:
                            pass
                    pending = sorted(pending, key=lambda link: not re.search(r"contact|kontakt|impressum", link, re.I))[:6]
                except WebsiteError as exc:
                    report["errors"].append({"url": url, "code": str(exc)})
        except WebsiteError as exc:
            report["errors"].append({"url": lead["website"], "code": str(exc)})
        if lead["phone_candidates"]:
            enriched += 1
            report["status"] = "candidates_found"
            lead["flags"] = [f for f in lead["flags"] if f != "missing_or_unrecognized_phone"]
            lead["flags"].append("website_contact_scope_unverified")
            lead["phone_candidates"].sort(key=lambda p: {"reception": 0, "main": 1, "general": 2}.get(p.get("role"), 3))
        else:
            report["status"] = "failed" if report["errors"] else "no_phone_found"
        if on_progress:
            on_progress({"kind": "website", "id": lead["lead_id"], "label": lead["name"], "status": report["status"]})
    # Recompute conflicts and shared-switchboard flags after enrichment.
    leads[:] = merge_leads(leads)
    return {"websites_attempted": attempted, "leads_enriched": enriched, "http_requests": session.requests,
            "max_websites": max_websites,
            "incomplete": any(lead["website_enrichment"]["errors"] or lead["website_enrichment"].get("reason") == "website_budget" for lead in leads),
            "unresolved": sum(not lead["phone"] for lead in leads)}
