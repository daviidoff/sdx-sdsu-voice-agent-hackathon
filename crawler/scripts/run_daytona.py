"""Optional Daytona v2 launcher. The worker itself has no SDK dependency."""

import argparse
import json
import math
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from disaster_crawler.models import DiscoveryRequest
from disaster_crawler.engine import plan


def run_in_daytona(client, request, provider="mock"):
    if provider not in ("mock", "osm", "apify"):
        raise ValueError("provider must be mock, osm, or apify")
    if provider == "osm":
        from disaster_crawler.osm import OSMProvider
        OSMProvider().prepare(request, plan(request)[0])
    env = {}
    if provider == "apify":
        if not os.environ.get("APIFY_TOKEN"):
            raise ValueError("APIFY_TOKEN is required for live discovery")
        env["APIFY_TOKEN"] = os.environ["APIFY_TOKEN"]
    # Unique sandbox per request; no local .env or repository credentials uploaded.
    sandbox = client.v2.create(name="discovery-" + uuid.uuid4().hex[:12], env=env, wait_seconds=60)
    try:
        remote = "/tmp/disaster-crawler"
        sandbox.fs.mkdir(remote)
        sandbox.fs.mkdir(remote + "/disaster_crawler")
        sandbox.fs.mkdir(remote + "/disaster_crawler/fixtures")
        files = sorted((ROOT / "disaster_crawler").glob("*.py"))
        files.append(ROOT / "disaster_crawler/fixtures/facilities.json")
        for file in files:
            sandbox.fs.upload_file(str(file), remote + "/" + file.relative_to(ROOT).as_posix())
        sandbox.fs.write_text(remote + "/request.json", json.dumps(request.to_dict()))
        tasks, _ = plan(request)
        timeout = math.ceil(len(tasks) / request.concurrency) * (request.task_timeout_seconds + 10) + 30
        if request.enrich_websites:
            timeout += request.max_websites * 25
        # Only fixed paths and an allowlisted provider enter this command.
        command = ("cd /tmp/disaster-crawler && python3 -m disaster_crawler "
                   "--request request.json --output result.json --provider " + provider)
        response = sandbox.process.run(command, timeout=timeout)
        if response.exit_code is None:
            raise RuntimeError("Daytona worker exceeded its wait deadline; sandbox cleanup requested")
        if response.exit_code not in (0, 1):
            raise RuntimeError("Daytona worker failed before producing a discovery report")
        result = json.loads(sandbox.fs.read_text(remote + "/result.json"))
        result["execution"] = {"runtime": "daytona", "sandbox_id": sandbox.id}
        return result
    finally:
        # Deletion also stops a worker still running after process.run times out.
        # Apify Actors are separate jobs and retain their server-side timeout.
        try:
            client.v2.delete(sandbox)
        except Exception:
            print(f"Daytona cleanup failed; remove sandbox {sandbox.id} manually.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=ROOT / "examples/demo-request.json")
    parser.add_argument("--provider", choices=("mock", "osm", "apify"), default="mock")
    parser.add_argument("--output", type=Path, default=ROOT / "out/daytona-result.json")
    args = parser.parse_args()
    payload = json.loads(args.request.read_text())
    if args.provider == "osm" and isinstance(payload, dict):
        payload.setdefault("sources", ["osm"])
    request = DiscoveryRequest.from_dict(payload)
    if not os.environ.get("DAYTONA_API_KEY"):
        parser.error("DAYTONA_API_KEY is required")
    try:
        from daytona import Daytona
    except ImportError:
        parser.error("Install scripts/requirements-daytona.txt in a virtual environment first")
    with Daytona() as client:
        result = run_in_daytona(client, request, args.provider)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {args.output}")
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
