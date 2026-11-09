import type { Dispatch, LatLng, Responder } from '../types'
import { tripFraction } from './dispatch.ts'

export interface CrewSimulation { responders: Responder[]; dispatches: Dispatch[] }
export const emptySimulation = (): CrewSimulation => ({ responders: [], dispatches: [] })

export function patrolAt(position: LatLng, now: number): NonNullable<Responder['patrol']> {
  const [lat, lng] = position
  return { startedAt: now, durationSec: 240, path: [position, [lat, lng + .003], [lat + .002, lng + .003], [lat + .002, lng], position] }
}

export function spawnCrews(center: LatLng, now: number): CrewSimulation {
  const kinds: Responder['kind'][] = ['engine', 'ambulance', 'wheelchair_van', 'engine']
  return { dispatches: [], responders: kinds.map((kind, i) => {
    // Separate patrol areas by several kilometres, accounting for longitude scale.
    const longitudeScale = Math.max(.1, Math.cos(center[0] * Math.PI / 180))
    const position: LatLng = [center[0] + (i < 2 ? -2.5 : 2.5) / 111.32, center[1] + (i % 2 ? 3 : -3) / (111.32 * longitudeScale)]
    return { id: `sim-crew-${i}`, name: `Sim ${kind === 'engine' ? 'Engine' : kind === 'ambulance' ? 'Medic' : 'Access'} ${i + 1}`, kind, position,
      status: 'available', wheelchair: kind === 'wheelchair_van', seats: kind === 'engine' ? 4 : kind === 'ambulance' ? 2 : 6,
      simulated: true, patrol: patrolAt(position, now) }
  }) }
}

export function relocateCrew(state: CrewSimulation, crewId: string, position: LatLng, now: number): CrewSimulation {
  if (!state.responders.some((r) => r.id === crewId && r.simulated)
    || !position.every(Number.isFinite) || Math.abs(position[0]) > 90 || Math.abs(position[1]) > 180) return state
  return {
    responders: state.responders.map((r) => r.id === crewId
      ? { ...r, position, status: 'available', patrol: patrolAt(position, now) } : r),
    dispatches: state.dispatches.map((d) => d.crewId === crewId && d.status !== 'done'
      ? { ...d, status: 'done', radio: [...d.radio, { id: `${d.id}-moved-${now}`, callId: d.id, speaker: 'system',
        text: 'Simulated route cancelled: crew repositioned on the map.', at: now }] } : d),
  }
}

export function advanceSimulation(state: CrewSimulation, now: number): CrewSimulation {
  const dispatches = state.dispatches.map((d): Dispatch => {
    if (d.status === 'calling' && d.acceptedAt !== undefined && now >= d.acceptedAt) return { ...d, status: 'en_route', radio: [...d.radio,
      { id: `${d.id}-accepted`, callId: d.id, speaker: 'caller', text: `Simulated crew accepted. Heading to ${d.target.label}.`, at: now }] }
    if (d.status === 'en_route' && tripFraction(d, now) >= 1) return { ...d, status: 'on_scene', radio: [...d.radio,
      { id: `${d.id}-arrived`, callId: d.id, speaker: 'caller', text: `Simulation arrived at ${d.target.label}.`, at: now }] }
    return d
  })
  if (dispatches.every((d, i) => d === state.dispatches[i])) return state
  return { dispatches, responders: state.responders.map((r) => {
    const d = dispatches.find((d) => d.crewId === r.id && d.status !== 'done')
    return d ? { ...r, status: d.status === 'on_scene' ? 'on_scene' : d.status === 'en_route' ? 'en_route' : 'available' } : r
  }) }
}
