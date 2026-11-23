"""Exercise ambiguous hospitals through browser microphone, ASR, tools and TTS.

Copies the operator's zones into an isolated backend. No typed model input, mocked
geocoder, or mocked provider. Generated speech substitutes for the physical mic.
"""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import time
import wave

import httpx
from dotenv import dotenv_values
from playwright.sync_api import sync_playwright
from scripts.smoke_location_browser import MICROPHONE, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='http://127.0.0.1:8000')
    parser.add_argument('--port', type=int, default=8027)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    out = ROOT/'.runtime'/('hospital-browser-'+time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    report = {'scope':'Production browser SDK with generated microphone speech, live ASR/LLM/TTS, real geocoding and copies of operator-created polygons. Physical microphone hardware excluded.',
              'runs':[], 'page_errors':[], 'passed':False}
    snapshot = httpx.get(args.source+'/api/dashboard/snapshot').json()
    zones = snapshot['zones']
    (out/'zones.json').write_text(json.dumps(zones,indent=2))
    shutil.copytree(ROOT/'web/dist',out/'web_dist')
    shutil.copytree(ROOT/'frontend/dist',out/'frontend_dist')
    # Preserve discovery records, including the hospital's real place reference.
    (out/'facilities.json').write_text(json.dumps(snapshot['facilities']))
    paths = [*list((ROOT/'app').glob('*.py')),ROOT/'scripts/configure_elevenlabs.py',*list((ROOT/'web/src').glob('*.ts'))]
    hashes = lambda: {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report['source_hashes'] = hashes()
    v=dotenv_values(ROOT/'.env')
    def provider_hash():
        r=httpx.get('https://api.elevenlabs.io/v1/convai/agents/'+v['ELEVENLABS_AGENT_ID'],headers={'xi-api-key':v['ELEVENLABS_API_KEY']},timeout=20)
        r.raise_for_status()
        return hashlib.sha256(json.dumps(r.json()['conversation_config'],sort_keys=True).encode()).hexdigest()
    report['provider_hash']=provider_hash()
    utterances = {
        'ambiguous':'I am at Mercy Hospital. What should I do?',
        'clarify':'The one in San Diego.',
        'ambiguous-2':'I am at Mercy Hospital right now. Can you check the instructions for me?',
        'clarify-2':'I mean the San Diego hospital.',
        'ambiguous-3':'Mercy Hospital. That is where I am. What are the instructions?',
        'clarify-3':'San Diego, not Chula Vista.',
        'recheck':'Please check the latest operator instruction for my hospital again. I have not moved.',
        'move':'I need to correct my location. I am at Mercy Hospital, but I am not sure which campus.',
        'chula':'The hospital in Chula Vista.',
    }
    for label,text in utterances.items():
        subprocess.run(['say','-v','Samantha','-r','155','-o',str(out/(label+'.aiff')),text],check=True)
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(out/(label+'.aiff')),'-ac','1','-ar','48000',str(out/(label+'.wav'))],check=True)
    env={**os.environ,'DEMO_DB_PATH':str(out/'test.sqlite'),'TEAM_DATA_DIR':str(out),'GEOCODING_ENABLED':'1','DAYTONA_API_KEY':'','CONTACTS_AUTO_RESEARCH':'0','LOCATION_TEST_STATIC':str(out)}
    log=(out/'server.log').open('w')
    server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','scripts.smoke_location_browser:test_app','--factory','--host','127.0.0.1','--port',str(args.port),'--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=log)
    base=f'http://127.0.0.1:{args.port}'
    client=httpx.Client(base_url=base,timeout=25)
    def api(path,body=None):
        r=client.get(path) if body is None else client.post(path,json=body);r.raise_for_status();return r.json()
    try:
        for _ in range(60):
            try:api('/api/health');break
            except httpx.HTTPError:time.sleep(.1)
        for z in zones:api('/api/dashboard/zones',{k:z[k] for k in ('id','label','area','level','polygon','instruction')})
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required'])
            for repeat in range(args.repeat):
                context=browser.new_context(viewport={'width':1440,'height':1000})
                phone=context.new_page();phone.add_init_script(MICROPHONE)
                events=[];audio=bytearray();last=[time.monotonic()];rate=[16000]
                def frame(raw):
                    try:d=json.loads(raw)
                    except (ValueError,TypeError):return
                    kind=d.get('type')
                    if kind=='conversation_initiation_metadata':
                        fmt=d['conversation_initiation_metadata_event'].get('agent_output_audio_format','pcm_16000')
                        if fmt.startswith('pcm_'):rate[0]=int(fmt.split('_')[1])
                    if kind=='audio':audio.extend(base64.b64decode(d['audio_event']['audio_base_64']))
                    if kind in {'audio','user_transcript','agent_response','agent_response_correction','client_tool_call','agent_response_complete'}:
                        last[0]=time.monotonic()
                        if kind!='audio':events.append(d)
                phone.on('websocket',lambda ws:ws.on('framereceived',frame))
                phone.on('pageerror',lambda e:report['page_errors'].append(str(e)))
                phone.goto(base+'/?source=dashboard')
                phone.get_by_role('button',name='Call 911 test line').click()
                phone.wait_for_function("document.querySelector('#voice-state')?.textContent==='Listening to you'",timeout=45000)
                def settled(before, user=True):
                    deadline=time.monotonic()+50
                    while time.monotonic()<deadline:
                        phone.wait_for_timeout(200)
                        kinds={e['type'] for e in events[before:]}
                        if ('agent_response' in kinds and (not user or 'user_transcript' in kinds)
                            and time.monotonic()-last[0]>1.5 and phone.locator('#voice-state').inner_text()=='Listening to you'):
                            return
                    raise RuntimeError('Voice turn did not finish')
                settled(0,False)
                call_id=api('/api/calls')['calls'][0]['id']
                run={'call_id':call_id,'turns':[]};report['runs'].append(run)
                def speak(label):
                    before=len(events);audio_before=len(audio)
                    phone.evaluate('(audio)=>window.speakTestAudio(audio)',base64.b64encode((out/(label+'.wav')).read_bytes()).decode())
                    settled(before)
                    e=events[before:];call=api('/api/calls/'+call_id)
                    turn={'label':label,'heard':[x['user_transcription_event']['user_transcript'] for x in e if x['type']=='user_transcript'],
                          'agent':[x['agent_response_event']['agent_response'] for x in e if x['type']=='agent_response'],
                          'tools':[x['client_tool_call'] for x in e if x['type']=='client_tool_call'],
                          'audio_bytes':len(audio)-audio_before,'call':call}
                    run['turns'].append(turn)
                    (out/'report.json').write_text(json.dumps(report,indent=2))
                    print(json.dumps({k:turn[k] for k in ('label','heard','agent','audio_bytes')}),flush=True)
                    assert turn['audio_bytes']>0 and turn['heard'], 'Missing actual ASR/TTS'
                    assert not phone.locator('#error').inner_text(), 'Phone displayed a tool or session error'
                    return turn,call,' '.join(turn['agent']).lower()
                t,c,said=speak('ambiguous'+(f'-{repeat+1}' if repeat in (1,2) else ''))
                assert 'san diego' in said and 'chula vista' in said and '?' in said, 'Must ask which hospital before giving guidance'
                assert not c.get('instruction'), 'Must not select a campus before clarification'
                assert (c.get('reported_zone') or {})['resolution']['status']=='ambiguous'
                t,c,said=speak('clarify'+(f'-{repeat+1}' if repeat in (1,2) else ''))
                assert c['instruction']['action']=='evacuate' and 'evacuat' in said, 'Must retrieve and speak operator guidance immediately after city answer'
                assert any(x['tool_name']=='confirm_location' for x in t['tools'])
                assert not any(x['tool_name']=='propose_location' for x in t['tools']), 'No redundant proposal/confirmation loop'
                assert c['instruction']['zone_id'] in {z['id'] for z in zones}
                if repeat==0:
                    z=next(z for z in zones if z['id']==c['instruction']['zone_id'])
                    body={k:z[k] for k in ('id','label','area','level','polygon','instruction')}
                    api('/api/dashboard/zones',{**body,'level':'shelter','instruction':'TEST ONLY: Shelter in place and await the operator update.'})
                    t,c,said=speak('recheck')
                    assert c['instruction']['action']=='shelter' and 'shelter' in said and 'evacuate now' not in said
                    t,c,said=speak('move')
                    assert not c.get('instruction') and 'chula vista' in said and 'san diego' in said
                    t,c,said=speak('chula')
                    assert c['instruction']['action']=='unknown' and c['assessment']['location_resolution']['status']=='resolved'
                    assert 'chula vista' in c['assessment']['location'].lower()
                    assert not c['instruction'].get('zone_id'), 'Do not carry San Diego instruction to Chula Vista'
                    api('/api/dashboard/zones',body)
                dashboard=context.new_page();dashboard.goto(base+'/dashboard/')
                dashboard.get_by_role('navigation',name='Workspace').get_by_role('button',name=re.compile('^calls',re.I)).click()
                dashboard.get_by_role('button').filter(has_text='Voice · '+call_id[:8]).first.click()
                dashboard.get_by_text(c['assessment']['location'],exact=False).first.wait_for()
                dashboard.screenshot(path=str(out/f'dashboard-{repeat+1}.png'),full_page=True)
                phone.get_by_role('button',name='End call',exact=True).click()
                phone.wait_for_function("document.querySelector('#voice-state')?.textContent==='Call ended'",timeout=10000)
                assert api('/api/calls/'+call_id)['status']=='ended'
                with wave.open(str(out/f'agent-{repeat+1}.wav'),'wb') as w:
                    w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate[0]);w.writeframes(audio)
                run['passed']=True
                context.close()
            browser.close()
        assert hashes()==report['source_hashes'], 'Source changed during test'
        assert provider_hash()==report['provider_hash'], 'Provider configuration changed during test'
        assert not report['page_errors']
        report['passed']=True
    except Exception as e:
        report['error']=type(e).__name__+': '+str(e)[:500]
        print(report['error'],flush=True)
        try:phone.screenshot(path=str(out/'failure.png'),full_page=True)
        except Exception:pass
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2))
        client.close();server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait()
        log.close()
    print(json.dumps({'passed':report['passed'],'report':str(out/'report.json')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
