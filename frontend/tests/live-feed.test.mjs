import assert from 'node:assert/strict'
import test from 'node:test'
import { toCall, toLines, createFeed } from '../src/lib/feed.ts'
import { callDuration, byPriority } from '../src/lib/geo.ts'
import { situationLabel } from '../src/components/labels.ts'

const rawCall = (changes = {}) => ({
  id: 'airport-call', status: 'ended', mode: 'elevenlabs', scenario_id: 'dashboard',
  created_at: '2026-11-08T22:51:20.088076+00:00', ended_at: '2026-11-08T22:53:21.551407+00:00',
  assessment: { location: 'San Diego Airport', people_count: 2, transport_needed: true }, events: [], ...changes,
})

test('ended airport duration remains 2:01 as the wall clock advances', () => {
  const call = toCall(rawCall())
  assert.equal(callDuration(call, Date.parse('2026-11-08T23:00:00Z')), '2:01')
  assert.equal(callDuration(call, Date.parse('2026-11-09T23:00:00Z')), '2:01')
})

test('live durations advance; ended records without an end time stay unknown', () => {
  const call = toCall(rawCall({ status: 'active', ended_at: undefined }))
  assert.equal(callDuration(call, call.startedAt + 30_000), '0:30')
  assert.equal(callDuration(call, call.startedAt + 31_000), '0:31')
  assert.equal(callDuration({ ...call, status: 'ended' }, call.startedAt + 31_000), '—')
  const historical = toCall(rawCall({ ended_at: undefined, events: [{ id: '1', type: 'call.ended', created_at: '2026-11-08T22:53:21Z', payload: {} }] }))
  assert.equal(callDuration(historical, Date.now()), '2:00')
})

test('transport requested is explicit and does not infer a mobility limitation', () => {
  const call = toCall(rawCall({ assessment: { transport_needed: true, mobility_needs: null, wheelchair_users: null } }))
  assert.equal(situationLabel(call), 'Transport requested')
  assert.equal(call.mobility, 'Mobility needs not confirmed')
  assert.equal(call.canEvacuate, undefined)
  assert.equal(call.wheelchairUsers, undefined)
  const unknown = toCall(rawCall({ assessment: {} }))
  assert.equal(situationLabel(unknown), 'Needs unconfirmed')
  assert.equal(unknown.situation, 'unknown')
})

test('only resolved valid coordinates get a map position', () => {
  const position = { status: 'resolved', lat: 32.733, lng: -117.19, precision: 'place_reference' }
  assert.deepEqual(toCall(rawCall({ assessment: { location_resolution: position } })).position, [32.733, -117.19])
  for (const location_resolution of [{ ...position, status: 'ambiguous' }, { ...position, lat: 100 }, { ...position, lng: undefined }]) {
    assert.equal(toCall(rawCall({ assessment: { location_resolution } })).position, undefined)
  }
})

test('historical instruction and later map lookup remain distinct', () => {
  const instruction = { text: 'No instruction matched during this call.', version: null }
  const current_spatial_instruction = { text: 'Operator evacuation instruction', version: 3, zone_id: 'airport-zone' }
  const call = toCall(rawCall({ instruction, current_spatial_instruction }))
  assert.equal(call.instruction.text, instruction.text)
  assert.equal(call.currentSpatialInstruction.text, current_spatial_instruction.text)
})

test('corrected location removes stale pin and a resolved update moves it', () => {
  const location_resolution = { status: 'resolved', query: 'San Diego Airport', lat: 32.733, lng: -117.19 }
  assert.equal(toCall(rawCall({ assessment: { location: 'Pacific Beach', location_resolution } })).position, undefined)
  const next = { status: 'resolved', query: 'Pacific Beach', lat: 32.7925867, lng: -117.2463902 }
  assert.deepEqual(toCall(rawCall({ assessment: { location: 'Pacific Beach', location_resolution: next } })).position, [32.7925867, -117.2463902])
  assert.equal(toCall(rawCall({ assessment: { location: 'Pacific Beach', location_resolution: { ...next, status: 'pending' } } })).position, undefined)
})

test('transcript corrections keep stable IDs and do not append correction notifications', () => {
  const original = { id: '10', call_id: 'airport-call', type: 'transcript', payload: { role: 'agent', text: 'Please wait.' }, created_at: '2026-11-08T22:51:30Z' }
  const lines = toLines(rawCall({ events: [original] }))
  const updated = toLines(rawCall({ events: [
    { ...original, payload: { role: 'agent', text: 'Please wait. I am checking your updated location.' } },
    { ...original, id: '11', type: 'transcript.corrected', payload: { original_event_id: '10' } },
  ] }))
  assert.equal(updated.length, 1)
  assert.equal(updated[0].id, lines[0].id)
  assert.equal(updated[0].text, 'Please wait. I am checking your updated location.')
})

test('active unknown callers sort before ended callers who requested transport', () => {
  const ended = toCall(rawCall())
  const active = toCall(rawCall({ id: 'new-call', status: 'active', assessment: {} }))
  assert.deepEqual([ended, active].sort(byPriority).map((c) => c.id), ['new-call', 'airport-call'])
})

test('unchanged polls do not replace transcript state; changed content does', { timeout: 5000 }, async (t) => {
  const events = []
  let polls = 0
  const snapshot = { calls: [rawCall()], zones: [], facilities: [], incidents: [], routes: [] }
  let finish
  const completed = new Promise((resolve) => { finish = resolve })
  t.mock.method(globalThis, 'fetch', async () => {
    polls++
    const response = { ...snapshot, updated_at: String(polls) }
    if (polls >= 3) response.calls = [rawCall({ assessment: { people_count: 3 } })]
    return { ok: true, json: async () => response }
  })
  const stop = createFeed().start((event) => {
    events.push(event)
    if (events.length === 2) finish()
  })
  try {
    await completed
    assert.equal(polls, 3)
    assert.equal(events[0].type, 'snapshot')
    assert.equal(events[1].snapshot.calls[0].assessment.people_count, 3)
  } finally { stop() }
})
