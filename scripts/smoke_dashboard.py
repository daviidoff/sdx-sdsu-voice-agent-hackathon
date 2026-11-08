"""Real ElevenLabs tool round-trip through the dashboard API, using labeled test inputs.
Run after publishing an instruction for 'Integration Test Area' on the test dashboard.
Does not test microphone capture or telephone service.
"""
import argparse
import json
from pathlib import Path
import certifi
import httpx
import websocket
from smoke_areas import TypedCall


class DashboardCall(TypedCall):
    def start(self):
        self.call_id = self.api('/api/calls', {'mode': 'elevenlabs', 'scenario_id': 'dashboard'})['id']
        auth = self.api(f'/api/voice/session?call_id={self.call_id}')
        self.connection = websocket.create_connection(auth['signed_url'], timeout=20, sslopt={'ca_certs': certifi.where()})
        self.connection.settimeout(.5)
        self.send({'type': 'conversation_initiation_client_data', 'dynamic_variables': {'call_id': self.call_id}})
        self.receive_turn()
        self.send({'type': 'contextual_update', 'text': 'Shared dashboard context; preserve test labels: ' + json.dumps(self.api('/api/dashboard/context'))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8010')
    args = parser.parse_args()
    summary = {'test': 'dashboard-real-elevenlabs', 'passed': False}
    with httpx.Client(base_url=args.base_url, timeout=20) as client:
        call = DashboardCall(client, 45)
        try:
            zones = call.api('/api/dashboard/context')['zones']
            if not any(z['area'] == 'Integration Test Area' for z in zones):
                raise RuntimeError('Publish the labeled test instruction first')
            call.start()
            print('Real ElevenLabs conversation connected.', flush=True)
            for text in [
                'This is a test. I am currently in Integration Test Area.',
                'Yes, I confirm Integration Test Area is my current location. Please check the current instruction using your location tool.',
                'We are four people. We can evacuate on our own. Nobody has mobility needs, zero wheelchair users, and we do not need transport. Please save these confirmed facts.',
            ]:
                call.utter(text)
                print(json.dumps({'tools': call.tools, 'responses': len(call.responses)}), flush=True)
            snapshot = call.api('/api/dashboard/snapshot')
            stored = next(c for c in snapshot['calls'] if c['id'] == call.call_id)
            summary.update(call_id=call.call_id, tools=call.tools, assessment=stored['assessment'], instruction=stored['instruction'],
                           transcript_events=sum(e['type'] == 'transcript' for e in stored['events']), audio_bytes=call.audio_bytes)
            summary['passed'] = bool(stored['assessment'].get('people_count') == 4 and stored['instruction'].get('source') == 'dashboard'
                and 'ORCHID' in stored['instruction'].get('text', '') and call.audio_bytes > 0 and any(t['name'] == 'update_assessment' and t['success'] for t in call.tools))
            # A dashboard-origin operator message goes through the same persisted queue used by the browser.
            queued = call.api(f'/api/calls/{call.call_id}/steering', {'text': 'Ask whether any pets are accompanying the caller.'})['events'][-1]
            call.send({'type': 'contextual_update', 'text': 'Operator steering: '+json.dumps(queued['payload'])})
            call.api(f'/api/calls/{call.call_id}/steering/{queued["id"]}/ack', {'status': 'context_delivered'})
            before = len(call.responses)
            call.utter('Please ask me the latest question the operator sent, and repeat the coordinator reference from the dashboard.')
            said = ' '.join(call.responses[before:]).lower()
            summary['operator_question_spoken'] = 'pet' in said
            summary['dashboard_reference_spoken'] = 'orchid' in said
            summary['passed'] = summary['passed'] and summary['operator_question_spoken'] and summary['dashboard_reference_spoken']
        except Exception as error:
            summary['error_type'] = type(error).__name__
        finally:
            summary['agent_responses'] = call.responses
            call.close()
    output = Path(__file__).resolve().parents[1] / '.runtime' / 'smoke-dashboard.json'
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ('agent_responses', 'instruction')}), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
