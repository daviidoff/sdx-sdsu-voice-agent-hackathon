"""Account-free OSM facility discovery. One bounded Overpass request per job."""

from datetime import datetime, timezone
import json
import re
import socket
import ssl
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener

from .models import ProviderError, SearchResult
from .normalize import coordinates, text
from .providers import NoRedirects
from .tls import tls_context


# AND within a selector, OR between selectors. The same definitions drive the
# remote query and local classification, avoiding mismatched category filters.
SELECTORS = {
    "care_home": [
        [("amenity", "nursing_home")],
        [("amenity", "social_facility"), ("social_facility", "(group_home|nursing_home|assisted_living)")],
    ],
    "disability_support": [
        [("amenity", "social_facility"), ("social_facility:for", ".*(disabled|disability|mental_health).*" )],
    ],
    "health_clinic": [
        [("amenity", "(clinic|doctors|hospital)")],
        [("healthcare", "(clinic|doctor|hospital|centre)")],
    ],
    "shelter": [[("amenity", "social_facility"), ("social_facility", "shelter")]],
    "accessible_transport": [[("amenity", "taxi"), ("wheelchair", "yes")]],
    "community_organization": [
        [("amenity", "(community_centre|social_centre)")],
        [("office", "(ngo|charity)")],
    ],
}
ATTRIBUTION = {
    "text": "© OpenStreetMap contributors",
    "url": "https://www.openstreetmap.org/copyright",
    "license": "ODbL-1.0",
}


def matches(tags, category):
    return any(all(isinstance(tags.get(key), str) and re.fullmatch(pattern, tags[key])
                   for key, pattern in selector) for selector in SELECTORS[category])


class OSMProvider:
    mode = "live"
    name = "osm"
    attribution = ATTRIBUTION
    ENDPOINT = "https://overpass-api.de/api/interpreter"
    ELEMENT_LIMIT = 1000
    MAX_BYTES = 5_000_000

    def __init__(self, *, transport=None):
        self.transport = transport or self._http
        self._lock = threading.Lock()
        self._prepared = False
        self._response = None
        self._error = None

    def prepare(self, request, tasks):
        if request.sources != ["osm"]:
            raise ValueError("The osm provider requires sources: [\"osm\"]")
        if len(request.locations) != 1 or request.bounds is None:
            raise ValueError("OSM requires one location label and explicit bounds [west, south, east, north]")
        west, south, east, north = request.bounds
        if east - west > 1 or north - south > 1:
            raise ValueError("OSM public queries are limited to a box at most 1 degree wide and tall")
        self._request = request
        self._categories = list(dict.fromkeys(t.category for t in tasks))
        self._response = None
        self._error = None
        self._prepared = True

    def query(self):
        if not self._prepared:
            raise ValueError("prepare the OSM provider before building a query")
        west, south, east, north = self._request.bounds
        timeout = max(1, min(25, self._request.task_timeout_seconds - 5))
        filters = list(dict.fromkeys(
            "nwr" + "".join(f'[{json.dumps(key)}~{json.dumps("^" + pattern + "$")}]'
                             for key, pattern in selector) + ";"
            for category in self._categories for selector in SELECTORS[category]
        ))
        return (f"[out:json][timeout:{timeout}][maxsize:16777216][bbox:{south},{west},{north},{east}];\n"
                "(\n" + "\n".join(filters) + f"\n);\nout body center {self.ELEMENT_LIMIT + 1};")

    def _http(self, query, timeout):
        request = Request(self.ENDPOINT, data=urlencode({"data": query}).encode(), method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                   "User-Agent": "DisasterResponseDiscovery/0.1 (bounded facility lookup)",
                                   "Accept": "application/json"})
        try:
            with build_opener(NoRedirects(), HTTPSHandler(context=tls_context())).open(request, timeout=timeout) as response:
                raw = response.read(self.MAX_BYTES + 1)
            if len(raw) > self.MAX_BYTES:
                raise ProviderError("osm_response_too_large")
            return json.loads(raw)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            # No immediate retries or alternate-server hopping on a busy public service.
            raise ProviderError(f"osm_http_{code}") from None
        except URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise ProviderError("osm_tls_certificate_error") from None
            raise ProviderError("osm_network_error") from None
        except (socket.timeout, TimeoutError):
            raise ProviderError("osm_network_error") from None
        except (ValueError, UnicodeDecodeError):
            raise ProviderError("osm_invalid_json") from None

    def search(self, task, request):
        if not self._prepared or request != self._request or task.category not in self._categories:
            raise ValueError("OSMProvider must be prepared for this discovery job")
        with self._lock:
            if self._error:
                raise ProviderError(self._error)
            if self._response is None:
                try:
                    data = self.transport(self.query(), min(35, request.task_timeout_seconds))
                    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
                        raise ProviderError("osm_invalid_response")
                    self._response = data
                    self._retrieved_at = datetime.now(timezone.utc).isoformat()
                except Exception as exc:
                    self._error = exc.code if isinstance(exc, ProviderError) else "osm_invalid_response"
                    raise ProviderError(self._error) from None
        data = self._response
        elements = data["elements"]
        warnings = []
        if data.get("remark"):
            # Overpass may send HTTP 200 plus partial results on a runtime error.
            if not elements:
                raise ProviderError("osm_query_incomplete")
            warnings.append("osm_query_incomplete")
        rows = []
        malformed = False
        for element in elements[:self.ELEMENT_LIMIT]:
            if not isinstance(element, dict) or not isinstance(element.get("tags"), dict):
                malformed = True
                continue
            tags = element["tags"]
            if not matches(tags, task.category):
                continue
            row = element_record(element)
            if row is None:
                malformed = True
                continue
            rows.append(row)
        if malformed:
            warnings.append("osm_invalid_elements")
        limit = request.max_results_per_task
        return SearchResult(rows[:limit], limit_reached=len(rows) > limit or len(elements) > self.ELEMENT_LIMIT,
                            retrieved_at=self._retrieved_at, warnings=warnings)


