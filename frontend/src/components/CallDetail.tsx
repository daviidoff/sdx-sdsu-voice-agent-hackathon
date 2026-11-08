import { memo, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Accessibility, MapPin, MessageSquareText, Phone, PhoneCall, Send, Truck, Users, Volume2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { etaMin, needsRescue, needsWheelchair, suggestCrews } from '@/lib/dispatch'
import { callDuration, zoneFor } from '@/lib/geo'
import { cn } from '@/lib/utils'
import type { Call, Dispatch, Responder, TranscriptLine, Zone } from '@/types'
import { SITUATION, STATUS, situationLabel } from './labels'

const QUICK_STEERS = [
  'Ask them to stay on the line while we find a crew.',
  'Ask if there are pets or medical equipment.',
  'Ask them to confirm their current location.',
]

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
      <div className="max-h-[45%] shrink-0 space-y-2 overflow-y-auto p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="text-base font-semibold">{call.callerName}</div>
            <div className="break-all text-[10px] text-muted-foreground">{call.id}</div>
          </div>
          <div className="flex items-center gap-1.5">
            {call.status === 'active' && <span className="flex items-center gap-1 text-xs font-medium text-red-600"><span className="size-2 animate-pulse rounded-full bg-red-500" />LIVE</span>}
            <span className="font-mono text-xs tabular-nums text-muted-foreground">{callDuration(call, now)}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge className={SITUATION[call.situation].badge}>{situationLabel(call)}</Badge>
          <Badge variant="outline">{STATUS[call.status]}</Badge>
        </div>
        <div className="grid gap-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5"><MapPin className="size-3.5" />{call.address}</span>
          <span className="flex items-center gap-1.5"><Phone className="size-3.5" />{call.phone}</span>
          <span className="flex items-center gap-1.5"><Users className="size-3.5" />{call.people ?? 'Unknown'} people · {call.mobility}</span>
        </div>
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
          <div className="font-medium">{ended ? 'Instruction recorded during the call' : call.instruction?.zone_id ? `Published instruction · v${call.instruction.version ?? '—'}` : 'No matched instruction'}</div>
          <div className="mt-0.5">{call.instruction?.text ?? 'Confirm the current location and request operator guidance.'}</div>
        </div>}
        <div className="text-xs text-muted-foreground">{call.scenarioId === 'dashboard' ? 'Shared dashboard context' : 'Demonstration scenario'} · {call.position ? 'Approximate place location · not GPS' : 'Location not mapped'}{call.wheelchairUsers !== undefined ? ` · ${call.wheelchairUsers} wheelchair users` : ''}</div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          {sourceUrl && /^https?:\/\//.test(sourceUrl) && <a href={sourceUrl} target="_blank" rel="noreferrer" className="underline">Location source</a>}
          {onRefreshLocation && <button type="button" onClick={() => void refreshLocation()} disabled={rechecking || !call.locationQuery || call.mode !== 'elevenlabs' || call.scenarioId !== 'dashboard'} className="underline disabled:no-underline disabled:opacity-50">{rechecking ? 'Checking location…' : 'Recheck location & zone'}</button>}
        </div>
        <Rescue call={call} responders={responders} dispatches={dispatches} now={now} onDispatch={onDispatch} onSelectCrew={onSelectCrew} />
      </div>
      <Separator />
      <div className="flex shrink-0 items-center gap-2 px-4 py-2 text-xs">
        <MessageSquareText className="size-3.5" />
        <button className={!showActivity ? 'font-semibold' : 'text-muted-foreground'} onClick={() => setShowActivity(false)}>Conversation</button>
        <button className={showActivity ? 'font-semibold' : 'text-muted-foreground'} onClick={() => setShowActivity(true)}>Include activity</button>
        <button onClick={jumpToLatest} className="ml-auto whitespace-nowrap text-[11px] underline">Latest ↓</button>
      </div>
      <div ref={scroller} role="log" aria-label="Call transcript" tabIndex={0}
        onScroll={(event) => { const el = event.currentTarget; followLatest.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48 }}
        className="min-h-28 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-4 py-3 [scrollbar-gutter:stable]">
        <div className="flex min-w-0 flex-col gap-3">
          {!visibleLines.length && <p className="text-sm text-muted-foreground">No transcript yet.</p>}
          {visibleLines.map((line) => <TranscriptRow key={line.id} line={line} />)}
        </div>
      </div>
      <Separator />
      {ended ? <div className="shrink-0 border-t bg-muted/30 p-3 text-xs text-muted-foreground">Call ended · recorded duration {callDuration(call, now)}. Assistance outcome remains unconfirmed.</div> : <div className="shrink-0 space-y-2 p-3">
        <div className="text-xs font-medium text-muted-foreground">Steer the agent</div>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_STEERS.map((q) => (
            <button key={q} disabled={ended || sending} onClick={() => send('context', q)} className="rounded-full border px-2.5 py-1 text-left text-xs hover:bg-muted">
              {q}
            </button>
          ))}
        </div>
        <Input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send('context')} placeholder="Instruction for the agent…" disabled={ended || sending} />
        <div className="flex gap-2">
          <Button size="sm" variant="outline" className="flex-1" onClick={() => send('context')} disabled={!draft.trim() || ended || sending}>
            <Send /> Inform agent
          </Button>
          <Button size="sm" className="flex-1" onClick={() => send('say')} disabled={!draft.trim() || ended || sending}>
            <Volume2 /> Request spoken update
          </Button>
        </div>
      </div>}
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
          {d.status === 'calling' && 'Calling the crew… caller is not told until they accept.'}
          {d.status === 'en_route' && `Accepted · en route ${d.routeText} · ETA ${etaMin(d, now)} min`}
          {d.status === 'on_scene' && 'On scene, picking people up'}
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
        <span>Send a rescue crew</span>
        {needsWheelchair(call) && <span className="flex items-center gap-1 text-muted-foreground"><Accessibility className="size-3.5" />wheelchair needed</span>}
      </div>
      <div className="flex flex-col gap-1.5">
        {options.map(({ responder: r, km, fits, available }, i) => (
          <div key={r.id} className="flex items-center gap-2 text-xs">
            <button className="min-w-0 flex-1 truncate text-left hover:underline" onClick={() => onSelectCrew(r.id)}>
              <span className="font-medium">{r.name}</span>
              <span className="text-muted-foreground"> · {km.toFixed(1)} km{!available ? ' · busy' : !fits ? ' · no wheelchair lift' : i === 0 ? ' · best match' : ''}</span>
            </button>
            <Button size="xs" variant={i === 0 && available && fits ? 'default' : 'outline'} disabled={!available || !fits} onClick={() => onDispatch(r.id)}>
              <PhoneCall /> Call & dispatch
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
      <div className={cn('min-w-0 max-w-[92%] whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-sm leading-relaxed [overflow-wrap:anywhere]', caller ? 'bg-muted' : 'bg-primary text-primary-foreground')}>
        <div className={cn('mb-0.5 text-[10px] uppercase tracking-wide', caller ? 'text-muted-foreground' : 'text-primary-foreground/70')}>{caller ? 'Caller' : 'AI agent'} <time className="ml-1 normal-case tracking-normal">{new Date(line.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time></div>
        {line.text}
      </div>
    </div>
  )
}, (previous, next) => previous.line.id === next.line.id && previous.line.text === next.line.text && previous.line.speaker === next.line.speaker && previous.line.at === next.line.at)
