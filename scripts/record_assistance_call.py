"""Record one live Central Library exercise. The caller uses ElevenLabs TTS.

Start ./scripts/run-demo.sh --assistance-call first. This records the configured
intake agent, its real client tool calls and the dashboard polling the same call.
Requires ffmpeg, ffprobe, Playwright Chromium, and a key with Agents and TTS access.
"""
import argparse
import asyncio
import base64
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import wave

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright, expect

from scripts.assistance_demo import LIBRARY, ZONE
from scripts.smoke_location_browser import MICROPHONE, ROOT

# Baxter is a dry, conversational Australian male voice. The intake agent keeps
# its own provider-configured voice; nothing here changes the agent's settings.
CALLER_VOICE = "jSuBIjxMKhqIfb0wCK1F"
LINES = {
    "address": "I'm at the San Diego Central Library, three thirty Park Boulevard in San Diego, California.",
    "confirm": "Yes, that's where I am.",
    "assistance": "No, I need assistance. I can't leave on my own.",
    "people": "It's just me.",
}


def caller_audio(provider, out, voice):
    for name, text in LINES.items():
        response = provider.post(f"/v1/text-to-speech/{voice}", params={"output_format": "mp3_44100_128"},
                                 json={"text": text, "model_id": "eleven_multilingual_v2"})
        response.raise_for_status()
        if not response.headers.get("content-type", "").startswith("audio/"):
            raise RuntimeError("ElevenLabs returned no caller audio.")
        (out / f"caller-{name}.mp3").write_bytes(response.content)


def seconds(path):
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], text=True))


