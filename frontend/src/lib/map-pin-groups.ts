import type { LatLng } from '@/types'

const PIN_GROUP_RADIUS = 52

/** Compare world pixels at the current zoom so panning cannot change membership. */
export function groupMapPins<T extends { position: LatLng }>(
  pins: T[],
  project: (position: LatLng) => { x: number; y: number },
) {
  const groups: { anchor: T; point: { x: number; y: number }; pins: T[] }[] = []
  for (const pin of pins) {
    const point = project(pin.position)
    let nearest: typeof groups[number] | undefined
    let distance = PIN_GROUP_RADIUS
    for (const group of groups) {
      const gap = Math.hypot(point.x - group.point.x, point.y - group.point.y)
      if (gap < distance) {
        nearest = group
        distance = gap
      }
    }
    // Keep the anchor fixed so neighboring badges retain their spacing.
    if (nearest) nearest.pins.push(pin)
    else groups.push({ anchor: pin, point, pins: [pin] })
  }
  return groups
}
