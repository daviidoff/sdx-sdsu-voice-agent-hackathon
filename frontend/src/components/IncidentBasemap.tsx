import { useEffect, useMemo, useState } from 'react'
import { Pane, Polygon, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import type { LeafletMouseEvent } from 'leaflet'
import type { GeoJSONSource, Map as VectorMap } from 'maplibre-gl'
import { useWildfireFeatures, type FireFeatures } from '@/hooks/useWildfireFeatures'
import { AERIAL_ATTRIBUTION, AERIAL_LAYER, AERIAL_TILES, FIRE_FOOTPRINT, FIRE_SOURCE, OSM_ATTRIBUTION } from '@/lib/incident-map-style'
import { FIRE_STYLE } from '@/lib/fire-materials'
import type { LatLng, SimulatedFire } from '@/types'

export function IncidentBasemap({ aerial, fires, replays, drawing, onSelect, raster, onFallback }: {
  aerial: boolean; fires: SimulatedFire[]; replays: Record<string, number>; drawing: boolean
  onSelect: (id: string) => void; raster: boolean; onFallback: () => void
}) {
  const map = useMap()
  const data = useWildfireFeatures(fires, replays)
  const [renderer, setRenderer] = useState<VectorMap>()

  useEffect(() => {
    if (raster) return
    let disposed = false
    let close: (() => void) | undefined
    const fallback = () => { if (!disposed) onFallback() }
    void import('@/lib/vector-basemap').then(({ openVectorBasemap }) => {
      if (!disposed) close = openVectorBasemap(map, setRenderer, fallback)
    }).catch(fallback)
    return () => { disposed = true; close?.() }
  }, [map, raster, onFallback])

  useEffect(() => {
    const control = map.attributionControl
    if (!raster || !aerial) control?.addAttribution(OSM_ATTRIBUTION)
    if (aerial) control?.addAttribution(AERIAL_ATTRIBUTION)
    return () => {
      if (!raster || !aerial) control?.removeAttribution(OSM_ATTRIBUTION)
      if (aerial) control?.removeAttribution(AERIAL_ATTRIBUTION)
    }
  }, [map, aerial, raster])

  useEffect(() => {
    if (!renderer || raster) return
    renderer.setGlobalStateProperty(AERIAL_LAYER, aerial)
  }, [renderer, raster, aerial])
  useEffect(() => {
    if (!renderer || raster) return
    const source = renderer.getSource<GeoJSONSource>(FIRE_SOURCE)
    let current = true
    void source?.setData(data).catch(() => { if (current) onFallback() })
    return () => { current = false }
  }, [renderer, raster, data, onFallback])

  const pickLayers = useMemo(() => {
    if (!renderer || raster) return []
    return renderer.getStyle().layers.filter((layer) => layer.id === FIRE_FOOTPRINT || (layer.type === 'fill' &&
      (layer['source-layer'] === 'ocean' || layer['source-layer'] === 'water_polygons'))).map((layer) => layer.id)
  }, [renderer, raster])
  const pick = (e: LeafletMouseEvent) => {
    if (drawing || raster || !renderer || !data.features.length) return
    // Give operator zones and markers above the basemap their usual click priority.
    if (e.originalEvent.target instanceof Element && e.originalEvent.target.closest('.leaflet-interactive, .leaflet-control, button')) return
    const point = renderer.project([e.latlng.lng, e.latlng.lat])
    const [hit] = renderer.queryRenderedFeatures(point, { layers: pickLayers })
    if (hit?.layer.id === FIRE_FOOTPRINT) return String(hit.properties.fireId)
  }
  useMapEvents({
    click(e) { const id = pick(e); if (id) onSelect(id) },
    mousemove(e) { map.getContainer().classList.toggle('fire-under-pointer', !e.originalEvent.buttons && !!pick(e)) },
    mouseout() { map.getContainer().classList.remove('fire-under-pointer') },
  })

  return raster ? <RasterBasemap key={String(aerial)} aerial={aerial} data={data} fires={fires} drawing={drawing} onSelect={onSelect} /> : null
}

function RasterBasemap({ aerial, data, fires, drawing, onSelect }: {
  aerial: boolean; data: FireFeatures; fires: SimulatedFire[]; drawing: boolean; onSelect: (id: string) => void
}) {
  const [ready, setReady] = useState(false)
  const map = useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  const [zoom, setZoom] = useState(() => map.getZoom())
  const tileEvents = useMemo(() => ({ tileload: () => setReady(true) }), [])
  return <>
    <TileLayer className={aerial ? 'wildfire-aerial-basemap' : 'response-basemap'}
      url={aerial ? AERIAL_TILES : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'} eventHandlers={tileEvents} />
    {ready && <Pane name="wildfire" style={{ zIndex: 350 }}>
      {data.features.map((feature) => <RasterFireFeature key={`${feature.id}-${drawing}`} feature={feature} drawing={drawing} aerial={aerial} zoom={zoom}
        label={fires.find((fire) => fire.id === feature.properties.fireId)?.label} onSelect={onSelect} />)}
    </Pane>}
  </>
}

function RasterFireFeature({ feature, drawing, label, onSelect, aerial, zoom }: {
  feature: FireFeatures['features'][number]; drawing: boolean; label?: string; onSelect: (id: string) => void
  aerial: boolean; zoom: number
}) {
  const map = useMap()
  const { fireId, heat } = feature.properties
  const { geometry } = feature
  const latLng = ([lng, lat]: number[]): LatLng => [lat, lng]
  if (geometry.type === 'MultiPolygon') {
    const positions = geometry.coordinates.map(polygon => polygon.map(ring => ring.map(latLng)))
    const { part } = feature.properties
    if (part === 'scar' || part === 'core') return <Polygon positions={positions} interactive={false}
      pathOptions={{ stroke: false, fillColor: FIRE_STYLE[part], fillOpacity: heat * (part === 'scar' ? FIRE_STYLE.scarOpacity : FIRE_STYLE.coreOpacity) }} />
    return <Polygon positions={positions}
      className="wildfire-footprint" interactive={!drawing} bubblingMouseEvents={false}
      eventHandlers={drawing ? {} : { click: () => onSelect(fireId) }}
      pathOptions={{ color: aerial ? FIRE_STYLE.aerialPerimeter : FIRE_STYLE.perimeter, weight: 1.8, dashArray: '5.4 5.4',
        fillColor: `color-mix(in srgb, ${FIRE_STYLE.fill} ${heat * 100}%, ${FIRE_STYLE.core})`,
        fillOpacity: FIRE_STYLE.cooledOpacity + heat * (FIRE_STYLE.fillOpacity - FIRE_STYLE.cooledOpacity) }}>
      {!drawing && <Tooltip sticky>{label} · simulated wildfire</Tooltip>}
    </Polygon>
  }

  const lines = geometry.coordinates.map(line => line.map(latLng))
  const teeth: LatLng[][][] = []
  for (const line of lines) {
    const points = line.map(point => map.project(point, zoom))
    let next = FIRE_STYLE.spacing / 2
    for (let i = 1; i < points.length; i++) {
      const start = points[i - 1], end = points[i]
      const length = start.distanceTo(end)
      if (!length) continue
      const direction = end.subtract(start).divideBy(length)
      for (; next <= length; next += FIRE_STYLE.spacing) {
        const base = start.add(direction.multiplyBy(next))
        const half = direction.multiplyBy(FIRE_STYLE.toothWidth / 2)
        const tip = base.add([-direction.y * FIRE_STYLE.toothHeight, direction.x * FIRE_STYLE.toothHeight])
        teeth.push([[base.subtract(half), base.add(half), tip].map(point => {
          const { lat, lng } = map.unproject(point, zoom)
          return [lat, lng]
        })])
      }
      next -= length
    }
  }
  return <>
    <Polyline positions={lines} interactive={false} pathOptions={{ color: FIRE_STYLE.casing, weight: 7, opacity: heat }} />
    <Polyline positions={lines} interactive={false} pathOptions={{ color: FIRE_STYLE.front, weight: 3.8, opacity: heat }} />
    <Polygon positions={teeth} interactive={false} pathOptions={{ stroke: false, fillColor: FIRE_STYLE.front, fillOpacity: heat }} />
  </>
}
