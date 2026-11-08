"""Self-contained, escaped HTML transcripts plus machine-readable evidence."""
from collections import Counter
from html import escape
import json
from pathlib import Path


def write_report(directory, report):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    report['counts'] = dict(Counter(c['status'] for c in report['cases']))
    temporary=directory/'results.json.tmp'
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    temporary.replace(directory/'results.json')
    cards = []
    for c in report['cases']:
        chat = []
        for step in c.get('steps', []):
            if step.get('say'):
                chat.append('<p class="caller"><b>Caller</b> '+escape(step['say'])+'</p>')
            for response in step.get('responses', []):
                chat.append('<p class="agent"><b>Agent</b> '+escape(response)+'</p>')
            if step.get('action'):
                chat.append('<p class="event">Injected event: '+escape(step['action'])+'</p>')
            for check in step.get('checks', []):
                actual=check.get('actual')
                chat.append('<p class="check '+('good' if check['passed'] else 'bad')+'">'+('✓ ' if check['passed'] else '✗ ')+escape(check['name'])+(' '+escape(str(actual)) if actual is not None and actual!=[] else '')+'</p>')
            if step.get('tools'):
                chat.append('<details><summary>Tool arguments and results</summary><pre>'+escape(json.dumps(step['tools'], indent=2))+'</pre></details>')
            if step.get('screenshot'):
                chat.append('<a href="'+escape(step['screenshot'],quote=True)+'">Dashboard screenshot</a>')
        failures = [x for x in c.get('checks',[]) if not x['passed']]
        cards.append('<details class="case" data-status="'+escape(c['status'])+'"><summary><strong>'+escape(c['key'])+' · '+escape(c['title'])+'</strong> <span>'+escape(c['status'])+'</span></summary>'
                     +'<p class="bad">'+escape(c.get('error',''))+'</p>'
                     +'<p>'+escape('Capability gaps: '+'; '.join(c.get('gaps',[])))+'</p>'
                     +'<p><b>Human review:</b> '+escape(c.get('review',''))+'</p>'
                     +'<p>'+escape('Failed checks: '+', '.join(x['name'] for x in failures))+'</p>'
                     +''.join(chat)+'<details><summary>Final stored state / dashboard snapshot</summary><pre>'+escape(json.dumps(c.get('final',{}), indent=2))+'</pre></details></details>')
    text = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Disaster agent evaluation</title><style>
body{font:15px/1.55 system-ui;background:#f4f6f8;color:#17212b;max-width:1100px;margin:40px auto;padding:0 24px}h1{font-size:28px}summary{cursor:pointer}summary span{float:right;font-weight:700}.case{background:white;border:1px solid #ccd4dd;border-radius:10px;padding:18px;margin:14px 0}p{white-space:pre-wrap}.caller,.agent{padding:12px 16px;border-radius:8px}.caller{background:#e8efff;margin-right:12%}.agent{background:#e5f3ec;margin-left:6%}b{margin-right:10px}.event,.check{font-size:13px}.bad{color:#a51425}.good{color:#166044}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f4f6f8;padding:14px;max-height:500px;overflow:auto}input,select{font:inherit;padding:10px;border:1px solid #ccd4dd;border-radius:6px}input{width:60%}
</style><h1>Disaster agent — text evaluation</h1>
<p>No microphone, transcription, speech synthesis, real dispatch, or live geocoding. The deployed agent is exercised in text-only mode. Synthetic backend fixtures are isolated.</p>
<p><b>Checks passed is not a full scenario pass.</b> Read the human rubric and capability gaps. Failed = observed assertion failure; blocked = missing capability/configuration; review = automated checks passed, semantic review remains.</p>'''
    text += '<p>'+escape(json.dumps(report['counts']))+'</p><details><summary>Run configuration and limitations</summary><pre>'+escape(json.dumps(report.get('metadata',{}),indent=2))+'</pre></details>'
    metadata=report.get('metadata',{})
    configurations=metadata.get('shards',[metadata])
    if any(m.get('agent_configuration_changed_during_run') or m.get('source_files_changed_during_run') for m in configurations):
        text+='<p class="bad"><b>Configuration drift detected.</b> The deployed agent or source files changed while these conversations ran. These are exploratory observations, not a stable regression baseline. Inspect the recorded start/end hashes before comparing scores.</p>'
    text += '<input id="search" placeholder="Search cases, responses, failures"><select id="status"><option value="">All results</option><option>failed</option><option>blocked</option><option>review</option><option>not_run</option></select>'
    text += ''.join(cards)+'''<script>
function filter(){const q=document.querySelector('#search').value.toLowerCase(),s=document.querySelector('#status').value;document.querySelectorAll('.case').forEach(e=>e.hidden=!(e.textContent.toLowerCase().includes(q)&&(!s||e.dataset.status===s)))}document.querySelector('#search').addEventListener('input',filter);document.querySelector('#status').addEventListener('change',filter);
</script></html>'''
    temporary=directory/'report.html.tmp'
    temporary.write_text(text)
    temporary.replace(directory/'report.html')
