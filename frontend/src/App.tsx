import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Flame, RotateCcw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CallDetail } from '@/components/CallDetail'
import { CallList } from '@/components/CallList'
import { CrewDetail } from '@/components/CrewDetail'
import { DisasterMap } from '@/components/DisasterMap'
import { ZoneEditor } from '@/components/ZoneEditor'
import { facilities, initialMission, initialResponders, initialZones } from '@/data/fake'
import { activeDispatch, crewPosition, fetchRoute, needsWheelchair, radioLine, tripFraction } from '@/lib/dispatch'
import { createFeed } from '@/lib/feed'
import { byPriority, zoneFor } from '@/lib/geo'
import type { Call, Dispatch, DispatchTarget, FeedEvent, LatLng, Responder, Selection, TranscriptLine, Zone } from '@/types'

let idSeq = 0
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${++idSeq}`

export default function App() {
  const feed = useMemo(() => createFeed(), [])
  const [calls, setCalls] = useState<Record<string, Call>>({})
  const [lines, setLines] = useState<Record<string, TranscriptLine[]>>({})
  const [zones, setZones] = useState<Zone[]>(initialZones)
  const [responders, setResponders] = useState<Responder[]>(initialResponders)
  const [dispatches, setDispatches] = useState<Dispatch[]>([])
  const [selection, setSelection] = useState<Selection>()
  const [drawing, setDrawing] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [run, setRun] = useState(0)

  // Latest state for async callbacks (timers, route fetches).
  const callsRef = useRef(calls)
  const respondersRef = useRef(responders)
  const dispatchesRef = useRef(dispatches)
  callsRef.current = calls
  respondersRef.current = responders
  dispatchesRef.current = dispatches
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const later = (ms: number, fn: () => void) => timers.current.push(setTimeout(fn, ms))

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [])

  const addLine = useCallback((callId: string, speaker: TranscriptLine['speaker'], text: string) => {
    const line: TranscriptLine = { id: nextId('line'), callId, speaker, text, at: Date.now() }
    setLines((prev) => ({ ...prev, [callId]: [...(prev[callId] ?? []), line] }))
  }, [])
  const setCallStatus = useCallback((callId: string, status: Call['status']) => {
    setCalls((prev) => (prev[callId] ? { ...prev, [callId]: { ...prev[callId], status } } : prev))
  }, [])

  const steerCall = useCallback(
    (callId: string, text: string, mode: 'context' | 'say') => {
      addLine(callId, 'steer', mode === 'say' ? `Say now: ${text}` : text)
      void feed.steer(callId, text, mode)
    },
    [addLine, feed],
  )

  // Call a crew (fake radio call for now; later an ElevenLabs outbound call) and send it to a target.
  const dispatchCrew = useCallback(
    async (crewId: string, target: DispatchTarget) => {
      const crew = respondersRef.current.find((r) => r.id === crewId)
      if (!crew || activeDispatch(dispatchesRef.current, crewId)) return
      const id = nextId('dispatch')
      const call = target.kind === 'call' ? callsRef.current[target.id] : undefined
      const update = (fn: (d: Dispatch) => Dispatch) => setDispatches((prev) => prev.map((d) => (d.id === id ? fn(d) : d)))
      const say = (speaker: 'agent' | 'caller' | 'system', text: string) => update((d) => ({ ...d, radio: [...d.radio, radioLine(id, speaker, text)] }))

      setDispatches((prev) => [...prev, { id, crewId, target, status: 'calling', route: [], routeText: '', durationSec: 0, radio: [radioLine(id, 'system', `Calling ${crew.name}…`)] }])
      const route = await fetchRoute(crewPosition(crew, dispatchesRef.current, Date.now()), target.position)
      const eta = Math.ceil(route.durationSec / 60)
      update((d) => ({ ...d, route: route.path, routeText: route.routeText, durationSec: route.durationSec }))

      const request = call
        ? `${crew.name}, rescue request at ${call.address}. ${call.people} ${call.people === 1 ? 'person' : 'people'}${needsWheelchair(call) ? ', wheelchair transport needed' : ''}. ${call.mobility}. Route ${route.routeText}, about ${eta} minutes. Can you take it?`
        : `${crew.name}, ${target.label}. Route ${route.routeText}, about ${eta} minutes. Please confirm.`
      later(600, () => say('agent', request))
      later(2600, () => say('caller', `Copy. ${crew.name} en route to ${call?.address ?? target.label}.`))
      later(3200, () => {
        update((d) => ({ ...d, status: 'en_route', acceptedAt: Date.now() }))
        setResponders((prev) => prev.map((r) => (r.id === crewId ? { ...r, status: 'en_route' } : r)))
        if (call) {
          // Honesty rule: the caller hears "help is coming" only after a crew has accepted.
          setCallStatus(call.id, 'help_assigned')
          addLine(call.id, 'system', `${crew.name} accepted · ETA ${eta} min`)
          steerCall(call.id, `Help is on the way: ${crew.name}, about ${eta} minutes. Stay inside near the door.`, 'say')
        }
      })
    },
    [addLine, setCallStatus, steerCall],
  )

  // Start (or replay) the feed and reset the world.
  useEffect(() => {
    timers.current.forEach(clearTimeout)
    timers.current = []
    setCalls({})
    setLines({})
    setZones(initialZones)
    setResponders(initialResponders)
    setDispatches([])
    const onEvent = (e: FeedEvent) => {
      if (e.type === 'call') setCalls((prev) => ({ ...prev, [e.call.id]: e.call }))
      else
        setLines((prev) => {
          const list = prev[e.line.callId] ?? []
          if (list.some((l) => l.id === e.line.id)) return prev
          return { ...prev, [e.line.callId]: [...list, e.line] }
        })
    }
    const stop = feed.start(onEvent)
    const site = facilities.find((f) => f.id === initialMission.facilityId)
    if (site) void dispatchCrew(initialMission.crewId, { kind: 'facility', id: site.id, label: initialMission.label, position: site.position })
    return () => {
      stop()
      timers.current.forEach(clearTimeout)
    }
  }, [feed, run, dispatchCrew])

  // Arrivals: on scene, then the crew picks people up and becomes available again.
  useEffect(() => {
    for (const d of dispatches) {
      if (d.status !== 'en_route' || tripFraction(d, now) < 1) continue
      const crew = respondersRef.current.find((r) => r.id === d.crewId)
      setDispatches((prev) => prev.map((x) => (x.id === d.id ? { ...x, status: 'on_scene', radio: [...x.radio, radioLine(d.id, 'caller', `${crew?.name} on scene at ${d.target.kind === 'call' ? callsRef.current[d.target.id]?.address : d.target.label}.`)] } : x)))
      setResponders((prev) => prev.map((r) => (r.id === d.crewId ? { ...r, status: 'on_scene' } : r)))
      if (d.target.kind === 'call') addLine(d.target.id, 'system', `${crew?.name} on scene.`)
      if (d.target.kind === 'call')
        later(6000, () => {
          setDispatches((prev) => prev.map((x) => (x.id === d.id ? { ...x, status: 'done', radio: [...x.radio, radioLine(d.id, 'caller', 'Everyone aboard. Heading to Westside Community Shelter.')] } : x)))
          setResponders((prev) => prev.map((r) => (r.id === d.crewId ? { ...r, status: 'available', position: d.target.position } : r)))
          addLine(d.target.id, 'system', `Picked up by ${crew?.name}.`)
          setCallStatus(d.target.id, 'resolved')
        })
    }
  }, [now, dispatches, addLine, setCallStatus])

  const callList = useMemo(() => Object.values(calls), [calls])
  useEffect(() => {
    if (!selection && callList.length) setSelection({ kind: 'call', id: [...callList].sort(byPriority)[0].id })
  }, [callList, selection])

  // Zones (police edit).
  const addZone = useCallback((sw: LatLng, ne: LatLng) => {
    setZones((prev) => {
      const used = new Set(prev.map((z) => z.id))
      const id = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').find((l) => !used.has(l)) ?? String(prev.length + 1)
      const zone: Zone = {
        id,
        label: `Zone ${id} — Evacuate now`,
        level: 'evacuate',
        polygon: [[ne[0], sw[1]], [ne[0], ne[1]], [sw[0], ne[1]], [sw[0], sw[1]]],
        instruction: 'Leave now. Head west on University Ave to the Westside Community Shelter.',
      }
      setSelection({ kind: 'zone', id })
      return [...prev, zone]
    })
    setDrawing(false)
  }, [])
  const updateZone = (zone: Zone) => setZones((prev) => prev.map((z) => (z.id === zone.id ? zone : z)))
  const deleteZone = (id: string) => {
    setZones((prev) => prev.filter((z) => z.id !== id))
    setSelection(undefined)
  }
  const notifyZone = (zone: Zone) => {
    for (const c of callList) if (c.status !== 'resolved' && zoneFor(c.position, zones)?.id === zone.id) steerCall(c.id, `Update for your area: ${zone.instruction}`, 'say')
  }

  const active = callList.filter((c) => c.status !== 'resolved')
  const stats = [
    { label: 'Active calls', value: active.length },
    { label: 'Trapped', value: active.filter((c) => c.situation === 'trapped').length, tone: 'text-red-600' },
    { label: 'Need help', value: active.filter((c) => c.situation === 'needs_help').length, tone: 'text-amber-600' },
    { label: 'Crews en route', value: dispatches.filter((d) => d.status === 'en_route').length, tone: 'text-blue-600' },
  ]

  const selectedCall = selection?.kind === 'call' ? calls[selection.id] : undefined
  const selectedCrew = selection?.kind === 'crew' ? responders.find((r) => r.id === selection.id) : undefined
  const selectedZone = selection?.kind === 'zone' ? zones.find((z) => z.id === selection.id) : undefined

  return (
    <div className="flex h-dvh flex-col bg-muted/30 text-foreground">
      <header className="flex items-center gap-4 border-b bg-background px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-orange-600 text-white"><Flame className="size-4" /></div>
          <div>
            <div className="text-sm font-semibold leading-tight">Emergency OS</div>
            <div className="text-xs text-muted-foreground">Call dashboard · North Park fire (simulated)</div>
          </div>
        </div>
        <div className="ml-4 hidden items-center gap-5 lg:flex">
          {stats.map((s) => (
            <div key={s.label} className="leading-tight">
              <div className={`text-lg font-semibold tabular-nums ${s.tone ?? ''}`}>{s.value}</div>
              <div className="text-[11px] text-muted-foreground">{s.label}</div>
            </div>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Badge variant="outline">{feed.source === 'fake' ? 'Fake data' : 'Supabase live'}</Badge>
          <span className="font-mono text-xs tabular-nums text-muted-foreground">{new Date(now).toLocaleTimeString()}</span>
          {feed.source === 'fake' && (
            <Button size="sm" variant="ghost" onClick={() => { setSelection(undefined); setDrawing(false); setRun((r) => r + 1) }}>
              <RotateCcw /> Replay
            </Button>
          )}
        </div>
      </header>
      <main className="grid min-h-0 flex-1 grid-cols-[320px_1fr_380px]">
        <aside className="min-h-0 border-r bg-background">
          <CallList calls={callList} lines={lines} zones={zones} responders={responders} dispatches={dispatches} selection={selection} onSelect={setSelection} now={now} />
        </aside>
        <section className="min-h-0">
          <DisasterMap
            calls={callList}
            zones={zones}
            responders={responders}
            dispatches={dispatches}
            now={now}
            selection={selection}
            onSelect={setSelection}
            drawing={drawing}
            onDrawingChange={setDrawing}
            onZoneDrawn={addZone}
          />
        </section>
        <aside className="min-h-0 border-l bg-background">
          {selectedZone ? (
            <ZoneEditor
              zone={selectedZone}
              callersInside={active.filter((c) => zoneFor(c.position, zones)?.id === selectedZone.id).length}
              onChange={updateZone}
              onDelete={() => deleteZone(selectedZone.id)}
              onNotify={() => notifyZone(selectedZone)}
              onClose={() => setSelection(undefined)}
            />
          ) : selectedCrew ? (
            <CrewDetail
              crew={selectedCrew}
              calls={callList}
              dispatches={dispatches}
              now={now}
              onDispatch={(call) => void dispatchCrew(selectedCrew.id, { kind: 'call', id: call.id, label: call.callerName, position: call.position })}
              onSelectCall={(id) => setSelection({ kind: 'call', id })}
            />
          ) : (
            <CallDetail
              call={selectedCall}
              lines={selectedCall ? lines[selectedCall.id] ?? [] : []}
              zones={zones}
              responders={responders}
              dispatches={dispatches}
              now={now}
              onSteer={(text, mode) => selectedCall && steerCall(selectedCall.id, text, mode)}
              onDispatch={(crewId) => selectedCall && void dispatchCrew(crewId, { kind: 'call', id: selectedCall.id, label: selectedCall.callerName, position: selectedCall.position })}
              onSelectCrew={(id) => setSelection({ kind: 'crew', id })}
            />
          )}
        </aside>
      </main>
    </div>
  )
}
