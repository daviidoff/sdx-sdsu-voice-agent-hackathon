import type { Call, LatLng, LocationCandidate } from '@/types'

function candidatePosition(candidate: LocationCandidate): LatLng | undefined {
  const { lat, lng } = candidate
  return typeof lat === 'number' && typeof lng === 'number' && Number.isFinite(lat) && Number.isFinite(lng)
    && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? [lat, lng] : undefined
}

/** Alternatives are lookup results, never a confirmed caller position. */
export function callMapCandidates(call?: Call): { position: LatLng; label: string }[] {
  const resolution = call?.locationResolution
  if (!call || call.position || resolution?.status !== 'ambiguous'
    || (resolution.query && resolution.query !== call.locationQuery)) return []
  const unique = new Set<string>()
  return (resolution.candidates ?? []).flatMap((candidate) => {
    const position = candidatePosition(candidate)
    if (!position || unique.has(position.join(','))) return []
    unique.add(position.join(','))
    return [{ position, label: candidate.display_name || call.address }]
  })
}

export function callMapUncertaintyBounds(call?: Call): LatLng[] {
  if (!callMapCandidates(call).length) return []
  const bounds = call?.locationResolution?.uncertainty_bounds
  if (!bounds || bounds.length !== 4) return []
  const [west, north, east, south] = bounds
  if (!candidatePosition({ lat: north, lng: west }) || !candidatePosition({ lat: south, lng: east })
    || west > east || south > north) return []
  return [[north, west], [north, east], [south, east], [south, west]]
}

/** Serialize geographic values so polling object identity cannot retrigger map movement. */
export function mapFocusKey(target?: LatLng, candidates: { position: LatLng }[] = [], bounds: LatLng[] = []): string {
  return JSON.stringify(target ? [target] : [...candidates.map((candidate) => candidate.position), ...bounds])
}
