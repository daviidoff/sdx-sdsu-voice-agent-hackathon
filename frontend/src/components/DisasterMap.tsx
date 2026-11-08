import { useEffect } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polygon, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { PencilRuler } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DrawPolygon } from './DrawPolygon'
const MAP_CENTER: [number, number] = [32.7525, -117.1145]
const MAP_ZOOM = 12
import { activeDispatch, crewPosition, etaMin } from '@/lib/dispatch'
import type { Call, Dispatch, Facility, LatLng, Responder, Selection, Zone } from '@/types'
import { SITUATION } from './labels'

const FACILITY_STYLE: Record<string, { letter: string; color: string }> = {
  shelter: { letter: 'S', color: '#059669' },
  school: { letter: 'S', color: '#059669' },
  assisted_living: { letter: 'C', color: '#7c3aed' },
  memory_care: { letter: 'C', color: '#7c3aed' },
  care_home: { letter: 'C', color: '#7c3aed' },
  disability_support: { letter: 'C', color: '#7c3aed' },
  health_clinic: { letter: '+', color: '#2563eb' },
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
    if (target) map.flyTo(target, Math.max(map.getZoom(), 14), { duration: 0.6 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map])
  return null
}

export function DisasterMap({
  calls,
  facilities,
  zones,
  responders,
  dispatches,
  now,
  selection,
  onSelect,
  drawing,
  onDrawingChange,
  onZoneDrawn,
  draftZone,
  contactsActive, contactPolygon, contactDrawing, onContactDrawn, onContactDrawingChange,
}: {
  contactsActive: boolean; contactPolygon: LatLng[]; contactDrawing: boolean
  onContactDrawn: (points: LatLng[]) => void; onContactDrawingChange: (on: boolean) => void
  draftZone?: Zone
  calls: Call[]
  facilities: Facility[]
  zones: Zone[]
  responders: Responder[]
  dispatches: Dispatch[]
  now: number
  selection?: Selection
  onSelect: (s: Selection) => void
  drawing: boolean
  onDrawingChange: (on: boolean) => void
  onZoneDrawn: (points: LatLng[]) => void
}) {
  const anyDrawing = drawing || contactDrawing
  const selectedCall = selection?.kind === 'call' ? calls.find((c) => c.id === selection.id) : undefined
  const selectedCrew = selection?.kind === 'crew' ? responders.find((r) => r.id === selection.id) : undefined
  const selectedFacility = selection?.kind === 'facility' ? facilities.find((f) => f.id === selection.id) : undefined
  const flyTarget = selectedFacility?.position ?? selectedCall?.position ?? (selectedCrew ? crewPosition(selectedCrew, dispatches, now) : undefined)

  return (
    <div className="relative h-full w-full">
      <MapContainer center={MAP_CENTER} zoom={MAP_ZOOM} className="h-full w-full" zoomControl={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {zones.filter((z) => z.polygon.length >= 3).map((z) => {
          const selected = selection?.kind === 'zone' && selection.id === z.id
          return (
            <Polygon
              key={`${z.id}-${z.level}-${drawing}`}
              positions={z.polygon}
              interactive={!anyDrawing}
              eventHandlers={{ click: () => !anyDrawing && onSelect({ kind: 'zone', id: z.id }) }}
              pathOptions={{ color: z.level === 'evacuate' ? '#dc2626' : '#d97706', weight: selected ? 4 : 2, dashArray: selected ? undefined : '6 6', fillOpacity: selected ? 0.14 : 0.06 }}
            >
              <Tooltip sticky>{z.label} · {z.level} · v{z.version ?? 1} · click to edit</Tooltip>
            </Polygon>
          )
        })}
        {draftZone && !draftZone.version && draftZone.polygon.length >= 3 && <Polygon key={`draft-${drawing}`} interactive={!anyDrawing} positions={draftZone.polygon} pathOptions={{ color: '#2563eb', weight: 3, dashArray: '4 6', fillOpacity: 0.08 }}><Tooltip sticky>Unpublished draft · publish to apply</Tooltip></Polygon>}
        {facilities.map((f) => f.position && (
          <Marker interactive={!anyDrawing} key={`${f.id}-${anyDrawing}`} position={f.position} icon={facilityIcon(f)} title={f.name} alt={f.name} eventHandlers={{ click: () => !anyDrawing && onSelect({ kind: 'facility', id: f.id }) }}>
            <Tooltip direction="top" offset={[0, -10]}>
              <div className="font-medium">{f.name}</div>
              <div>{f.type.replaceAll('_', ' ')} · {f.contact || 'Phone needs review'}</div>
            </Tooltip>
          </Marker>
        ))}
        {dispatches
          .filter((d) => (d.status === 'en_route' || d.status === 'calling') && d.route.length > 1)
          .map((d) => (
            <Polyline interactive={!anyDrawing} key={`${d.id}-${drawing}`} positions={d.route} pathOptions={{ color: '#2563eb', weight: 5, opacity: d.status === 'calling' ? 0.35 : 0.8, dashArray: d.status === 'calling' ? '4 8' : undefined }} />
          ))}
        {calls.filter((c) => c.position).map((c) => {
          const selected = selection?.kind === 'call' && selection.id === c.id
          return (
            <CircleMarker
              interactive={!anyDrawing}
              key={`${c.id}-${anyDrawing}`}
              center={c.position!}
              radius={selected ? 13 : 9}
              eventHandlers={{ click: () => !anyDrawing && onSelect({ kind: 'call', id: c.id }) }}
              pathOptions={{ color: selected ? '#0f172a' : '#fff', weight: selected ? 3 : 2, fillColor: c.status === 'resolved' || c.status === 'ended' ? '#94a3b8' : SITUATION[c.situation].color, fillOpacity: 0.95 }}
            >
              <Tooltip direction="top" offset={[0, -8]}>{c.callerName} · {c.address}<br />Approximate {c.locationResolution?.precision === 'intersection' ? 'intersection' : 'place reference'}{c.status === 'ended' ? ' · Call ended' : ''}</Tooltip>
            </CircleMarker>
          )
        })}
        {responders.map((r) => {
          const d = activeDispatch(dispatches, r.id)
          const label = d?.status === 'en_route' ? `${r.name} · ${etaMin(d, now)} min` : d?.status === 'calling' ? `${r.name} · calling…` : d?.status === 'on_scene' ? `${r.name} · on scene` : r.name
          return (
            <Marker
              interactive={!anyDrawing}
              key={`${r.id}-${drawing}`}
              position={crewPosition(r, dispatches, now)}
              icon={crewIcon(r, label, selection?.kind === 'crew' && selection.id === r.id)}
              eventHandlers={{ click: () => !anyDrawing && onSelect({ kind: 'crew', id: r.id }) }}
              zIndexOffset={1000}
            />
          )
        })}
        {contactsActive && contactPolygon.length >= 3 && !contactDrawing && <Polygon positions={contactPolygon} interactive={false} pathOptions={{ color: '#2563eb', dashArray: '5 5', weight: 2, fillOpacity: .06 }} />}
        {contactsActive && contactDrawing && <DrawPolygon onDone={onContactDrawn} onCancel={() => onContactDrawingChange(false)} />}
        <ContactAreaFocus polygon={contactsActive ? contactPolygon : []} />
        {drawing && <DrawPolygon onDone={onZoneDrawn} onCancel={() => onDrawingChange(false)} />}
        <KeepSized />
        <FitFacilities facilities={facilities} hidden={anyDrawing || !contactsActive} />
        <FlyTo target={flyTarget} />
      </MapContainer>

      {!anyDrawing && !contactsActive && <div className="absolute top-3 left-3 z-[1000]">
        <Button size="sm" variant="outline" className="bg-background/95 shadow-sm" onClick={() => onDrawingChange(true)}>
          <PencilRuler /> Instruction Zone
        </Button>
      </div>}

      {selectedCall && !selectedCall.position && !anyDrawing && !contactsActive && <div role="status" className="absolute top-16 left-3 z-[1000] max-w-sm rounded-lg border border-amber-300 bg-background/95 p-3 text-xs shadow-sm">
        <div className="font-semibold">{selectedCall.callerName} · {selectedCall.locationResolution?.status === 'pending' ? 'Locating updated position…' : 'Current location has no map pin'}</div>
        <p className="mt-1">{selectedCall.address}</p>
        <p className="mt-1 text-muted-foreground">{selectedCall.locationResolution?.message || 'Waiting for coordinates for this location. Other call markers do not show this caller’s position.'}</p>
      </div>}
      <div className="absolute bottom-6 left-3 z-[1000] rounded-lg border bg-background/95 p-3 text-xs shadow-sm">
        <div className="mb-1.5 font-medium">Legend</div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <Legend color="#64748b" label="Needs unconfirmed / ended" round />
          <Legend color="#f97316" label="Operator zones" />
          <Legend color="#d97706" label="Assistance requested" round />
          <Legend color="#7c3aed" label="Care facility" />
          <Legend color="#16a34a" label="Can leave" round />
          <Legend color="#059669" label="Shelter" />

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

// Prefer the newest discovery area to avoid fitting Berlin and demo San Diego together.
function FitFacilities({ facilities, hidden }: { facilities: Facility[]; hidden: boolean }) {
  const map = useMap()
  const mapped = facilities.filter((f) => f.position)
  const discovered = mapped.filter((f) => f.discovery).sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))
  const targets = discovered.length ? discovered.filter((f) => f.runId === discovered[0].runId) : mapped
  const fit = () => { if (targets.length) map.fitBounds(targets.map((f) => f.position!), { padding: [45, 65], maxZoom: 16 }) }
  if (hidden) return null
  return <div className="absolute right-3 top-3 z-[1000]"><Button size="sm" variant="outline" className="bg-background" disabled={!targets.length} onClick={fit}>Show discovered facilities</Button></div>
}

function ContactAreaFocus({ polygon }: { polygon: LatLng[] }) {
  const map = useMap()
  const key = JSON.stringify(polygon)
  useEffect(() => { const points = JSON.parse(key) as LatLng[]; if (points.length) map.fitBounds(points, { padding: [35, 70], maxZoom: 15 }) }, [key, map])
  return null
}
