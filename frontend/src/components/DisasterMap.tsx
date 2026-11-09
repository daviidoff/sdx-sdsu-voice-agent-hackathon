import { useEffect, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polygon, Polyline, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { Flame, PencilRuler } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DrawPolygon } from './DrawPolygon'
import { FirePerimeter } from './FirePerimeter'
const MAP_CENTER: [number, number] = [32.7525, -117.1145]
const MAP_ZOOM = 12
import { activeDispatch, crewPosition, etaMin } from '@/lib/dispatch'
import { callMapCandidates, callMapUncertaintyBounds, mapFocusKey } from '@/lib/call-map'
import type { Call, Dispatch, Facility, LatLng, Responder, Selection, Zone, SimulatedFire } from '@/types'
import { SITUATION } from './labels'
import { FacilitySymbol } from './map-symbols'
import { facilitySymbol, crewSymbol, symbolMarkup } from './map-symbol-data'

const CREW_COLOR: Record<Responder['status'], string> = { available: '#334155', en_route: '#2563eb', on_scene: '#7c3aed' }
const iconCache = new Map<string, L.DivIcon>()
const escapeHtml = (text: string) => text.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!))

const crewIcon = (r: Responder, label: string, selected: boolean) => {
  const key = `${r.id}|${r.kind}|${r.status}|${label}|${selected}`
  if (!iconCache.has(key)) {
    // Bound the cache as ETA labels change during long operator sessions.
    if (iconCache.size > 256) iconCache.clear()
    iconCache.set(key, L.divIcon({
      className: 'response-marker', iconSize: [32, 32], iconAnchor: [16, 16],
      html: `<div class="crew-marker"><span class="map-symbol ${selected ? 'is-selected' : ''}" style="--symbol-color:${CREW_COLOR[r.status]}">${symbolMarkup(crewSymbol(r.kind))}</span><span class="crew-marker-label">${escapeHtml(label)}</span></div>`,
    }))
  }
  return iconCache.get(key)!
}

const facilityIcon = (f: Facility, selected: boolean) => {
  const symbol = facilitySymbol(f.type)
  const key = `facility|${f.type}|${selected}`
  if (!iconCache.has(key)) iconCache.set(key, L.divIcon({
    className: 'response-marker', iconSize: [32, 32], iconAnchor: [16, 16],
    html: `<span class="map-symbol ${selected ? 'is-selected' : ''}" style="--symbol-color:${symbol.color}">${symbolMarkup(symbol)}</span>`,
  }))
  return iconCache.get(key)!
}

const ZONE_COLOR: Record<Zone['level'], string> = { evacuate: '#dc2626', warning: '#b45309', shelter: '#0f766e', unknown: '#64748b' }

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

function FlyTo({ focus }: { focus: string }) {
  const map = useMap()
  useEffect(() => {
    // A newer lookup must stop an animation toward the caller's former location.
    map.stop()
    const positions = JSON.parse(focus) as LatLng[]
    if (positions.length === 1) map.flyTo(positions[0], Math.max(map.getZoom(), 14), { duration: 0.6 })
    else if (positions.length > 1) map.flyToBounds(positions, { padding: [55, 90], maxZoom: 16, duration: 0.6 })
    return () => { map.stop() }
  }, [focus, map])
  return null
}

