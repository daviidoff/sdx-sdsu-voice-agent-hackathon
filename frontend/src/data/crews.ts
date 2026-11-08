// Simulated crews from the team's data/resources.json (a local, git-ignored file).
// Read when the dashboard is built; if the file is missing, the map just shows no crews.
// Rebuild the dashboard after editing the file.
import type { Responder } from '@/types'

const files = import.meta.glob('../../../data/resources.json', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

type Row = { id: string; name?: string; kind?: string; passenger_capacity?: number; wheelchair_capacity?: number; lat?: number; lng?: number }

const toCrew = (r: Row): Responder => ({
  id: r.id,
  name: r.name ?? r.id,
  kind: r.kind === 'engine' ? 'engine' : r.kind === 'ambulance' ? 'ambulance' : 'wheelchair_van',
  position: [r.lat as number, r.lng as number],
  status: 'available',
  wheelchair: (r.wheelchair_capacity ?? 0) > 0,
  seats: r.passenger_capacity ?? 0,
})

export const crews: Responder[] = Object.values(files).flatMap((raw) => {
  try {
    const rows = JSON.parse(raw) as Row[]
    return rows.filter((r) => typeof r.lat === 'number' && typeof r.lng === 'number').map(toCrew)
  } catch {
    return []
  }
})
