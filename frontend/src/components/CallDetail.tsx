import { useEffect, useRef, useState } from 'react'
import { Accessibility, MapPin, MessageSquareText, Phone, PhoneCall, Send, Truck, Users, Volume2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { etaMin, needsRescue, needsWheelchair, suggestCrews } from '@/lib/dispatch'
import { elapsed, zoneFor } from '@/lib/geo'
import { cn } from '@/lib/utils'
import type { Call, Dispatch, Responder, TranscriptLine, Zone } from '@/types'
import { SITUATION, STATUS } from './labels'

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
}) {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines.length, call?.id])

  if (!call) return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Select a call</div>
  const zone = zoneFor(call.position, zones)
  const ended = call.status === 'ended' || call.status === 'resolved'
  const send = async (mode: 'context' | 'say', text = draft) => {
    if (!text.trim() || ended || sending) return
    setSending(true)
    try { await onSteer(text.trim(), mode); setDraft('') }
    catch { /* Parent displays the backend error; keep the draft for retry. */ }
    finally { setSending(false) }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="text-base font-semibold">{call.callerName}</div>
            <div className="text-xs text-muted-foreground">{call.id}</div>
          </div>
          <div className="flex items-center gap-1.5">
            {call.status === 'active' && <span className="flex items-center gap-1 text-xs font-medium text-red-600"><span className="size-2 animate-pulse rounded-full bg-red-500" />LIVE</span>}
            <span className="font-mono text-xs tabular-nums text-muted-foreground">{elapsed(call.startedAt, now)}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge className={SITUATION[call.situation].badge}>{SITUATION[call.situation].label}</Badge>
          <Badge variant="outline">{STATUS[call.status]}</Badge>
        </div>
        <div className="grid gap-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5"><MapPin className="size-3.5" />{call.address}</span>
          <span className="flex items-center gap-1.5"><Phone className="size-3.5" />{call.phone}</span>
          <span className="flex items-center gap-1.5"><Users className="size-3.5" />{call.people ?? 'Unknown'} people · {call.mobility}</span>
        </div>
        <div className={cn('rounded-md border p-2.5 text-xs', zone?.level === 'evacuate' ? 'border-red-200 bg-red-50 text-red-900' : zone ? 'border-amber-200 bg-amber-50 text-amber-900' : 'bg-muted')}>
          <div className="font-medium">{call.instruction?.zone_id ? `Published instruction · v${call.instruction.version ?? '—'}` : zone ? zone.label : 'No matched instruction'}</div>
          <div className="mt-0.5">{call.instruction?.text ?? zone?.instruction ?? 'Confirm the current location and request operator guidance.'}</div>
        </div>
        <div className="text-xs text-muted-foreground">{call.scenarioId === 'dashboard' ? 'Shared dashboard context' : 'Demonstration scenario'} · {call.position ? 'Location mapped' : 'No confirmed map coordinates'}{call.wheelchairUsers !== undefined ? ` · ${call.wheelchairUsers} wheelchair users` : ''}</div>
        <Rescue call={call} responders={responders} dispatches={dispatches} now={now} onDispatch={onDispatch} onSelectCrew={onSelectCrew} />
      </div>
      <Separator />
      <div className="flex items-center gap-1.5 px-4 pt-3 text-xs font-medium text-muted-foreground"><MessageSquareText className="size-3.5" />Live transcript</div>
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
        <div className="flex flex-col gap-2">
          {lines.map((l) => (
            <TranscriptRow key={l.id} line={l} />
          ))}
        </div>
      </div>
      <Separator />
      <div className="space-y-2 p-3">
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
      </div>
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
  if (!needsRescue(call)) return null
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

function TranscriptRow({ line }: { line: TranscriptLine }) {
  if (line.speaker === 'system') return <div className="text-center text-[11px] text-muted-foreground">{line.text}</div>
  if (line.speaker === 'steer')
    return (
      <div className="rounded-md border border-dashed border-blue-300 bg-blue-50 px-2.5 py-1.5 text-xs text-blue-900">
        <span className="font-medium">Dispatcher → agent:</span> {line.text}
      </div>
    )
  const caller = line.speaker === 'caller'
  return (
    <div className={cn('flex', caller ? 'justify-start' : 'justify-end')}>
      <div className={cn('max-w-[85%] rounded-lg px-3 py-2 text-sm', caller ? 'bg-muted' : 'bg-primary text-primary-foreground')}>
        <div className={cn('mb-0.5 text-[10px] uppercase tracking-wide', caller ? 'text-muted-foreground' : 'text-primary-foreground/70')}>{caller ? 'Caller' : 'AI agent'}</div>
        {line.text}
      </div>
    </div>
  )
}
