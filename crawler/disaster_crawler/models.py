from dataclasses import asdict, dataclass, field
import math


CATEGORIES = {
    "care_home": "residential care home assisted living",
    "disability_support": "disability support services",
    "health_clinic": "health clinic",
    "shelter": "community shelter",
    "accessible_transport": "wheelchair accessible transport",
    "community_organization": "community assistance organization",
}


def bounded_int(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")


def short_text(value, name, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a nonempty string of at most {maximum} characters")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} cannot contain control characters")


@dataclass(frozen=True)
class DiscoveryRequest:
    incident_id: str
    locations: list[str]
    categories: list[str]
    country_code: str = "US"
    sources: list[str] = field(default_factory=lambda: ["maps", "web"])
    # Optional [west, south, east, north]; no inference of disaster boundaries.
    bounds: list[float] | None = None
    max_tasks: int = 16
    max_results_per_task: int = 20
    max_leads: int = 100
    concurrency: int = 3
    task_timeout_seconds: int = 120
    max_charge_usd_per_task: float = 0.5
    enrich_websites: bool = False
    max_websites: int = 10

    def __post_init__(self):
        short_text(self.incident_id, "incident_id", 100)
        if type(self.enrich_websites) is not bool:
            raise ValueError("enrich_websites must be a boolean")
        bounded_int(self.max_websites, "max_websites", 1, 20)
        if not isinstance(self.locations, list) or not 1 <= len(self.locations) <= 8:
            raise ValueError("locations must contain 1–8 location names")
        for location in self.locations:
            short_text(location, "location")
        if not isinstance(self.categories, list) or not self.categories:
            raise ValueError("categories must be a nonempty list")
        if any(c not in CATEGORIES for c in self.categories):
            raise ValueError(f"categories must be selected from {', '.join(CATEGORIES)}")
        if not isinstance(self.sources, list) or not self.sources or any(s not in ("maps", "web", "osm") for s in self.sources):
            raise ValueError("sources must contain maps, web, and/or osm")
        if not isinstance(self.country_code, str) or len(self.country_code) != 2 or not self.country_code.isalpha() or not self.country_code.isupper():
            raise ValueError("country_code must be a two-letter uppercase country code")
        for name, low, high in (("max_tasks", 1, 64), ("max_results_per_task", 1, 100),
                                ("max_leads", 1, 1000), ("concurrency", 1, 8),
                                ("task_timeout_seconds", 10, 600)):
            bounded_int(getattr(self, name), name, low, high)
        amount = self.max_charge_usd_per_task
        if type(amount) not in (int, float) or not math.isfinite(amount) or not 0 < amount <= 10:
            raise ValueError("max_charge_usd_per_task must be greater than 0 and at most 10")
        if self.bounds is not None:
            b = self.bounds
            if (not isinstance(b, list) or len(b) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in b) or
                not (-180 <= b[0] < b[2] <= 180 and -90 <= b[1] < b[3] <= 90)):
                raise ValueError("bounds must be [west, south, east, north], without crossing the antimeridian")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("request must be a JSON object")
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError("request contains missing, unknown, or incorrectly typed fields") from exc

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SearchTask:
    task_id: str
    location: str
    category: str
    source: str
    query: str


@dataclass
class SearchResult:
    records: list[dict]
    run_id: str | None = None
    build_id: str | None = None
    limit_reached: bool = False
    retrieved_at: str | None = None
    warnings: list[str] = field(default_factory=list)


class ProviderError(Exception):
    def __init__(self, code, run_id=None, cleanup_failed=False):
        super().__init__(code)
        self.code = code
        self.run_id = run_id
        self.cleanup_failed = cleanup_failed
