import type L from 'leaflet'
import { maplibreGL } from '@maplibre/maplibre-gl-leaflet'
import { setWorkerUrl, type Map as VectorMap } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import { incidentMapStyle } from './incident-map-style'
import { FRONT_TOOTH, frontToothImage } from './fire-materials'

setWorkerUrl(workerUrl)

export function openVectorBasemap(map: L.Map, ready: (renderer: VectorMap) => void, fallback: () => void) {
  const layer = maplibreGL({
    style: import.meta.env.VITE_OSM_STYLE_URL || 'https://vector.openstreetmap.org/styles/shortbread/neutrino.json',
    transformStyle: (_previous, next) => incidentMapStyle(next),
    interactive: false, attributionControl: false,
    canvasContextAttributes: { antialias: true, powerPreference: 'low-power' },
  })
  try {
    layer.addTo(map)
  } catch {
    // Leaflet has already registered the layer when WebGL creation fails.
    // The adapter's normal onRemove assumes the GL map was constructed.
    if (!layer.getMaplibreMap()) layer.onRemove = () => { layer.getContainer()?.remove(); return layer }
    layer.remove()
    fallback()
    return () => {}
  }
  const renderer = layer.getMaplibreMap()
  layer.getCanvas().setAttribute('aria-hidden', 'true')
  layer.getCanvas().tabIndex = -1
  let loaded = false
  renderer.setMissingStyleImageResolver((id) => {
    if (id === FRONT_TOOTH) renderer.addImage(id, frontToothImage(), { pixelRatio: 2 })
  })
  const onLoad = () => { loaded = true; ready(renderer) }
  renderer.once('load', onLoad)
  // A style or basemap tile failure on startup should still leave a usable map.
  renderer.on('error', (event) => {
    if (loaded) return
    const source = 'sourceId' in event && typeof event.sourceId === 'string' ? renderer.getSource(event.sourceId) : undefined
    if (!renderer.getStyle()?.layers?.length || source?.type === 'vector') fallback()
  })
  return () => { renderer.off('load', onLoad); layer.remove() }
}
