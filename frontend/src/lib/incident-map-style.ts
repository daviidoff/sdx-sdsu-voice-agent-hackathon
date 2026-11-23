import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from 'maplibre-gl'
import { FIRE_STYLE, FRONT_TOOTH } from './fire-materials.ts'

export const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
export const AERIAL_ATTRIBUTION = '<a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USDA, USGS National Geospatial Program</a>'
export const AERIAL_TILES = 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}'
export const FIRE_SOURCE = 'incident-fires'
export const FIRE_FOOTPRINT = 'incident-fire-footprint'
export const AERIAL_LAYER = 'incident-aerial'
const aerialEnabled: ExpressionSpecification = ['boolean', ['global-state', AERIAL_LAYER], false]
const fireLayers: LayerSpecification[] = [
  { id: FIRE_FOOTPRINT, type: 'fill', source: FIRE_SOURCE, filter: ['==', 'part', 'footprint'],
    paint: { 'fill-color': ['interpolate', ['linear'], ['get', 'heat'], 0, FIRE_STYLE.core, 1, FIRE_STYLE.fill],
      'fill-opacity': ['interpolate', ['linear'], ['get', 'heat'], 0, FIRE_STYLE.cooledOpacity, 1, FIRE_STYLE.fillOpacity] } },
  { id: 'incident-fire-scar', type: 'fill', source: FIRE_SOURCE, filter: ['==', 'part', 'scar'],
    paint: { 'fill-color': FIRE_STYLE.scar, 'fill-opacity': ['*', FIRE_STYLE.scarOpacity, ['get', 'heat']] } },
  { id: 'incident-fire-core', type: 'fill', source: FIRE_SOURCE, filter: ['==', 'part', 'core'],
    paint: { 'fill-color': FIRE_STYLE.core, 'fill-opacity': ['*', FIRE_STYLE.coreOpacity, ['get', 'heat']] } },
  { id: 'incident-fire-perimeter', type: 'line', source: FIRE_SOURCE, filter: ['==', 'part', 'footprint'],
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': ['case', aerialEnabled, FIRE_STYLE.aerialPerimeter, FIRE_STYLE.perimeter],
      'line-width': 1.8, 'line-dasharray': [3, 3] } },
  { id: 'incident-fire-head-casing', type: 'line', source: FIRE_SOURCE, filter: ['==', 'part', 'head'],
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': FIRE_STYLE.casing, 'line-width': 7, 'line-opacity': ['get', 'heat'] } },
  { id: 'incident-fire-head', type: 'line', source: FIRE_SOURCE, filter: ['==', 'part', 'head'],
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': FIRE_STYLE.front, 'line-width': 3.8, 'line-opacity': ['get', 'heat'] } },
  { id: 'incident-fire-teeth', type: 'symbol', source: FIRE_SOURCE, filter: ['==', 'part', 'head'],
    layout: { 'symbol-placement': 'line', 'symbol-spacing': FIRE_STYLE.spacing, 'icon-image': FRONT_TOOTH,
      'icon-allow-overlap': true, 'icon-ignore-placement': true, 'icon-rotation-alignment': 'map', 'icon-keep-upright': false },
    paint: { 'icon-opacity': ['get', 'heat'] } },
]

const neutrinoGround = 'rgb(246,240,246)'
const neutralGround = '#f1f2f0'
const neutralLandColors = new Map([
  [neutrinoGround, neutralGround],
  ['rgb(239,233,239)', '#e8eae7'],
  ['rgb(248,238,238)', '#edeee8'],
])

function referenceLayer(layer: LayerSpecification): LayerSpecification {
  if (layer.type === 'background' && layer.paint?.['background-color'] === neutrinoGround) {
    return { ...layer, paint: { ...layer.paint, 'background-color': neutralGround } }
  }
  if (layer.type === 'fill' && layer['source-layer'] === 'land' && typeof layer.paint?.['fill-color'] === 'string') {
    const color = neutralLandColors.get(layer.paint['fill-color'])
    if (color) return { ...layer, paint: { ...layer.paint, 'fill-color': color } }
  }
  // Keep names legible over the fire perimeter and reference lines light over photography.
  if (layer.type === 'symbol' && layer.layout?.['text-field']) {
    return { ...layer, paint: { ...layer.paint,
      'text-color': ['case', aerialEnabled, '#f8f5ed', '#475153'],
      'text-halo-color': ['case', aerialEnabled, '#292928', '#faf8f5'], 'text-halo-width': 1.1, 'text-halo-blur': 0.3,
    } }
  }
  if (layer.type === 'line' && layer['source-layer'] === 'streets' && typeof layer.paint?.['line-color'] === 'string') {
    const aerialColor = layer.id.endsWith(':outline') ? 'rgba(33,41,44,0.12)' : 'rgba(249,244,229,0.22)'
    return { ...layer, paint: { ...layer.paint, 'line-color': ['case', aerialEnabled, aerialColor, layer.paint['line-color']] } }
  }
  if (layer.type === 'fill' && ['ocean', 'water_polygons'].includes(layer['source-layer'] ?? '') && typeof layer.paint?.['fill-color'] === 'string') {
    return { ...layer, paint: { ...layer.paint, 'fill-color': ['case', aerialEnabled, '#253f4a', layer.paint['fill-color']] } }
  }
  if (layer.type === 'fill' && ['buildings', 'sites', 'street_polygons'].includes(layer['source-layer'] ?? '') && typeof layer.paint?.['fill-color'] === 'string') {
    return { ...layer, paint: { ...layer.paint, 'fill-color': ['case', aerialEnabled, 'rgba(235,230,215,0.16)', layer.paint['fill-color']] } }
  }
  return layer
}

export function incidentMapStyle(base: StyleSpecification): StyleSpecification {
  // Shortbread draws the ocean first. Draw it alongside inland water so both
  // stay visible over the incident. Streets, buildings and labels follow them.
  const isOcean = (layer: LayerSpecification) => layer.type === 'fill' && layer['source-layer'] === 'ocean'
  const ocean = base.layers.filter(isOcean).map(referenceLayer)
  const layers = base.layers.filter((layer) => !isOcean(layer)).map(referenceLayer)
  const split = layers.findIndex((layer) => layer.type === 'symbol' || ('source-layer' in layer &&
    (['water_lines', 'streets', 'street_polygons', 'buildings'].includes(layer['source-layer'] ?? '') ||
      (layer['source-layer'] === 'water_polygons' && layer.id !== 'land-glacier'))))
  const index = split < 0 ? layers.length : split
  const aerial: LayerSpecification = { id: AERIAL_LAYER, type: 'raster', source: AERIAL_LAYER,
    layout: { visibility: ['case', aerialEnabled, 'visible', 'none'] }, paint: { 'raster-brightness-max': 0.85, 'raster-saturation': -0.12 } }
  return { ...base, state: { ...base.state, [AERIAL_LAYER]: { default: false } }, sources: { ...base.sources,
    [AERIAL_LAYER]: { type: 'raster', tiles: [AERIAL_TILES], tileSize: 256, maxzoom: 19 },
    [FIRE_SOURCE]: { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, maxzoom: 20, tolerance: 0.2 },
  }, layers: [...layers.slice(0, index), aerial, ...fireLayers, ...ocean, ...layers.slice(index)] }
}
