import { useEffect, useRef, useState } from 'react'
import { Accessibility, PhoneCall, Radio, Truck } from 'lucide-react'
import { NativeSelect, NativeSelectOptGroup, NativeSelectOption } from '@/components/ui/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { activeDispatch, endedAssistanceLocations, etaMin, suggestCalls } from '@/lib/dispatch'
import { cn } from '@/lib/utils'
import type { Call, Dispatch, Facility, Responder, TranscriptLine } from '@/types'
import { CREW_KIND, CREW_STATUS, SITUATION } from './labels'

export function CrewDetail({
  crew,
  calls,
  dispatches,
  now,
  onDispatch,
  onSelectCall, facilities, onRoute, onRelease,
}: {
  facilities: Facility[]
  onRoute: (facility: Facility) => void
  onRelease: () => void
  crew: Responder
  calls: Call[]
  dispatches: Dispatch[]
  now: number
  onDispatch: (call: Call) => void
  onSelectCall: (id: string) => void
}) {
  const [destination, setDestination] = useState('')
  const destinations = facilities.filter((f) => f.position)
  const reportedLocations = endedAssistanceLocations(crew, calls, dispatches)
  const chosen = destinations.find((f) => `place:${f.id}` === destination)
  const reported = reportedLocations.find((call) => `call:${call.id}` === destination)
  const d = activeDispatch(dispatches, crew.id)
  const last = d ?? [...dispatches].reverse().find((x) => x.crewId === crew.id)
  const options = suggestCalls(crew, calls, dispatches, now)
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [last?.radio.length])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-1.5 text-base font-semibold"><Truck className="size-4" />{crew.name}</div>
            <div className="text-xs text-muted-foreground">{CREW_KIND[crew.kind]} · {crew.seats} seats</div>
          </div>
          <Badge className={CREW_STATUS[crew.status].badge}>{CREW_STATUS[crew.status].label}</Badge>
        </div>
        {crew.wheelchair && <Badge variant="secondary"><Accessibility /> Wheelchair transport</Badge>}
        {d && (
          <div className="rounded-md border border-blue-200 bg-blue-50 p-2.5 text-xs text-blue-900">
            <div className="font-medium">{d.target.kind === 'call' ? `Rescue: ${d.target.label}` : d.target.label}</div>
            <div className="mt-0.5">
              {d.status === 'calling' && 'Calling the crew…'}
              {d.status === 'en_route' && `En route ${d.routeText} · ETA ${etaMin(d, now)} min`}
              {d.status === 'on_scene' && 'On scene (simulated)'}
            </div>
            <Button size="sm" variant="outline" className="mt-2" onClick={onRelease}>{d.status === 'on_scene' ? 'Resume patrol' : 'Cancel route'}</Button>
            {d.target.kind === 'call' && (
              <button className="mt-1 underline" onClick={() => onSelectCall(d.target.id)}>Open caller</button>
            )}
          </div>
        )}
      </div>
      <Separator />
      {!d && (
        <div className="space-y-2 p-4">
          <div className="space-y-2 rounded-lg border p-3">
            <label htmlFor="crew-destination" className="text-sm font-medium">Route destination</label>
            <NativeSelect id="crew-destination" className="w-full" selectClassName="h-auto bg-background py-2 pl-2" value={destination} onChange={(event) => setDestination(event.target.value)}>
              <NativeSelectOption value="">Choose a destination…</NativeSelectOption>
              {reportedLocations.length > 0 && <NativeSelectOptGroup label="Assistance reported on ended calls">
                {reportedLocations.map((call) => <NativeSelectOption key={call.id} value={`call:${call.id}`}>{call.address} · {call.callerName}</NativeSelectOption>)}
              </NativeSelectOptGroup>}
              {destinations.length > 0 && <NativeSelectOptGroup label="Points of interest">
                {destinations.map((f) => <NativeSelectOption key={f.id} value={`place:${f.id}`}>{f.name}</NativeSelectOption>)}
              </NativeSelectOptGroup>}
            </NativeSelect>
            {reported && <p className="text-xs text-muted-foreground">Assistance reported · last confirmed caller location</p>}
            {!destinations.length && !reportedLocations.length && <p className="text-xs text-muted-foreground">No mapped destinations available.</p>}
            <Button size="sm" disabled={!chosen && !reported} onClick={() => { if (reported) onDispatch(reported); else if (chosen) onRoute(chosen) }}>
              {reported ? 'Dispatch simulated crew' : 'Set simulated route'}
            </Button>
            <p className="text-xs text-muted-foreground">Routes do not account for disaster conditions.</p>
          </div>
          <div className="text-xs font-medium text-muted-foreground">Simulate a rescue route</div>
          {options.length === 0 && <p className="text-xs text-muted-foreground">No active calls awaiting a crew.</p>}
          {options.slice(0, 4).map(({ call, km, fits }, i) => (
            <div key={call.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{call.callerName}</div>
                  <div className="truncate text-xs text-muted-foreground">{call.address} · {km.toFixed(1)} km</div>
                </div>
                <Badge className={SITUATION[call.situation].badge}>{SITUATION[call.situation].label}</Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{call.mobility}</div>
              <div className="mt-2 flex items-center gap-2">
                {i === 0 && fits && <Badge variant="outline">Best match</Badge>}
                {!fits && <span className="text-xs text-red-600">Can't carry a wheelchair</span>}
                <Button size="sm" className="ml-auto" onClick={() => onDispatch(call)} disabled={!fits || !call.position}>
                  <PhoneCall /> Simulate crew dispatch
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
      {last && (
        <>
          <div className="flex items-center gap-1.5 px-4 pt-3 text-xs font-medium text-muted-foreground"><Radio className="size-3.5" />Call with crew (AI dispatcher · simulated)</div>
          <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
            <div className="flex flex-col gap-2">
              {last.radio.map((l) => <RadioRow key={l.id} line={l} />)}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function RadioRow({ line }: { line: TranscriptLine }) {
  if (line.speaker === 'system') return <div className="text-center text-[11px] text-muted-foreground">{line.text}</div>
  const crew = line.speaker === 'caller'
  return (
    <div className={cn('flex', crew ? 'justify-start' : 'justify-end')}>
      <div className={cn('max-w-[85%] rounded-lg px-3 py-2 text-sm', crew ? 'bg-muted' : 'bg-blue-600 text-white')}>
        <div className={cn('mb-0.5 text-[10px] uppercase tracking-wide', crew ? 'text-muted-foreground' : 'text-white/70')}>{crew ? 'Crew' : 'AI dispatcher'}</div>
        {line.text}
      </div>
    </div>
  )
}
