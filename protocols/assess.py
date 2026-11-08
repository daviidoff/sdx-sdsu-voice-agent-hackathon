"""Deterministic demo computation, run unchanged locally and in Daytona."""
import itertools
import json
from pathlib import Path
import re
import sys


def mobility_details(value):
    """Respect explicit negative answers without inferring broader independence."""
    mobility = str(value or "").strip()
    normalized = " ".join(mobility.lower().split()).strip(" .!;")
    if normalized in {"none", "no", "no mobility needs", "no mobility issues",
                      "no mobility limitations", "no mobility assistance needed"}:
        return "", False
    # Remove explicitly negated mentions before detecting an affirmative mention.
    # "No wheelchair; needs a walker" still preserves the reported walker need.
    affirmative = re.sub(
        r"\b(?:no|without|does not need|doesn't need|does not use|doesn't use|not using)\s+(?:a\s+)?wheelchairs?\b"
        r"|\bwheelchairs?\s+(?:(?:is|are)\s+)?(?:not needed|not required|not used)\b",
        "", normalized,
    )
    return mobility, bool(re.search(r"\bwheelchairs?\b", affirmative))


def assess(payload, directory):
    facts = payload["assessment"]
    directory = Path(directory)
    mobility, wheelchair = mobility_details(facts.get("mobility_needs"))
    needs_transport = facts.get("transport_needed") is True or facts.get("can_evacuate") is False
    tags = {"intake"}
    if needs_transport:
        tags.add("transport")
    if mobility:
        tags.add("mobility")
    protocols = []
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text())
        if tags.intersection(document.get("tags", [])):
            protocols.append({"id": document["id"], "version": document["version"],
                              "source": f"protocols/{path.name}", "questions": document["questions"]})
    resources = payload.get("resources")
    if resources is None:
        resources = json.loads((directory / "resources.demo.json").read_text())
    synthetic = resources.get("synthetic", "resources" not in payload)
    people = facts.get("people_count")
    missing = []
    assumptions = []
    unmet = []
    if not isinstance(people, int) or isinstance(people, bool) or people < 1:
        missing.append("people_count")
        people = None
    if not str(facts.get("location") or "").strip():
        missing.append("location")
    if facts.get("can_evacuate") is None and facts.get("transport_needed") is None:
        missing.append("can_evacuate_or_transport_needed")
    wheelchair_count = facts.get("wheelchair_users") if wheelchair else 0
    if wheelchair and (not isinstance(wheelchair_count, int) or isinstance(wheelchair_count, bool) or wheelchair_count < 1):
        wheelchair_count = 1
        assumptions.append("One wheelchair place used for planning; wheelchair user count is unconfirmed.")
        missing.append("wheelchair_users")
    if wheelchair and people is not None and wheelchair_count > people:
        missing.append("resolve_wheelchair_count_exceeds_people_count")
    if mobility:
        unmet.append("Responder must confirm boarding assistance and suitability for the reported mobility needs.")
    candidate = None
    if needs_transport and people is not None:
        options = []
        vehicles = resources["vehicles"]
        for count in range(1, len(vehicles) + 1):
            for group in itertools.combinations(vehicles, count):
                seats = sum(vehicle["passenger_capacity"] for vehicle in group)
                accessible = sum(vehicle["wheelchair_capacity"] for vehicle in group)
                if seats >= people and accessible >= wheelchair_count:
                    options.append((count, seats - people, tuple(vehicle["id"] for vehicle in group), seats, accessible))
        if options:
            _, _, ids, seats, accessible = min(options)
            candidate = {"vehicle_ids": list(ids), "passenger_capacity": seats,
                         "wheelchair_capacity": accessible, "status": "proposal_only",
                         "requires_confirmation": True, "resource_source": resources["source"],
                         "resource_version": resources["version"]}
        else:
            unmet.append("Available capacity records cannot satisfy the reported passenger and wheelchair capacity.")
    if needs_transport:
        unmet.append("Transport acceptance, destination, and authorized travel instructions remain unconfirmed.")
    instruction = payload.get("instruction") or {}
    status = "needs_more_information" if missing else (
        "proposal_ready" if candidate else "unmet_needs" if needs_transport else "assessment_complete")
    return {"status": status, "synthetic_resources": synthetic, "protocols": protocols,
            "proposed_candidate": candidate, "unmet_needs": unmet, "missing_fields": missing,
            "assumptions": assumptions, "instruction_reference": {
                key: instruction[key] for key in ("id", "version", "zone_id", "updated_at") if key in instruction},
            "dispatch_status": "not_dispatched",
            "summary": "Capacity calculation only; responder confirmation is required for assistance."}


if __name__ == "__main__":
    payload = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(assess(payload, Path(__file__).parent), sort_keys=True))
