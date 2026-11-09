import { memo, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Accessibility, ChevronDown, MapPin, MessageSquareText, Phone, PhoneCall, Send, Truck, Users } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { etaMin, needsRescue, needsWheelchair, suggestCrews } from '@/lib/dispatch'
import { callDuration, zoneFor } from '@/lib/geo'
import { callMapCandidates } from '@/lib/call-map'
import { cn } from '@/lib/utils'
import type { Call, Dispatch, Responder, TranscriptLine, Zone } from '@/types'
import { SITUATION, STATUS, situationLabel } from './labels'

export function CallDetail({
  call,
  lines,
  zones,
  responders,
  dispatches,
  now,
  onSteer,
  onDispatch,
  onSelectCrew,
  onRefreshLocation,
}: {
  call?: Call
  lines: TranscriptLine[]
  zones: Zone[]
  responders: Responder[]
  dispatches: Dispatch[]
  now: number
  onSteer: (text: string, mode: 'context' | 'say') => Promise<void>
  onDispatch: (crewId: string) => void
  onSelectCrew: (id: string) => void
  onRefreshLocation?: () => Promise<void>
}) {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [rechecking, setRechecking] = useState(false)
  const [showActivity, setShowActivity] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [steerMode, setSteerMode] = useState<'context' | 'say'>('context')
  const scroller = useRef<HTMLDivElement>(null)
  const followLatest = useRef(true)
  const displayedCall = useRef<string | undefined>(undefined)
  const visibleLines = useMemo(() => lines.filter((line) => showActivity || line.speaker === 'caller' || line.speaker === 'agent'), [lines, showActivity])
  const contentKey = visibleLines.map((line) => `${line.id}:${line.text}`).join('\n')
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el) return
    if (displayedCall.current !== call?.id) {
      displayedCall.current = call?.id
      followLatest.current = call?.status !== 'ended' && call?.status !== 'resolved'
      el.scrollTop = followLatest.current ? el.scrollHeight : 0
    } else if (followLatest.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [contentKey, call?.id, call?.status])
  const jumpToLatest = () => {
    followLatest.current = true
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }

  if (!call) return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Select a call</div>
  const zone = zoneFor(call.position, zones)
  const ended = call.status === 'ended' || call.status === 'resolved'
  const sourceUrl = call.locationResolution?.source_url
  const possibleLocations = callMapCandidates(call)
  const locationStatus = call.position ? 'Approximate place location · not GPS'
    : possibleLocations.length ? 'Possible locations shown · exact position unconfirmed'
    : call.locationResolution?.status === 'pending' ? 'Locating updated position…' : 'Location not mapped'
  const refreshLocation = async () => {
    if (!onRefreshLocation || rechecking) return
    setRechecking(true)
    try { await onRefreshLocation() } catch { /* Parent displays lookup errors. */ }
    finally { setRechecking(false) }
  }
  const send = async (mode: 'context' | 'say', text = draft) => {
    if (!text.trim() || ended || sending) return
    setSending(true)
    try { await onSteer(text.trim(), mode); setDraft('') }
    catch { /* Parent displays the backend error; keep the draft for retry. */ }
    finally { setSending(false) }
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <div className="shrink-0 space-y-2 border-b px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <h2 className="min-w-0 truncate text-sm font-semibold" title={call.callerName}>{call.callerName}</h2>
          <div className="flex shrink-0 items-center gap-2">
            {call.status === 'active' && <span className="flex items-center gap-1 text-xs font-medium text-red-600"><span className="size-2 animate-pulse rounded-full bg-red-500" />LIVE</span>}
            <span className="font-mono text-xs tabular-nums text-muted-foreground">{callDuration(call, now)}</span>
            <button type="button" onClick={() => setShowDetails(!showDetails)} aria-expanded={showDetails} aria-controls="call-details" className="flex items-center gap-1 rounded px-1 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground">
              Details <ChevronDown className={cn('size-3 transition-transform', showDetails && 'rotate-180')} />
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge className={SITUATION[call.situation].badge}>{situationLabel(call)}</Badge>
          {call.status !== 'active' && <Badge variant="outline">{STATUS[call.status]}</Badge>}
        </div>
        <div className="grid gap-1 text-xs text-muted-foreground">
          <span className="flex min-w-0 items-center gap-1.5"><MapPin className="size-3.5 shrink-0" /><span className="truncate" title={call.address}>{call.address}</span></span>
          <span className="flex min-w-0 items-center gap-1.5"><Users className="size-3.5 shrink-0" /><span className="truncate" title={`${call.people ?? 'Unknown'} people · ${call.mobility}`}>{call.people ?? 'Unknown'} people · {call.mobility}</span></span>
        </div>
      </div>
      {showDetails && <div id="call-details" className="max-h-[30%] shrink-0 space-y-2 overflow-y-auto border-b bg-muted/20 px-4 py-3 text-xs">
        <div className="break-all text-muted-foreground">Call {call.id}</div>
        <div className="flex items-center gap-1.5 text-muted-foreground"><Phone className="size-3.5" />{call.phone}</div>
        <p>{call.address} · {call.people ?? 'Unknown'} people · {call.mobility}</p>
        {ended && call.currentSpatialInstruction ? <>
          <div className="rounded-md border border-blue-200 bg-blue-50 p-2.5 text-xs text-blue-900">
            <div className="font-medium">Current map instruction · looked up after this call</div>
            <p className="mt-1">{call.currentSpatialInstruction.text}</p>
          </div>
          <details className="rounded-md border bg-muted/30 p-2 text-xs">
            <summary className="cursor-pointer font-medium">Instruction recorded during the call</summary>
            <p className="mt-2">{call.instruction?.text ?? 'No instruction was recorded.'}</p>
            <p className="mt-1 text-muted-foreground">Historical record. The conversation below is unchanged.</p>
          </details>
        </> : <div className={cn('rounded-md border p-2.5 text-xs', !ended && call.instruction?.zone_id && zone?.level === 'evacuate' ? 'border-red-200 bg-red-50 text-red-900' : 'bg-muted')}>
          <div className="font-medium">{ended ? 'Instruction recorded during the call' : call.instruction?.zone_id ? `Shared area instruction · v${call.instruction.version ?? '—'}` : 'No matched instruction'}</div>
          <div className="mt-0.5">{call.instruction?.text ?? 'Confirm the current location and request operator guidance.'}</div>
        </div>}
        <div className="text-xs text-muted-foreground">{call.scenarioId === 'dashboard' ? 'Shared dashboard context' : 'Demonstration scenario'} · {locationStatus}{call.wheelchairUsers !== undefined ? ` · ${call.wheelchairUsers} wheelchair users` : ''}</div>
        {!call.position && call.locationResolution?.message && <p className="text-xs text-muted-foreground">{call.locationResolution.message}</p>}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          {sourceUrl && /^https?:\/\//.test(sourceUrl) && <a href={sourceUrl} target="_blank" rel="noreferrer" className="underline">Location source</a>}
          {onRefreshLocation && <button type="button" onClick={() => void refreshLocation()} disabled={rechecking || !call.locationQuery || call.mode !== 'elevenlabs' || call.scenarioId !== 'dashboard'} className="underline disabled:no-underline disabled:opacity-50">{rechecking ? 'Checking location…' : 'Recheck location & zone'}</button>}
        </div>
      </div>}
      <Rescue call={call} responders={responders} dispatches={dispatches} now={now} onDispatch={onDispatch} onSelectCrew={onSelectCrew} />
      <div className="flex shrink-0 items-center gap-2 px-4 py-2 text-xs">
        <MessageSquareText className="size-3.5" />
        <button aria-pressed={!showActivity} className={!showActivity ? 'font-semibold' : 'text-muted-foreground'} onClick={() => setShowActivity(false)}>Conversation</button>
        <button aria-pressed={showActivity} className={showActivity ? 'font-semibold' : 'text-muted-foreground'} onClick={() => setShowActivity(true)}>Activity</button>
        <button onClick={jumpToLatest} className="ml-auto whitespace-nowrap text-[11px] underline">Latest ↓</button>
      </div>
      <div ref={scroller} role="log" aria-label="Call transcript" tabIndex={0}
        onScroll={(event) => { const el = event.currentTarget; followLatest.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48 }}
        className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-4 py-3 [scrollbar-gutter:stable]">
        <div className="flex min-w-0 flex-col gap-3">
          {!visibleLines.length && <p className="text-sm text-muted-foreground">No transcript yet.</p>}
          {visibleLines.map((line) => <TranscriptRow key={line.id} line={line} />)}
        </div>
      </div>
      <Separator />
      {ended ? <div className="shrink-0 bg-muted/30 px-4 py-2 text-xs text-muted-foreground">Call ended · {callDuration(call, now)} · Assistance outcome unconfirmed</div> : <form className="flex shrink-0 items-center gap-2 p-3" onSubmit={(event) => { event.preventDefault(); void send(steerMode) }}>
        <Input aria-label="Message to the agent" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Message the agent…" disabled={sending} />
        <select aria-label="Message delivery" title="Inform adds context; Speak requests an immediate spoken update" value={steerMode} onChange={(event) => setSteerMode(event.target.value as 'context' | 'say')} disabled={sending} className="h-8 max-w-24 rounded-lg border bg-background px-1.5 text-xs">
          <option value="context">Inform</option>
          <option value="say">Speak</option>
        </select>
        <Button type="submit" size="icon" aria-label={steerMode === 'say' ? 'Request spoken update' : 'Inform agent'} title={steerMode === 'say' ? 'Request spoken update' : 'Inform agent'} disabled={!draft.trim() || sending}>
          <Send className="size-4" />
        </Button>
      </form>}

    </div>
  )
}

