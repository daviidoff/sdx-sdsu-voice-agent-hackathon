// Shared cartographic symbols for the vector and raster maps.
export const FIRE_STYLE = {
  fill: '#e93e2d',
  fillOpacity: 0.54,
  scar: '#302d31',
  scarOpacity: 0.42,
  core: '#2c292e',
  coreOpacity: 0.22,
  cooledOpacity: 0.62,
  perimeter: '#754b41',
  aerialPerimeter: '#ffe4cc',
  front: '#dc4125',
  casing: '#fff6e5',
  spacing: 33,
  toothWidth: 14,
  toothHeight: 9,
} as const

export const FRONT_TOOTH = 'wildfire-front-tooth'

export function frontToothImage() {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 32
  const context = canvas.getContext('2d')!
  context.scale(2, 2)
  context.fillStyle = FIRE_STYLE.front
  // MapLibre centers the symbol on the line. The outside of a screen-space
  // contour lies to the right of its direction of travel.
  context.beginPath()
  context.moveTo(8 - FIRE_STYLE.toothWidth / 2, 7)
  context.lineTo(8 + FIRE_STYLE.toothWidth / 2, 7)
  context.lineTo(8, 7 + FIRE_STYLE.toothHeight)
  context.closePath()
  context.fill()
  return context.getImageData(0, 0, canvas.width, canvas.height)
}
