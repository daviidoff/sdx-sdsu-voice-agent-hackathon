import { Polygon, Tooltip } from 'react-leaflet'
import type { SimulatedFire } from '@/types'

// Match the original dashboard's abstract fire overlay, with one static perimeter.
export function FirePerimeter({ fire, selected, drawing, onSelect }: {
  fire: SimulatedFire; selected: boolean; drawing: boolean; onSelect: () => void
}) {
  return <Polygon
    key={String(drawing)}
    positions={fire.polygon}
    interactive={!drawing}
    eventHandlers={{ click: onSelect }}
    pathOptions={{ color: '#ea580c', weight: selected ? 3 : 2, fillColor: '#f97316', fillOpacity: 0.5 }}
  >
    <Tooltip sticky><strong>{fire.label}</strong><br />Simulated fire · static perimeter · click to edit</Tooltip>
  </Polygon>
}
