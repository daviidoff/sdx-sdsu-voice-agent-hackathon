import { useEffect, useRef, useState } from 'react'
import { useMap } from 'react-leaflet'
import type { Feature, FeatureCollection, MultiLineString, MultiPolygon } from 'geojson'
import { FIRE_GRID_ZOOM, fireContours, firePlaybackTick, modelWildfire, windFacingEdges } from '@/lib/wildfire'
import type { SimulatedFire } from '@/types'

type FireFeature = Feature<MultiPolygon | MultiLineString, { fireId: string; part: 'footprint' | 'scar' | 'core' | 'head'; heat: number; simulated: true }>
export type FireFeatures = FeatureCollection<FireFeature['geometry'], FireFeature['properties']>
export const EMPTY_FIRES: FireFeatures = { type: 'FeatureCollection', features: [] }

interface Run {
  geometry: string
  replay: number
  started: number
  endTick: number
  contoursAt: ReturnType<typeof fireContours>
  tick: number
  features: FireFeature[]
}

// A demo replay belongs to this dashboard tab. Refreshing the map resumes it.
function playbackStart(id: string, geometry: string, restart: boolean) {
  const now = Date.now()
  const key = `wildfire.playback.${id}`
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) ?? 'null')
    if (!restart && stored?.geometry === geometry && Number.isFinite(stored.started) && stored.started <= now) return stored.started as number
    sessionStorage.setItem(key, JSON.stringify({ geometry, started: now }))
  } catch { /* The run still works when tab storage is disabled. */ }
  return now
}

export function useWildfireFeatures(fires: SimulatedFire[], replays: Record<string, number>) {
  const map = useMap()
  const runs = useRef(new Map<string, Run>())
  const [data, setData] = useState<FireFeatures>(EMPTY_FIRES)
  useEffect(() => {
    const current = runs.current
    const ids = new Set(fires.map((fire) => fire.id))
    let changed = false
    for (const id of current.keys()) {
      if (!ids.has(id)) { current.delete(id); changed = true }
    }
    for (const fire of fires) {
      const geometry = JSON.stringify(fire.polygon)
      const previous = current.get(fire.id)
      const replay = replays[fire.id] ?? 0
      if (previous?.geometry === geometry && previous.replay === replay) continue
      const points = fire.polygon.map((point) => map.project(point, FIRE_GRID_ZOOM))
      if (!points.length) { current.delete(fire.id); changed = true; continue }
      // Mercator scale varies by latitude. Measure one projected unit on the
      // ground so a larger drawing or a camera zoom never speeds up the fire.
      const groundScale = map.distance(fire.polygon[0], map.unproject(points[0].add([1, 0]), FIRE_GRID_ZOOM))
      const model = modelWildfire(points, fire.id, groundScale)
      if (!model) { current.delete(fire.id); changed = true; continue }
      const started = playbackStart(fire.id, geometry, !!previous && previous.replay !== replay)
      current.set(fire.id, { geometry, replay, started, endTick: model.endTick, contoursAt: fireContours(model), tick: -1, features: [] })
    }

    let timer: number | undefined
    const update = () => {
      const now = Date.now()
      for (const [id, run] of current) {
        const tick = firePlaybackTick(now - run.started, run.endTick)
        if (run.tick === tick) continue
        const frame = run.contoursAt(tick)
        const { heat, footprint } = frame
        const coordinate = ({ x, y }: { x: number; y: number }) => {
          const { lat, lng } = map.unproject([x, y], FIRE_GRID_ZOOM)
          return [lng, lat]
        }
        run.features = []
        for (const part of ['footprint', 'scar', 'core'] as const) {
          if (!frame[part].length) continue
          run.features.push({ type: 'Feature', id: `${id}/${part}`, properties: { fireId: id, part, heat, simulated: true },
            geometry: { type: 'MultiPolygon', coordinates: frame[part].map(polygon => polygon.map(ring => ring.map(coordinate))) } })
        }
        if (heat > 0) {
          const head = windFacingEdges(footprint)
          if (head.length) run.features.push({ type: 'Feature', id: `${id}/head`, properties: { fireId: id, part: 'head', heat, simulated: true },
            geometry: { type: 'MultiLineString', coordinates: head.map((line) => line.map(coordinate)) } })
        }
        run.tick = tick
        changed = true
      }
      if (changed) {
        setData({ type: 'FeatureCollection', features: Array.from(current.values()).flatMap((run) => run.features) })
        changed = false
      }
      if (current.size) timer = window.setTimeout(update, 1000)
    }
    timer = window.setTimeout(update, 0)
    return () => window.clearTimeout(timer)
  }, [fires, replays, map])
  return data
}
