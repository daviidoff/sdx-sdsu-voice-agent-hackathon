import { Polygon } from 'react-leaflet'
import type { SimulatedFire } from '@/types'

// The drawn seed is shown while editing. Selection uses the current fire footprint.
export function FirePerimeter({ fire, draft = false }: { fire: SimulatedFire; draft?: boolean }) {
  return <Polygon positions={fire.polygon} interactive={false}
    pathOptions={{ color: draft ? '#db8c1b' : '#a36a24', dashArray: '4 5', weight: draft ? 2 : 1,
      opacity: draft ? 0.95 : 0.65, fillOpacity: draft ? 0.06 : 0 }} />
}
