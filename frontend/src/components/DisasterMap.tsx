import { useCallback, useEffect, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Polygon, Polyline, Tooltip, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { ChevronDown, Flame, Layers2, PencilRuler, Scan } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DrawPolygon } from './DrawPolygon'
import { FirePerimeter } from './FirePerimeter'
import { IncidentBasemap } from './IncidentBasemap'
import { ResponseMarkers } from './ResponseMarkers'
import { callMapCandidates, callMapUncertaintyBounds, mapFocusKey } from '@/lib/call-map'
import type { Call, Dispatch, Facility, LatLng, Responder, Selection, Zone, SimulatedFire } from '@/types'
import { ENDED_CALL_COLOR, SITUATION } from './labels'
import { MapKeySymbol } from './map-symbols'
import { callerSymbol, facilitySymbol } from './map-symbol-data'

const MAP_CENTER: [number, number] = [32.7525, -117.1145]
const MAP_ZOOM = 12
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

function FlyTo({ focus, crewId }: { focus: string; crewId?: string }) {
  const map = useMap()
  const focusedCrew = useRef<string | undefined>(undefined)
  useEffect(() => {
    // Repositioning the selected crew should leave the operator's map view alone.
    if (crewId && focusedCrew.current === crewId) return
    focusedCrew.current = crewId
    // A newer lookup must stop an animation toward the caller's former location.
    map.stop()
    const positions = JSON.parse(focus) as LatLng[]
    if (positions.length === 1) map.flyTo(positions[0], Math.max(map.getZoom(), 14), { duration: 0.6 })
    else if (positions.length > 1) map.flyToBounds(positions, { padding: [55, 90], maxZoom: 16, duration: 0.6 })
    return () => { map.stop() }
  }, [focus, crewId, map])
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
  contactsActive, contactZoneIds, fires, draftFire, fireEditorOpen, fireDrawing, fireReplays, onAddFire, onFireDrawn, onFireDrawingCancel,
}: {
  onCenterChange: (center: LatLng) => void
  fires: SimulatedFire[]; draftFire?: SimulatedFire; fireEditorOpen: boolean; fireDrawing: boolean; fireReplays: Record<string, number>
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
  const [basemap, setBasemap] = useState<'streets' | 'aerial'>('streets')
  const [raster, setRaster] = useState(false)
  const fallbackToRaster = useCallback(() => setRaster(true), [])
  const aerial = basemap === 'aerial'
  const selectedCall = selection?.kind === 'call' ? calls.find((c) => c.id === selection.id) : undefined
  const selectedCrew = selection?.kind === 'crew' ? responders.find((r) => r.id === selection.id) : undefined
  const selectedFacility = selection?.kind === 'facility' ? facilities.find((f) => f.id === selection.id) : undefined
  const flyTarget = selectedFacility?.position ?? selectedCall?.position ?? selectedCrew?.position
  const locationCandidates = callMapCandidates(selectedCall)
  const uncertaintyBounds = callMapUncertaintyBounds(selectedCall)
  const savedFire = fires.find((fire) => fire.id === draftFire?.id)
  const draftIgnition = draftFire && JSON.stringify(draftFire.polygon) !== JSON.stringify(savedFire?.polygon) ? draftFire : undefined

  return (
    <div className="incident-map relative h-full w-full">
      <MapContainer center={MAP_CENTER} zoom={MAP_ZOOM} minZoom={1} maxZoom={19} className="h-full w-full" zoomControl={false}>
        <ZoomControl position="topright" />
        <IncidentBasemap aerial={aerial} fires={fires} replays={fireReplays} drawing={anyDrawing} raster={raster}
          onFallback={fallbackToRaster} onSelect={(id) => onSelect({ kind: 'fire', id })} />
        {fireEditorOpen && savedFire && !draftIgnition && <FirePerimeter fire={savedFire} />}
        {!!draftIgnition?.polygon.length && <FirePerimeter fire={draftIgnition} draft />}
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
        <ResponseMarkers calls={calls} facilities={facilities} responders={responders} dispatches={dispatches} now={now}
          drawing={anyDrawing} selection={selection} onSelect={onSelect} onMoveCrew={onMoveCrew} />
        <ContactAreaFocus polygon={contactsActive ? zones.filter((z) => contactZoneIds.includes(z.id)).flatMap((z) => z.polygon) : []} />
        {fireDrawing && <DrawPolygon label="Ignition area" onDone={onFireDrawn} onCancel={onFireDrawingCancel} />}
        {drawing && <DrawPolygon onDone={onZoneDrawn} onCancel={() => onDrawingChange(false)} />}
        <KeepSized />
        {responders.length > 0 && <FitSimulation responders={responders} />}
        <ReportCenter onChange={onCenterChange} />
        <FitFacilities facilities={facilities} hidden={anyDrawing || !contactsActive} />
        <FlyTo crewId={!anyDrawing && !contactsActive ? selectedCrew?.id : undefined} focus={anyDrawing || contactsActive ? '[]' : mapFocusKey(flyTarget, locationCandidates, uncertaintyBounds)} />
      </MapContainer>

      {!anyDrawing && <div role="group" aria-label="Map drawing tools" className="map-surface absolute top-3 left-3 z-[1000] flex items-center gap-0.5 p-0.5">
        <Button size="sm" variant="ghost" className="max-sm:px-1.5" onClick={onAddFire}><Flame className="text-destructive" /> Add fire</Button>
        <span aria-hidden="true" className="h-4 w-px bg-border" />
        <Button size="sm" variant="ghost" className="max-sm:px-1.5" onClick={() => onDrawingChange(true)}>
          <PencilRuler /> Instruction zone
        </Button>
      </div>}

      {selectedCall && !selectedCall.position && !anyDrawing && !contactsActive && <div role="status" className="map-location-status map-surface p-3 text-xs">
        <div className="font-semibold">{selectedCall.callerName} · {selectedCall.locationResolution?.status === 'pending' ? 'Locating updated position…' : locationCandidates.length ? 'Exact position unconfirmed' : 'Current location has no map pin'}</div>
        <p className="mt-1">{selectedCall.address}</p>
        {locationCandidates.length > 0 && <p className="mt-1">Dashed amber circles show {locationCandidates.length === 1 ? 'a possible place match' : `${locationCandidates.length} possible place matches`}, not the caller’s exact position.</p>}
        <p className="mt-1 text-muted-foreground">{selectedCall.locationResolution?.message || 'Waiting for coordinates for this location. Other call markers do not show this caller’s position.'}</p>
      </div>}
      <details className="map-key map-surface group absolute bottom-9 z-[1000] max-w-[calc(100%-1.5rem)] text-xs">
        <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 rounded-lg px-2.5 font-medium hover:bg-muted [&::-webkit-details-marker]:hidden">
          <Layers2 aria-hidden="true" className="size-3.5 text-muted-foreground" />
          Map key
          {fires.length > 0 && <span className="border-l pl-2 text-amber-700 dark:text-amber-300">Simulated wildfire</span>}
          <ChevronDown aria-hidden="true" className="ml-auto size-3.5 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        <div className="flex items-center gap-1 border-t p-2" role="group" aria-label="Basemap">
          <Button size="xs" variant="ghost" aria-pressed={!aerial} className="aria-pressed:bg-muted" onClick={() => setBasemap('streets')}>Streets</Button>
          <Button size="xs" variant="ghost" aria-pressed={aerial} className="aria-pressed:bg-muted" onClick={() => setBasemap('aerial')}>Aerial</Button>
          {raster && <span className="px-1 text-xs text-muted-foreground">Raster fallback</span>}
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 border-t p-3">
          <div className="flex items-center gap-2"><MapKeySymbol symbol={facilitySymbol('clinic')} />Health clinic</div>
          <div className="flex items-center gap-2"><MapKeySymbol symbol={facilitySymbol('care_home')} />Care facility</div>
          <div className="flex items-center gap-2"><MapKeySymbol symbol={facilitySymbol('shelter')} />Shelter / school</div>
          <div className="flex items-center gap-2"><MapKeySymbol symbol={facilitySymbol('community')} />Community</div>
          {!contactsActive && <>
            <Legend color={SITUATION.unknown.color} label="Unconfirmed needs" />
            <Legend color={ENDED_CALL_COLOR} label="Ended / resolved" />
            <Legend color={SITUATION.trapped.color} label="Trapped" />
            <Legend color={SITUATION.needs_help.color} label="Needs help" />
            <Legend color={SITUATION.can_leave.color} label="Can leave" />
          </>}
        </div>
        <div className="space-y-1 border-t px-3 py-2 text-muted-foreground">
          <div>Numbered markers · grouped map items</div>
          <div>Colored zones · operator instructions</div>
          {fires.length > 0 && <div>Red band · active fire<br />Charcoal interior · burned ground<br />Coral teeth · advancing front</div>}
        </div>
      </details>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return <div className="flex items-center gap-2"><MapKeySymbol symbol={callerSymbol} color={color} />{label}</div>
}

// Prefer the newest discovery area to avoid fitting Berlin and demo San Diego together.
function FitFacilities({ facilities, hidden }: { facilities: Facility[]; hidden: boolean }) {
  const map = useMap()
  const mapped = facilities.filter((f) => f.position)
  const discovered = mapped.filter((f) => f.discovery).sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))
  const targets = discovered.length ? discovered.filter((f) => f.runId === discovered[0].runId) : mapped
  const fit = () => { if (targets.length) map.fitBounds(targets.map((f) => f.position!), { padding: [45, 65], maxZoom: 16 }) }
  if (hidden || !targets.length) return null
  return <div className="map-surface absolute top-3 right-12 z-[1000] p-0.5 min-[375px]:right-14"><Button size="sm" variant="ghost" className="max-sm:px-1.5" aria-label="Fit contacts" title="Fit contacts" onClick={fit}><Scan aria-hidden="true" /><span className="hidden min-[375px]:inline">Fit contacts</span></Button></div>
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

function FitSimulation({ responders }: { responders: Responder[] }) {
  const map = useMap()
  const [positions] = useState(() => responders.map((r) => r.position))
  useEffect(() => {
    map.fitBounds(positions, { padding: [100, 100], maxZoom: 14 })
  }, [map, positions])
  return null
}
