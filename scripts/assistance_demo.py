"""Run the real browser intake agent against an isolated, single-address exercise."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount


VENUE = "San Diego Central Library"
STREET = "330 Park Boulevard"
ADDRESS = f"{STREET}, San Diego, California"
PLACE = f"{VENUE}, {ADDRESS}"
# The OSM point represents the building, not an entrance or the caller's GPS.
LIBRARY = {
    "id": "san-diego-central-library", "name": VENUE, "type": "library",
    "address": ADDRESS, "latitude": 32.7089055, "longitude": -117.1541411,
    "source_url": "https://www.openstreetmap.org/way/377357193",
    "aliases": [
        f"{name}{street}{city}"
        for name in ("", f"{VENUE}, ", "Central Library, ")
        for street in (STREET, "330 Park Blvd")
        for city in ("", ", San Diego", ", San Diego, CA", ", San Diego, California",
                     ", San Diego, CA 92101", ", San Diego, California 92101")
    ],
}
ZONE = {
    "id": "central-library-exercise", "label": "Central Library exercise area",
    "area": VENUE, "level": "evacuate",
    "instruction": "For this exercise, evacuate the library.",
    "polygon": [[32.7115, -117.1570], [32.7115, -117.1514],
                [32.7068, -117.1514], [32.7068, -117.1570]],
}

# Fictional exercise stations around downtown San Diego. Each has its own
# open call in the operator queue. They never connect to a voice provider.
STATIONS = [
    ("Laurel Street check-in", 32.7361, -117.1838, "I'm alone at the Laurel Street check-in.", 1, None),
    ("Harbor check-in", 32.7207, -117.1725, "There are three of us at the harbor check-in.", 3, None),
    ("Marina meeting point", 32.7075, -117.1694, "Both of us can leave the marina together.", 2, True),
    ("East Village information desk", 32.7143, -117.1480, "I'm alone at the information desk in East Village.", 1, None),
    ("Cortez Hill check-in", 32.7227, -117.1592, "Four of us are waiting here for an update.", 4, None),
    ("Broadway assembly point", 32.7154, -117.1617, "The two of us can leave the Broadway assembly point on our own.", 2, True),
]


async def seed_queue(client):
    async def post(path, body):
        return (await client.post(path, json=body)).raise_for_status().json()

    for name, _, _, text, people, can_leave in STATIONS:
        call = await post("/api/calls", {"mode": "elevenlabs", "scenario_id": "dashboard"})
        path = f"/api/calls/{call['id']}"
        await post(path + "/transcript", {"role": "user", "text": text})
        await post(path + "/resolve", {"location": name})
        facts = {"people_count": people}
        if can_leave is not None:
            facts["can_evacuate"] = can_leave
        await post(path + "/assessment", facts)


def run(directory: Path, port: int):
    stations = [{"id": f"exercise-station-{i}", "name": name, "type": "community",
                 "latitude": lat, "longitude": lng, "simulated": True}
                for i, (name, lat, lng, _, _, _) in enumerate(STATIONS)]
    (directory / "facilities.json").write_text(json.dumps([LIBRARY, *stations]))
    os.environ.update(TEAM_DATA_DIR=str(directory), DEMO_DB_PATH=str(directory / "exercise.sqlite3"),
                      DAYTONA_API_KEY="", CONTACTS_AUTO_RESEARCH="0")
    from app.main import app

    @asynccontextmanager
    async def lifespan(_):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://127.0.0.1") as client:
                response = await client.post("/api/dashboard/zones", json=ZONE)
                response.raise_for_status()
                await seed_queue(client)
            print(f"Caller: http://127.0.0.1:{port}/", flush=True)
            print(f"Operator: http://127.0.0.1:{port}/dashboard/?view=calls", flush=True)
            yield

    exercise = Starlette(routes=[Mount("/", app=app)], lifespan=lifespan)
    uvicorn.run(exercise, host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    with TemporaryDirectory(prefix="central-library-exercise-") as directory:
        run(Path(directory), int(os.environ.get("PORT", "8018")))
