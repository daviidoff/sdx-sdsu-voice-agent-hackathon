import { useEffect, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, Polygon, Polyline, Tooltip, useMapEvents } from 'react-leaflet'
import { Check, PencilRuler, Undo2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { LatLng } from '@/types'

// Mounted only during drawing, so finishing or cancelling clears every draft point.
export function DrawPolygon({ onDone, onCancel }: { onDone: (points: LatLng[]) => void; onCancel: () => void }) {
  const [points, setPoints] = useState<LatLng[]>([])
  const [cursor, setCursor] = useState<LatLng>()
  const map = useMapEvents({
    click(e) {
      const point: LatLng = [e.latlng.lat, e.latlng.lng]
      setPoints((previous) => previous.some(([lat, lng]) => lat === point[0] && lng === point[1]) ? previous : [...previous, point])
    },
    mousemove(e) { setCursor([e.latlng.lat, e.latlng.lng]) },
    mouseout() { setCursor(undefined) },
  })
  useEffect(() => {
    const container = map.getContainer()
    const previousCursor = container.style.cursor
    const doubleClickZoom = map.doubleClickZoom.enabled()
    container.style.cursor = 'crosshair'
    map.doubleClickZoom.disable()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => {
      container.style.cursor = previousCursor
      if (doubleClickZoom) map.doubleClickZoom.enable()
      window.removeEventListener('keydown', onKey)
    }
  }, [map, onCancel])

  // Translate before calculating area to avoid cancellation with geographic coordinates.
  const origin = points[0]
  const area = points.reduce((sum, point, index) => {
    const next = points[(index + 1) % points.length]
    return sum + (point[1] - origin[1]) * (next[0] - origin[0]) - (next[1] - origin[1]) * (point[0] - origin[0])
  }, 0)
  const canFinish = points.length >= 3 && Math.abs(area) > 1e-12
  const finish = () => { if (canFinish) onDone(points) }
  const preview = cursor && points.length ? [...points, cursor, points[0]] : points

  return <>
    {points.length >= 3 && <Polygon positions={points} interactive={false} pathOptions={{ color: '#dc2626', weight: 2, fillOpacity: 0.12 }} />}
    {preview.length >= 2 && <Polyline positions={preview} interactive={false} pathOptions={{ color: '#dc2626', weight: 2, dashArray: '6 6' }} />}
    {points.map((point, index) => <CircleMarker
      key={index}
      center={point}
      radius={index === 0 ? 7 : 5}
      bubblingMouseEvents={false}
      pathOptions={{ color: '#dc2626', weight: 2, fillColor: '#fff', fillOpacity: 1 }}
      eventHandlers={{ click: () => { if (index === 0) finish() } }}
    >
      <Tooltip>{index === 0 && canFinish ? 'Click to close polygon' : `Point ${index + 1}`}</Tooltip>
    </CircleMarker>)}
    <div className="absolute top-3 left-3 right-3 z-[1000] w-fit max-w-[calc(100%-1.5rem)] rounded-lg border border-red-300 bg-background/95 p-2 text-xs shadow-sm"
      ref={(element) => { if (element) { L.DomEvent.disableClickPropagation(element); L.DomEvent.disableScrollPropagation(element) } }}>
      <div role="status" className="mb-2 flex items-center gap-2"><PencilRuler className="size-3.5 shrink-0 text-red-600" />
        {points.length < 3 ? `Click the map to add corners · ${points.length}/3 minimum` : 'Add corners, then Finish or click the first point.'}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <Button size="xs" disabled={!canFinish} onClick={finish}><Check /> Finish</Button>
        <Button size="xs" variant="outline" disabled={!points.length} onClick={() => setPoints((previous) => previous.slice(0, -1))}><Undo2 /> Undo</Button>
        <Button size="xs" variant="ghost" onClick={onCancel}><X /> Cancel</Button>
      </div>
    </div>
  </>

}
