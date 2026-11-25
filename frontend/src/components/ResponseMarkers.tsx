import { Fragment, useMemo, useState, type ReactElement } from 'react'
import L from 'leaflet'
import { Marker, Popup, Tooltip, useMapEvents } from 'react-leaflet'
import { Button } from '@/components/ui/button'
import { activeDispatch, crewPosition, etaMin, needsRescue } from '@/lib/dispatch'
import { groupMapPins } from '@/lib/map-pin-groups'
import type { Call, Dispatch, Facility, LatLng, Responder, Selection } from '@/types'
import { ENDED_CALL_COLOR, SITUATION, situationLabel } from './labels'
import { callerSymbol, facilitySymbol, crewSymbol, symbolMarkup } from './map-symbol-data'

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

type AssistanceLabel = '' | 'Needs assistance' | 'Assistance reported'

function assistanceBadge(label: string) {
  if (!label) return ''
  const style = label === 'Assistance reported' ? 'map-assistance-label is-historical' : 'map-assistance-label'
  return `<span class="${style}">${escapeHtml(label)}</span>`
}

const callerIcon = (color: string, selected: boolean, sharedLocation: boolean, assistance: AssistanceLabel, ping: boolean) => {
  const key = `caller|${color}|${selected}|${sharedLocation}|${assistance}|${ping}`
  if (!iconCache.has(key)) iconCache.set(key, L.divIcon({
    className: `response-marker caller-marker${selected ? ' caller-marker-selected' : ''}${sharedLocation ? ' caller-marker-shared' : ''}${ping ? ' assistance-ping' : ''}`,
    iconSize: [32, 32],
    // Keep the underlying coordinate while making room for both click targets.
    iconAnchor: sharedLocation ? [-18, 16] : [16, 16],
    tooltipAnchor: sharedLocation ? [34, 0] : [0, 0],
    html: `<span class="map-symbol ${selected ? 'is-selected' : ''}" style="--symbol-color:${color}">${symbolMarkup(callerSymbol)}</span>${assistanceBadge(assistance)}`,
  }))
  return iconCache.get(key)!
}

type Pin = {
  kind: 'call' | 'facility' | 'crew'
  id: string
  position: LatLng
  name: string
  urgent?: string
  ping?: boolean
  element: ReactElement
}

const pinKey = (pin: Pin) => `${pin.kind}:${pin.id}`
const pinLabels = { call: ['Caller', 'callers'], facility: ['Contact', 'contacts'], crew: ['Crew', 'crews'] } as const

