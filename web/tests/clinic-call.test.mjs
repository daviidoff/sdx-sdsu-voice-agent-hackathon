import test from 'node:test';
import assert from 'node:assert/strict';
import {mountClinicPhone} from '../src/clinic-call.ts';

const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(predicate) {
  for (let i = 0; i < 100; i++) {if (predicate()) return; await tick();}
  assert.fail('Expected call state did not arrive');
}
function harness(t, {claimedElsewhere = false} = {}) {
  const elements = new Map();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {textContent: '', innerHTML: '', hidden: false, disabled: false,
      classList: {toggle() {}}, setAttribute() {}});
    return elements.get(selector);
  };
  const requests = [], listeners = new Map();
  let options, stopped = 0, ended = 0;
  let current = {id: 'clinic-session', status: 'approved', facility_name: 'Bay Clinic'};
  const globals = {document: {querySelector: element, body: {}}, window: {addEventListener: (name, handler) => listeners.set(name, handler)},
    navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop: () => stopped++}]})}, sendBeacon: () => true},
    fetch: async (url, init = {}) => {
      const body = init.body ? JSON.parse(init.body) : undefined;
      requests.push({url, body, method: init.method || 'GET'});
      let result;
      if (url === '/api/contacts/clinic-1/demo-call') result = body ? current : {id: 'clinic-1', name: 'Bay Clinic', voice_configured: true};
      else if (url.endsWith('/voice')) {
        if (claimedElsewhere) return {ok: false, status: 409, json: async () => ({detail: 'Already in use'})};
        result = {signed_url: 'wss://outreach-test', dynamic_variables: {facility_name: 'Bay Clinic', facility_address: 'Clinic address'}};
      } else if (url.endsWith('/connected')) result = current = {...current, status: 'connected'};
      else if (url.endsWith('/end')) result = current = {...current, status: body.status};
      else if (url.endsWith('/context')) result = {instruction: {text: 'Clinic exercise guidance'}};
      else if (url.endsWith('/report')) result = {saved: true};
      else if (url.endsWith('/transcript')) result = current;
      else if (url === '/api/contacts/sessions/clinic-session') result = current;
      else throw new Error('Unexpected route: ' + url);
      return {ok: true, json: async () => result};
    }};
  for (const [key, value] of Object.entries(globals)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, {configurable: true, value});
    t.after(() => {if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];});
  }
  const load = async () => ({Conversation: {startSession: async supplied => {
    options = supplied; return {endSession: async () => {ended++;}, setMicMuted() {}, setVolume() {}};
  }}});
  t.after(() => listeners.get('beforeunload')?.());
  return {element, requests, load, options: () => options, stopped: () => stopped, ended: () => ended};
}

test('clinic phone uses outreach credentials and tools, persists corrections and ends its own session', async t => {
  const h = harness(t);
  await mountClinicPhone('clinic-1', h.load);
  assert.match(h.element('#app').innerHTML, /Bay Clinic/);
  assert.match(h.element('#app').innerHTML, /class="iphone"/);
  assert.equal(h.element('#call-label').textContent, 'Respond as clinic');
  assert.equal(h.requests.length, 1, 'Opening the tab does not start a call');
  h.element('#call-toggle').onclick();
  await until(() => h.element('#call-label').textContent === 'End call');
  assert.equal(h.options().signedUrl, 'wss://outreach-test');
  assert.equal(h.options().dynamicVariables.facility_name, 'Bay Clinic');
  assert.equal(h.stopped(), 1, 'Permission probe releases its microphone');
  h.options().onMessage({role: 'user', message: 'Two patients need transport', event_id: 1});
  h.options().onMessage({role: 'agent', message: 'Three patients', event_id: 2, response_id: 'response-a'});
  h.options().onAgentResponseCorrection({corrected_agent_response: 'Two patients', event_id: 3, response_id: 'response-a'});
  const saved = JSON.parse(await h.options().clientTools.record_contact_report({source_quote: 'Two patients need transport'}));
  assert.equal(saved.saved, true);
  const writes = h.requests.filter(r => r.url.endsWith('/transcript'));
  assert.equal(writes.length, 3);
  assert.equal(writes[1].body.id, writes[2].body.id, 'Correction replaces the same agent response');
  assert.ok(h.requests.indexOf(writes[2]) < h.requests.findIndex(r => r.url.endsWith('/report')));
  assert.match(await h.options().clientTools.get_clinic_context(), /Clinic exercise guidance/);
  h.element('#call-toggle').onclick();
  await until(() => h.element('#voice-state').textContent === 'Call ended');
  assert.equal(h.ended(), 1);
  assert.equal(h.requests.find(r => r.url.endsWith('/end')).body.status, 'completed');
  assert.ok(h.requests.every(r => r.url.startsWith('/api/contacts/')), 'No inbound 911 calls or tools used');
});

test('a second phone tab cannot end a clinic call owned by another tab', async t => {
  const h = harness(t, {claimedElsewhere: true});
  await mountClinicPhone('clinic-1', h.load);
  h.element('#call-toggle').onclick();
  await until(() => h.element('#voice-state').textContent === 'Call not connected');
  assert.match(h.element('#error').textContent, /Already in use/);
  assert.equal(h.options(), undefined);
  assert.ok(!h.requests.some(r => r.url.endsWith('/end')));
});
