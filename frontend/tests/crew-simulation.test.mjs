import assert from 'node:assert/strict'
import test from 'node:test'
import { advanceSimulation, relocateCrew, spawnCrews } from '../src/lib/crew-simulation.ts'
import { crewPosition, distanceKm, endedAssistanceLocations, fetchRoute, suggestCalls } from '../src/lib/dispatch.ts'

test('an operator can route to an ended assistance call without treating it as a live call', () => {
  const medic = spawnCrews([32.71, -117.15], 0).responders.find((r) => r.kind === 'ambulance')
  const report = { id: 'library', status: 'ended', situation: 'needs_help', position: [32.7089, -117.1541],
    mobility: '', endedAt: 8000, startedAt: 1000 }
  const calls = [report, {...report, id: 'older', endedAt: 7000}, {...report, id: 'wheelchair', mobility: 'Wheelchair lift'},
    {...report, id: 'cleared', situation: 'can_leave'}, {...report, id: 'unmapped', position: undefined},
    {...report, id: 'resolved', status: 'resolved'}, {...report, id: 'on-call', status: 'active'}]
  assert.deepEqual(endedAssistanceLocations(medic, calls, []).map((c) => c.id), ['library', 'older'])
  assert.deepEqual(suggestCalls(medic, calls, [], 9000).map((item) => item.call.id), ['on-call'])
  const assigned = {status: 'en_route', target: {kind: 'call', id: 'library'}}
  assert.deepEqual(endedAssistanceLocations(medic, calls, [assigned]).map((c) => c.id), ['older'])
})

test('four distinct simulated crews patrol slowly near the chosen map center', () => {
  const now = 10000
  const state = spawnCrews([32.75, -117.11], now)
  assert.equal(state.responders.length, 4)
  assert.equal(new Set(state.responders.map((r) => r.id)).size, 4)
  for (const crew of state.responders) {
    assert.equal(crew.simulated, true)
    const start = crewPosition(crew, [], now)
    const later = crewPosition(crew, [], now + 1000)
    assert.ok(distanceKm(start, later) > 0)
    assert.ok(distanceKm(start, later) < .005)
    assert.deepEqual(crewPosition(crew, [], now + 240000), start)
  }
})

test('crews start at least four kilometres apart across different latitudes', () => {
  for (const center of [[32.75, -117.11], [60, 20], [-35, 145]]) {
    const { responders } = spawnCrews(center, 0)
    for (let i = 0; i < responders.length; i++) {
      for (const other of responders.slice(i + 1)) assert.ok(distanceKm(responders[i].position, other.position) > 4)
    }
  }
})

test('moving a crew restarts patrol at the drop and cancels only its active route', () => {
  for (const status of ['calling', 'en_route', 'on_scene']) {
    const state = spawnCrews([32.75, -117.11], 10000)
    const crew = state.responders[0]
    state.dispatches = [{ id: 'moving', crewId: crew.id, status, acceptedAt: 10000,
      target: { kind: 'facility', id: 'poi', label: 'Shelter', position: [32.8, -117.1] },
      route: [crew.position, [32.8, -117.1]], routeText: 'test', durationSec: 90, radio: [] }]
    const destination = [32.79, -117.16]
    const moved = relocateCrew(state, crew.id, destination, 20000)
    assert.deepEqual(crewPosition(moved.responders[0], moved.dispatches, 20000), destination)
    assert.equal(moved.responders[0].status, 'available')
    assert.equal(moved.dispatches[0].status, 'done')
    assert.match(moved.dispatches[0].radio[0].text, /cancelled/)
    assert.equal(moved.responders[1], state.responders[1])
    assert.equal(advanceSimulation(moved, 200000), moved)
    assert.ok(distanceKm(crewPosition(moved.responders[0], moved.dispatches, 21000), destination) < .005)
    assert.equal(relocateCrew(state, crew.id, [NaN, 0], 20000), state)
    assert.equal(relocateCrew(state, 'missing', destination, 20000), state)
  }
})

test('dispatch waits for acceptance, travels, arrives once and remains on scene', () => {
  const state = spawnCrews([32.75, -117.11], 10000)
  const crew = state.responders[0]
  const target = { kind: 'facility', id: 'poi', label: 'Shelter', position: [32.76, -117.11] }
  state.dispatches.push({ id: 'd', crewId: crew.id, target, status: 'calling', acceptedAt: 13000,
    route: [crew.position, target.position], routeText: 'test route', durationSec: 90, radio: [] })
  assert.equal(advanceSimulation(state, 12000), state)
  const accepted = advanceSimulation(state, 13000)
  assert.equal(accepted.dispatches[0].status, 'en_route')
  const midpoint = crewPosition(crew, accepted.dispatches, 58000)
  assert.notDeepEqual(midpoint, crew.position)
  assert.notDeepEqual(midpoint, target.position)
  const arrived = advanceSimulation(accepted, 103000)
  assert.equal(arrived.dispatches[0].status, 'on_scene')
  assert.equal(arrived.responders[0].status, 'on_scene')
  assert.deepEqual(crewPosition(crew, arrived.dispatches, 103000), target.position)
  assert.equal(advanceSimulation(arrived, 104000), arrived)
  assert.equal(arrived.dispatches[0].radio.length, 2)
})

test('offline route remains usable and explicitly labeled as straight-line simulation', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => { throw new Error('offline') }
  try {
    const route = await fetchRoute([32.75, -117.11], [32.76, -117.12])
    assert.equal(route.path.length, 2)
    assert.match(route.routeText, /straight-line simulation/)
    assert.ok(route.durationSec > 0)
  } finally { globalThis.fetch = original }
})
