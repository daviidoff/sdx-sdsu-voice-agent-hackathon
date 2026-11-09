"""Tests of the evaluator, not fabricated passes for the disaster agent."""
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
from evaluation.backend import Sandbox, ROOT
from evaluation.agent import TextAgent, AgentError
from evaluation.cases import all_cases
from evaluation.report import write_report
from evaluation.run import evaluate, inject
from evaluation.merge import merge


def test_every_documented_case_has_unique_executable_data():
    cases=all_cases()
    documented=set(re.findall(r'\bTC-\d{2}\b',(ROOT/'test cases.md').read_text()))
    assert {c['id'] for c in cases}==documented
    keys=[(c['id'],c.get('variant','base')) for c in cases]
    assert len(keys)==len(set(keys))
    for c in cases:
        assert c['turns'] and c['review']
        assert any('say' in t for t in c['turns'])


def test_isolation_prevents_real_data_or_cloud_jobs(monkeypatch):
    monkeypatch.setenv('DAYTONA_API_KEY','not-a-real-key')
    monkeypatch.setenv('TEAM_DATA_DIR','/does/not/exist')
    with Sandbox() as a:
        assert os.environ['DAYTONA_API_KEY']==''
        assert os.environ['GEOCODING_ENABLED']=='0'
        a.tool('update_assessment',{'people_count':7})
        directory=a.directory
    assert not directory.exists()
    assert os.environ['DAYTONA_API_KEY']=='not-a-real-key'
    with Sandbox() as b:
        assert b.call()['assessment']=={}


@pytest.mark.parametrize('place,zone', [('North Ridge','A'),('River Park','B'),('East Meadow','C'),('West Harbor','D'),('Outside Point',None),('Boundary Point',None)])
def test_real_polygon_resolution_with_independent_expected_zone(place,zone):
    with Sandbox() as s:
        result,error=s.tool('confirm_location',{'location':place})
        assert not error
        assert result['zone_id']==zone
        assert s.snapshot()['calls'][0]['instruction']['zone_id']==zone


def test_zone_move_preserves_needs_and_history():
    with Sandbox() as s:
        original=s.call_id
        s.tool('confirm_location',{'location':'North Ridge'})
        s.tool('update_assessment',{'people_count':2,'transport_needed':True})
        s.tool('confirm_location',{'location':'River Park'})
        state=s.call()
        assert state['id']==original and state['instruction']['zone_id']=='B'
        assert state['assessment']['transport_needed'] is True
        assert state['assessment']['people_count']==2
        assert any((e['payload'] or {}).get('zone_id')=='A' for e in state['events'] if e['type']=='instruction.updated')


def test_pending_move_clears_old_guidance_preserves_needs_and_rejects_mismatch():
    with Sandbox() as s:
        s.tool('confirm_location',{'location':'North Ridge'})
        s.tool('update_assessment',{'people_count':2,'transport_needed':True})
        old = s.call()
        s.tool('propose_location',{'location':'River Park'})
        pending = s.call()
        assert pending['pending_location']=='River Park'
        assert pending['instruction'] is None
        assert pending['assessment'].get('location_resolution') is None
        assert pending['assessment'].get('location') is None
        assert pending['revision']>old['revision']
        _, error=s.tool('confirm_location',{'location':'North Ridge'})
        assert error and s.call()['pending_location']=='River Park'
        _, error=s.tool('confirm_location',{'location':'River Park'})
        assert error  # Even the correct place cannot be confirmed in the proposal turn.
        s.transcript('user','Yes, River Park is where we are now.')
        s.tool('confirm_location',{'location':'River Park'})
        assert s.call()['instruction']['zone_id']=='B'
        assert not s.call().get('pending_location')
        assert s.call()['assessment']['people_count']==2
        assert s.call()['assessment']['transport_needed'] is True


def test_operator_bridge_receipt_idempotency_and_fact_guard():
    with Sandbox() as s:
        result,error=s.tool('message_operator',{'text':'Needs water','request_id':'need-water'})
        assert not error and result['status']=='received'
        s.tool('message_operator',{'text':'Needs water','request_id':'need-water'})
        inbox,error=s.tool('check_operator_messages',{})
        assert not error and len(inbox['messages'])==1
        agent=TextAgent('unused','unused',s)
        agent.send=lambda value:None
        agent.sync_context=lambda:None
        agent.operator_turn=True
        agent.handle({'type':'client_tool_call','client_tool_call':{'tool_call_id':'operator-fact','tool_name':'update_assessment','parameters':{'people_count':99}}})
        assert s.call()['assessment'].get('people_count') is None
        assert not s.trace[-1]['success']


