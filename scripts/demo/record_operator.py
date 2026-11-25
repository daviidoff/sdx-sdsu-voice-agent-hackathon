"""Film the operator workflow around a saved, verified ElevenLabs library call."""
import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import wave

import httpx
from playwright.async_api import async_playwright, expect

from scripts.assistance_demo import LIBRARY, STATIONS
from scripts.smoke_location_browser import MICROPHONE, ROOT


@asynccontextmanager
async def exercise():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PORT": str(port), "GEOCODING_ENABLED": "0", "PYTHON_DOTENV_DISABLED": "1",
           "ELEVENLABS_AGENT_ID": "recorded-exercise", "ELEVENLABS_API_KEY": ""}
    server = await asyncio.create_subprocess_exec(sys.executable, "-m", "scripts.assistance_demo",
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15) as api:
            for _ in range(100):
                if server.returncode is not None:
                    raise RuntimeError("The private exercise server stopped during startup.")
                try:
                    if (await api.get("/api/config")).is_success:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.1)
            else:
                raise RuntimeError("The exercise server did not start.")
            yield base, api
    finally:
        if server.returncode is None:
            server.terminate()
            await server.wait()


class RecordedConversation:
    """Play the original media and tool exchange into the ordinary browser SDK."""

    def __init__(self, source):
        self.source = source
        self.call = json.loads((source / "call.json").read_text())
        self.turns = {t["turn"]: t for t in json.loads((source / "turns.json").read_text())}
        self.timing = json.loads((source / "audio-timing.json").read_text())
        self.receipt = next(e["payload"] for e in reversed(self.call["events"])
                            if e["type"] == "operator.requested" and e["payload"].get("source") == "agent")
        self.place = self.call["assessment"]["location"]
        self.ready = asyncio.Event()
        self.results = {}
        self.ws = None
        self.tracks = []

    def connect(self, ws):
        self.ws = ws

        def received(raw):
            if not isinstance(raw, str):
                return
            packet = json.loads(raw)
            if packet.get("type") == "conversation_initiation_client_data":
                self.send("conversation_initiation_metadata", "conversation_initiation_metadata_event", {
                    "conversation_id": "library-replay", "user_input_audio_format": "pcm_16000",
                    "agent_output_audio_format": "pcm_16000",
                })
                self.ready.set()
            elif packet.get("type") == "client_tool_result":
                self.results[packet["tool_call_id"]].set_result(packet)

        ws.on_message(received)

    def send(self, kind, key, value):
        self.ws.send(json.dumps({"type": kind, key: value}))

    async def tool(self, kind, parameters, index):
        key = f"recorded-{index}-{kind}"
        self.results[key] = asyncio.get_running_loop().create_future()
        self.send("client_tool_call", "client_tool_call", {
            "tool_name": kind, "tool_call_id": key, "parameters": parameters})
        response = await asyncio.wait_for(self.results[key], timeout=8)
        if response.get("is_error") or '"error":' in str(response.get("result", "")):
            raise RuntimeError(f"The browser could not complete {kind}.")

    async def play(self, phone, origin):
        await asyncio.wait_for(self.ready.wait(), 15)
        beginning = time.monotonic() + .65
        previous_end = 0
        shortened = 0
        receipt_hold_until = 0
        for index, clip in enumerate(self.timing):
            role, name = Path(clip["file"]).stem.split("-", 1)
            turn = self.turns[name]
            shortened += max(0, clip["start"] - previous_end - 1.15)
            previous_end = clip["start"] + clip["duration"]
            await asyncio.sleep(max(0, max(beginning + clip["start"] - shortened, receipt_hold_until) - time.monotonic()))
            path = self.source / clip["file"]
            self.tracks.append({"file": path.name, "start": time.monotonic()-origin,
                                "duration": clip["duration"], "text": " ".join(turn["heard" if role == "caller" else "replies"])})
            if role == "agent":
                with wave.open(str(path), "rb") as stream:
                    assert stream.getframerate() == 16000 and stream.getnchannels() == 1
                    pcm = stream.readframes(stream.getnframes())
                self.send("agent_response", "agent_response_event", {"event_id": index+1, "agent_response": " ".join(turn["replies"])})
                self.send("audio", "audio_event", {"event_id": index+1, "audio_base_64": base64.b64encode(pcm).decode()})
                continue
            await phone.evaluate("data => window.speakTestAudio(data)", base64.b64encode(path.read_bytes()).decode())
            self.send("user_transcript", "user_transcription_event", {"event_id": index+1, "user_transcript": " ".join(turn["heard"])})
            for kind in turn["tools"]:
                if kind in ("propose_location", "confirm_location"):
                    parameters = {"location": self.place}
                elif kind == "update_assessment" and name == "people":
                    parameters = {"people_count": self.call["assessment"]["people_count"]}
                elif kind == "update_assessment" and name == "assistance":
                    parameters = {"can_evacuate": False}
                elif kind == "message_operator" and name == "assistance":
                    parameters = {"request_id": "library-assistance", "text": self.receipt["text"]}
                else:
                    raise ValueError(f"Unexpected recorded tool {kind} at {name}")
                await self.tool(kind, parameters, index)
                if kind == "message_operator":
                    # Leave the caller's words and the saved assistance pin together for one beat.
                    receipt_hold_until = time.monotonic() + 2.6
        await asyncio.sleep(max(0, self.tracks[-1]["start"] + self.tracks[-1]["duration"] - (time.monotonic()-origin)))


