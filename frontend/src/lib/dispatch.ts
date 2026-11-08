// Crew dispatch: road routes, matching crews to callers, moving vehicles, and the (fake) radio call.
import type { Call, Dispatch, LatLng, Responder, TranscriptLine } from '@/types'

/** Playback speed. 1 = real time: a 5-minute drive takes 5 minutes on screen. Raise it only to fast-forward. */
export const DEMO_SPEED = 1

export function distanceKm([lat1, lng1]: LatLng, [lat2, lng2]: LatLng): number {
  const r = (d: number) => (d * Math.PI) / 180
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lng2 - lng1) / 2) ** 2
  return 6371 * 2 * Math.asin(Math.sqrt(a))
}

/** Real road route from the public OSRM demo server (OpenStreetMap data). Falls back to a straight line. */
export async function fetchRoute(from: LatLng, to: LatLng): Promise<{ path: LatLng[]; durationSec: number; routeText: string }> {
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${from[1]},${from[0]};${to[1]},${to[0]}?overview=full&geometries=geojson&steps=true`
    const res = await fetch(url, { signal: AbortSignal.timeout(5000) })
    const route = (await res.json()).routes?.[0]
    if (route) {
      const names: string[] = []
      for (const step of route.legs[0].steps as { name: string; distance: number }[])
        if (step.name && step.distance > 150 && !names.includes(step.name)) names.push(step.name)
      return {
        path: (route.geometry.coordinates as [number, number][]).map(([lng, lat]) => [lat, lng]),
        durationSec: Math.max(90, route.duration),
        routeText: names.length ? `via ${names.slice(0, 3).join(', ')}` : 'follow the route on screen',
      }
    }
  } catch {
    // network or server problem: use the fallback below
  }
  return { path: [from, to], durationSec: (distanceKm(from, to) / 35) * 3600 + 60, routeText: 'direct route (offline estimate)' }
}

/** Where along the path the vehicle is, for a fraction 0..1 of the trip. */
export function pointAlong(path: LatLng[], frac: number): LatLng {
  if (path.length < 2 || frac <= 0) return path[0]
  if (frac >= 1) return path[path.length - 1]
  const seg = path.slice(1).map((p, i) => distanceKm(path[i], p))
  let goal = seg.reduce((a, b) => a + b, 0) * frac
  for (let i = 0; i < seg.length; i++) {
    if (goal <= seg[i]) {
      const t = seg[i] ? goal / seg[i] : 0
      const [a, b] = [path[i], path[i + 1]]
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    }
    goal -= seg[i]
  }
  return path[path.length - 1]
}

export function tripFraction(d: Dispatch, now: number): number {
  if (d.status !== 'en_route' || !d.acceptedAt) return d.status === 'on_scene' || d.status === 'done' ? 1 : 0
  return Math.min(1, (now - d.acceptedAt) / ((d.durationSec * 1000) / DEMO_SPEED))
}

export function etaMin(d: Dispatch, now: number): number {
  return Math.max(0, Math.ceil(((1 - tripFraction(d, now)) * d.durationSec) / 60))
}

export function activeDispatch(dispatches: Dispatch[], crewId: string): Dispatch | undefined {
  return dispatches.find((d) => d.crewId === crewId && d.status !== 'done')
}

export function crewPosition(r: Responder, dispatches: Dispatch[], now: number): LatLng {
  const d = activeDispatch(dispatches, r.id)
  return d && d.route.length ? pointAlong(d.route, tripFraction(d, now)) : r.position
}

export const needsWheelchair = (call: Call) => /wheelchair/i.test(call.mobility)
export const needsRescue = (call: Call) => call.status !== 'resolved' && call.status !== 'ended' && (call.situation === 'needs_help' || call.situation === 'trapped')

/** Crews for a caller: available first, then ones that fit (wheelchair), then nearest. Code decides, not the model. */
export function suggestCrews(call: Call, responders: Responder[], dispatches: Dispatch[], now: number) {
  return responders
    .map((r) => {
      const fits = !needsWheelchair(call) || r.wheelchair
      const available = r.status === 'available' && !activeDispatch(dispatches, r.id)
      return { responder: r, km: call.position ? distanceKm(crewPosition(r, dispatches, now), call.position) : Infinity, fits, available }
    })
    .sort((a, b) => Number(b.available) - Number(a.available) || Number(b.fits) - Number(a.fits) || a.km - b.km)
}

/** Callers a crew could go to: trapped first, then needs help; skips callers who already have a crew. */
export function suggestCalls(crew: Responder, calls: Call[], dispatches: Dispatch[], now: number) {
  const covered = new Set(dispatches.filter((d) => d.status !== 'done' && d.target.kind === 'call').map((d) => d.target.id))
  const here = crewPosition(crew, dispatches, now)
  return calls
    .filter((c) => needsRescue(c) && !covered.has(c.id))
    .map((c) => ({ call: c, km: c.position ? distanceKm(here, c.position) : Infinity, fits: !needsWheelchair(c) || crew.wheelchair }))
    .sort((a, b) => Number(b.fits) - Number(a.fits) || (a.call.situation === 'trapped' ? 0 : 1) - (b.call.situation === 'trapped' ? 0 : 1) || a.km - b.km)
}

let seq = 0
export const radioLine = (dispatchId: string, speaker: 'agent' | 'caller' | 'system', text: string): TranscriptLine => ({
  id: `radio-${++seq}`,
  callId: dispatchId,
  speaker,
  text,
  at: Date.now(),
})
