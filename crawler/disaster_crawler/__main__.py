import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from .engine import discover, plan
from .models import DiscoveryRequest
from .providers import ApifyProvider, MockProvider
from .osm import OSMProvider


def main():
    parser = argparse.ArgumentParser(description="Discover public facility contacts; mock mode is the default.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--provider", choices=("mock", "osm", "apify"), default="mock")
    parser.add_argument("--output", type=Path, help="Atomic JSON output; default is stdout")
    parser.add_argument("--plan", action="store_true", help="Show bounded tasks without calling any provider")
    parser.add_argument("--enrich-websites", action="store_true", help="Visit listed websites for missing public phone contacts")
    parser.add_argument("--max-websites", type=int, help="Maximum facilities to enrich (1–20, default 10)")
    parser.add_argument("--publish-url", help="Import the completed report into the dashboard backend, e.g. http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        payload = json.loads(args.request.read_text())
        if isinstance(payload, dict):
            if args.enrich_websites:
                payload["enrich_websites"] = True
            if args.max_websites is not None:
                payload["max_websites"] = args.max_websites
        if args.provider == "osm" and isinstance(payload, dict):
            payload.setdefault("sources", ["osm"])
        request = DiscoveryRequest.from_dict(payload)
        if args.plan:
            from dataclasses import asdict
            tasks, skipped = plan(request)
            result = {"tasks": [asdict(t) for t in tasks], "tasks_skipped": len(skipped)}
            result["website_enrichment"] = {"enabled": request.enrich_websites, "max_websites": request.max_websites,
                                            "max_pages_per_website": 3, "max_http_requests": 80}
            if args.provider == "osm":
                provider = OSMProvider()
                provider.prepare(request, tasks)
                result.update(overpass_query=provider.query(), public_api_requests=1,
                              note="No account or API key required. Public Overpass availability varies.")
            elif args.provider == "apify":
                result.update(max_actor_charge_usd_requested=round(len(tasks) * request.max_charge_usd_per_task, 2))
        else:
            provider = {"mock": MockProvider, "osm": OSMProvider, "apify": ApifyProvider}[args.provider]()
            result = discover(request, provider)
        content = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent,
                                                 prefix=".crawler-", delete=False) as file:
                    temporary = file.name
                    file.write(content)
                os.replace(temporary, args.output)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            print(f"Wrote {args.output}", file=sys.stderr)
        else:
            print(content, end="")
        if args.publish_url and not args.plan:
            from .publish import publish_report
            receipt = publish_report(result, args.publish_url)
            print("Dashboard import: " + json.dumps(receipt), file=sys.stderr)
        return 1 if result.get("status") == "failed" else 0
    except (ValueError, OSError) as exc:
        print(f"Crawler error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
