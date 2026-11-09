"""Explicit mock reception conversation using real ElevenLabs audio and the contact API.
No telephone call is made. Creates a labeled demo report in the chosen local backend.
"""
import argparse
import base64
import json
from pathlib import Path
import time
from uuid import uuid4
import certifi
import httpx
import websocket


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base-url',default='http://127.0.0.1:8002');args=parser.parse_args()
    result={'passed':False,'mock':True,'tools':[],'audio_bytes':0}
    with httpx.Client(base_url=args.base_url,timeout=25) as client:
        def api(path,body=None):
            r=client.get(path) if body is None else client.post(path,json=body)
            r.raise_for_status();return r.json()
        found=[f for f in api('/api/dashboard/snapshot')['facilities'] if f.get('incident_id')=='san-diego-demo' and f.get('simulated') and f.get('type')=='health_clinic']
        if not found: raise RuntimeError('Run an offline San Diego contact search first')
        facility=found[0]
        session=api('/api/contacts/'+facility['id']+'/demo-call',{})
        prefix='/api/contacts/sessions/'+session['id'];result['session_id']=session['id']
        conn=None
        responses=[]
        try:
            auth=api(prefix+'/voice',{})
            conn=websocket.create_connection(auth['signed_url'],timeout=20,sslopt={'ca_certs':certifi.where()});conn.settimeout(.5)
            def send(payload):conn.send(json.dumps(payload))
            send({'type':'conversation_initiation_client_data','dynamic_variables':auth['dynamic_variables']})
            api(prefix+'/connected',{})
            def receive_turn():
                deadline=time.monotonic()+45;initial=len(responses);last=time.monotonic()
                while time.monotonic()<deadline:
                    try:
                        raw=conn.recv()
                        if not raw:raise RuntimeError('Voice session closed')
                        message=json.loads(raw);kind=message.get('type')
                        if kind=='ping':send({'type':'pong','event_id':message['ping_event']['event_id']})
                        elif kind=='audio':result['audio_bytes']+=len(base64.b64decode(message['audio_event']['audio_base_64']));last=time.monotonic()
                        elif kind=='agent_response':
                            text=message['agent_response_event']['agent_response'];responses.append(text);last=time.monotonic()
                            api(prefix+'/transcript',{'id':'agent-'+str(len(responses)),'role':'agent','text':text})
                        elif kind=='client_tool_call':
                            tool=message['client_tool_call'];failed=False
                            try:
                                if tool['tool_name']=='record_contact_report':
                                    saved=api(prefix+'/report',tool['parameters'])
                                    answer={'saved':True,'report_id':saved['id'],'mock':True}
                                elif tool['tool_name']=='get_clinic_context':
                                    answer=api(prefix+'/context')
                                else:raise RuntimeError('Unexpected tool')
                            except httpx.HTTPStatusError as e:failed=True;answer={'saved':False,'error':e.response.json()}
                            result['tools'].append({'name':tool['tool_name'],'success':not failed})
                            send({'type':'client_tool_result','tool_call_id':tool['tool_call_id'],'result':json.dumps(answer),'is_error':failed});last=time.monotonic()
                    except websocket.WebSocketTimeoutException:pass
                    if len(responses)>initial and time.monotonic()-last>1.5:return
                raise TimeoutError('Voice response timed out')
            receive_turn()
            text='Yes, I am reception at '+facility['name']+'. What would you like to know first?'
            api(prefix+'/transcript',{'id':'typed-'+str(uuid4()),'role':'user','text':text})
            send({'type':'user_message','text':text});receive_turn()
            result['intake_opening']=responses[-1]
            text='This is a mock test. Yes, I am reception at '+facility['name']+'. Two people need wheelchair transport from the front entrance at 200 Example Lane in San Diego. They can wait safely, nobody is in immediate danger, and no one else needs help.'
            # Like the browser's typed mode, save the receiver's actual input before sending.
            api(prefix+'/transcript',{'id':'typed-'+str(uuid4()),'role':'user','text':text})
            send({'type':'user_message','text':text});receive_turn()
            overview=api('/api/contacts/overview');report=next((r for r in overview['reports'] if r['session_id']==session['id']),None)
            if not report:
                text='Please save the reported need now, using my exact words: Two people need wheelchair transport from the front entrance at 200 Example Lane in San Diego.'
                api(prefix+'/transcript',{'id':'typed-'+str(uuid4()),'role':'user','text':text});send({'type':'user_message','text':text});receive_turn()
                report=next((r for r in api('/api/contacts/overview')['reports'] if r['session_id']==session['id']),None)
            text='Our clinic is at '+(facility.get('address') or 'the listed address')+'. What are the current exercise instructions for this clinic? Please check the coordinator guidance.'
            api(prefix+'/transcript',{'id':'typed-'+str(uuid4()),'role':'user','text':text})
            send({'type':'user_message','text':text});receive_turn()
            result['context_fetched']=any(t['name']=='get_clinic_context' and t['success'] for t in result['tools'])
            result['report_saved']=bool(report)
            needs=[n for n in api('/api/contacts/needs') if n['session_id']==session['id']]
            result['needs']=needs
            result['passed']=bool(report and report['content']['reception_confirmed'] and any(n['people_count']==2 for n in needs) and result['audio_bytes']>0 and result['context_fetched'])
        finally:
            if conn:conn.close()
            api(prefix+'/end',{'status':'completed' if result['passed'] else 'failed'})
            result['responses']=responses
            path=Path('.runtime/smoke-contacts.json');path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(result,indent=2))
            print(json.dumps({k:v for k,v in result.items() if k not in ('responses','needs')},indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