class Pointer:
    def __init__(self, page):
        self.page = page
        self.x, self.y = 135, 620

    async def click(self, target):
        await target.scroll_into_view_if_needed()
        box = await target.bounding_box()
        if not box:
            raise RuntimeError("The operator's control was not visible.")
        x, y = box["x"]+box["width"]/2, box["y"]+box["height"]/2
        await self.page.evaluate("""([x,y,u,v]) => new Promise(done => {
          const t=performance.now(); function move(now) {
            const a=Math.min(1,(now-t)/430), k=a*a*(3-2*a);
            window.point([x+(u-x)*k,y+(v-y)*k,false]); if(a<1)requestAnimationFrame(move); else done();
          } requestAnimationFrame(move);
        })""", [self.x, self.y, x, y])
        await self.page.mouse.move(x, y)
        await self.page.evaluate("p => window.point(p)", [x, y, True])
        await target.click()
        self.x, self.y = x, y


async def capture(source, out):
    conversation = RecordedConversation(source)
    here = Path(__file__).parent
    async with exercise() as (base, api), async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--enable-unsafe-swiftshader"])
        context = await browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
            record_video_dir=out, record_video_size={"width": 1920, "height": 1080})
        await context.add_init_script("if (location.pathname === '/') {" + MICROPHONE + "}")
        await context.route(base + "/recording-desk", lambda r: r.fulfill(path=here / "desktop.html", content_type="text/html"))
        await context.route("**/api/voice/session?*", lambda r: r.fulfill(json={"signed_url": base.replace("http:", "ws:")+"/recorded-intake"}))
        await context.route_web_socket("**/recorded-intake*", conversation.connect)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(base + "/recording-desk", wait_until="domcontentloaded")
        await page.frame_locator('iframe[name="operator"]').get_by_role("navigation", name="Workspace").wait_for()
        await page.frame_locator('iframe[name="caller"]').locator(".iphone").wait_for(state="attached")
        phone = await (await page.locator('iframe[name="caller"]').element_handle()).content_frame()
        dashboard = await (await page.locator('iframe[name="operator"]').element_handle()).content_frame()
        nav = dashboard.get_by_role("navigation", name="Workspace")
        queue = dashboard.get_by_role("region", name="Overview panel")
        details = dashboard.get_by_role("region", name="Call details panel")
        async def tab(name):
            await nav.get_by_role("button", name=name, exact=True).click()

        # Stage ordinary synthetic patrols before the shot, with a medic near East Village.
        await queue.get_by_role("button", name=re.compile("Laurel Street check-in")).click()
        await asyncio.sleep(1)
        await tab("Crews")
        await queue.get_by_role("button", name="Simulate AI crews").click()
        await tab("Calls")
        await queue.get_by_role("button", name=re.compile("Broadway assembly point")).click()
        await asyncio.sleep(.95)
        await details.get_by_role("button", name="Close Call details").click()
        await expect(queue.get_by_text(f"{len(STATIONS)} active · 0 ended")).to_be_visible()
        await expect(phone.get_by_role("button", name="Call 911 test line")).to_be_enabled()
        await page.evaluate("window.framePhone()")
        await dashboard.evaluate("document.fonts.ready")
        await asyncio.sleep(1.8)
        await page.screenshot(path=out/"overview.png")
        # A technical slate before frame one gives a frame-accurate clock for the two voices.
        await page.evaluate("""() => {const m=document.createElement('div');m.id='slate';
          m.style='position:fixed;inset:0;z-index:20;background:#ff00ff';document.body.append(m)}""")
        await asyncio.sleep(.55)
        await page.evaluate("document.querySelector('#slate').remove()")
        origin = time.monotonic()
        marks = {}
        def mark(name):
            marks[name] = round(time.monotonic()-origin, 3)
            print(name, marks[name], flush=True)
        pointer = Pointer(page)
        await asyncio.sleep(1.0)
        async with page.expect_response(lambda r: r.url == base+"/api/calls" and r.request.method == "POST") as created:
            await pointer.click(phone.get_by_role("button", name="Call 911 test line"))
        call_id = (await (await created.value).json())["id"]
        play = asyncio.create_task(conversation.play(phone, origin))
        await expect(phone.locator("#voice-state")).to_have_text("EmergencyOS is speaking")
        mark("pickup")
        await expect(queue.get_by_text(f"{len(STATIONS)+1} active · 0 ended")).to_be_visible()
        await asyncio.sleep(.9)
        await page.screenshot(path=out/"pickup.png")
        row = queue.get_by_role("button", name=re.compile(call_id[:8]))
        await row.evaluate("el => el.scrollIntoView({block:'nearest', behavior:'smooth'})")
        await asyncio.sleep(.7)
        await pointer.click(row)
        await expect(details).to_be_visible()
        mark("open_call")
        await asyncio.sleep(.5)
        await page.evaluate("shot('full')")
        await asyncio.sleep(1.1)
        await pointer.click(queue.get_by_role("button", name="Close Overview"))
        await page.evaluate("shot('call')")
        await expect(details.get_by_text(conversation.place, exact=True).first).to_be_visible(timeout=40000)
        await expect(dashboard.locator(".caller-marker-selected")).to_be_visible()
        # The map itself zooms into the confirmed library building.
        await asyncio.sleep(.8)
        zoom = dashboard.get_by_role("button", name="Zoom in", exact=True)
        await zoom.click()
        await asyncio.sleep(.4)
        await zoom.click()
        await asyncio.sleep(.6)
        await page.screenshot(path=out/"confirmed.png")
        pulse = dashboard.locator(".caller-marker-selected.assistance-ping")
        await expect(pulse).to_be_visible(timeout=30000)
        await expect(pulse.locator(".map-assistance-label")).to_have_text("Needs assistance")
        report = details.get_by_role("log").get_by_text("No, I need assistance.", exact=False).last
        await expect(report).to_be_in_viewport()
        mark("assistance")
        await asyncio.sleep(.3)
        await page.screenshot(path=out/"assistance.png")
        await play
        mark("speech_end")
        saved = (await api.get("/api/calls/" + call_id)).raise_for_status().json()
        facts = saved["assessment"]
        assert saved["status"] == "active" and facts["can_evacuate"] is False
        assert facts.get("transport_needed") is None
        point = facts["location_resolution"]
        assert (point["lat"], point["lng"]) == (LIBRARY["latitude"], LIBRARY["longitude"])
        assert any(e["type"] == "operator.requested" and e["payload"].get("source") == "agent" for e in saved["events"])
        await asyncio.sleep(.25)  # Leave one full frame after the last audio sample.
        assert not errors, errors
        video = page.video
        await context.close()
        raw = await video.path()
        raw.rename(out/"desktop.webm")
        (out/"edit.json").write_text(json.dumps({"source": str(source), "call_id": call_id,
            "background_calls": len(STATIONS), "marks": marks, "tracks": conversation.tracks}, indent=2))
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Successful library-call directory from record_assistance_call")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    output = args.out or Path(tempfile.mkdtemp(prefix="operator-film-", dir=ROOT/".runtime"))
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Choose an empty output directory.")
    print("Recording in", output.resolve(), flush=True)
    asyncio.run(capture(args.source.resolve(), output.resolve()))
