import hashlib
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit


def text(value, limit=500):
    return value.strip()[:limit] if isinstance(value, str) else ""


def stable_id(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def safe_url(value):
    try:
        parts = urlsplit(text(value, 2000))
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
            return None
        if any(ord(c) < 33 for c in value):
            return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    except (ValueError, TypeError):
        return None


def phone_candidate(raw, country):
    """Conservative formatting, not proof of assignment or reachability."""
    raw = text(raw, 100)
    formatted = raw.translate(str.maketrans({'–': '-', '—': '-', '‑': '-'}))
    match = re.fullmatch(r"([+\d() ./\u00a0-]+?)(?:\s*(?:ext\.?|x|#|durchwahl)\s*(\d{1,8}))?", formatted, re.I)
    if not match:
        return None
    number, extension = match.groups()
    # The optional German trunk prefix is often printed as +49 (0)30.
    if country == "DE":
        number = re.sub(r"^(\+49|0049)\s*\(0\)", r"\1", number.strip())
    digits = re.sub(r"\D", "", number)
    if country == "DE" and digits.startswith("0049") and 10 <= len(digits) <= 17:
        normalized = "+" + digits[2:]
    elif country == "DE" and digits.startswith("0") and not digits.startswith("00") and 8 <= len(digits) <= 14:
        normalized = "+49" + digits[1:]
    elif number.strip().startswith("+") and 8 <= len(digits) <= 15 and not digits.startswith("0"):
        normalized = "+" + digits
    elif country in ("US", "CA") and len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789":
        normalized = "+1" + digits
    elif country in ("US", "CA") and len(digits) == 11 and digits[0] == "1" and digits[1] in "23456789" and digits[4] in "23456789":
        normalized = "+" + digits
    else:
        return None
    return {"number": normalized, "extension": extension, "raw": raw,
            "verification": "format_only"}


def coordinates(value):
    if not isinstance(value, dict):
        return None
    lat, lng = value.get("lat"), value.get("lng")
    if (type(lat) not in (int, float) or type(lng) not in (int, float) or
        not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180):
        return None
    return {"lat": lat, "lng": lng}


def normalize(row, task, request, observed_at, mode, run_id):
    name = text(row.get("title"), 250)
    if not name:
        return None
    address = text(row.get("address")) or None
    point = coordinates(row.get("location"))
    url = safe_url(row.get("url"))
    website = safe_url(row.get("website"))
    place_id = text(row.get("placeId"), 200) or None
    # Web snippets remain research links. A number in a search excerpt is not
    # attributed to the named facility without inspecting the source page.
    phone_raw = text(row.get("phoneUnformatted") or row.get("phone"), 100) if task.source == "maps" else ""
    raw_values = row.get("phoneValues", []) if task.source == "osm" else [phone_raw]
    phone_candidates = [p for raw in raw_values if (p := phone_candidate(raw, request.country_code))]
    if task.source == "osm":
        phone_raw = "; ".join(raw_values)
    phone = phone_candidates[0] if len({(p["number"], p["extension"]) for p in phone_candidates}) == 1 else None
    closed = row.get("permanentlyClosed") is True or row.get("temporarilyClosed") is True
    area = "not_checked"
    if request.bounds:
        west, south, east, north = request.bounds
        area = "unknown" if not point else (
            "inside" if west <= point["lng"] <= east and south <= point["lat"] <= north else "outside")
    if place_id:
        identity = "place:" + place_id
    elif address:
        identity = "address:" + name.casefold() + "|" + address.casefold()
    else:
        identity = "link:" + name.casefold() + "|" + (url or task.task_id)
    evidence_id = stable_id(json.dumps([task.task_id, identity, phone_raw, url, address, point, closed], sort_keys=True))
    evidence = {"evidence_id": evidence_id, "source": task.source, "source_url": url,
                "retrieved_at": observed_at, "source_updated_at": None,
                "task_id": task.task_id, "provider_run_id": run_id,
                "query": task.query, "search_location": task.location,
                "observed": {"name": name, "address": address, "coordinates": point,
                             "phone_raw": phone_raw or None, "phone": phone,
                             "listed_closed": closed},
                "excerpt": text(row.get("description"), 600) or None}
    if task.source == "osm":
        evidence["observed"]["phone_candidates"] = phone_candidates
        evidence["observed"]["phone_tags"] = row.get("phoneTags", {})
        evidence["observed"]["osm_tags"] = row.get("sourceTags", {})
        evidence["observed"]["coordinate_basis"] = row.get("coordinateBasis")
        evidence["attribution"] = row.get("attribution")
    return {"lead_id": stable_id(identity), "incident_id": request.incident_id,
            "name": name, "place_ids": [place_id] if place_id else [],
            "categories": [task.category], "category_basis": "search_query_unverified",
            "address": address, "coordinates": point, "area_match": area,
            "website": website, "source_url": url,
            "phone_candidates": phone_candidates, "phone": phone,
            "listed_closed": closed, "evidence": [evidence], "is_mock": mode == "mock",
            "review_status": "needs_review", "contact_status": "not_contacted",
            "safety_status": "unknown", "capacity_status": "unknown",
            "flags": ["approximate_coordinates"] if row.get("coordinateBasis") == "bounding_box_center" else []}


def merge_leads(leads):
    """Merge exact place IDs or exact name/address; never merge by phone alone."""
    merged = []
    for lead in leads:
        same = None
        for existing in merged:
            same_place = bool(set(lead["place_ids"]) & set(existing["place_ids"]))
            same_address = (lead["address"] and existing["address"] and
                            lead["name"].casefold() == existing["name"].casefold() and
                            lead["address"].casefold() == existing["address"].casefold() and
                            not (lead["place_ids"] and existing["place_ids"]))
            if same_place or same_address or lead["lead_id"] == existing["lead_id"]:
                same = existing
                break
        if same is None:
            merged.append(lead)
            continue
        for field in ("address", "coordinates"):
            if same[field] and lead[field] and same[field] != lead[field]:
                same["flags"].append(field + "_conflict")
            elif not same[field]:
                same[field] = lead[field]
                if field == "coordinates":
                    same["area_match"] = lead["area_match"]
        for field in ("categories", "place_ids", "phone_candidates", "flags"):
            for value in lead[field]:
                if value not in same[field]:
                    same[field].append(value)
        known = {e["evidence_id"] for e in same["evidence"]}
        same["evidence"].extend(e for e in lead["evidence"] if e["evidence_id"] not in known)
        same["listed_closed"] |= lead["listed_closed"]
        same["website"] = same["website"] or lead["website"]
        same["source_url"] = same["source_url"] or lead["source_url"]

    phones = {}
    for lead in merged:
        candidates = {(p["number"], p["extension"]) for p in lead["phone_candidates"]}
        if len(candidates) > 1:
            lead["flags"].append("phone_conflict")
            lead["phone"] = None
        elif candidates:
            lead["phone"] = lead["phone_candidates"][0]
        else:
            lead["phone"] = None
            lead["flags"].append("missing_or_unrecognized_phone")
        if not lead["coordinates"]:
            lead["flags"].append("missing_coordinates")
        if not lead["address"]:
            lead["flags"].append("missing_address")
        if lead["area_match"] == "outside":
            lead["flags"].append("outside_requested_bounds")
        if lead["area_match"] in ("unknown", "not_checked"):
            lead["flags"].append("area_needs_review")
        if lead["listed_closed"]:
            lead["flags"].append("listed_closed")
        if not any(e["source_url"] for e in lead["evidence"]):
            lead["flags"].append("missing_source_url")
        if all(e["source"] == "web" for e in lead["evidence"]):
            lead["flags"].append("research_link_only")
        for number, _ in candidates:
            phones.setdefault(number, []).append(lead)
    for matches in phones.values():
        if len({lead["lead_id"] for lead in matches}) > 1:
            for lead in matches:
                lead["flags"].append("shared_phone_across_facilities")
    for lead in merged:
        lead["flags"] = sorted(set(lead["flags"]))
        blocking = {"phone_conflict", "address_conflict", "coordinates_conflict", "listed_closed",
                    "outside_requested_bounds", "missing_source_url", "research_link_only"}
        lead["next_action"] = ("verify_contact_and_location" if lead["phone"] and not blocking.intersection(lead["flags"])
                               else "research_needed")
        lead["handoff"] = {"status": "draft", "dial_allowed": False,
                           "requires": ["operator_review", "verified_public_contact", "incident_authorization"],
                           "suggested_questions": [
                               "Is this the public reception for this facility, and what is its current location?",
                               "Are there unmet assistance needs your organization can report?",
                               "Can reception relay the approved callback information to people who need help?",
                               "Which public organization should the response team contact next?"
                           ]}
    return sorted(merged, key=lambda lead: (lead["next_action"] != "verify_contact_and_location", lead["name"], lead["lead_id"]))
