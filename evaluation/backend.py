"""Isolated real application, synthetic geography, and the browser's client tools."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles
from app.backend import create_app

ROOT = Path(__file__).resolve().parents[1]
LOCATIONS = {'North Ridge': [32.71, -117.21], 'River Park': [32.71, -117.19],
             'East Meadow': [32.71, -117.17], 'West Harbor': [32.71, -117.15],
             'Outside Point': [32.75, -117.25], 'Boundary Point': [32.71, -117.20]}
ZONES = [
    ('A', 'North Ridge', 'evacuate', 'Evacuate North Ridge. No route is approved. Reference CEDAR.'),
    ('B', 'River Park', 'shelter', 'Shelter in place in River Park and await official updates. Reference ORCHID.'),
    ('C', 'East Meadow', 'warning', 'Prepare for possible evacuation in East Meadow and monitor official updates. This is a preparation notice. Reference MAPLE.'),
    ('D', 'West Harbor', 'warning', 'Monitor official updates in West Harbor and avoid the closed pier. Reference WILLOW.'),
]


class Sandbox:
    def __enter__(self):
        self.stack = ExitStack()
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='disaster-eval-')))
        self.stack.enter_context(patch.dict(os.environ, {
            'TEAM_DATA_DIR': str(self.directory), 'DAYTONA_API_KEY': '', 'GEOCODING_ENABLED': '0'}))
        facilities = [{'id': 'fixture-'+str(i), 'name': name,
                       'aliases': [name+', San Diego', name+' in San Diego', name+', San Diego, California'],
                       'latitude': p[0], 'longitude': p[1],
                       'simulated': True} for i, (name, p) in enumerate(LOCATIONS.items())]
        (self.directory/'facilities.json').write_text(json.dumps(facilities))
        (self.directory/'resources.json').write_text('[]')
        self.app = create_app(self.directory/'test.sqlite')
        dist = Path(os.environ.get('EVAL_FRONTEND_DIST',str(ROOT/'frontend/dist')))
        if (dist/'index.html').exists():
            self.app.mount('/dashboard', StaticFiles(directory=dist, html=True))
        self.client = self.stack.enter_context(TestClient(self.app))
        self.zone_records = {}
        for zone, name, level, instruction in ZONES:
            lat, lng = LOCATIONS[name]
            record = dict(id=zone, label=name, area=name, level=level, instruction='TEST ONLY: '+instruction,
                          polygon=[[lat-.01, lng-.01], [lat-.01, lng+.01], [lat+.01, lng+.01], [lat+.01, lng-.01]])
            self.zone_records[zone] = record
            self.api('/api/dashboard/zones', record)
        self.call_id = self.new_call()
        self.trace = []
        self.fault = None
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def api(self, path, body=None):
        r = self.client.get(path) if body is None else self.client.post(path, json=body)
        r.raise_for_status()
        return r.json()

    def new_call(self):
        return self.api('/api/calls', {'mode': 'elevenlabs', 'scenario_id': 'dashboard'})['id']

    def call(self):
        return self.api('/api/calls/'+self.call_id)

    def snapshot(self):
        return self.api('/api/dashboard/snapshot')

    def transcript(self, role, text, segment=None, replace=False):
        return self.api(f'/api/calls/{self.call_id}/transcript',
                        dict(role=role, text=text, segment_id=segment, replace=replace))

    def tool(self, name, parameters):
        entry = {'name': name, 'arguments': parameters, 'success': False}
        self.trace.append(entry)
        path = f'/api/calls/{self.call_id}'
        try:
            if self.fault == 'write_rejected' and name in {'update_assessment', 'request_assistance'}:
                self.fault = None
                entry['result'] = {'error': 'Test-injected write rejected before commit; not saved.'}
                return entry['result'], True
            if name == 'confirm_location':
                result = self.api(path+'/resolve', {'location': parameters['location']})
            elif name in {'update_assessment', 'request_assistance'}:
                body = {**parameters, **({'transport_needed': True} if name == 'request_assistance' else {})}
                # This deliberately preserves backend validation, including its gaps.
                call = self.api(path+'/assessment', body)
                # Same compactToolResult contract as web/src/main.ts.
                result = {key: call[key] for key in ('assessment','instruction','status','revision')}
            else:
                entry['result'] = {'error': 'Unsupported client tool; no action performed.'}
                return entry['result'], True
            entry.update(success=True, result=result)
            return result, False
        except Exception as exc:
            # Provider URLs and credentials must not appear in reports.
            entry['result'] = {'error': type(exc).__name__, 'message': 'Local tool failed; outcome not confirmed.'}
            return entry['result'], True

    def publish(self, zone, **changes):
        record = {**self.zone_records[zone], **changes}
        self.zone_records[zone] = record
        return self.api('/api/dashboard/zones', record)
