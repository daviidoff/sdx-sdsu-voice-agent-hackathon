import { contours } from 'd3-contour'

type Point = { x: number; y: number }

export const FIRE_GRID_ZOOM = 12
export const SPREAD_TICKS = 232 // The demo advances one tick per second.
// Illustrative ground speed in still air with full fuel.
const METRES_PER_SECOND = 1.25
const WIND_BIAS = 0.59
const NEIGHBORS = [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]]
// Screen coordinates point east and south. The demo wind blows toward the northeast.
const FIRE_WIND = { x: 0.65, y: -0.76 }

export interface FireCell extends Point {
  index: number
  ignition: number
  duration: number
}

export interface Wildfire {
  origin: Point
  cellSize: number
  width: number
  height: number
  cells: FireCell[]
  endTick: number
}

// Include the final cooled frame once, then replay the same drawn ignition.
export function firePlaybackTick(elapsedMs: number, endTick: number) {
  const elapsedTicks = Math.max(0, Math.floor(elapsedMs / 1000))
  return elapsedTicks % (endTick + 1)
}

function noise(x: number, y: number, seed: number) {
  const bits = Math.imul(x, 374761393) + Math.imul(y, 668265263) + seed
  const mixed = Math.imul(bits ^ (bits >>> 13), 1274126177)
  return ((mixed ^ (mixed >>> 16)) >>> 0) / 4294967296
}

function fuelAt(x: number, y: number, seed: number) {
  const fieldX = x / 8
  const fieldY = y / 8
  const left = Math.floor(fieldX)
  const top = Math.floor(fieldY)
  const u = fieldX - left
  const v = fieldY - top
  const upper = noise(left, top, seed) * (1 - u) + noise(left + 1, top, seed) * u
  const lower = noise(left, top + 1, seed) * (1 - u) + noise(left + 1, top + 1, seed) * u
  return 0.2 + 0.8 * (upper * (1 - v) + lower * v)
}

function inside(x: number, y: number, polygon: Point[]) {
  let hit = false
  let previous = polygon[polygon.length - 1]
  for (const point of polygon) {
    if ((point.y > y) !== (previous.y > y) && x < (previous.x - point.x) * (y - point.y) / (previous.y - point.y) + point.x) hit = !hit
    previous = point
  }
  return hit
}

export function modelWildfire(polygon: Point[], id: string, metresPerUnit: number): Wildfire | undefined {
  if (polygon.length < 3 || !Number.isFinite(metresPerUnit) || metresPerUnit <= 0) return
  const xs = polygon.map(({ x }) => x)
  const ys = polygon.map(({ y }) => y)
  const left = Math.min(...xs)
  const top = Math.min(...ys)
  const spanX = Math.max(...xs) - left
  const spanY = Math.max(...ys) - top
  const span = Math.max(spanX, spanY)
  if (!Number.isFinite(span) || span <= 0) return
  const cellSize = Math.max(5 / metresPerUnit, span / 160)
  const cellMetres = cellSize * metresPerUnit
  const margin = Math.ceil(SPREAD_TICKS * METRES_PER_SECOND * (1 + WIND_BIAS) / cellMetres) + 2

  const seed = Array.from(id).reduce((value, char) => Math.imul(value, 31) + char.charCodeAt(0) | 0, 0)
  const origin = { x: left - margin * cellSize, y: top - margin * cellSize }
  const width = Math.ceil(spanX / cellSize) + margin * 2 + 1
  const height = Math.ceil(spanY / cellSize) + margin * 2 + 1
  const gridPolygon = polygon.map(({ x, y }) => ({ x: (x - origin.x) / cellSize, y: (y - origin.y) / cellSize }))
  const ignition = new Float32Array(width * height).fill(Infinity)
  const fuel = new Float32Array(ignition.length)
  const queue = Array.from({ length: SPREAD_TICKS + 1 }, () => [] as number[])
  const igniteSeed = (x: number, y: number) => {
    const index = y * width + x
    if (ignition[index] === Infinity) {
      ignition[index] = -Math.floor(noise(x, y, seed) * 16)
      queue[0].push(index)
    }
  }

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      fuel[y * width + x] = fuelAt(x, y, seed)
      if (x >= margin && x <= width - margin && y >= margin && y <= height - margin && inside(x + 0.5, y + 0.5, gridPolygon)) igniteSeed(x, y)
    }
  }
  // Sample edges too so even a very narrow drawn area gets an ignition line.
  for (const [index, from] of gridPolygon.entries()) {
    const to = gridPolygon[(index + 1) % gridPolygon.length]
    const steps = Math.max(1, Math.ceil(Math.hypot(to.x - from.x, to.y - from.y) * 2))
    for (let step = 0; step < steps; step++) {
      igniteSeed(Math.floor(from.x + (to.x - from.x) * step / steps), Math.floor(from.y + (to.y - from.y) * step / steps))
    }
  }

  // Visit ignition events in time order. Each burning cell can ignite its neighbors;
  // the earliest arrival wins when two parts of the front reach the same fuel.
  const directions = NEIGHBORS.map(([dx, dy]) => {
    const distance = Math.hypot(dx, dy)
    const tailwind = (dx * FIRE_WIND.x + dy * FIRE_WIND.y) / distance
    return { dx, dy, delay: cellMetres * distance / (METRES_PER_SECOND * (1 + WIND_BIAS * tailwind)) }
  })
  for (const [tick, burning] of queue.entries()) {
    for (const index of burning) {
      if (Math.max(0, ignition[index]) !== tick) continue
      for (const { dx, dy, delay } of directions) {
        const x = index % width + dx
        const y = Math.floor(index / width) + dy
        if (x < 0 || x >= width || y < 0 || y >= height) continue
        const neighbor = y * width + x
        const arrival = tick + Math.ceil(delay / fuel[neighbor])
        if (arrival <= SPREAD_TICKS && arrival < ignition[neighbor]) {
          ignition[neighbor] = arrival
          queue[arrival].push(neighbor)
        }
      }
    }
  }

  const cells: FireCell[] = []
  let endTick = 0
  for (const [index, tick] of ignition.entries()) {
    if (!Number.isFinite(tick)) continue
    const x = index % width
    const y = Math.floor(index / width)
    const duration = 18 + Math.round(fuel[index] * 15)
    cells.push({ index, x, y, ignition: tick, duration })
    endTick = Math.max(endTick, tick + duration)
  }
  return { origin, cellSize, width, height, cells, endTick }
}

