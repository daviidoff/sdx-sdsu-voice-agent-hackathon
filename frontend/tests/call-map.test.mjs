import assert from 'node:assert/strict'
import test from 'node:test'
import { toCall } from '../src/lib/feed.ts'
import { callMapCandidates, callMapUncertaintyBounds, mapFocusKey } from '../src/lib/call-map.ts'

const airport = { status: 'resolved', query: 'San Diego Airport', lat: 32.733, lng: -117.19 }
const crownPoint = {
  status: 'ambiguous', query: 'Crown Point, Pacific Beach',
  candidates: [
    { lat: 32.79, lng: -117.23, display_name: 'Crown Point' },
    { lat: 32.786, lng: -117.231, display_name: 'Crown Point Park' },
  ],
  uncertainty_bounds: [-117.24, 32.80, -117.22, 32.78],
}
const call = (resolution, location = resolution.query) => toCall({
  id: 'same-live-call', status: 'active', mode: 'elevenlabs', scenario_id: 'dashboard',
  created_at: '2026-11-08T22:51:20Z', events: [],
  assessment: { location, location_resolution: resolution },
})
const focus = (value) => mapFocusKey(value.position, callMapCandidates(value), callMapUncertaintyBounds(value))

test('same selected call moves airport → pending → Crown Point alternatives → confirmed point', () => {
  const first = call(airport)
  const pending = call({ ...crownPoint, status: 'pending' })
  const alternatives = call(crownPoint)
  const resolved = call({ ...crownPoint, status: 'resolved', lat: 32.79, lng: -117.23 })
  assert.deepEqual(JSON.parse(focus(first)), [[32.733, -117.19]])
  assert.equal(pending.position, undefined)
  assert.equal(focus(pending), '[]')
  assert.equal(alternatives.position, undefined)
  assert.equal(callMapCandidates(alternatives).length, 2)
  assert.ok(!focus(alternatives).includes('32.733'))
  assert.deepEqual(JSON.parse(focus(resolved)), [[32.79, -117.23]])
  assert.deepEqual(callMapCandidates(resolved), [])
  assert.equal(first.id, resolved.id)
})

test('stale results, pending results and invalid coordinates never become alternative markers', () => {
  assert.deepEqual(callMapCandidates(call(crownPoint, 'New location')), [])
  assert.deepEqual(callMapUncertaintyBounds(call(crownPoint, 'New location')), [])
  const malformed = call({ ...crownPoint, candidates: [
    ...crownPoint.candidates, crownPoint.candidates[0],
    { lat: 100, lng: 0 }, { lat: NaN, lng: 0 }, { lat: 0, lng: Infinity }, { lat: 0 },
  ] })
  assert.equal(callMapCandidates(malformed).length, 2)
})

test('area bounds preserve geographic coordinate order and reject malformed boxes', () => {
  assert.deepEqual(callMapUncertaintyBounds(call(crownPoint)), [
    [32.80, -117.24], [32.80, -117.22], [32.78, -117.22], [32.78, -117.24],
  ])
  for (const uncertainty_bounds of [[0, 91, 1, 0], [2, 1, 0, 0], [0, 0, 1, 2], [0, 1, 2], [0, 1, Infinity, 0]]) {
    assert.deepEqual(callMapUncertaintyBounds(call({ ...crownPoint, uncertainty_bounds })), [])
  }
})

test('identical polls preserve focus; new coordinates change focus without selecting a different call', () => {
  assert.equal(focus(call(crownPoint)), focus(call(structuredClone(crownPoint))))
  assert.notEqual(focus(call(airport)), focus(call({ ...airport, lat: 32.75 })))
})
