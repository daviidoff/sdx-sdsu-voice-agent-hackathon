"""Exercise interruption/correction/recheck/resume with the real configured voice model.

Uses labeled operator instructions on an isolated backend (default port 8012).
Typed input and generated audio test the conversation policy, not microphone ASR.
"""
import argparse
import json
from pathlib import Path
import httpx
from smoke_dashboard import DashboardCall


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8012')
    args = parser.parse_args()
    summary = {'test': 'voice-correction-recheck-resume', 'passed': False, 'turns': []}
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        call = DashboardCall(client, 45)
        def api(path, payload=None):
            return call.api(path, payload)
        def say(text):
            before = len(call.responses)
            before_tools = len(call.tools)
            call.utter(text)
            turn = {'caller': text, 'agent': call.responses[before:], 'tools': call.tools[before_tools:]}
            summary['turns'].append(turn)
            print(json.dumps(turn), flush=True)
            return ' '.join(turn['agent']).lower(), turn['tools']
        try:
            for suffix, marker in [('North', 'CEDAR'), ('South', 'ORCHID')]:
                api('/api/dashboard/zones', {'id': 'flow-test-'+suffix.lower(), 'label': 'Voice policy test '+suffix,
                    'area': 'Voice Test '+suffix, 'level': 'warning', 'polygon': [],
                    'instruction': f'TEST ONLY: Current coordinator reference is {marker}. No transport has been assigned.'})
            call.start()
            say('This is a test. I am currently at Voice Test North. There are two people including me and we need transport assistance.')
            # Pause the pending intake question and supply a current-location correction.
            correction, correction_tools = say('Wait, stop the questions. I need to correct my location: I am at Voice Test South right now. What instruction applies here?')
            corrected = api(f'/api/calls/{call.call_id}')
            summary['correction_before_intake'] = ('orchid' in correction and 'wheelchair' not in correction and 'mobility' not in correction
                and any(t['name']=='confirm_location' and t['success'] for t in correction_tools)
                and corrected['assessment']['location'] == 'Voice Test South')
            # Publish a new instruction. A recheck must refresh even if location did not change.
            updated = api('/api/dashboard/zones', {'id': 'flow-test-south', 'label': 'Voice policy test South',
                'area': 'Voice Test South', 'level': 'warning', 'polygon': [],
                'instruction': 'TEST ONLY: The new coordinator reference is MAPLE. No transport has been assigned.'})
            call.send({'type':'contextual_update', 'text':'CURRENT OPERATOR INSTRUCTION UPDATE. Prioritize the caller concern over the pending intake question: '+json.dumps(updated)})
            recheck, recheck_tools = say('Are you sure that is the latest instruction for my current location? Please check again before asking anything else.')
            summary['fresh_recheck'] = 'maple' in recheck and any(t['name']=='confirm_location' and t['success'] for t in recheck_tools)
            pause, _ = say('Wait a moment. Please pause the questions while I talk to the other person.')
            summary['pause_respected'] = '?' not in pause and not any(word in pause for word in ('wheelchair', 'mobility', 'how many'))
            resumed, _ = say('Okay, I am ready to continue. Nobody has mobility limitations and there are zero wheelchair users. Please record that.')
            snapshot = api(f'/api/calls/{call.call_id}')
            summary.update(call_id=call.call_id, assessment=snapshot['assessment'], audio_bytes=call.audio_bytes,
                           resumed_facts_saved=snapshot['assessment'].get('wheelchair_users')==0)
            summary['passed'] = all(summary[k] for k in ('correction_before_intake', 'fresh_recheck', 'pause_respected', 'resumed_facts_saved')) and call.audio_bytes > 0
        except Exception as exc:
            summary['error_type'] = type(exc).__name__
        finally:
            call.close()
    output = Path(__file__).resolve().parents[1]/'.runtime'/'smoke-voice-flexibility.json'
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='turns'}),flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
