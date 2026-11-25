"""Run the Riverbend Hall operator exercise on a fresh local dashboard."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route


HALL = "Riverbend Hall"
ZONES = [
    {
        "id": "valley-assembly", "label": "Valley assembly zone", "level": "evacuate",
        "instruction": "For the drill, meet at the upper plaza for pickup.",
        "polygon": [[32.779, -117.172], [32.786, -117.154], [32.782, -117.143],
                    [32.781, -117.127], [32.774, -117.109], [32.768, -117.116],
                    [32.767, -117.146], [32.771, -117.166]],
    },
    {
        "id": "hall-access", "label": "Hall access zone", "level": "shelter",
        "instruction": "For the drill, wait at the step-free lobby desk for an update.",
        "polygon": [[32.779, -117.149], [32.785, -117.142], [32.783, -117.132],
                    [32.776, -117.128], [32.772, -117.136], [32.773, -117.146]],
    },
]
FIRE = {
    "id": "riverbend-drill", "label": "Riverbend wildfire drill", "simulated": True,
    "polygon": [[32.789, -117.141], [32.797, -117.136], [32.799, -117.131],
                [32.795, -117.124], [32.789, -117.129], [32.786, -117.136]],
}


async def post(client, path, body):
    response = await client.post(path, json=body)
    response.raise_for_status()
    return response.json()


async def play_call(client):
    # Dashboard calls use the voice intake API. Supply the exercise dialogue
    # directly so the same decision can be replayed without a voice session.
    call = await post(client, "/api/calls", {"mode": "elevenlabs", "scenario_id": "dashboard"})
    path = f"/api/calls/{call['id']}"

    async def transcript(role, text):
        await post(client, path + "/transcript", {"role": role, "text": text})

    await transcript("user", "We're at Riverbend Hall for the drill. Where should we wait for pickup?")
    instruction = await post(client, path + "/resolve", {"location": HALL})
    if instruction["match_status"] != "overlapping_zones":
        raise RuntimeError("The exercise location must match both instruction zones.")
    await asyncio.sleep(4)
    await transcript("agent", "How many people need a ride, and can everyone reach the upper plaza?")
    await asyncio.sleep(6)
    await transcript("user", "Three of us. I need a wheelchair lift. The plaza has stairs, but I can reach the lobby.")
    await post(client, path + "/assessment", {
        "people_count": 3, "wheelchair_users": 1, "transport_needed": True,
        "can_evacuate": False, "mobility_needs": "Wheelchair lift and step-free pickup.",
    })
    await asyncio.sleep(3)
    await transcript("agent", "I've logged the transport request and asked the operator which pickup point applies.")


def run(directory, port):
    facility = {
        "id": "riverbend-hall", "name": HALL, "type": "community_center",
        "latitude": 32.7764, "longitude": -117.1409, "area": "Mission Valley", "simulated": True,
    }
    (directory / "facilities.json").write_text(json.dumps([facility]))
    os.environ.update(
        TEAM_DATA_DIR=str(directory), DEMO_DB_PATH=str(directory / "drill.sqlite3"),
        GEOCODING_ENABLED="0", PYTHON_DOTENV_DISABLED="1", DAYTONA_API_KEY="",
        ELEVENLABS_API_KEY="", ELEVENLABS_AGENT_ID="", ELEVENLABS_OUTREACH_AGENT_ID="",
    )
    from app.main import app

    @asynccontextmanager
    async def lifespan(drill):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://127.0.0.1") as client:
                for zone in ZONES:
                    await post(client, "/api/dashboard/zones", zone)
                await post(client, "/api/dashboard/fires", FIRE)
                drill.state.client = client
                drill.state.started = False
                print(f"Open http://127.0.0.1:{port}/ to start the Riverbend Hall drill.", flush=True)
                yield

    async def enter(request):
        playback = None
        if request.method == "GET" and not request.app.state.started:
            request.app.state.started = True
            playback = BackgroundTask(play_call, request.app.state.client)
        return RedirectResponse("/dashboard/?view=calls", background=playback)

    drill = Starlette(routes=[Route("/", enter), Mount("/", app=app)], lifespan=lifespan)
    uvicorn.run(drill, host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    if not (Path(__file__).resolve().parents[1] / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the dashboard with ./scripts/run-demo.sh --dashboard-drill")
    with TemporaryDirectory(prefix="riverbend-drill-") as folder:
        run(Path(folder), int(os.getenv("PORT", "8017")))