export function DisasterMap({
  onCenterChange,
  calls,
  facilities,
  zones,
  responders,
  dispatches,
  now,
  selection,
  onSelect,
  onMoveCrew,
  drawing,
  onDrawingChange,
  onZoneDrawn,
  draftZone,
  contactsActive, contactZoneIds, fires, draftFire, fireDrawing, onAddFire, onFireDrawn, onFireDrawingCancel,
}: {
  onCenterChange: (center: LatLng) => void
  fires: SimulatedFire[]; draftFire?: SimulatedFire; fireDrawing: boolean
  onAddFire: () => void; onFireDrawn: (points: LatLng[]) => void; onFireDrawingCancel: () => void
  contactsActive: boolean; contactZoneIds: string[]
  draftZone?: Zone
  calls: Call[]
  facilities: Facility[]
  zones: Zone[]
  responders: Responder[]
  dispatches: Dispatch[]
  now: number
  selection?: Selection
  onSelect: (s: Selection) => void
  onMoveCrew: (crewId: string, position: LatLng) => void
  drawing: boolean
  onDrawingChange: (on: boolean) => void
  onZoneDrawn: (points: LatLng[]) => void
}) {
  const anyDrawing = drawing || fireDrawing
  const selectedCall = selection?.kind === 'call' ? calls.find((c) => c.id === selection.id) : undefined
  const selectedCrew = selection?.kind === 'crew' ? responders.find((r) => r.id === selection.id) : undefined
  const selectedFacility = selection?.kind === 'facility' ? facilities.find((f) => f.id === selection.id) : undefined
  const flyTarget = selectedFacility?.position ?? selectedCall?.position ?? selectedCrew?.position
  const locationCandidates = callMapCandidates(selectedCall)
  const uncertaintyBounds = callMapUncertaintyBounds(selectedCall)

  return (
    <div className="relative h-full w-full">
      <MapContainer center={MAP_CENTER} zoom={MAP_ZOOM} className="h-full w-full" zoomControl={false}>
        <ZoomControl position="topright" />
        <TileLayer className="response-basemap"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {[...fires.filter((fire) => fire.id !== draftFire?.id), ...(draftFire?.polygon.length ? [draftFire] : [])].map((fire) => <FirePerimeter key={fire.id} fire={fire} selected={fire.id === draftFire?.id} drawing={anyDrawing} onSelect={() => onSelect({ kind: 'fire', id: fire.id })} />)}
        {zones.filter((z) => z.polygon.length >= 3).map((z) => {
          const selected = contactsActive ? contactZoneIds.includes(z.id) : selection?.kind === 'zone' && selection.id === z.id
          return (
            <Polygon
              key={`${z.id}-${z.level}-${anyDrawing}`}
              positions={z.polygon}
              interactive={!anyDrawing}
              eventHandlers={{ click: () => !anyDrawing && onSelect({ kind: 'zone', id: z.id }) }}
              pathOptions={{ color: contactsActive && selected ? '#2563eb' : ZONE_COLOR[z.level], weight: selected ? 4 : 2, dashArray: selected ? undefined : '6 6', fillOpacity: selected ? 0.14 : 0.06 }}
            >
              <Tooltip sticky>{z.label} · {z.level} · v{z.version ?? 1} · {contactsActive ? (selected ? 'selected for contact search' : 'click to select for contact search') : 'click to edit'}</Tooltip>
            </Polygon>
          )
        })}
        {draftZone && !draftZone.version && draftZone.polygon.length >= 3 && <Polygon key={`draft-${drawing}`} interactive={!anyDrawing} positions={draftZone.polygon} pathOptions={{ color: '#2563eb', weight: 3, dashArray: '4 6', fillOpacity: 0.08 }}><Tooltip sticky>Add an instruction to activate this area</Tooltip></Polygon>}
        {facilities.map((f) => f.position && (
          <Marker interactive={!anyDrawing} key={`${f.id}-${anyDrawing}`} position={f.position} icon={facilityIcon(f, selection?.kind === 'facility' && selection.id === f.id)} zIndexOffset={selection?.id === f.id ? 500 : 0} title={f.name} alt={f.name} eventHandlers={{ click: () => !anyDrawing && onSelect({ kind: 'facility', id: f.id }) }}>
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
        {!anyDrawing && !contactsActive && uncertaintyBounds.length > 0 && <Polygon positions={uncertaintyBounds} interactive={false} pathOptions={{ color: '#b45309', weight: 2, dashArray: '5 5', fillOpacity: .04 }} />}
        {!anyDrawing && !contactsActive && locationCandidates.map((candidate, index) => <CircleMarker
          key={`candidate-${selectedCall!.id}-${candidate.position.join(',')}`}
          center={candidate.position} radius={12}
          pathOptions={{ color: '#b45309', weight: 3, dashArray: '4 4', fillOpacity: .08 }}>
          <Tooltip direction="top">Possible location {index + 1} · {candidate.label}<br />Exact caller position unconfirmed</Tooltip>
        </CircleMarker>)}
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
            <CrewMarker
              key={`${r.id}-${anyDrawing}`}
              crew={r}
              drawing={anyDrawing}
              position={crewPosition(r, dispatches, now)}
              icon={crewIcon(r, label, selection?.kind === 'crew' && selection.id === r.id)}
              onSelect={() => onSelect({ kind: 'crew', id: r.id })}
              onMove={onMoveCrew}
            />
          )
        })}
        <ContactAreaFocus polygon={contactsActive ? zones.filter((z) => contactZoneIds.includes(z.id)).flatMap((z) => z.polygon) : []} />
        {fireDrawing && <DrawPolygon label="Fire perimeter" onDone={onFireDrawn} onCancel={onFireDrawingCancel} />}
        {drawing && <DrawPolygon onDone={onZoneDrawn} onCancel={() => onDrawingChange(false)} />}
        <KeepSized />
        {responders.length > 0 && <FitSimulation responders={responders} />}
        <ReportCenter onChange={onCenterChange} />
        <FitFacilities facilities={facilities} hidden={anyDrawing || !contactsActive} />
        <FlyTo focus={anyDrawing || contactsActive ? '[]' : mapFocusKey(flyTarget, locationCandidates, uncertaintyBounds)} />
      </MapContainer>

      {!anyDrawing && <div className="absolute top-3 left-3 z-[1000] flex flex-wrap gap-2">
        <Button size="sm" variant="outline" className="border-orange-300 bg-background/95 text-orange-800 shadow-sm" onClick={onAddFire}><Flame /> Add fire</Button>
        <Button size="sm" variant="outline" className="bg-background/95 shadow-sm" onClick={() => onDrawingChange(true)}>
          <PencilRuler /> Zone
        </Button>
      </div>}

      {selectedCall && !selectedCall.position && !anyDrawing && !contactsActive && <div role="status" className="absolute top-16 left-3 z-[1000] max-w-sm rounded-lg border border-amber-300 bg-background/95 p-3 text-xs shadow-sm">
        <div className="font-semibold">{selectedCall.callerName} · {selectedCall.locationResolution?.status === 'pending' ? 'Locating updated position…' : locationCandidates.length ? 'Exact position unconfirmed' : 'Current location has no map pin'}</div>
        <p className="mt-1">{selectedCall.address}</p>
        {locationCandidates.length > 0 && <p className="mt-1">Dashed amber circles show {locationCandidates.length === 1 ? 'a possible place match' : `${locationCandidates.length} possible place matches`}, not the caller’s exact position.</p>}
        <p className="mt-1 text-muted-foreground">{selectedCall.locationResolution?.message || 'Waiting for coordinates for this location. Other call markers do not show this caller’s position.'}</p>
      </div>}
      <details className="map-key absolute bottom-7 right-3 z-[1000] max-w-[calc(100%-1.5rem)] rounded-xl border bg-background/95 p-3 text-xs shadow-sm">
        <summary className="cursor-pointer font-semibold">Map key</summary>
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
          <div className="flex items-center gap-2"><FacilitySymbol type="clinic" className="size-6!" /> Health clinic</div>
          <div className="flex items-center gap-2"><FacilitySymbol type="care_home" className="size-6!" /> Care facility</div>
          <div className="flex items-center gap-2"><FacilitySymbol type="shelter" className="size-6!" /> Shelter / school</div>
          <div className="flex items-center gap-2"><FacilitySymbol type="community" className="size-6!" /> Community</div>
          {!contactsActive && <>
            <Legend color="#64748b" label="Unconfirmed needs" />
            <Legend color="#94a3b8" label="Ended / resolved" />
            <Legend color="#dc2626" label="Trapped" />
            <Legend color="#d97706" label="Needs help" />
            <Legend color="#16a34a" label="Can leave" />
          </>}
        </div>
        <div className="mt-3 border-t pt-2 text-muted-foreground">Dashed boundaries · operator instruction areas</div>
      </details>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return <div className="flex items-center gap-2"><span className="mx-1.5 size-3 rounded-full ring-2 ring-white" style={{ background: color }} />{label}</div>
}

