"""Real browser/SDK/ASR/tool/map test with a synthetic microphone and isolated data.

Requires macOS `say`, ffmpeg, and Playwright Chromium. Copies published zones from
--source; never writes to that server. Real ElevenLabs usage is incurred.
"""
import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MICROPHONE = r"""(() => {
  let context, destination;
  navigator.mediaDevices.getUserMedia = async () => {
    if (!context) {
      context = new AudioContext({sampleRate: 48000});
      destination = context.createMediaStreamDestination();
      const oscillator = context.createOscillator();
      const gain = context.createGain(); gain.gain.value = 0;
      oscillator.connect(gain).connect(destination); oscillator.start();
    }
    await context.resume();
    return destination.stream.clone();
  };
  window.speakTestAudio = async (encoded) => {
    await context.resume();
    const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
    const audio = await context.decodeAudioData(bytes.buffer);
    const source = context.createBufferSource(); source.buffer = audio;
    source.connect(destination);
    await new Promise(resolve => { source.onended=resolve; source.start(); });
    source.disconnect();
  };
})();
"""


def test_app():
    """Serve frozen build output so another chat rebuilding cannot change this run."""
    from app.main import app
    from fastapi.staticfiles import StaticFiles
    static = Path(os.environ['LOCATION_TEST_STATIC'])
    for route in app.routes:
        if getattr(route, 'path', None) == '/dashboard':
            route.app = StaticFiles(directory=static/'frontend_dist', html=True)
        elif getattr(route, 'name', None) == 'web':
            route.app = StaticFiles(directory=static/'web_dist', html=True)
    return app


