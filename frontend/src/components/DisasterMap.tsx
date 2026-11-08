import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polygon, Polyline, Rectangle, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { PencilRuler, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fireStages, facilities, MAP_CENTER, MAP_ZOOM } from '@/data/fake'
import { activeDispatch, crewPosition, etaMin } from '@/lib/dispatch'
import type { Call, Dispatch, Facility, LatLng, Responder, Selection, Zone } from '@/types'
import { SITUATION } from './labels'

const FACILITY_STYLE: Record<string, { letter: string; color: string }> = {
  shelter: { letter: 'S', color: '#059669' },
  school: { letter: 'S', color: '#059669' },
  assisted_living: { letter: 'C', color: '#7c3aed' },
  memory_care: { letter: 'C', color: '#7c3aed' },
  clinic: { letter: '+', color: '#2563eb' },
}
const CREW_LETTER: Record<Responder['kind'], string> = { engine: 'E', ambulance: 'M', wheelchair_van: 'W' }
const CREW_COLOR: Record<Responder['status'], string> = { available: '#0f172a', en_route: '#2563eb', on_scene: '#7c3aed' }

const square = (letter: string, color: string) =>
  L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<div style="width:22px;height:22px;border-radius:6px;background:${color};color:#fff;font:600 12px/22px system-ui;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35)">${letter}</div>`,
  })

// Icons are cached so moving crews don't rebuild their marker every tick.
const iconCache = new Map<string, L.DivIcon>()
const crewIcon = (r: Responder, label: string, selected: boolean) => {
  const key = `${r.id}|${r.status}|${label}|${selected}`
  if (!iconCache.has(key)) iconCache.set(key, buildCrewIcon(r, label, selected))
  return iconCache.get(key)!
}
const buildCrewIcon = (r: Responder, label: string, selected: boolean) =>
  L.divIcon({
    className: '',
    iconSize: [0, 0],
    iconAnchor: [14, 14],
    html: `<div style="display:flex;align-items:center;gap:4px;white-space:nowrap">
      <div style="width:28px;height:28px;border-radius:999px;background:${CREW_COLOR[r.status]};color:#fff;font:700 12px/28px system-ui;text-align:center;border:${selected ? '3px solid #f59e0b' : '2px solid #fff'};box-shadow:0 1px 5px rgba(0,0,0,.4)">${CREW_LETTER[r.kind]}${r.wheelchair ? '♿' : ''}</div>
      <div style="background:rgba(255,255,255,.95);border-radius:6px;padding:1px 6px;font:600 11px system-ui;color:#0f172a;box-shadow:0 1px 3px rgba(0,0,0,.2)">${label}</div>
    </div>`,
  })

const facilityIcon = (f: Facility) => {
  const s = FACILITY_STYLE[f.type] ?? { letter: '•', color: '#475569' }
  return square(s.letter, s.color)
}

// Leaflet measures its box once; re-measure whenever the grid layout resizes it.
function KeepSized() {
  const map = useMap()
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize())
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map])
  return null
}

function FlyTo({ target }: { target?: LatLng }) {
  const map = useMap()
  const key = target?.join(',')
  useEffect(() => {
    if (target) map.flyTo(target, Math.max(map.getZoom(), 15), { duration: 0.6 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map])
  return null
}

// Police draw a rectangle: press, drag, release.
function DrawRect({ active, onDone }: { active: boolean; onDone: (sw: LatLng, ne: LatLng) => void }) {
  const [start, setStart] = useState<LatLng>()
  const [end, setEnd] = useState<LatLng>()
  const map = useMapEvents({
    mousedown(e) {
      if (!active) return
      map.dragging.disable()
      setStart([e.latlng.lat, e.latlng.lng])
      setEnd([e.latlng.lat, e.latlng.lng])
    },
    mousemove(e) {
      if (active && start) setEnd([e.latlng.lat, e.latlng.lng])
    },
    mouseup() {
      if (!active || !start || !end) return
      map.dragging.enable()
      const sw: LatLng = [Math.min(start[0], end[0]), Math.min(start[1], end[1])]
      const ne: LatLng = [Math.max(start[0], end[0]), Math.max(start[1], end[1])]
      setStart(undefined)
      setEnd(undefined)
      if (Math.abs(ne[0] - sw[0]) > 0.0005 && Math.abs(ne[1] - sw[1]) > 0.0005) onDone(sw, ne)
    },
  })
  useEffect(() => {
    const el = map.getContainer()
    el.style.cursor = active ? 'crosshair' : ''
    if (!active) map.dragging.enable()
  }, [active, map])
  return start && end ? <Rectangle bounds={[start, end]} pathOptions={{ color: '#dc2626', weight: 2, dashArray: '6 6', fillOpacity: 0.1 }} /> : null
}

export function DisasterMap({
  calls,
  zones,
  responders,
  dispatches,
  now,
  selection,
  onSelect,
  drawing,
  onDrawingChange,
  onZoneDrawn,
}: {
  calls: Call[]
  zones: Zone[]
  responders: Responder[]
  dispatches: Dispatch[]
  now: number
  selection?: Selection
  onSelect: (s: Selection) => void
  drawing: boolean
  onDrawingChange: (on: boolean) => void
  onZoneDrawn: (sw: LatLng, ne: LatLng) => void
}) {
  const selectedCall = selection?.kind === 'call' ? calls.find((c) => c.id === selection.id) : undefined
  const selectedCrew = selection?.kind === 'crew' ? responders.find((r) => r.id === selection.id) : undefined
  const flyTarget = selectedCall?.position ?? (selectedCrew ? crewPosition(selectedCrew, dispatches, now) : undefined)
  // Only fly when the selection changes, not every time a crew moves.
  const flyRef = useRef<{ id?: string; pos?: LatLng }>({})
  if (flyRef.current.id !== selection?.id) flyRef.current = { id: selection?.id, pos: flyTarget }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onDrawingChange(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onDrawingChange])

  return (
    <div className="relative h-full w-full">
      <MapContainer center={MAP_CENTER} zoom={MAP_ZOOM} className="h-full w-full" zoomControl={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Routes: OSRM'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {fireStages.map((f, i) => (
          <Polygon
            key={f.label}
            positions={f.polygon}
            interactive={false}
            pathOptions={{ color: '#ea580c', weight: i === fireStages.length - 1 ? 2 : 1, dashArray: i === fireStages.length - 1 ? undefined : '3 5', fillColor: '#f97316', fillOpacity: [0.12, 0.22, 0.5][i] ?? 0.3 }}
          />
        ))}
        {zones.map((z) => {
          const selected = selection?.kind === 'zone' && selection.id === z.id
          return (
            <Polygon
              key={`${z.id}-${z.level}`}
              positions={z.polygon}
              eventHandlers={{ click: () => !drawing && onSelect({ kind: 'zone', id: z.id }) }}
              pathOptions={{ color: z.level === 'evacuate' ? '#dc2626' : '#d97706', weight: selected ? 4 : 2, dashArray: selected ? undefined : '6 6', fillOpacity: selected ? 0.14 : 0.06 }}
            >
              <Tooltip sticky>{z.label} · click to edit</Tooltip>
            </Polygon>
          )
        })}
        {facilities.map((f) => f.position && (
          <Marker key={f.id} position={f.position} icon={facilityIcon(f)}>
            <Tooltip direction="top" offset={[0, -10]}>
              <div className="font-medium">{f.name}</div>
              <div>{f.type.replaceAll('_', ' ')} · {f.contact}</div>
            </Tooltip>
          </Marker>
        ))}
        {dispatches
          .filter((d) => (d.status === 'en_route' || d.status === 'calling') && d.route.length > 1)
          .map((d) => (
            <Polyline key={d.id} positions={d.route} pathOptions={{ color: '#2563eb', weight: 5, opacity: d.status === 'calling' ? 0.35 : 0.8, dashArray: d.status === 'calling' ? '4 8' : undefined }} />
          ))}
        {calls.map((c) => {
          const selected = selection?.kind === 'call' && selection.id === c.id
          return (
            <CircleMarker
              key={c.id}
              center={c.position}
              radius={selected ? 13 : 9}
              eventHandlers={{ click: () => onSelect({ kind: 'call', id: c.id }) }}
              pathOptions={{ color: selected ? '#0f172a' : '#fff', weight: selected ? 3 : 2, fillColor: c.status === 'resolved' ? '#94a3b8' : SITUATION[c.situation].color, fillOpacity: 0.95 }}
            >
              <Tooltip direction="top" offset={[0, -8]}>{c.callerName} · {c.address}</Tooltip>
            </CircleMarker>
          )
        })}
        {responders.map((r) => {
          const d = activeDispatch(dispatches, r.id)
          const label = d?.status === 'en_route' ? `${r.name} · ${etaMin(d, now)} min` : d?.status === 'calling' ? `${r.name} · calling…` : d?.status === 'on_scene' ? `${r.name} · on scene` : r.name
          return (
            <Marker
              key={r.id}
              position={crewPosition(r, dispatches, now)}
              icon={crewIcon(r, label, selection?.kind === 'crew' && selection.id === r.id)}
              eventHandlers={{ click: () => onSelect({ kind: 'crew', id: r.id }) }}
              zIndexOffset={1000}
            />
          )
        })}
        <DrawRect active={drawing} onDone={onZoneDrawn} />
        <KeepSized />
        <FlyTo target={flyRef.current.pos} />
      </MapContainer>

      <div className="absolute top-3 left-3 z-[1000] flex items-center gap-2">
        {drawing ? (
          <div className="flex items-center gap-2 rounded-lg border border-red-300 bg-background/95 px-3 py-1.5 text-xs shadow-sm">
            <PencilRuler className="size-3.5 text-red-600" /> Drag on the map to draw an evacuation zone
            <Button size="xs" variant="ghost" onClick={() => onDrawingChange(false)}><X /> Cancel</Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" className="bg-background/95 shadow-sm" onClick={() => onDrawingChange(true)}>
            <PencilRuler /> Draw evacuation zone
          </Button>
        )}
      </div>

      <div className="absolute bottom-6 left-3 z-[1000] rounded-lg border bg-background/95 p-3 text-xs shadow-sm">
        <div className="mb-1.5 font-medium">Legend</div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <Legend color="#dc2626" label="Trapped caller" round />
          <Legend color="#f97316" label="Fire (now / forecast)" />
          <Legend color="#d97706" label="Needs help" round />
          <Legend color="#7c3aed" label="Care facility" />
          <Legend color="#16a34a" label="Can leave" round />
          <Legend color="#059669" label="Shelter" />
          <Legend color="#0f172a" label="Crew available" round />
          <Legend color="#2563eb" label="Crew en route + route" round />
        </div>
      </div>
    </div>
  )
}

function Legend({ color, label, round }: { color: string; label: string; round?: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={round ? 'size-2.5 rounded-full' : 'size-2.5 rounded-sm'} style={{ background: color }} />
      {label}
    </div>
  )
}
