import assert from 'node:assert/strict'
import test from 'node:test'
import { fireContours, firePlaybackTick, modelWildfire, SPREAD_TICKS, windFacingEdges } from '../src/lib/wildfire.ts'

const ignitionArea = [{ x: 120, y: 100 }, { x: 200, y: 100 }, { x: 200, y: 150 }, { x: 120, y: 150 }]

test('spread starts in the drawn footprint, ignites neighboring fuel, then burns out', () => {
  const fire = modelWildfire(ignitionArea, 'demo', 1)
  const burning = (tick) => fire.cells.filter((cell) => cell.ignition <= tick && tick < cell.ignition + cell.duration)
  const worldX = (cell) => fire.origin.x + (cell.x + 0.5) * fire.cellSize
  const initial = burning(0)
  const front = burning(100)
  assert.ok(initial.length > 0)
  assert.ok(initial.every((cell) => worldX(cell) <= 200 + fire.cellSize / 2))
  assert.ok(front.some((cell) => worldX(cell) > 210))
  assert.ok(front.every((cell) => cell.ignition > 0))
  assert.equal(burning(fire.endTick).length, 0)

  for (const cell of fire.cells) {
    if (cell.ignition <= 0) continue
    assert.ok(fire.cells.some((other) => other.ignition < cell.ignition && Math.abs(other.x - cell.x) <= 1 && Math.abs(other.y - cell.y) <= 1))
  }
})

test('vector footprints expand gradually and hold position while the last heat cools', () => {
  const fire = modelWildfire(ignitionArea, 'demo', 1)
  const at = fireContours(fire)
  const furthestEast = (shapes) => Math.max(...shapes.flat(2).map(({ x }) => x))
  const start = furthestEast(at(0).footprint)
  const early = furthestEast(at(25).footprint)
  const later = furthestEast(at(100).footprint)
  assert.ok(Number.isFinite(start) && start < 200 + 2 * fire.cellSize)
  assert.ok(early > start && early < later)
  assert.ok(later > 210)
  assert.deepEqual(at(fire.endTick).footprint, at(SPREAD_TICKS).footprint)
})

test('the hotter head follows the north and east sides of the actual perimeter', () => {
  const nw = { x: 0, y: 0 }, ne = { x: 4, y: 0 }, se = { x: 4, y: 4 }, sw = { x: 0, y: 4 }
  const lines = windFacingEdges([[[ne, nw, sw, se, ne]]])
  const segments = lines.flatMap(line => line.slice(1).map((end, i) => [line[i], end]))
  assert.deepEqual(segments, [[ne, nw], [se, ne]])
})

test('a narrow ignition area still lights and replay reproduces the same fuel and spread', () => {
  const thinArea = [{ x: 0, y: 1 }, { x: 100, y: 1.2 }, { x: 0, y: 1.4 }]
  const fire = modelWildfire(thinArea, 'thin', 1)
  assert.ok(fire.cells.some((cell) => cell.ignition === 0))
  assert.ok(fire.cells.some((cell) => cell.ignition > 0))
  assert.deepEqual(modelWildfire(thinArea, 'thin', 1), fire)
})

test('a city-sized ignition still advances only a short ground distance each minute', () => {
  for (const width of [150, 12_000]) {
    const polygon = [{ x: 0, y: 0 }, { x: width, y: 0 }, { x: width, y: width }, { x: 0, y: width }]
    const fire = modelWildfire(polygon, 'scale', 1)
    const at = fireContours(fire)
    const east = (tick) => Math.max(...at(tick).footprint.flat(2).map(({ x }) => x))
    const advance = east(120) - east(0)
    assert.ok(advance > 0 && advance <= 240, `${width} m seed advanced ${advance} m`)
    const scaled = modelWildfire(polygon.map(({ x, y }) => ({ x: x / 10, y: y / 10 })), 'scale', 10)
    assert.deepEqual(scaled.cells, fire.cells)
  }
})

test('a broad ignition develops one nested scar and core and cools to a single footprint', () => {
  const box = [{ x: 0, y: 0 }, { x: 8000, y: 0 }, { x: 8000, y: 8000 }, { x: 0, y: 8000 }]
  const fire = modelWildfire(box, 'san-diego', 1)
  const at = fireContours(fire)
  const frame = at(60)
  const area = ([ring]) => Math.abs(ring.slice(1).reduce((sum, p, i) => sum + ring[i].x * p.y - p.x * ring[i].y, 0)) / 2
  for (const part of ['footprint', 'scar', 'core']) assert.equal(frame[part].length, 1)
  assert.ok(area(frame.core[0]) < area(frame.scar[0]))
  assert.ok(area(frame.scar[0]) < area(frame.footprint[0]))
  assert.ok(area(frame.core[0]) > area(frame.footprint[0]) * 0.6)
  assert.deepEqual(at(fire.endTick), { footprint: at(SPREAD_TICKS).footprint, scar: [], core: [], heat: 0 })
})

test('the starting fire contour follows the drawn edges and corners within grid resolution', () => {
  const drawings = {
    square: [[0, 0], [500, 0], [500, 500], [0, 500]],
    triangle: [[0, 0], [470, 135], [70, 490]],
    concave: [[0, 0], [500, 0], [500, 180], [190, 180], [190, 500], [0, 500]],
    slender: [[80, 20], [120, 0], [360, 450], [320, 470]],
  }
  function distanceToRing(point, ring) {
    return Math.min(...ring.map((a, i) => {
      const b = ring[(i + 1) % ring.length]
      const dx = b.x - a.x, dy = b.y - a.y
      const lengthSquared = dx * dx + dy * dy
      const t = lengthSquared ? Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared)) : 0
      return Math.hypot(point.x - a.x - t * dx, point.y - a.y - t * dy)
    }))
  }
  for (const [name, vertices] of Object.entries(drawings)) {
    const drawing = vertices.map(([x, y]) => ({ x, y }))
    const fire = modelWildfire(drawing, 'same-fuel', 1)
    const footprint = fireContours(fire)(0).footprint
    assert.equal(footprint.length, 1, name)
    assert.equal(footprint[0].length, 1, name)
    const ring = footprint[0][0]
    for (const point of drawing) assert.ok(distanceToRing(point, ring) <= 2 * fire.cellSize, name + ' lost a corner')
    for (const point of ring) assert.ok(distanceToRing(point, drawing) <= 2 * fire.cellSize, name + ' substituted an edge')
  }
})

test('a saved demo returns to an active front after burnout, including after a long absence', () => {
  const fire = modelWildfire(ignitionArea, 'replay', 1)
  const at = fireContours(fire)
  const cycleMs = (fire.endTick + 1) * 1000
  assert.equal(at(firePlaybackTick(cycleMs - 1, fire.endTick)).heat, 0)
  assert.deepEqual(at(firePlaybackTick(cycleMs, fire.endTick)), at(0))
  const resumed = at(firePlaybackTick(100 * cycleMs + 60_000, fire.endTick))
  assert.ok(resumed.heat > 0)
  assert.ok(windFacingEdges(resumed.footprint).length > 0)
  assert.deepEqual(resumed, at(60))
})