// Disabled or trapped callers: show the assigned crew, or the best crews to call.
function Rescue({
  call,
  responders,
  dispatches,
  now,
  onDispatch,
  onSelectCrew,
}: {
  call: Call
  responders: Responder[]
  dispatches: Dispatch[]
  now: number
  onDispatch: (crewId: string) => void
  onSelectCrew: (id: string) => void
}) {
  const d = dispatches.find((x) => x.status !== 'done' && x.target.kind === 'call' && x.target.id === call.id)
  if (d) {
    const crew = responders.find((r) => r.id === d.crewId)
    return (
      <div className="rounded-md border border-blue-200 bg-blue-50 p-2.5 text-xs text-blue-900">
        <div className="flex items-center gap-1.5 font-medium"><Truck className="size-3.5" />{crew?.name}</div>
        <div className="mt-0.5">
          {d.status === 'calling' && 'Simulating crew radio…'}
          {d.status === 'en_route' && `Simulated · en route ${d.routeText} · ETA ${etaMin(d, now)} min`}
          {d.status === 'on_scene' && 'Simulation arrived · live assistance remains unconfirmed'}
        </div>
        <button className="mt-1 underline" onClick={() => onSelectCrew(d.crewId)}>Open crew</button>
      </div>
    )
  }
  if (!needsRescue(call) || !responders.length) return null
  const options = suggestCrews(call, responders, dispatches, now).slice(0, 3)
  return (
    <div className="rounded-md border p-2.5">
      <div className="mb-1.5 flex items-center justify-between text-xs font-medium">
        <span>Simulate a rescue route</span>
        {needsWheelchair(call) && <span className="flex items-center gap-1 text-muted-foreground"><Accessibility className="size-3.5" />wheelchair needed</span>}
      </div>
      <div className="flex flex-col gap-1.5">
        {options.map(({ responder: r, km, fits, available }, i) => (
          <div key={r.id} className="flex items-center gap-2 text-xs">
            <button className="min-w-0 flex-1 truncate text-left hover:underline" onClick={() => onSelectCrew(r.id)}>
              <span className="font-medium">{r.name}</span>
              <span className="text-muted-foreground"> · {km.toFixed(1)} km{!available ? ' · busy' : !fits ? ' · no wheelchair lift' : i === 0 ? ' · best match' : ''}</span>
            </button>
            <Button size="xs" variant={i === 0 && available && fits ? 'default' : 'outline'} disabled={!available || !fits || !call.position} onClick={() => onDispatch(r.id)}>
              <PhoneCall /> Simulate
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}

const TranscriptRow = memo(function TranscriptRow({ line }: { line: TranscriptLine }) {
  if (line.speaker === 'system') return <div className="break-words rounded border border-dashed bg-muted/30 p-2 text-[11px] leading-relaxed text-muted-foreground">{line.text}</div>
  if (line.speaker === 'steer')
    return (
      <div className="rounded-md border border-dashed border-blue-300 bg-blue-50 px-2.5 py-1.5 text-xs text-blue-900">
        <span className="font-medium">Dispatcher → agent:</span> {line.text}
      </div>
    )
  const caller = line.speaker === 'caller'
  return (
    <div className={cn('flex', caller ? 'justify-start' : 'justify-end')}>
      <div className={cn('min-w-0 max-w-[96%] whitespace-pre-wrap break-words rounded-xl px-3 py-2.5 text-sm leading-relaxed [overflow-wrap:anywhere]', caller ? 'bg-muted' : 'border border-blue-100 bg-blue-50/70 text-foreground')}>
        <div className={cn('mb-0.5 text-[10px] uppercase tracking-wide', caller ? 'text-muted-foreground' : 'text-blue-700')}>{caller ? 'Caller' : 'AI agent'} <time className="ml-1 normal-case tracking-normal">{new Date(line.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time></div>
        {line.text}
      </div>
    </div>
  )
}, (previous, next) => previous.line.id === next.line.id && previous.line.text === next.line.text && previous.line.speaker === next.line.speaker && previous.line.at === next.line.at)
