import assert from 'node:assert/strict'
import test from 'node:test'
import { AERIAL_LAYER, FIRE_FOOTPRINT, FIRE_SOURCE, incidentMapStyle } from '../src/lib/incident-map-style.ts'
import { FRONT_TOOTH } from '../src/lib/fire-materials.ts'

test('the fire and aerial imagery share the OSM style, below water, roads, buildings and labels', () => {
  const base = { version: 8, sources: { osm: { type: 'vector', tiles: ['https://example.test/{z}/{x}/{y}.mvt'] } }, layers: [
    { id: 'background', type: 'background' },
    ...[['sea', 'fill', 'ocean'], ['park', 'fill', 'land'], ['lake', 'fill', 'water_polygons'],
      ['buildings', 'fill', 'buildings'], ['road', 'line', 'streets'], ['names', 'symbol', 'place_labels']]
      .map(([id, type, sourceLayer]) => ({ id, type, source: 'osm', 'source-layer': sourceLayer })),
  ] }
  const style = incidentMapStyle(base)
  assert.equal(style.sources.osm, base.sources.osm)
  assert.equal(style.sources[FIRE_SOURCE].type, 'geojson')
  assert.deepEqual(style.sources[FIRE_SOURCE].data.features, [])
  assert.equal(style.sources[AERIAL_LAYER].type, 'raster')
  assert.equal(style.state[AERIAL_LAYER].default, false)
  const ids = style.layers.map(({ id }) => id)
  assert.equal(new Set(ids).size, ids.length)
  const fire = style.layers.filter((layer) => layer.source === FIRE_SOURCE).map(({ id }) => id)
  assert.ok(fire.includes(FIRE_FOOTPRINT))
  for (const id of fire) {
    assert.ok(ids.indexOf('park') < ids.indexOf(AERIAL_LAYER) && ids.indexOf(AERIAL_LAYER) < ids.indexOf(id))
    for (const reference of ['sea', 'lake', 'road', 'buildings', 'names']) assert.ok(ids.indexOf(id) < ids.indexOf(reference))
  }
})

test('direction markers follow the simulated head and leave the footprint selectable', () => {
  const { layers } = incidentMapStyle({ version: 8, sources: {}, layers: [] })
  const teeth = layers.find(layer => layer.layout?.['icon-image'] === FRONT_TOOTH)
  assert.deepEqual(teeth.filter, ['==', 'part', 'head'])
  assert.equal(teeth.layout['symbol-placement'], 'line')
  assert.equal(teeth.layout['icon-ignore-placement'], true)
  assert.deepEqual(teeth.paint['icon-opacity'], ['get', 'heat'])
  assert.deepEqual(layers.find(layer => layer.id === FIRE_FOOTPRINT).filter, ['==', 'part', 'footprint'])
})

test('Neutrino ground and land fills use neutral colors while border and vegetation colors are retained', () => {
  const background = { id: 'background', type: 'background', paint: { 'background-color': 'rgb(246,240,246)' } }
  const residential = { id: 'land-residential', type: 'fill', source: 'osm', 'source-layer': 'land',
    paint: { 'fill-color': 'rgb(239,233,239)', 'fill-opacity': 0.8 } }
  const forest = { ...residential, id: 'land-forest', paint: { 'fill-color': 'rgb(217,227,217)' } }
  const border = { id: 'boundary-country', type: 'line', source: 'osm', 'source-layer': 'boundaries',
    paint: { 'line-color': 'rgb(230,204,216)' } }
  const { layers } = incidentMapStyle({ version: 8, sources: {}, layers: [background, residential, forest, border] })
  const byId = new Map(layers.map(layer => [layer.id, layer]))

  assert.equal(byId.get('background').paint['background-color'], '#f1f2f0')
  assert.deepEqual(byId.get('land-residential').paint, { 'fill-color': '#e8eae7', 'fill-opacity': 0.8 })
  assert.deepEqual(byId.get('land-forest'), forest)
  assert.deepEqual(byId.get('boundary-country'), border)
})