export function ResponseMarkers({ calls, facilities, responders, dispatches, now, drawing, selection, onSelect, onMoveCrew }: {
  calls: Call[]; facilities: Facility[]; responders: Responder[]; dispatches: Dispatch[]; now: number
  drawing: boolean; selection?: Selection; onSelect: (selection: Selection) => void
  onMoveCrew: (crewId: string, position: LatLng) => void
}) {
  const map = useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  const [zoom, setZoom] = useState(() => map.getZoom())
  const [draggingCrew, setDraggingCrew] = useState<string>()
  const facilityPositions = useMemo(() => new Set(facilities.flatMap((f) => f.position ? [f.position.join(',')] : [])), [facilities])
  const isSelected = (kind: Pin['kind'], id: string) => selection?.kind === kind && selection.id === id
  const destination = selection?.kind === 'crew' ? activeDispatch(dispatches, selection.id)?.target : undefined
  const isDestination = (kind: Pin['kind'], id: string) => destination?.kind === kind && destination.id === id
  const pins: Pin[] = []

  for (const f of facilities) {
    if (!f.position) continue
    const selected = isSelected('facility', f.id)
    pins.push({
      kind: 'facility', id: f.id, position: f.position, name: f.name,
      element: <Marker interactive={!drawing} keyboard={!drawing} position={f.position} icon={facilityIcon(f, selected)}
        zIndexOffset={selected ? 500 : 0} title={f.name} alt={f.name}
        eventHandlers={{ click: () => !drawing && onSelect({ kind: 'facility', id: f.id }) }}>
        <Tooltip direction="top" offset={[0, -10]}>
          <div className="font-medium">{f.name}</div>
          <div>{f.type.replaceAll('_', ' ')} · {f.contact || 'Phone needs review'}</div>
        </Tooltip>
      </Marker>,
    })
  }

  for (const c of calls) {
    if (!c.position) continue
    const selected = isSelected('call', c.id)
    const sharedLocation = facilityPositions.has(c.position.join(','))
    const closed = c.status === 'resolved' || c.status === 'ended'
    const activeNeed = needsRescue(c)
    const historicalNeed = c.status === 'ended' && (c.situation === 'needs_help' || c.situation === 'trapped')
    const ping = (activeNeed || historicalNeed) && c.assistanceNeededAt !== undefined && now >= c.assistanceNeededAt && now - c.assistanceNeededAt < 5000
    const assistance = activeNeed ? 'Needs assistance' : historicalNeed && (selected || ping || isDestination('call', c.id)) ? 'Assistance reported' : ''
    const label = `${c.callerName} · ${c.address} · ${closed ? 'Call ended' : situationLabel(c)}${historicalNeed ? ' · Assistance reported' : ''}`
    pins.push({
      kind: 'call', id: c.id, position: c.position, name: c.callerName, urgent: activeNeed ? situationLabel(c) : undefined, ping,
      element: <Marker interactive={!drawing} keyboard={!drawing} position={c.position}
        icon={callerIcon(closed ? ENDED_CALL_COLOR : SITUATION[c.situation].color, selected, sharedLocation, assistance, ping)}
        title={c.callerName} zIndexOffset={selected ? 750 : activeNeed ? 550 : 250}
        eventHandlers={{ click: () => !drawing && onSelect({ kind: 'call', id: c.id }) }}>
        <Tooltip direction="top" offset={[0, -12]}>{label}<br />Approximate {c.locationResolution?.precision === 'intersection' ? 'intersection' : 'place reference'}</Tooltip>
      </Marker>,
    })
  }

  for (const r of responders) {
    const d = activeDispatch(dispatches, r.id)
    const label = d?.status === 'en_route' ? `${r.name} · ${etaMin(d, now)} min` : d?.status === 'calling' ? `${r.name} · calling…` : d?.status === 'on_scene' ? `${r.name} · on scene` : r.name
    const position = crewPosition(r, dispatches, now)
    pins.push({
      kind: 'crew', id: r.id, position, name: r.name,
      element: <CrewMarker crew={r} drawing={drawing} position={position}
        icon={crewIcon(r, label, isSelected('crew', r.id))}
        onSelect={() => onSelect({ kind: 'crew', id: r.id })}
        onDragChange={setDraggingCrew} onMove={onMoveCrew} />,
    })
  }

  const singles: Pin[] = []
  const eligible = pins.filter((pin) => {
    if (isSelected(pin.kind, pin.id) || isDestination(pin.kind, pin.id) || (pin.kind === 'crew' && draggingCrew === pin.id)) {
      singles.push(pin)
      return false
    }
    return true
  })
  const groups = groupMapPins(eligible, (position) => map.project(position, zoom))
  singles.push(...groups.filter((group) => group.pins.length === 1).map((group) => group.anchor))

  return <>
    {singles.map((pin) => <Fragment key={`${pinKey(pin)}:${drawing}`}>{pin.element}</Fragment>)}
    {groups.filter((group) => group.pins.length > 1).map(({ anchor, pins }) => (
      <PinGroup key={`${pinKey(anchor)}:${drawing}`} anchor={anchor.position} pins={pins}
        zoom={zoom} drawing={drawing} map={map} onSelect={onSelect} />
    ))}
  </>
}