def export_movie(screen, tracks, screen_end, output):
    screen_duration = seconds(screen)
    screen_start = screen_end - screen_duration
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(screen)]
    filters = []
    for index, (started, audio) in enumerate(tracks, 1):
        cmd.extend(["-i", str(audio)])
        delay = max(0, round(1000 * (started - screen_start)))
        filters.append(f"[{index}:a]loudnorm=I=-18:TP=-2:LRA=9,aresample=48000,adelay={delay}:all=1[a{index}]")
    inputs = "".join(f"[a{i}]" for i in range(1, len(tracks) + 1))
    filters.append(f"{inputs}amix=inputs={len(tracks)}:normalize=0,apad[mix]")
    start = max(0, tracks[0][0] - screen_start - 0.25)
    cmd.extend(["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]",
                "-ss", f"{start:.3f}", "-t", f"{screen_duration-start:.3f}",
                "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "128k", "-movflags", "+faststart", str(output)])
    subprocess.run(cmd, check=True)
    timings = [{"file": clip.name, "start": round(at - screen_start - start, 3),
                "duration": seconds(clip)} for at, clip in tracks]
    output.with_name("audio-timing.json").write_text(json.dumps(timings, indent=2))


async def record(base, out, api):
    tracks, turns, page_errors = [], [], []
    pending = {}
    sample_rate = 16000
    call_id = None

    def packet(raw):
        nonlocal sample_rate
        if not isinstance(raw, str):
            return
        data = json.loads(raw)
        kind = data.get("type")
        if kind == "conversation_initiation_metadata":
            encoding = data["conversation_initiation_metadata_event"]["agent_output_audio_format"]
            pending["encoding"] = encoding
            if encoding.startswith("pcm_"):
                sample_rate = int(encoding.removeprefix("pcm_"))
        elif kind == "audio":
            pending.setdefault("first_audio", time.monotonic())
            pending["audio"].extend(base64.b64decode(data["audio_event"]["audio_base_64"]))
            pending["last_packet"] = time.monotonic()
        elif kind == "user_transcript":
            pending["heard"].append(data["user_transcription_event"]["user_transcript"])
        elif kind == "client_tool_call":
            pending["tools"].append(data["client_tool_call"]["tool_name"])
        elif kind == "agent_response":
            pending["replies"].append(data["agent_response_event"]["agent_response"])
        elif kind == "agent_response_correction":
            page_errors.append("The agent was interrupted. Review the corrected response before export.")

    async with AsyncExitStack() as resources:
        p = await resources.enter_async_context(async_playwright())
        browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--enable-unsafe-swiftshader"])
        dashboard_context = await browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=2,
            record_video_dir=out, record_video_size={"width": 1280, "height": 720})
        dashboard = await dashboard_context.new_page()
        phone = await browser.new_page()
        for page in [phone, dashboard]:
            page.on("pageerror", lambda error: page_errors.append(str(error)))
        phone.on("websocket", lambda ws: ws.on("framereceived", packet))
        await phone.add_init_script(MICROPHONE)
        await dashboard.goto(base + "/dashboard/?view=calls")
        await phone.goto(base + "/")
        nav = dashboard.get_by_role("region", name="Overview panel")
        await expect(nav).to_be_visible()
        await dashboard.evaluate("document.fonts.ready")
        async def turn(name):
            nonlocal call_id
            pending.clear()
            pending.update(audio=bytearray(), heard=[], tools=[], replies=[], last_packet=0)
            if name == "greeting":
                async with phone.expect_response(lambda r: r.url == base + "/api/calls" and r.request.method == "POST") as created:
                    await phone.get_by_role("button", name="Call 911 test line").click()
                call_id = (await (await created.value).json())["id"]
                resources.callback(api.post, f"/api/calls/{call_id}/end", json={})
                await nav.get_by_role("button", name=re.compile(call_id[:8])).click()
                await nav.get_by_role("button", name="Close Overview").click()
            else:
                audio = out / f"caller-{name}.mp3"
                encoded = base64.b64encode(audio.read_bytes()).decode()
                tracks.append((time.monotonic(), audio))
                await phone.evaluate("(encoded) => window.speakTestAudio(encoded)", encoded)
            deadline = time.monotonic() + 55
            while time.monotonic() < deadline:
                await asyncio.sleep(0.12)
                error = await phone.locator("#error").inner_text()
                if error:
                    raise RuntimeError(error)
                listening = await phone.locator("#voice-state").inner_text() == "Listening to you"
                if (listening and pending["replies"] and pending["audio"] and
                    (name == "greeting" or pending["heard"]) and time.monotonic() - pending["last_packet"] > 0.7):
                    break
            else:
                raise RuntimeError(f"The configured agent did not finish the {name} turn.")
            if name == "greeting" and not pending.get("encoding", "").startswith("pcm_"):
                raise RuntimeError("This recorder requires PCM audio output from the configured agent.")
            source = out / f"agent-{name}.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
                wav.writeframes(pending["audio"])
            tracks.append((pending["first_audio"], source))
            turns.append({"turn": name, **{key: list(pending[key]) for key in ("heard", "tools", "replies")}})
            (out / "turns.json").write_text(json.dumps(turns, indent=2))
            return turns[-1]

        await turn("greeting")
        path = "/api/calls/" + call_id
        marker = dashboard.locator(".caller-marker-selected")
        label = marker.locator(".map-assistance-label")
        proposed = await turn("address")
        call = api.get(path).json()
        assert "propose_location" in proposed["tools"] and not call.get("instruction")
        assert call["reported_zone"]["resolution"]["status"] == "resolved"
        heard_address = " ".join(proposed["heard"]).lower()
        assert "park" in heard_address and "san diego" in heard_address, "The caller's specific address was not recognized."
        readback = " ".join(proposed["replies"]).lower()
        assert "?" in readback and ("library" in readback or "park" in readback), "The agent did not ask the caller to confirm the place."
        await expect(marker).to_have_count(0)
        confirmed = await turn("confirm")
        call = api.get(path).json()
        assert "confirm_location" in confirmed["tools"] and call["instruction"]["zone_id"] == ZONE["id"]
        point = call["assessment"]["location_resolution"]
        assert (point["lat"], point["lng"]) == (LIBRARY["latitude"], LIBRARY["longitude"])
        reply = " ".join(confirmed["replies"])
        assert "evacuat" in reply.lower(), "Agent must relay the exercise instruction after confirmation."
        await expect(marker).to_be_visible()
        await expect(label).to_have_count(0)
        await dashboard.wait_for_timeout(850)
        await dashboard.get_by_role("button", name="Zoom in", exact=True).click()
        await dashboard.wait_for_timeout(450)
        await dashboard.get_by_role("button", name="Zoom in", exact=True).click()
        await dashboard.wait_for_timeout(450)
        await dashboard.mouse.move(5, 45)
        await dashboard.screenshot(path=out / "confirmed.png")
        if re.search(r"how many|anyone with you|are you alone", reply, re.I):
            reply = " ".join((await turn("people"))["replies"])
        questions = re.findall(r"[^.!?]*\?", reply.lower())
        question = questions[-1] if questions else ""
        if not (re.search(r"\b(can you|are you able|will you be able|could you)\b", question)
                and re.search(r"\b(leave|evacuate|get out|make it out|way out)\b", question)
                and not re.search(r"\b(transport|how many|people count)\b", question)):
            raise RuntimeError(f"The agent asked a different question. Review its actual reply: {reply}")

        async def capture_ping():
            await expect(dashboard.locator(".caller-marker-selected.assistance-ping")).to_be_visible(timeout=45000)
            await expect(label).to_have_text("Needs assistance")
            await dashboard.wait_for_timeout(250)
            await dashboard.screenshot(path=out / "assistance.png")

        before_answer = {event["id"] for event in api.get(path).json()["events"]}
        answered, _ = await asyncio.gather(turn("assistance"), capture_ping())
        call = api.get(path).json()
        assert any("assistance" in text.lower() for text in answered["heard"])
        assert call["assessment"].get("can_evacuate") is False
        assert call["assessment"].get("transport_needed") is None, "A generic help request must leave transport unknown."
        assert {"update_assessment", "message_operator"}.issubset(answered["tools"])
        assert any(event["id"] not in before_answer and event["type"] == "operator.requested"
                   and event["payload"].get("source") == "agent" and event["payload"].get("status") == "received"
                   and re.search(r"assistan|help|cannot leave|unable to", event["payload"]["text"], re.I)
                   for event in call["events"]), "The assistance request must reach the operator during this turn."
        await expect(label).to_be_visible()
        await dashboard.wait_for_timeout(1400)
        (out / "call.json").write_text(json.dumps(call, indent=2))
        screen_end = time.monotonic()
        video = dashboard.video
        await dashboard_context.close()
        screen = await video.path()
        await phone.get_by_role("button", name="End call", exact=True).click()
        await browser.close()
    if page_errors:
        raise RuntimeError(str(page_errors))
    export_movie(screen, tracks, screen_end, out / "assistance-call.mp4")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8018)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    key, agent = os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_AGENT_ID")
    if not key or not agent:
        raise SystemExit("Set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID in the project .env.")
    base = f"http://127.0.0.1:{args.port}"
    with httpx.Client(base_url=base, timeout=12) as api, httpx.Client(
        base_url="https://api.elevenlabs.io", headers={"xi-api-key": key}, timeout=30
    ) as provider:
        snapshot = api.get("/api/dashboard/snapshot").raise_for_status().json()
        if [z["id"] for z in snapshot["zones"]] != [ZONE["id"]]:
            raise SystemExit("Start the isolated --assistance-call exercise first.")
        config = provider.get("/v1/convai/agents/" + agent)
        if not config.is_success:
            raise SystemExit(f"ElevenLabs could not authorize the configured intake agent (HTTP {config.status_code}).")
        agent_voice = config.json()["conversation_config"]["tts"]["voice_id"]
        # If the agent itself uses Baxter (or its legacy ID), choose Eldrin,
        # a different male voice, for the caller.
        voice = "6WwXjDDEMyNmFG95zycZ" if agent_voice in {CALLER_VOICE, "IKne3meq5aSn9XLyUdCD"} else CALLER_VOICE
        (ROOT / ".runtime").mkdir(exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix="library-call-", dir=ROOT / ".runtime"))
        print(f"Recording files: {out}", flush=True)
        (out / "voices.json").write_text(json.dumps({"caller_voice_id": voice, "agent_voice_id": agent_voice}, indent=2))
        caller_audio(provider, out, voice)
        asyncio.run(record(base, out, api))
        print(f"Verified recording: {out / 'assistance-call.mp4'}")


if __name__ == "__main__":
    main()