def test_turn_waits_for_explicit_completion_after_tool_chain():
    with Sandbox() as s:
        agent=TextAgent('unused','unused',s)
        agent.send=lambda value:None
        agent.sync_context=lambda:None
        messages=iter([
            {'type':'agent_response','agent_response_event':{'agent_response':'I will record that.'}},
            {'type':'client_tool_call','client_tool_call':{'tool_call_id':'save','tool_name':'update_assessment','parameters':{'people_count':2}}},
            {'type':'agent_response','agent_response_event':{'agent_response':'Recorded two people.'}},
            {'type':'agent_response_complete','agent_response_complete_event':{'event_id':4}},
        ])
        class Socket:
            def recv(self):
                return json.dumps(next(messages))
        agent.connection=Socket()
        assert agent.receive_turn()==['I will record that.','Recorded two people.']
        assert s.call()['assessment']['people_count']==2


def test_evaluator_fails_wrong_zone_missing_facts_and_premature_confirmation():
    with Sandbox() as s:
        s.tool('confirm_location',{'location':'North Ridge'})
        checks=evaluate({'zone':'B','facts':{'people_count':2},'no_location_tool':True},s.call(),['Hello'],s.trace,s)
        assert sum(not c['passed'] for c in checks)==3


def test_zero_is_not_unknown_and_negative_assertion_detects_inference():
    with Sandbox() as s:
        s.tool('update_assessment',{'wheelchair_users':0,'transport_needed':True})
        checks=evaluate({'unknown':['wheelchair_users'],'not_true':['transport_needed']},s.call(),[],[],s)
        assert sum(not c['passed'] for c in checks)==2


def test_fault_rejection_is_not_saved_and_retry_does_not_duplicate_case():
    with Sandbox() as s:
        s.fault='write_rejected'
        result,error=s.tool('update_assessment',{'people_count':3})
        assert error and 'people_count' not in s.call()['assessment']
        result,error=s.tool('update_assessment',{'people_count':3})
        assert not error and result['assessment']['people_count']==3
        assert set(result)=={'assessment','instruction','status','revision'}
        assert len(s.snapshot()['calls'])==1


def test_stale_context_uses_real_browser_filter():
    with Sandbox() as s:
        s.tool('confirm_location',{'location':'North Ridge'})
        before=s.call()
        s.tool('confirm_location',{'location':'River Park'})
        class Sink:
            def context(self,text):
                pytest.fail('Stale event was forwarded: '+text)
        result=inject({'action':'stale_context'},s,Sink(),None,{'steps':[{'state':before}]})
        assert all(c['passed'] for c in result['checks'])


def test_agent_rejects_audio_and_deduplicates_tool_delivery():
    with Sandbox() as s:
        agent=TextAgent('unused','unused',s)
        sent=[]
        agent.send=sent.append
        agent.sync_context=lambda:None
        message={'type':'client_tool_call','client_tool_call':{'tool_call_id':'same','tool_name':'update_assessment','parameters':{'people_count':2}}}
        agent.handle(message)
        agent.handle(message)
        assert len(s.trace)==1 and sent[0]==sent[1]
        with pytest.raises(AgentError,match='Audio received'):
            agent.handle({'type':'audio','audio_event':{'audio_base_64':'must not be logged'}})


def test_html_escapes_untrusted_transcripts_and_keeps_failures(tmp_path):
    report={'metadata':{},'cases':[{'key':'TC-01','title':'Example','status':'failed','review':'Review me','steps':[{'say':'<script>alert(1)</script>','responses':['<img src=x onerror=alert(1)>'], 'checks':[{'name':'Wrong zone','passed':False}]}]}]}
    write_report(tmp_path,report)
    html=(tmp_path/'report.html').read_text()
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert 'Wrong zone' in html
    assert json.loads((tmp_path/'results.json').read_text())['counts']=={'failed':1}


def test_unknown_case_selection_exits_nonzero():
    result=subprocess.run([os.sys.executable,'-m','evaluation.run','--case','TC-999','--list'],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==2
    assert 'Unknown cases' in result.stderr


def test_wrong_evacuation_directive_fails_even_if_zone_data_is_correct():
    with Sandbox() as s:
        s.tool('confirm_location',{'location':'River Park'})
        checks=evaluate({'zone':'B'},s.call(),['You must evacuate immediately.'],[],s)
        assert any(not c['passed'] and 'evacuation directive' in c['name'] for c in checks)
        checks=evaluate({'zone':'B'},s.call(),['Do not evacuate on the basis of a different zone notice.'],[],s)
        assert all(c['passed'] for c in checks)


def test_merge_preserves_screenshots_and_rejects_duplicate_runs(tmp_path):
    inputs=[]
    for n in range(2):
        folder=tmp_path/str(n)
        folder.mkdir()
        (folder/'image.png').write_bytes(b'test-image')
        write_report(folder,{'metadata':{'shard':n},'cases':[{'key':f'TC-{n+1:02}:base','title':'Synthetic evaluator test','status':'review','repetition':1,'steps':[{'screenshot':'image.png'}]}]})
        inputs.append(folder)
    output=tmp_path/'merged'
    combined=merge(inputs,output)
    assert len(combined['cases'])==2
    assert all((output/c['steps'][0]['screenshot']).read_bytes()==b'test-image' for c in combined['cases'])
    with pytest.raises(ValueError,match='Duplicate'):
        merge([inputs[0],inputs[0]],tmp_path/'duplicates')
