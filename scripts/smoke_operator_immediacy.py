"""Real-provider operator steering without any caller utterance.

Uses the same operator-attributed SDK user_message transport as the browser.
Generated audio/response timing is evidence of provider delivery, not that a human
heard it. Run only on an isolated test backend; default port 8014.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import httpx
import websocket
from smoke_dashboard import DashboardCall

ROOT = Path(__file__).resolve().parents[1]


class OperatorCall(DashboardCall):
    def __init__(self, client, timeout):
        super().__init__(client, timeout)
        self.interruptions = 0
        self.operator_messages = set()
        self.echoes = []
        self.latency = {}
        self.sent_at = 0
        self.await_interruption = False

    def handle(self, message):
        if message.get('type') == 'interruption':
            self.interruptions += 1
            self.await_interruption = False
            self.latency['interruption_seconds'] = round(time.monotonic()-self.sent_at,3)
        if message.get('type') == 'audio' and self.sent_at and not self.await_interruption:
            self.latency.setdefault('first_audio_seconds',round(time.monotonic()-self.sent_at,3))
        if message.get('type') == 'user_transcript':
            self.echoes.append(message.get('user_transcription_event', {}).get('user_transcript'))
        return super().handle(message)

    def steer(self, text, during_output=False):
        snapshot = self.api(f'/api/calls/{self.call_id}/steering', {'text': text})
        event = next(e for e in reversed(snapshot['events']) if e['type'] == 'steering.queued')
        # Run the production formatter so this test cannot drift into a fake caller prompt.
        formatter = "import {operatorTurnMessage} from './web/src/voice-context.ts'; let s=''; for await(const c of process.stdin)s+=c;const x=JSON.parse(s);console.log(operatorTurnMessage(x.event,x.call));"
        message = subprocess.run(['node', '--input-type=module', '-e', formatter], input=json.dumps({'event':event,'call':snapshot}), text=True, capture_output=True, check=True, cwd=ROOT).stdout.strip()
        self.operator_messages.add(message)
        self.send({'type':'contextual_update','text':'Operator dashboard context: '+json.dumps(event['payload'])})
        sent = time.monotonic()
        self.sent_at = sent
        self.latency = {}
        self.await_interruption = during_output
        self.send({'type':'user_message','text':message})
        self.api(f'/api/calls/{self.call_id}/steering/{event["payload"]["id"]}/ack', {'status':'response_requested'})
        return sent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8014')
    args=parser.parse_args()
    result={'test':'operator-immediate-provider','passed':False,'caller_utterances':0}
    with httpx.Client(base_url=args.base_url,timeout=30) as client:
        call=OperatorCall(client,35)
        try:
            call.start()
            initial=call.api(f'/api/calls/{call.call_id}')['assessment']
            before=len(call.responses);audio=call.audio_bytes
            start=call.steer('TEST ONLY: Tell the caller the operator reference is COBALT and ask if any pets are accompanying them.')
            call.receive_turn()
            idle=' '.join(call.responses[before:])
            result['idle']={'responses':call.responses[before:],'completed_seconds':round(time.monotonic()-start,3),**call.latency,'audio_bytes':call.audio_bytes-audio,'passed':'cobalt' in idle.lower() and 'pet' in idle.lower() and call.audio_bytes>audio}
            call.steer('TEST ONLY: Read the following operator update word for word: This is a coordination exercise. The operator is reviewing the information that was supplied. No transport has been assigned. No rescue commitment has been made. The caller can correct any detail at any time. The operator is still reviewing available contacts. Any specific movement instruction must come from the current published instruction. Please remain available for the next update. The exercise is continuing while the operator checks the current information.')
            # Inject during the first generated audio chunk, not after a quiet turn.
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                try:
                    message=json.loads(call.connection.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                call.handle(message)
                if message.get('type')=='audio':
                    break
            else: raise TimeoutError('No output available for interruption test')
            before=len(call.responses);audio=call.audio_bytes;interruptions=call.interruptions
            start=call.steer('TEST ONLY: Supersede the previous operator message. Immediately tell the caller the new operator reference is MAGNOLIA. Do not continue the previous message or ask intake questions.',during_output=True)
            call.receive_turn()
            said=' '.join(call.responses[before:])
            result['during_output']={'responses':call.responses[before:],'completed_seconds':round(time.monotonic()-start,3),**call.latency,'audio_bytes':call.audio_bytes-audio,'interruption_events':call.interruptions-interruptions,'passed':'magnolia' in said.lower() and call.audio_bytes>audio}
            snapshot=call.api(f'/api/calls/{call.call_id}')
            result.update(call_id=call.call_id,assessment_unchanged=snapshot['assessment']==initial,caller_transcript_rows=sum(e['type']=='transcript' and e['payload'].get('role')=='user' for e in snapshot['events']),tools=call.tools,echoes_are_operator_messages=all(e in call.operator_messages for e in call.echoes))
            result['passed']=result['idle']['passed'] and result['during_output']['passed'] and result['assessment_unchanged'] and result['caller_transcript_rows']==0
        except Exception as exc:
            result['error_type']=type(exc).__name__
            result['error']=str(exc)
        finally:
            call.close()
    output=ROOT/'.runtime'/'smoke-operator-immediacy.json'
    output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