def render_report(report, out):
    escape = html.escape
    rows = []
    for turn in report['turns']:
        label = turn['label']
        resolution = turn['assessment'].get('location_resolution', {})
        rows.append(f'<section><h2>{escape(label)} — {"PASS" if turn["passed"] else "FAIL"}</h2>'
                    f'<p><b>Speech recognition:</b> {escape(" ".join(turn["heard"]))}</p>'
                    f'<p><b>Agent:</b> {escape(" ".join(turn["agent"]))}</p>'
                    f'<p><b>Location:</b> {escape(turn["assessment"].get("location", ""))} · {escape(resolution.get("status", ""))}</p>'
                    f'<p><b>Instruction:</b> {escape(turn["instruction"].get("action", ""))} · '
                    f'<b>Map markers:</b> {len(turn["caller_markers"])} · <b>Turn:</b> {turn["seconds"]}s</p>'
                    f'<img src="{escape(label)}.png" alt="Dashboard after {escape(label)}" /></section>')
    document = ('<!doctype html><html><head><meta charset="utf-8"><title>Location voice test</title>'
                '<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#17202b}'
                'section{border-top:1px solid #ccc;margin-top:32px;padding-top:16px}img{width:100%;border:1px solid #ddd}</style>'
                '</head><body><h1>Location voice test — ' + ('PASS' if report.get('passed') else 'FAIL') + '</h1>'
                '<p>' + escape(report['scope']) + '</p><p>Checks: ' + escape(json.dumps(report['checks'])) + '</p>'
                + (('<p>Error: ' + escape(report['error']) + '</p>') if report.get('error') else '')
                + ''.join(rows) + '</body></html>')
    (out/'report.html').write_text(document)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='http://127.0.0.1:8010')
    parser.add_argument('--port', type=int, default=8026)
    args = parser.parse_args()
    out = ROOT / '.runtime' / ('location-browser-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    report = {'scope': 'Real browser SDK, generated microphone speech, provider ASR/LLM/TTS, real geocoding, persisted tools, dashboard rendering. Physical microphone and telephone service excluded.',
              'turns': [], 'checks': {}, 'page_errors': [], 'audio_bytes': 0}
    report['source_sha256'] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for folder, pattern in [('app','*.py'), ('web/dist','assets/*.js'), ('frontend/dist','assets/*.js')]
                             for path in (ROOT/folder).glob(pattern)}
    shutil.copytree(ROOT/'frontend/dist', out/'frontend_dist')
    shutil.copytree(ROOT/'web/dist', out/'web_dist')
    zones = httpx.get(args.source + '/api/dashboard/snapshot', timeout=10).json()['zones']
    (out / 'zones.json').write_text(json.dumps(zones, indent=2))
    env = {**os.environ, 'DEMO_DB_PATH': str(out / 'test.sqlite'), 'TEAM_DATA_DIR': str(out),
           'GEOCODING_ENABLED': '1', 'DAYTONA_API_KEY': '', 'CONTACTS_AUTO_RESEARCH': '0', 'LOCATION_TEST_STATIC': str(out)}
    log = open(out / 'server.log', 'w')
    server = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-m', 'uvicorn', 'scripts.smoke_location_browser:test_app', '--factory',
        '--host', '127.0.0.1', '--port', str(args.port), '--no-access-log'], cwd=ROOT, env=env, stdout=log, stderr=log)
    base = f'http://127.0.0.1:{args.port}'
    client = httpx.Client(base_url=base, timeout=20)
    def api(path, data=None):
        response = client.get(path) if data is None else client.post(path, json=data)
        response.raise_for_status()
        return response.json()
    try:
        for _ in range(60):
            try:
                api('/api/health'); break
            except httpx.HTTPError:
                time.sleep(.1)
        else:
            raise RuntimeError('Isolated backend did not start')
        for zone in zones:
            api('/api/dashboard/zones', {k:zone[k] for k in ('id','label','area','level','polygon','instruction')})
        utterances = [
            ('airport', 'I am at San Diego International Airport right now. What is the published instruction for my current location? Please answer that before other questions.', 'resolved', 'evacuate'),
            ('misheard-street', 'I need to correct my location. I am now at Pacific Beach Drive at Everest Street, in Pacific Beach, San Diego. Please check the instruction for my new location.', 'needs_confirmation', 'unknown'),
            ('confirmed-intersection', 'Yes, I mean Everts Street. That is spelled E V E R T S. I am currently at Pacific Beach Drive and Everts Street, in Pacific Beach, San Diego. What should I do?', 'resolved', 'shelter'),
            ('recheck', 'Please check the current instruction for that same intersection again. I have not moved.', 'resolved', 'shelter'),
            ('unknown-place', 'Wait, I was mistaken. I am actually at the Hideaway Club in Pacific Beach, San Diego. Please check that new location before giving advice.', 'unresolved', 'unknown'),
            ('airport-return', 'I need to correct that. I am back at San Diego International Airport right now. What is the instruction for the airport?', 'resolved', 'evacuate'),
        ]
        for label, text, _, _ in utterances:
            subprocess.run(['say', '-v', 'Samantha', '-r', '155', '-o', str(out / f'{label}.aiff'), text], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(out / f'{label}.aiff'), '-ac', '1', '-ar', '48000', str(out / f'{label}.wav')], check=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
            context = browser.new_context(viewport={'width': 1600, 'height': 1000})
            phone = context.new_page()
            phone.add_init_script(MICROPHONE)
            events = []
            last_activity = [time.monotonic()]
            def frame(payload):
                try:
                    data = json.loads(payload)
                except (ValueError, TypeError):
                    return
                kind = data.get('type')
                if kind == 'audio':
                    report['audio_bytes'] += len(base64.b64decode(data.get('audio_event', {}).get('audio_base_64', '')))
                elif kind in {'agent_response', 'user_transcript', 'client_tool_call', 'agent_response_correction'}:
                    events.append(data)
                if kind in {'audio','agent_response','user_transcript','client_tool_call','agent_response_correction'}:
                    last_activity[0] = time.monotonic()
            phone.on('websocket', lambda ws: ws.on('framereceived', frame))
            phone.on('pageerror', lambda error: report['page_errors'].append(str(error)))
            dashboard = context.new_page()
            dashboard.on('pageerror', lambda error: report['page_errors'].append(str(error)))
            dashboard.goto(base + '/dashboard/')
            phone.goto(base + '/?source=dashboard')
            phone.get_by_role('button', name='Call 911 test line').click(timeout=15000)
            phone.wait_for_function("document.querySelector('#voice-state')?.textContent==='Listening to you'", timeout=45000)
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                phone.wait_for_timeout(200)
                if any(e.get('type')=='agent_response' for e in events) and time.monotonic()-last_activity[0]>1.5 and phone.locator('#voice-state').inner_text()=='Listening to you':
                    break
            call_id = api('/api/dashboard/snapshot')['calls'][0]['id']
            report['call_id'] = call_id
            for label, text, resolution_status, action in utterances:
                before = len(events)
                started = time.monotonic()
                phone.evaluate('(audio) => window.speakTestAudio(audio)', base64.b64encode((out/f'{label}.wav').read_bytes()).decode())
                deadline = time.monotonic()+50
                complete = False
                while time.monotonic()<deadline:
                    phone.wait_for_timeout(200)
                    current_events = events[before:]
                    if any(e.get('type')=='user_transcript' for e in current_events) and any(e.get('type')=='agent_response' for e in current_events) and time.monotonic()-last_activity[0]>1.5 and phone.locator('#voice-state').inner_text()=='Listening to you':
                        complete = True; break
                call = api('/api/calls/' + call_id)
                resolution = call['assessment'].get('location_resolution', {})
                instruction = call.get('instruction') or {}
                new_events = events[before:]
                spoken = [e['agent_response_event']['agent_response'] for e in new_events if e['type']=='agent_response']
                heard = [e['user_transcription_event']['user_transcript'] for e in new_events if e['type']=='user_transcript']
                dashboard.get_by_role('tab', name=re.compile(r'^Calls')).click()
                dashboard.get_by_role('button').filter(has_text='Voice · '+call_id[:8]).first.click(timeout=5000)
                expected_location = call['assessment'].get('location', '')
                dashboard.wait_for_function('(location) => document.querySelectorAll("aside")[1]?.innerText.includes(location)', arg=expected_location, timeout=5000)
                dashboard.wait_for_timeout(1200)
                markers = dashboard.locator('.caller-marker').evaluate_all('els => els.map(e => e.title)')
                detail = dashboard.locator('aside').last.inner_text()
                turn = {'label': label, 'input': text, 'heard': heard, 'agent': spoken,
                        'tools': [e['client_tool_call']['tool_name'] for e in new_events if e['type']=='client_tool_call'],
                        'seconds': round(time.monotonic()-started,1), 'complete': complete,
                        'assessment': call['assessment'], 'instruction': instruction, 'caller_markers': markers,
                        'detail': detail}
                turn['passed'] = complete and resolution.get('status')==resolution_status and instruction.get('action')==action and len(markers)==int(resolution_status=='resolved')
                if action != 'unknown':
                    turn['passed'] &= ('shelter' if action=='shelter' else 'evacuat') in ' '.join(spoken).lower()
                if label=='misheard-street':
                    turn['passed'] &= 'everts' in ' '.join(spoken).lower()
                report['turns'].append(turn)
                dashboard.screenshot(path=str(out/f'{label}.png'),full_page=True)
                (out/'report.json').write_text(json.dumps(report,indent=2))
                print(json.dumps({k:turn[k] for k in ('label','passed','heard','agent','tools','seconds')}),flush=True)
            phone.get_by_role('button', name='End call', exact=True).click()
            phone.wait_for_function("document.querySelector('#voice-state')?.textContent==='Call ended'",timeout=10000)
            ended = api('/api/calls/'+call_id)
            report['checks']['ended_persisted'] = ended['status']=='ended' and bool(ended.get('ended_at'))
            report['checks']['operator_message_saved'] = any(e['type']=='operator.requested' for e in ended['events'])
            dashboard.reload();dashboard.get_by_role('tab', name=re.compile(r'^Calls')).click();dashboard.wait_for_timeout(1500)
            report['checks']['reload_retains_location'] = ended['assessment']['location'] in dashboard.locator('aside').last.inner_text()
            report['checks']['provider_audio_received'] = report['audio_bytes']>0
            report['checks']['no_browser_errors'] = not report['page_errors']
            report['passed'] = all(t['passed'] for t in report['turns']) and all(report['checks'].values())
            browser.close()
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)[:600]
        report['passed'] = False
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2))
        render_report(report, out)
        client.close();server.terminate()
        try: server.wait(timeout=5)
        except subprocess.TimeoutExpired: server.kill();server.wait()
        log.close()
    print(json.dumps({'passed':report.get('passed'), 'error':report.get('error'), 'report':str(out/'report.json')}),flush=True)
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
