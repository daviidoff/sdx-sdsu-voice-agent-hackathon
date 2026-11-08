"""Exercise real ElevenLabs conversation/tools/TTS with synthetic typed input.

This does not test microphone capture, speech recognition, or telephone service.
The local backend obtains the signed URL; credentials and audio are never logged.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
import time

import httpx
import certifi
import websocket


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--turn-timeout", type=float, default=40)
    args = parser.parse_args()
    summary = {"test": "real-elevenlabs-typed-input", "audio_bytes": 0, "agent_responses": [], "tools": [], "passed": False}
    call_id = None
    connection = None
    with httpx.Client(base_url=args.base_url, timeout=20) as client:
        def api(path, payload=None):
            response = client.get(path) if payload is None else client.post(path, json=payload)
            response.raise_for_status()
            return response.json()

        def send(payload):
            connection.send(json.dumps(payload))

        def handle(message):
            kind = message.get("type")
            if kind == "ping":
                send({"type": "pong", "event_id": message["ping_event"]["event_id"]})
            elif kind == "conversation_initiation_metadata":
                metadata = message["conversation_initiation_metadata_event"]
                summary["conversation_id"] = metadata.get("conversation_id")
                summary["output_audio_format"] = metadata.get("agent_output_audio_format")
            elif kind == "audio":
                encoded = message.get("audio_event", {}).get("audio_base_64", "")
                summary["audio_bytes"] += len(base64.b64decode(encoded))
            elif kind == "agent_response":
                data = message["agent_response_event"]
                text = data["agent_response"]
                summary["agent_responses"].append(text)
                segment = str(data.get("response_id") or data.get("event_id") or len(summary["agent_responses"]))
                api(f"/api/calls/{call_id}/transcript", {"role": "agent", "text": text, "segment_id": segment})
                print("Agent: " + text, flush=True)
            elif kind == "agent_response_correction":
                data = message.get("agent_response_correction_event", {})
                segment = str(data.get("response_id") or data.get("event_id"))
                api(f"/api/calls/{call_id}/transcript", {"role": "agent", "text": data.get("corrected_agent_response", ""), "segment_id": segment, "replace": True})
            elif kind == "client_tool_call":
                tool = message["client_tool_call"]
                name, parameters = tool["tool_name"], tool.get("parameters") or {}
                error = False
                try:
                    if name == "confirm_location":
                        result = api(f"/api/calls/{call_id}/resolve", {"location": parameters["location"]})
                    elif name == "update_assessment":
                        call = api(f"/api/calls/{call_id}/assessment", parameters)
                        result = {"assessment": call["assessment"], "instruction": call["instruction"], "simulation": True}
                    elif name == "request_assistance":
                        call = api(f"/api/calls/{call_id}/assessment", {**parameters, "transport_needed": True})
                        result = {"status": "requested", "assessment": call["assessment"], "message": "Background analysis started. Assistance is not dispatched or confirmed.", "simulation": True}
                    else:
                        error, result = True, {"error": "Unsupported client tool"}
                except Exception:
                    error, result = True, {"error": "Local tool failed"}
                summary["tools"].append({"name": name, "success": not error})
                print(f"Tool: {name}; success={not error}", flush=True)
                send({"type": "client_tool_result", "tool_call_id": tool["tool_call_id"], "result": json.dumps(result), "is_error": error})
            elif kind in {"error", "client_error"}:
                raise RuntimeError("Provider returned an error event")
            return kind

        def receive_turn():
            deadline = time.monotonic() + args.turn_timeout
            previous_count = len(summary["agent_responses"])
            last_activity = time.monotonic()
            while time.monotonic() < deadline:
                try:
                    raw = connection.recv()
                    if not raw:
                        raise RuntimeError("Conversation closed before completion")
                    kind = handle(json.loads(raw))
                    if kind in {"agent_response", "audio", "client_tool_call", "agent_response_correction"}:
                        last_activity = time.monotonic()
                except websocket.WebSocketTimeoutException:
                    pass
                if len(summary["agent_responses"]) > previous_count and time.monotonic() - last_activity >= 1.5:
                    return
            raise TimeoutError("Timed out waiting for an agent response")

        try:
            expected_daytona = api("/api/config").get("daytona_configured", False)
            call_id = api("/api/calls", {"mode": "elevenlabs", "scenario_id": "wildfire-north"})["id"]
            summary["call_id"] = call_id
            auth = api(f"/api/voice/session?call_id={call_id}")
            signed_url = auth.get("signed_url")
            if not signed_url:
                raise RuntimeError("Signed voice authorization unavailable")
            connection = websocket.create_connection(signed_url, timeout=20, sslopt={"ca_certs": certifi.where()})
            connection.settimeout(0.5)
            # Keep configured audio mode: typed messages still exercise real TTS.
            send({"type": "conversation_initiation_client_data", "dynamic_variables": {"call_id": call_id, "scenario_id": "wildfire-north"}})
            print("Connected to real ElevenLabs conversation; synthetic inputs only.", flush=True)
            receive_turn()
            utterances = [
                "I am in North Ridge.",
                "Yes, I confirm I am currently in North Ridge.",
                "I cannot evacuate on my own. I have no car and need transport.",
                "There are three people including me. One person uses a wheelchair and needs accessible transport.",
                "Yes, I confirm exactly one wheelchair user and three people total. We need transport. Please record those confirmed counts for the demo responders.",
            ]
            for index, text in enumerate(utterances):
                api(f"/api/calls/{call_id}/transcript", {"role": "user", "text": text, "segment_id": f"smoke-user-{index}"})
                print("Caller: " + text, flush=True)
                send({"type": "user_message", "text": text})
                receive_turn()
            # Wait for the latest facts' background result, without blocking the
            # provider's ping/pong channel, then exercise the return-to-voice path.
            background_result = None
            background_deadline = time.monotonic() + 40
            while time.monotonic() < background_deadline:
                snapshot = api(f"/api/calls/{call_id}")
                latest_job = max((int(item["id"]) for item in snapshot["events"] if item["type"] == "job.started"), default=0)
                completions = [item for item in snapshot["events"] if item["type"] == "job.completed" and int(item["id"]) > latest_job]
                if completions:
                    background_result = completions[-1]["payload"]["result"]
                    break
                if any(item["type"] == "job.failed" and int(item["id"]) > latest_job for item in snapshot["events"]):
                    break
                send({"type": "user_activity"})
                try:
                    raw = connection.recv()
                    if raw:
                        handle(json.loads(raw))
                except websocket.WebSocketTimeoutException:
                    pass
            summary["background_result"] = background_result
            if background_result:
                send({"type": "contextual_update", "text": "Backend background analysis for the latest confirmed caller facts: " + json.dumps(background_result) + ". This is a synthetic proposal, not a dispatch or commitment. Explain it when asked."})
                print("Relayed completed background analysis to the voice agent.", flush=True)
                question = "What did the transport analysis find? Please distinguish a proposal from help that has actually been dispatched."
                api(f"/api/calls/{call_id}/transcript", {"role": "user", "text": question, "segment_id": "smoke-user-background"})
                send({"type": "user_message", "text": question})
                receive_turn()
            snapshot = api(f"/api/calls/{call_id}")
            summary["assessment"] = snapshot["assessment"]
            summary["instruction"] = snapshot["instruction"]
            summary["job_event_types"] = [item["type"] for item in snapshot["events"] if item["type"].startswith("job.")]
            facts = snapshot["assessment"]
            summary["passed"] = bool(
                summary["audio_bytes"] > 0
                and snapshot["instruction"] and snapshot["instruction"].get("zone_id") == "north-ridge"
                and facts.get("can_evacuate") is False
                and facts.get("transport_needed") is True
                and facts.get("people_count") == 3
                and facts.get("wheelchair_users") == 1
                and "wheelchair" in str(facts.get("mobility_needs", "")).lower()
                and all(item["success"] for item in summary["tools"])
                and background_result and background_result.get("status") == "proposal_ready"
                and (not expected_daytona or background_result.get("provider") == "daytona")
            )
        except Exception as exc:
            # Exception messages can contain signed URLs, so emit only the class.
            summary["error_type"] = type(exc).__name__
            print("Smoke test stopped: " + type(exc).__name__, flush=True)
        finally:
            if connection is not None:
                connection.close()
            if call_id:
                try:
                    api(f"/api/calls/{call_id}/end", {})
                except Exception:
                    summary["cleanup"] = "Backend call end failed"
            output = Path(__file__).resolve().parents[1] / ".runtime" / "smoke-elevenlabs.json"
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"passed": summary["passed"], "audio_bytes": summary["audio_bytes"], "agent_response_count": len(summary["agent_responses"]), "tools": summary["tools"], "error_type": summary.get("error_type")}), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
