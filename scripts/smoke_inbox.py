"""Real provider inbox tool/reply smoke. Use an isolated backend, never live incidents.

Typed inputs and generated audio; this does not test microphone recognition.
"""
import argparse
import json
from pathlib import Path
import httpx
from smoke_dashboard import DashboardCall


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8013')
    args = parser.parse_args()
    summary = {'test': 'operator-inbox', 'passed': False}
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        call = DashboardCall(client, 45)
        try:
            for id, instruction in [('a', 'TEST ONLY: coordinator reference CEDAR.'), ('b', 'TEST ONLY: coordinator reference ORCHID.')]:
                call.api('/api/dashboard/zones', {'id': 'inbox-test-' + id, 'label': 'Inbox test ' + id,
                    'area': 'Inbox Test Area', 'level': 'warning', 'instruction': instruction})
            call.start()
            call.utter('I am currently in Inbox Test Area. Please check the current instruction.')
            conflict = call.api(f'/api/calls/{call.call_id}/operator-messages')
            summary['conflict_saved'] = any(e['payload']['source'] == 'backend' for e in conflict['messages'])
            call.utter('Please send a separate message to the operator asking whether I can bring my pet rabbit. Use your message tool and confirm only if it was saved.')
            thread = call.api(f'/api/calls/{call.call_id}/operator-messages')
            summary['agent_message_saved'] = any(e['payload']['source'] == 'agent' and 'rabbit' in e['payload']['text'].lower() for e in thread['messages'])
            print(json.dumps({'conflict_saved': summary['conflict_saved'], 'agent_message_saved': summary['agent_message_saved']}), flush=True)
            current = call.api(f'/api/calls/{call.call_id}')
            selected = call.api(f'/api/calls/{call.call_id}/operator-instruction', {'zone_id': 'inbox-test-b', 'revision': current['revision']})
            call.send({'type': 'contextual_update', 'text': 'CURRENT OPERATOR INSTRUCTION UPDATE: ' + json.dumps(selected['instruction'])})
            reply = call.api(f'/api/calls/{call.call_id}/steering', {'text': 'TEST OPERATOR REPLY: Your rabbit question is recorded under reference LANTERN. Pet acceptance is not yet confirmed.'})['events'][-1]
            call.send({'type': 'contextual_update', 'text': 'Operator reply: ' + json.dumps(reply['payload'])})
            call.api(f'/api/calls/{call.call_id}/steering/{reply["id"]}/ack', {})
            before = len(call.responses)
            call.utter('Please check the operator messages. What did the operator reply about my rabbit, and which coordinator reference applies now?')
            response = ' '.join(call.responses[before:]).lower()
            summary['reply_spoken'] = 'lantern' in response
            summary['resolved_instruction_spoken'] = 'orchid' in response
            summary['tools'] = call.tools
            summary['audio_bytes'] = call.audio_bytes
            summary['passed'] = all(summary[k] for k in ('conflict_saved', 'agent_message_saved', 'reply_spoken', 'resolved_instruction_spoken')) and call.audio_bytes > 0 and all(t['success'] for t in call.tools)
        except Exception as exc:
            summary['error_type'] = type(exc).__name__
        finally:
            summary['responses'] = call.responses
            call.close()
    output = Path(__file__).resolve().parents[1] / '.runtime' / 'smoke-inbox.json'
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