// Prefer the newest discovery area to avoid fitting Berlin and demo San Diego together.
function FitFacilities({ facilities, hidden }: { facilities: Facility[]; hidden: boolean }) {
  const map = useMap()
  const mapped = facilities.filter((f) => f.position)
  const discovered = mapped.filter((f) => f.discovery).sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))
  const targets = discovered.length ? discovered.filter((f) => f.runId === discovered[0].runId) : mapped
  const fit = () => { if (targets.length) map.fitBounds(targets.map((f) => f.position!), { padding: [45, 65], maxZoom: 16 }) }
  if (hidden) return null
  return <div className="absolute right-14 top-3 z-[1000]"><Button size="sm" variant="outline" className="bg-background" disabled={!targets.length} onClick={fit}>Fit contacts</Button></div>
}

function ContactAreaFocus({ polygon }: { polygon: LatLng[] }) {
  const map = useMap()
  const key = JSON.stringify(polygon)
  useEffect(() => { const points = JSON.parse(key) as LatLng[]; if (points.length) map.fitBounds(points, { padding: [35, 70], maxZoom: 15 }) }, [key, map])
  return null
}

function ReportCenter({ onChange }: { onChange: (center: LatLng) => void }) {
  const map = useMapEvents({ moveend: () => { const p = map.getCenter(); onChange([p.lat, p.lng]) } })
  useEffect(() => { const p = map.getCenter(); onChange([p.lat, p.lng]) }, [map, onChange])
  return null
}

function CrewMarker({ crew, position, icon, drawing, onSelect, onMove }: {
  crew: Responder; position: LatLng; icon: L.DivIcon; drawing: boolean
  onSelect: () => void; onMove: (crewId: string, position: LatLng) => void
}) {
  // Keep animation ticks from snapping Leaflet's marker back during a drag.
  const [dragOrigin, setDragOrigin] = useState<LatLng | null>(null)
  return <Marker interactive={!drawing} draggable={!!crew.simulated && !drawing}
    title={`${crew.name}${crew.simulated ? ' · Drag to reposition' : ''}`} alt={crew.name}
    position={dragOrigin ?? position} icon={icon} zIndexOffset={1000}
    eventHandlers={{
      click: () => { if (!drawing) onSelect() },
      dragstart: (event) => {
        const point = (event.target as L.Marker).getLatLng()
        setDragOrigin([point.lat, point.lng])
      },
      dragend: (event) => {
        const point = (event.target as L.Marker).getLatLng()
        onMove(crew.id, [point.lat, point.lng])
        setDragOrigin(null)
      },
    }}>
    {crew.simulated && <Tooltip direction="top" offset={[0, -12]}>Drag to reposition · restarts patrol and cancels the current simulated route</Tooltip>}
  </Marker>
}

function FitSimulation({ responders }: { responders: Responder[] }) {
  const map = useMap()
  const [positions] = useState(() => responders.map((r) => r.position))
  useEffect(() => {
    map.fitBounds(positions, { padding: [100, 100], maxZoom: 14 })
  }, [map, positions])
  return null
}
