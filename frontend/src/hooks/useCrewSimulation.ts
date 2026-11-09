import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { DispatchTarget, LatLng } from '@/types'
import { activeDispatch, crewPosition, fetchRoute, radioLine } from '@/lib/dispatch'
import { advanceSimulation, emptySimulation, patrolAt, relocateCrew, spawnCrews } from '@/lib/crew-simulation'

export function useCrewSimulation() {
  const [state, setState] = useState(emptySimulation)
  const current = useRef(state)
  const generation = useRef({ value: 0 })
  const pending = useRef(new Map<string, string>())
  useLayoutEffect(() => { current.current = state }, [state])
  useEffect(() => {
    const token = generation.current
    const requests = pending.current
    const timer = setInterval(() => setState((s) => advanceSimulation(s, Date.now())), 250)
    return () => { clearInterval(timer); token.value++; requests.clear() }
  }, [])
  const stop = () => { generation.current.value++; pending.current.clear(); setState(emptySimulation()) }
  const start = (center: LatLng) => { generation.current.value++; pending.current.clear(); setState(spawnCrews(center, Date.now())) }
  const dispatch = async (crewId: string, target: DispatchTarget) => {
    const crew = current.current.responders.find((r) => r.id === crewId)
    if (!crew || activeDispatch(current.current.dispatches, crewId) || pending.current.has(crewId)) return
    const version = generation.current.value
    const position = crewPosition(crew, current.current.dispatches, Date.now())
    const id = crypto.randomUUID()
    pending.current.set(crewId, id)
    setState((s) => ({ responders: s.responders.map((r) => r.id === crewId ? { ...r, position, patrol: undefined } : r),
      dispatches: [...s.dispatches, { id, crewId, target, status: 'calling', route: [], routeText: 'Calculating route…', durationSec: 0,
        radio: [radioLine(id, 'system', 'Simulation only · no real call or dispatch is sent.')] }] }))
    const route = await fetchRoute(position, target.position)
    if (version !== generation.current.value || pending.current.get(crewId) !== id) return
    pending.current.delete(crewId)
    setState((s) => ({ ...s, dispatches: s.dispatches.map((d) => d.id === id && d.status === 'calling' ? { ...d, route: route.path,
      routeText: route.routeText, durationSec: Math.max(route.durationSec, 90), acceptedAt: Date.now() + 2500,
      radio: [...d.radio, radioLine(id, 'agent', `${crew.name}, proceed to ${target.label} ${route.routeText}. Please confirm.`)] } : d) }))
  }
  const release = (crewId: string) => {
    const crew = current.current.responders.find((r) => r.id === crewId)
    if (!crew) return
    pending.current.delete(crewId)
    const now = Date.now()
    const position = crewPosition(crew, current.current.dispatches, now)
    setState((s) => ({ responders: s.responders.map((r) => r.id === crewId ? { ...r, position, status: 'available', patrol: patrolAt(position, now) } : r),
      dispatches: s.dispatches.map((d) => d.crewId === crewId && d.status !== 'done' ? { ...d, status: 'done' } : d) }))
  }
  const move = (crewId: string, position: LatLng) => {
    pending.current.delete(crewId)
    setState((s) => relocateCrew(s, crewId, position, Date.now()))
  }
  return { ...state, start, stop, dispatch, release, move }
}