export function fireContours(model: Wildfire) {
  const { width, height, origin, cellSize } = model
  const arrival = new Array<number>(width * height).fill(-(model.endTick + 12))
  for (const { index, ignition } of model.cells) arrival[index] = -ignition
  const generate = contours().size([width, height])
  const contour = (field: number[], level: number) => generate.contour(field, level).coordinates.map((polygon) =>
    polygon.map((ring) => ring.map(([x, y]) => ({ x: origin.x + x * cellSize, y: origin.y + y * cellSize }))))
  return (tick: number) => {
    const level = -Math.min(tick, SPREAD_TICKS)
    const footprint = contour(arrival, level)
    const heat = Math.min(1, (model.endTick - tick) / Math.max(1, model.endTick - SPREAD_TICKS))
    if (heat <= 0) return { footprint, scar: [], core: [], heat: 0 }

    // Distance from the current edge, in grid cells. A lower cost walking back
    // from the northeast front leaves a wider red shoulder on its advancing side.
    const depth = arrival.map(value => value >= level ? Infinity : 0)
    for (let y = 1; y < height - 1; y++) for (let x = 1; x < width - 1; x++) {
      const i = y * width + x
      depth[i] = Math.min(depth[i], depth[i - 1] + 1.3, depth[i - width] + 0.7, depth[i - width + 1] + 0.85, depth[i - width - 1] + 1.4)
    }
    for (let y = height - 2; y >= 1; y--) for (let x = width - 2; x >= 1; x--) {
      const i = y * width + x
      depth[i] = Math.min(depth[i], depth[i + 1] + 0.7, depth[i + width] + 1.3, depth[i + width - 1] + 1.9, depth[i + width + 1] + 1.4)
    }
    // The drawn seed represents an established burn. Newly reached cells must
    // also finish burning before they can join the contiguous interior scar.
    for (const cell of model.cells) {
      if (cell.ignition > 0) depth[cell.index] = Math.min(depth[cell.index], Math.max(0, tick - cell.ignition - cell.duration))
    }
    return { footprint, scar: contour(depth, 1 + 2.2 * heat), core: contour(depth, 1 + 5.5 * heat), heat }
  }
}

// Find the stretches where the simulated wind blows out of the burn scar.
// Average the tangent over neighboring contour cells to avoid short breaks.
export function windFacingEdges(footprint: Point[][][]) {
  const lines: Point[][] = []
  for (const [ring] of footprint) {
    const n = ring.length - 1
    const radius = Math.min(3, Math.floor((n - 2) / 2))
    let line: Point[] | undefined
    for (let i = 0; i < n; i++) {
      const before = ring[(i - radius + n) % n], after = ring[(i + radius + 1) % n]
      const dx = after.x - before.x, dy = after.y - before.y
      const outwardWind = dx * FIRE_WIND.y - dy * FIRE_WIND.x
      if (outwardWind <= 0.32 * Math.hypot(dx, dy)) { line = undefined; continue }
      if (!line) { line = [ring[i]]; lines.push(line) }
      line.push(ring[i + 1])
    }
  }
  return lines
}