def element_record(element):
    kind, identifier = element.get("type"), element.get("id")
    if kind not in ("node", "way", "relation") or type(identifier) is not int or identifier <= 0:
        return None
    tags = element["tags"]
    name = text(tags.get("name") or tags.get("official_name") or tags.get("operator"), 250)
    # Retain unnamed facilities with an explicit label, rather than fabricating a name.
    name = name or f"Unnamed OSM {kind}/{identifier}"
    point = None
    # OSM uses lon; the common wire contract uses lng.
    raw_point = element if kind == "node" else element.get("center")
    if isinstance(raw_point, dict):
        point = coordinates({"lat": raw_point.get("lat"), "lng": raw_point.get("lon")})
    street = " ".join(filter(None, [text(tags.get("addr:housenumber")), text(tags.get("addr:street"))]))
    address = text(tags.get("addr:full")) or ", ".join(filter(None, [street, text(tags.get("addr:city")),
                                                        text(tags.get("addr:state")), text(tags.get("addr:postcode"))]))
    phone_tags = {key: text(tags.get(key), 500) for key in ("phone", "contact:phone") if text(tags.get(key))}
    values = list(dict.fromkeys(value.strip() for raw in phone_tags.values() for value in raw.split(";") if value.strip()))
    selected_tags = {key: text(value, 500) for key, value in tags.items()
                     if key in ("amenity", "healthcare", "social_facility", "social_facility:for",
                                "office", "wheelchair", "phone", "contact:phone", "website", "contact:website",
                                "disused", "abandoned")}
    return {"title": name, "placeId": f"osm:{kind}/{identifier}", "address": address,
            "location": point, "phoneValues": values, "phoneTags": phone_tags,
            "website": tags.get("contact:website") or tags.get("website"),
            "url": f"https://www.openstreetmap.org/{kind}/{identifier}",
            "attribution": ATTRIBUTION, "sourceTags": selected_tags,
            "coordinateBasis": "node" if kind == "node" else "bounding_box_center",
            "permanentlyClosed": tags.get("disused") == "yes" or tags.get("abandoned") == "yes",
            "description": "OSM tag match; facility type and current services require verification."}