function PinGroup({ anchor, pins, zoom, drawing, map, onSelect }: {
  anchor: LatLng; pins: Pin[]; zoom: number; drawing: boolean
  map: L.Map; onSelect: (selection: Selection) => void
}) {
  const bounds = L.latLngBounds(pins.map((pin) => pin.position))
  const maxZoom = map.getMaxZoom()
  const canZoom = zoom < maxZoom && !bounds.getSouthWest().equals(bounds.getNorthEast(), 0)
  const counts = { call: 0, facility: 0, crew: 0 }
  let urgent = 0
  for (const pin of pins) {
    counts[pin.kind]++
    if (pin.urgent) urgent++
  }
  const summary = (Object.keys(counts) as Pin['kind'][]).filter((kind) => counts[kind])
    .map((kind) => `${counts[kind]} ${counts[kind] === 1 ? pinLabels[kind][0].toLowerCase() : pinLabels[kind][1]}`).join(', ')
  const action = canZoom ? 'Zoom in' : 'Show map items'
  const urgentLabel = urgent ? ` · ${urgent} urgent` : ''
  const count = pins.length
  const ping = pins.some((pin) => pin.ping)
  const assistanceLabel = urgent ? `${urgent} ${urgent === 1 ? 'needs' : 'need'} assistance` : ping ? 'Assistance reported' : ''
  const icon = useMemo(() => L.divIcon({
    className: ping ? 'response-cluster assistance-ping' : 'response-cluster',
    iconSize: [38, 38],
    iconAnchor: [19, 19],
    html: `<span class="sr-only">${action}: ${summary}${urgentLabel}</span><span aria-hidden="true" class="response-cluster-count${urgent ? ' response-cluster-urgent' : ''}">${count}</span>${assistanceBadge(assistanceLabel)}`,
  }), [action, summary, urgent, urgentLabel, count, ping, assistanceLabel])
  const expand = () => {
    const targetZoom = Math.max(zoom + 1, Math.min(zoom + 3, map.getBoundsZoom(bounds, false, L.point(96, 96))))
    map.flyTo(bounds.getCenter(), Math.min(maxZoom, targetZoom), { duration: 0.4 })
  }
  return <Marker position={anchor} icon={icon} zIndexOffset={350} interactive={!drawing} keyboard={!drawing}
    eventHandlers={drawing ? undefined : {
      ...(canZoom ? { click: expand } : {}),
      keydown: (event) => {
        const key = event.originalEvent as KeyboardEvent
        if (key.key !== 'Enter' && key.key !== ' ') return
        key.preventDefault()
        if (canZoom) expand()
        else (event.target as L.Marker).openPopup()
      },
    }}>
    {!drawing && <Tooltip direction="top" offset={[0, -16]}>{summary}{urgentLabel}<br />{action}</Tooltip>}
    {!drawing && !canZoom && <Popup className="response-cluster-popup" maxHeight={220} maxWidth={260}>
      <div className="text-xs font-semibold">{summary}</div>
      <ul aria-label="Grouped map items" className="mt-1">
        {pins.map((pin) => <li key={pinKey(pin)}>
          <Button size="sm" variant="ghost" className="h-auto w-full justify-start whitespace-normal px-2 text-left"
            onClick={() => { map.closePopup(); onSelect({ kind: pin.kind, id: pin.id }) }}>
            <span>{pin.name}<span className="block text-xs text-muted-foreground">{pinLabels[pin.kind][0]}{pin.urgent && ` · ${pin.urgent}`}</span></span>
          </Button>
        </li>)}
      </ul>
    </Popup>}
  </Marker>
}

function CrewMarker({ crew, position, icon, drawing, onSelect, onDragChange, onMove }: {
  crew: Responder; position: LatLng; icon: L.DivIcon; drawing: boolean
  onDragChange: (id?: string) => void
  onSelect: () => void; onMove: (crewId: string, position: LatLng) => void
}) {
  // Keep animation ticks from snapping Leaflet's marker back during a drag.
  const [dragOrigin, setDragOrigin] = useState<LatLng | null>(null)
  return <Marker interactive={!drawing} keyboard={!drawing} draggable={!!crew.simulated && !drawing}
    title={`${crew.name}${crew.simulated ? ' · Drag to reposition' : ''}`} alt={crew.name}
    position={dragOrigin ?? position} icon={icon} zIndexOffset={1000}
    eventHandlers={{
      click: () => { if (!drawing) onSelect() },
      dragstart: (event) => {
        const point = (event.target as L.Marker).getLatLng()
        setDragOrigin([point.lat, point.lng])
        onDragChange(crew.id)
      },
      dragend: (event) => {
        const point = (event.target as L.Marker).getLatLng()
        onMove(crew.id, [point.lat, point.lng])
        setDragOrigin(null)
        onDragChange(undefined)
      },
    }}>
    {crew.simulated && <Tooltip direction="top" offset={[0, -12]}>Drag to reposition · restarts patrol and cancels the current simulated route</Tooltip>}
  </Marker>
}
