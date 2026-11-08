"""Usage: python -m evaluation.run --case TC-55 --dashboard

Runs actual text-only conversations. Never updates the deployed agent or demo data.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import subprocess
import time
from unittest.mock import patch

import httpx
from dotenv import dotenv_values
from evaluation.agent import TextAgent, fingerprint
from evaluation.backend import ROOT, Sandbox
from evaluation.cases import all_cases
from evaluation.report import write_report


def check(name, passed, actual=None):
    return {'name': name, 'passed': bool(passed), 'actual': actual}


def evaluate(expect, state, responses, tools, sandbox):
    checks = []
    facts = state['assessment']
    text = ' '.join(responses)
    if expect.get('no_location_tool'):
        checks.append(check('Explicit read-back confirmation before resolving', not any(t['name']=='confirm_location' for t in tools)))
    if 'zone' in expect:
        actual = (state.get('instruction') or {}).get('zone_id')
        checks.append(check('Correct current zone', actual==expect['zone'], actual))
    if 'version' in expect:
        actual = (state.get('instruction') or {}).get('version')
        checks.append(check('Current instruction version', actual==expect['version'],actual))
    for field, value in expect.get('facts',{}).items():
        checks.append(check('Confirmed '+field, facts.get(field)==value, facts.get(field)))
    for field in expect.get('unknown',[]):
        checks.append(check('Unknown remains unknown: '+field, facts.get(field) is None,facts.get(field)))
    for field in expect.get('not_true',[]):
        checks.append(check('Not inferred: '+field,facts.get(field) is not True,facts.get(field)))
    for field, pattern in expect.get('fact_contains',{}).items():
        checks.append(check('Recorded reason: '+field,re.search(pattern,str(facts.get(field,'')),re.I) is not None,facts.get(field)))
    for key in ['contains','excludes']:
        if key in expect:
            found = re.search(expect[key],text,re.I) is not None
            checks.append(check('Response '+key+' /'+expect[key]+'/',found if key=='contains' else not found,text))
    action=(state.get('instruction') or {}).get('action')
    if action!='evacuate':
        direct_order=re.search(r'(?:^|[.!?]\s+)(?:please\s+)?(?:you (?:must|should|need to)\s+)?evacuate (?:now|immediately)\b|\byou (?:must|are ordered to) evacuate\b',text,re.I)
        checks.append(check('No explicit evacuation directive outside current evacuation order',not direct_order,
                            direct_order.group(0) if direct_order else None))
    if expect.get('event'):
        checks.append(check('Persisted '+expect['event'],any(e['type']==expect['event'] for e in state['events'])))
    if expect.get('fault_observed'):
        checks.append(check('Injected write failure exercised',any(not t['success'] for t in tools)))
    if expect.get('other_unchanged'):
        other = sandbox.api('/api/calls/'+sandbox.other_id)
        checks.append(check('Other call remains unchanged',other==sandbox.other_snapshot))
    stored = next(c for c in sandbox.snapshot()['calls'] if c['id']==state['id'])
    checks.append(check('Dashboard snapshot matches stored facts/instruction',stored['assessment']==facts and stored['instruction']==state['instruction']))
    return checks


def inject(step, sandbox, agent, dashboard, result):
    action = step['action']
    evidence = {'action':action,'checks':[]}
    if action=='fault':
        sandbox.fault = step['value']
    elif action=='publish':
        sandbox.publish(step['zone'],**step['changes'])
        current = sandbox.call()['instruction']
        agent.context('CURRENT OPERATOR INSTRUCTION UPDATE. Backend context, not caller speech: '+json.dumps(current))
    elif action=='context':
        agent.context(step['text'])
    elif action=='steer':
        queued = sandbox.api(f'/api/calls/{sandbox.call_id}/steering',{'text':step['text']})['events'][-1]
        agent.context('Operator steering: '+json.dumps(queued['payload']))
        sandbox.api(f'/api/calls/{sandbox.call_id}/steering/{queued["id"]}/ack',{'status':'context_delivered'})
    elif action=='other_call':
        sandbox.other_id=sandbox.new_call()
        sandbox.api('/api/calls/'+sandbox.other_id+'/resolve',{'location':'River Park'})
        sandbox.other_snapshot=sandbox.api('/api/calls/'+sandbox.other_id)
    elif action=='worker_failure':
        async def failed_job(*args,**kwargs):
            raise RuntimeError('Injected worker failure')
        sandbox.stack.enter_context(patch('app.workers.run_case_job',failed_job))
    elif action=='wait_jobs':
        deadline=time.monotonic()+4
        while sandbox.app.state.jobs and time.monotonic()<deadline:
            time.sleep(.02)
        evidence['checks'].append(check('Jobs completed within local budget',not sandbox.app.state.jobs))
        agent.context('Backend job events: '+json.dumps([e for e in sandbox.call()['events'] if e['type'].startswith('job.')]))
    elif action=='stale_context':
        # Exercise the same stale-revision gate as the browser; don't deliberately
        # deliver an event the production client would filter out.
        current=sandbox.call()
        old=next((s['state'] for s in result['steps'] if (s.get('state',{}).get('instruction') or {}).get('zone_id')=='A'),None)
        old_events=[{'call_id':sandbox.call_id,'type':'instruction.updated','payload':old['instruction']},
                    {'call_id':sandbox.call_id,'type':'job.completed','payload':{'revision':old['revision'],'result':{'status':'proposal_ready'}}}] if old else []
        filtered=subprocess.run(['node',str(ROOT/'evaluation/context.mjs')],input=json.dumps({'events':old_events,'call':current}),capture_output=True,text=True,check=True)
        context=json.loads(filtered.stdout)
        discarded=bool(old and context==[None,None])
        for text in context:
            if text is not None:
                agent.context(text)
        evidence['checks'].append(check('Old-zone event rejected by revision/zone gate',discarded))
        evidence['old_revision']=old['revision'] if old else None
        evidence['current_revision']=current['revision']
    elif action=='invalid_arguments':
        before=sandbox.call()['assessment']
        for endpoint,body in [('assessment',{'people_count':-1}),('assessment',{'people_count':'invalid'}),('resolve',{})]:
            r=sandbox.client.post(f'/api/calls/{sandbox.call_id}/{endpoint}',json=body)
            evidence['checks'].append(check('Invalid '+endpoint+' rejected',r.status_code==422,r.status_code))
        evidence['checks'].append(check('Bad args preserve prior facts',before==sandbox.call()['assessment']))
    elif action=='end':
        sandbox.api(f'/api/calls/{sandbox.call_id}/end',{})
        evidence['checks'].append(check('Conversation ended, not resolved',sandbox.call()['status']=='ended'))
    elif action=='reload':
        if dashboard:
            evidence['dashboard']=dashboard.inspect(sandbox.call(),reload=True)
            evidence['checks'].append(check('Reload preserves current marker count',evidence['dashboard']['marker_count_matches']))
        else:
            evidence['not_run']='Browser reload: use --dashboard'
    else:
        raise ValueError('Unknown action '+action)
    return evidence


def run_case(case, credentials, directory, browser=None, timeout=35, agent_factory=TextAgent):
    key=case['id']+':'+case.get('variant','base')
    result={**case,'key':key,'status':'blocked','steps':[],'checks':[]}
    result.pop('turns',None)
    agent=dashboard=None
    started=time.monotonic()
    with Sandbox() as sandbox:
        try:
            if browser:
                from evaluation.browser import Dashboard
                dashboard=Dashboard(browser,sandbox)
            agent=agent_factory(credentials['ELEVENLABS_API_KEY'],credentials['ELEVENLABS_AGENT_ID'],sandbox,timeout)
            agent.start()
            result['steps'].append({'responses':[m['text'] for m in agent.messages if m['role']=='agent']})
            for index,step in enumerate(case['turns']):
                if 'action' in step:
                    evidence=inject(step,sandbox,agent,dashboard,result)
                else:
                    before=len(sandbox.trace)
                    evidence={'say':step['say'],'responses':[],'checks':[]}
                    # Retain a partial turn even if provider/network fails mid-response.
                    result['steps'].append(evidence)
                    message_start=len(agent.messages)
                    try:
                        responses=agent.utter(step['say'])
                    finally:
                        evidence['responses']=[m['text'] for m in agent.messages[message_start:] if m['role']=='agent']
                        evidence['tools']=sandbox.trace[before:]
                        evidence['state']=sandbox.call()
                    evidence.update(responses=responses,tools=sandbox.trace[before:],state=sandbox.call())
                    evidence['checks']=evaluate(step.get('expect',{}),evidence['state'],responses,evidence['tools'],sandbox)
                    print('  Caller: '+step['say'],flush=True)
                    for text in responses:
                        print('  Agent: '+text,flush=True)
                if 'action' in step:
                    result['steps'].append(evidence)
                if dashboard:
                    filename=key.replace(':','-')+f'-{index:02}.png'
                    image=directory/filename if index==len(case['turns'])-1 or case['id']=='TC-55' else None
                    view=dashboard.inspect(sandbox.call(),image)
                    evidence['dashboard']=view
                    if image:
                        evidence['screenshot']=filename
                    evidence['checks'].extend([check('Dashboard location/instruction converged',not view['render_error'],view['render_error']),check('Rendered marker count',view['marker_count_matches']),check('Dashboard has no JS exceptions',not view['page_errors'],view['page_errors'])])
                result['checks'].extend(evidence['checks'])
            result['status']='failed' if any(not c['passed'] for c in result['checks']) else 'blocked' if case['gaps'] else 'review'
        except Exception as exc:
            result['error']=f'{type(exc).__name__}: run interrupted; inspect partial transcript/tools.'
            if type(exc).__name__=='AgentError':
                result['error']=str(exc)
            result['status']='failed' if any(not c['passed'] for c in result['checks']) else 'blocked'
        finally:
            # Include checks from partially completed steps, even on browser errors.
            result['checks']=[c for step in result['steps'] for c in step.get('checks',[])]
            if any(not c['passed'] for c in result['checks']):
                result['status']='failed'
            result['final']=sandbox.call()
            result['tool_trace']=sandbox.trace
            result['transcript']=agent.messages if agent else []
            result['audio_events']=agent.audio_events if agent else 0
            result['duration_seconds']=round(time.monotonic()-started,2)
            if agent:
                result['provider_conversation_id']=agent.metadata.get('conversation_id')
                agent.close()
            if dashboard:
                dashboard.close()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',action='append',default=[],help='TC-55 selects base and variants; TC-55:base selects just base. Repeat flag or comma-separate.')
    parser.add_argument('--list',action='store_true')
    parser.add_argument('--catalog-only',action='store_true',help='Write not-run coverage report without provider calls')
    parser.add_argument('--dashboard',action='store_true',help='Exercise built React dashboard in headless Chromium')
    parser.add_argument('--output',type=str)
    parser.add_argument('--turn-timeout',type=float,default=35)
    parser.add_argument('--repeat',type=int,default=1)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--shard-index',type=int,default=0,help='Zero-based independent-process shard')
    parser.add_argument('--shard-count',type=int,default=1)
    args=parser.parse_args()
    if args.repeat<1 or args.turn_timeout<=0 or (args.limit is not None and args.limit<1):
        parser.error('repeat, timeout, and limit must be positive')
    if args.shard_count<1 or not 0<=args.shard_index<args.shard_count:
        parser.error('shard index must be in [0, shard-count)')
    cases=all_cases()
    selected={part for value in args.case for part in value.split(',')}
    valid={c['id'] for c in cases}|{c['id']+':'+c.get('variant','base') for c in cases}
    if selected-valid:
        parser.error('Unknown cases: '+', '.join(sorted(selected-valid)))
    if selected:
        cases=[c for c in cases if c['id'] in selected or c['id']+':'+c.get('variant','base') in selected]
    if args.limit:
        cases=cases[:args.limit]
    cases=cases[args.shard_index::args.shard_count]
    if not cases:
        parser.error('Selection/shard contains no cases')
    if args.list:
        for c in cases:
            print(c['id']+':'+c.get('variant','base')+' '+c['title'])
        return 0
    directory=ROOT/(args.output or '.runtime/evaluations/'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    directory.mkdir(parents=True,exist_ok=True)
    credentials={**dotenv_values(ROOT/'.env')}
    import os
    credentials.update(os.environ)
    if not args.catalog_only:
        frozen_context=directory/'voice-context.ts'
        shutil.copy2(ROOT/'web/src/voice-context.ts',frozen_context)
        os.environ['EVAL_CONTEXT_MODULE']=str(frozen_context)
    if args.dashboard and not args.catalog_only and (ROOT/'frontend/dist/index.html').exists():
        frozen=directory/'frontend-build'
        shutil.copytree(ROOT/'frontend/dist',frozen,dirs_exist_ok=True)
        os.environ['EVAL_FRONTEND_DIST']=str(frozen)
    report={'metadata':{'created_at':datetime.now(timezone.utc).isoformat(),'transport':'ElevenLabs text-only hosted agent','dashboard':args.dashboard,
                        'shard_index':args.shard_index,'shard_count':args.shard_count,
                        'limitations':['Semantic rubrics require human review.','Synthetic geocoding and local worker only.','No actual dispatch or acceptance.','No exhaustive fault/wording coverage claimed.']},'cases':[]}
    sources=[ROOT/'scripts/configure_elevenlabs.py',ROOT/'web/src/voice-context.ts',ROOT/'web/src/main.ts',ROOT/'test cases.md']
    sources += [p for folder in ('evaluation','app','protocols','frontend/src','frontend/dist') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.py','.ts','.tsx','.mjs','.json','.js','.css','.html'}]
    report['metadata']['source_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report['metadata']['git_head']=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    report['metadata']['git_status']=subprocess.run(['git','status','--short'],cwd=ROOT,capture_output=True,text=True).stdout
    unavailable=None
    if not args.catalog_only:
        if not credentials.get('ELEVENLABS_API_KEY') or not credentials.get('ELEVENLABS_AGENT_ID'):
            unavailable='Missing ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID; configure locally in .env.'
        else:
            try:
                r=httpx.get('https://api.elevenlabs.io/v1/convai/agents/'+credentials['ELEVENLABS_AGENT_ID'],headers={'xi-api-key':credentials['ELEVENLABS_API_KEY']},timeout=20)
                r.raise_for_status()
                report['metadata']['agent']=fingerprint(r.json())
            except Exception as exc:
                unavailable='Provider preflight unavailable: '+type(exc).__name__
    with ExitStack() as stack:
        browser=None
        if args.dashboard and not args.catalog_only and not unavailable:
            try:
                if not (ROOT/'frontend/dist/index.html').exists():
                    raise RuntimeError('Build frontend first')
                from playwright.sync_api import sync_playwright
                playwright=stack.enter_context(sync_playwright())
                browser=playwright.chromium.launch(headless=True)
                stack.callback(browser.close)
            except Exception as exc:
                unavailable='Dashboard setup unavailable: '+type(exc).__name__+'; install evaluation requirements/Chromium and build frontend.'
        for repetition in range(args.repeat):
            for c in cases:
                print(c['id']+':'+c.get('variant','base')+' '+c['title'],flush=True)
                if args.catalog_only or unavailable:
                    result={**c,'key':c['id']+':'+c.get('variant','base'),'status':'not_run' if args.catalog_only else 'blocked','error':unavailable or '', 'steps':[], 'checks':[]}
                else:
                    repeat_directory=directory/f'repeat-{repetition+1}'
                    repeat_directory.mkdir(exist_ok=True)
                    result=run_case(c,credentials,repeat_directory,browser,args.turn_timeout)
                    for step in result.get('steps',[]):
                        if step.get('screenshot'):
                            step['screenshot']=f'repeat-{repetition+1}/'+step['screenshot']
                result['repetition']=repetition+1
                report['cases'].append(result)
                write_report(directory,report)  # Crash-safe progress after every case.
                print('  RESULT '+result['status'],flush=True)
    report['metadata']['source_files_changed_during_run']=[name for name,digest in report['metadata']['source_hashes'].items() if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    if not args.catalog_only and not unavailable:
        try:
            r=httpx.get('https://api.elevenlabs.io/v1/convai/agents/'+credentials['ELEVENLABS_AGENT_ID'],headers={'xi-api-key':credentials['ELEVENLABS_API_KEY']},timeout=20)
            r.raise_for_status()
            report['metadata']['agent_at_end']=fingerprint(r.json())
            report['metadata']['agent_configuration_changed_during_run']=report['metadata']['agent_at_end']['config_sha256']!=report['metadata']['agent']['config_sha256']
        except Exception:
            report['metadata']['agent_end_verification']='unavailable'
    write_report(directory,report)
    print('Report: '+str(directory/'report.html'),flush=True)
    print(json.dumps(report['counts']),flush=True)
    return 1 if report['counts'].get('failed') else 2 if report['counts'].get('blocked') else 0


if __name__=='__main__':
    raise SystemExit(main())
