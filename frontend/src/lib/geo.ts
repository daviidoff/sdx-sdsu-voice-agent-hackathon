import type { Call, LatLng, Zone } from '@/types'

// Ray casting: is the point inside the polygon?
export function pointInPolygon([lat, lng]: LatLng, polygon: LatLng[]): boolean {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [yi, xi] = polygon[i]
    const [yj, xj] = polygon[j]
    if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

// Code decides which marked area a caller is in. Evacuation zones win over warnings.
export function zoneFor(position: LatLng, zones: Zone[]): Zone | undefined {
  const hits = zones.filter((z) => pointInPolygon(position, z.polygon))
  return hits.find((z) => z.level === 'evacuate') ?? hits[0]
}

const SITUATION_RANK: Record<Call['situation'], number> = { trapped: 0, needs_help: 1, can_leave: 2 }
const STATUS_RANK: Record<Call['status'], number> = { active: 0, help_assigned: 1, instructed: 2, resolved: 3 }

export function byPriority(a: Call, b: Call): number {
  const resolved = Number(a.status === 'resolved') - Number(b.status === 'resolved')
  if (resolved) return resolved
  return SITUATION_RANK[a.situation] - SITUATION_RANK[b.situation] || STATUS_RANK[a.status] - STATUS_RANK[b.status] || a.startedAt - b.startedAt
}

export function elapsed(from: number, now: number): string {
  const s = Math.max(0, Math.floor((now - from) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
