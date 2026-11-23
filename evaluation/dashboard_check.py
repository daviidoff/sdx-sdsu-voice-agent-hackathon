"""Offline contract check of rendered facts, operator inbox, and a zone move.

This exercises production tools/UI with synthetic data, not generated agent replies.
"""
import argparse
import json
from pathlib import Path
import re

from evaluation.backend import Sandbox
from evaluation.browser import Dashboard


def run(output):
    from playwright.sync_api import sync_playwright
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    checks=[]
    def check(name, condition):
        checks.append({'name':name,'passed':bool(condition)})
    with Sandbox() as sandbox, sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        dashboard=Dashboard(browser,sandbox)
        try:
            sandbox.tool('confirm_location',{'location':'North Ridge'})
            sandbox.tool('update_assessment',{'people_count':2,'wheelchair_users':1,
                'transport_needed':True,'can_evacuate':False,'mobility_needs':'Cannot use stairs.'})
            view=dashboard.inspect(sandbox.call(),output/'confirmed-facts.png')
            check('People, wheelchair count, mobility barrier and transport are rendered',
                  all(text in view['detail'] for text in ['2 people','1 wheelchair users','Cannot use stairs.','Transport requested']))
            check('Initial map marker matches the named place',view['marker_geometry']['matches'])
            receipt,error=sandbox.tool('message_operator',{'text':'Needs drinking water and phone charging.','request_id':'water-and-power'})
            check('Inbox write returns received receipt',not error and receipt['status']=='received')
            page=dashboard.page
            page.get_by_role('button',name=re.compile(r'^Inbox')).click()
            log=page.get_by_role('log',name='Conversation history')
            log.get_by_text('Needs drinking water and phone charging.',exact=True).wait_for(timeout=6000)
            log.get_by_text('Saved in inbox · message '+str(receipt['message_id']),exact=True).wait_for(timeout=6000)
            check('Actual operator inbox renders message and receipt',True)
            page.screenshot(path=str(output/'operator-inbox.png'))
            page.get_by_role('button',name=re.compile(r'^Close inbox$',re.I)).click()
            sandbox.tool('propose_location',{'location':'River Park'})
            view=dashboard.inspect(sandbox.call(),output/'pending-move.png')
            check('Pending move clears marker and old instruction',view['expected_marker_count']==0 and view['marker_count_matches'] and sandbox.call()['instruction'] is None)
            check('Pending location is displayed', 'Confirmation pending: River Park' in view['detail'])
            sandbox.transcript('user','Yes, River Park is where we are now.')
            sandbox.tool('confirm_location',{'location':'River Park'})
            view=dashboard.inspect(sandbox.call(),output/'confirmed-move.png')
            check('Confirmed move renders new advice and exact fixture marker',not view['render_error'] and view['marker_geometry']['matches'] and 'Shelter in place in River Park' in view['detail'])
            check('Needs survive zone change',all(text in view['detail'] for text in ['2 people','1 wheelchair users','Cannot use stairs.','Transport requested']))
            check('Map remains visible and dashboard has no JavaScript errors',view['map_visible'] and not view['page_errors'])
        except Exception as exc:
            checks.append({'name':'UI contract completed','passed':False,'error':type(exc).__name__})
        finally:
            dashboard.close();browser.close()
    report={'scope':'Offline production dashboard/tool contract, synthetic caller data. No model, audio or real dispatch.', 'checks':checks}
    (output/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    return 0 if all(c['passed'] for c in checks) else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    raise SystemExit(run(p.parse_args().output))
