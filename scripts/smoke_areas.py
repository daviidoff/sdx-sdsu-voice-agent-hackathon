"""Real ElevenLabs typed-input smoke across the three synthetic instruction areas.

Checks real tools and generated audio, not microphone/ASR or telephone service.
Optional --exercise-updates publishes and restores one synthetic instruction and
tests a steering question. Requires a running configured local backend.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import time

import certifi
import httpx
import websocket


class TypedCall:
    def __init__(self, client, timeout):
        self.client, self.timeout = client, timeout
        self.call_id = None
        self.connection = None
        self.audio_bytes = 0
        self.responses = []
        self.tools = []
        self.turn = 0

    def api(self, path, body=None):
        response = self.client.get(path) if body is None else self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def send(self, payload):
        self.connection.send(json.dumps(payload))

    def start(self):
        # No area is supplied at creation: only the conversation establishes it.
        self.call_id = self.api('/api/calls', {'mode': 'elevenlabs', 'scenario_id': 'unknown-location'})['id']
        auth = self.api(f'/api/voice/session?call_id={self.call_id}')
        if not auth.get('signed_url'):
            raise RuntimeError('Signed provider session unavailable')
        self.connection = websocket.create_connection(auth['signed_url'], timeout=20,
                                                      sslopt={'ca_certs': certifi.where()})
        self.connection.settimeout(.5)
        self.send({'type': 'conversation_initiation_client_data',
                   'dynamic_variables': {'call_id': self.call_id, 'scenario_id': 'unknown-location'}})
        self.receive_turn()

    def handle(self, message):
        kind = message.get('type')
        if kind == 'ping':
            self.send({'type': 'pong', 'event_id': message['ping_event']['event_id']})
        elif kind == 'audio':
            self.audio_bytes += len(base64.b64decode(message.get('audio_event', {}).get('audio_base_64', '')))
        elif kind == 'agent_response':
            event = message['agent_response_event']
            text = event['agent_response']
            self.responses.append(text)
            segment = str(event.get('response_id') or event.get('event_id') or len(self.responses))
            self.api(f'/api/calls/{self.call_id}/transcript',
                     {'role': 'agent', 'text': text, 'segment_id': 'area-agent:' + segment})
        elif kind == 'agent_response_correction':
            event = message.get('agent_response_correction_event', {})
            segment = str(event.get('response_id') or event.get('event_id'))
            self.api(f'/api/calls/{self.call_id}/transcript', {'role': 'agent',
                     'text': event.get('corrected_agent_response', ''),
                     'segment_id': 'area-agent:' + segment, 'replace': True})
        elif kind == 'client_tool_call':
            tool = message['client_tool_call']
            name, params = tool['tool_name'], tool.get('parameters') or {}
            failed = False
            try:
                if name == 'confirm_location':
                    result = self.api(f'/api/calls/{self.call_id}/resolve', {'location': params['location']})
                elif name == 'message_operator':
                    result = self.api(f'/api/calls/{self.call_id}/operator-messages', params)
                elif name == 'check_operator_messages':
                    result = self.api(f'/api/calls/{self.call_id}/operator-messages')
                elif name in {'update_assessment', 'request_assistance'}:
                    if name == 'request_assistance':
                        params = {**params, 'transport_needed': True}
                    snapshot = self.api(f'/api/calls/{self.call_id}/assessment', params)
                    result = {'assessment': snapshot['assessment'], 'instruction': snapshot['instruction'],
                              'simulation': True, 'dispatch_status': 'not_dispatched'}
                else:
                    raise ValueError('Unsupported tool')
            except Exception:
                failed, result = True, {'error': 'Local client tool failed'}
            self.tools.append({'name': name, 'success': not failed})
            self.send({'type': 'client_tool_result', 'tool_call_id': tool['tool_call_id'],
                       'result': json.dumps(result), 'is_error': failed})
        elif kind in {'error', 'client_error'}:
            raise RuntimeError('Provider error event')
        return kind

    def receive_turn(self):
        deadline = time.monotonic() + self.timeout
        initial_count, last_activity = len(self.responses), time.monotonic()
        while time.monotonic() < deadline:
            try:
                raw = self.connection.recv()
                if not raw:
                    raise RuntimeError('Provider closed conversation')
                kind = self.handle(json.loads(raw))
                if kind in {'audio', 'agent_response', 'client_tool_call', 'agent_response_correction'}:
                    last_activity = time.monotonic()
            except websocket.WebSocketTimeoutException:
                pass
            if len(self.responses) > initial_count and time.monotonic() - last_activity >= 1.5:
                return
        raise TimeoutError('No completed provider response')

    def utter(self, text):
        self.turn += 1
        self.api(f'/api/calls/{self.call_id}/transcript',
                 {'role': 'user', 'text': text, 'segment_id': f'area-user:{self.turn}'})
        self.send({'type': 'user_message', 'text': text})
        self.receive_turn()

    def close(self):
        try:
            if self.connection:
                self.connection.close()
        finally:
            if self.call_id:
                self.api(f'/api/calls/{self.call_id}/end', {})


def exercise_updates(call, original):
    """Caller restores original action/text in finally, even on uncertain writes."""
    modified = call.api('/api/instructions', {'zone_id': original['zone_id'], 'action': original['action'],
                       'text': original['text'] + ' DEMO update reference: ORCHID.'})
    call.send({'type': 'contextual_update', 'text': 'Current authorized synthetic instruction updated: '
               + json.dumps(modified) + '. Supersedes earlier versions; relay when asked.'})
    snapshot = call.api(f'/api/calls/{call.call_id}/steering',
                        {'text': 'Ask the caller whether any pets are traveling with them.'})
    queued = next(event for event in reversed(snapshot['events']) if event['type'] == 'steering.queued')
    call.send({'type': 'contextual_update', 'text': 'Operator steering, not caller speech: '
               + json.dumps(queued['payload'])})
    call.api(f'/api/calls/{call.call_id}/steering/{queued["payload"].get("id", queued["id"])}/ack',
             {'status': 'context_delivered'})
    before, audio_before = len(call.responses), call.audio_bytes
    call.utter('Please tell me the latest responder instruction, including its demo update reference, and ask the new question the operator supplied.')
    text = ' '.join(call.responses[before:]).lower()
    current = call.api(f'/api/calls/{call.call_id}')
    return {'instruction_version': modified['version'], 'update_reference_spoken': 'orchid' in text,
            'steering_question_spoken': 'pet' in text, 'audio_generated': call.audio_bytes > audio_before,
            'steering_context_acknowledged': any(e['type'] == 'steering.acknowledged' for e in current['events']),
            'passed': 'orchid' in text and 'pet' in text and call.audio_bytes > audio_before}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--turn-timeout', type=float, default=40)
    parser.add_argument('--exercise-updates', action='store_true')
    args = parser.parse_args()
    summary = {'test': 'real-elevenlabs-three-areas', 'passed': False, 'areas': []}
    expected_zones = ('north-ridge', 'river-park', 'lake-view')
    with httpx.Client(base_url=args.base_url, timeout=20) as client:
        try:
            response = client.get('/api/instructions')
            response.raise_for_status()
            instructions = {item['zone_id']: item for item in response.json()['instructions']}
            if any(zone not in instructions for zone in expected_zones):
                raise ValueError('Three-area fixtures are not ready; no provider session started')
            for index, zone in enumerate(expected_zones):
                original = instructions[zone]
                area = {'zone_id': zone, 'expected_action': original['action'], 'passed': False}
                call = TypedCall(client, args.turn_timeout)
                restore_needed = False
                try:
                    call.start()
                    location = original['name']
                    call.utter(f'I am currently in {location}.')
                    call.utter(f'Yes, I confirm {location} is where I am right now.')
                    call.utter('What is the current approved instruction for my confirmed location?')
                    snapshot = call.api(f'/api/calls/{call.call_id}')
                    instruction = snapshot.get('instruction') or {}
                    area.update(call_id=call.call_id, actual_zone=instruction.get('zone_id'),
                                actual_action=instruction.get('action'), audio_bytes=call.audio_bytes,
                                tools=call.tools)
                    area['passed'] = bool(instruction.get('zone_id') == zone
                        and instruction.get('action') == original['action'] and call.audio_bytes > 0
                        and any(t['name'] == 'confirm_location' and t['success'] for t in call.tools)
                        and all(t['success'] for t in call.tools))
                    if args.exercise_updates and index == 0 and area['passed']:
                        restore_needed = True
                        area['midcall_updates'] = exercise_updates(call, original)
                        area['passed'] = area['passed'] and area['midcall_updates']['passed']
                except Exception as exc:
                    area['passed'] = False
                    area['error_type'] = type(exc).__name__
                finally:
                    area['agent_responses'] = call.responses
                    try:
                        call.close()
                    except Exception:
                        area.update(passed=False, cleanup='Backend call end failed')
                    if restore_needed:
                        try:
                            restored = call.api('/api/instructions', {key: original[key] for key in ('zone_id', 'action', 'text')})
                            area['instruction_restored'] = restored['action'] == original['action'] and restored['text'] == original['text']
                            if not area['instruction_restored']:
                                area['passed'] = False
                        except Exception:
                            area.update(passed=False, instruction_restored=False)
                    summary['areas'].append(area)
                print(json.dumps({key: area.get(key) for key in ('zone_id', 'passed', 'actual_action', 'audio_bytes', 'error_type')}), flush=True)
            summary['passed'] = len(summary['areas']) == 3 and all(area['passed'] for area in summary['areas'])
        except Exception as exc:
            summary['error_type'] = type(exc).__name__
    output = Path(__file__).resolve().parents[1] / '.runtime' / 'smoke-areas.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({'passed': summary['passed'], 'area_count': len(summary['areas']),
                      'error_type': summary.get('error_type')}), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
