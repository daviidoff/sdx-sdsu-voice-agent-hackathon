import { Accessibility, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { activeDispatch, etaMin } from '@/lib/dispatch'
import { byPriority, callDuration, zoneFor } from '@/lib/geo'
import { cn } from '@/lib/utils'
import type { Call, Dispatch, Responder, Selection, TranscriptLine, Zone } from '@/types'
import { CREW_KIND, CREW_STATUS, SITUATION, STATUS, situationLabel } from './labels'

export function CallList({
  calls,
  lines,
  zones,
  responders,
  dispatches,
  selection,
  onSelect,
  now,
  tab, onSimulate, onStopSimulation,
}: {
  onSimulate: () => void; onStopSimulation: () => void
  tab: 'calls' | 'crews'
  calls: Call[]
  lines: Record<string, TranscriptLine[]>
  zones: Zone[]
  responders: Responder[]
  dispatches: Dispatch[]
  selection?: Selection
  onSelect: (s: Selection) => void
  now: number
}) {
  const sorted = [...calls].sort(byPriority)
  return tab === 'calls' ? (
    <div className="h-full min-w-0 overflow-x-hidden overflow-y-auto">
      <div className="flex min-w-0 flex-col gap-3 p-4">
        {sorted.length ? <p className="text-xs text-muted-foreground">{calls.filter((c) => c.status !== 'resolved' && c.status !== 'ended').length} active · {calls.filter((c) => c.status === 'resolved' || c.status === 'ended').length} ended</p> : <p className="text-sm text-muted-foreground">No calls yet. Open the voice caller to begin.</p>}
        {sorted.map((c) => {
          const last = lines[c.id]?.findLast((l) => l.speaker === 'caller' || l.speaker === 'agent')
          const zone = zoneFor(c.position, zones)
          const crew = dispatches.find((d) => d.status !== 'done' && d.target.kind === 'call' && d.target.id === c.id)
          return (
            <button
              key={c.id}
              onClick={() => onSelect({ kind: 'call', id: c.id })}
              aria-pressed={selection?.kind === 'call' && selection.id === c.id}
              className="workspace-row"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{c.callerName}</div>
                  <div className="truncate text-xs text-muted-foreground">{c.address} · {c.people ?? 'Unknown'} {c.people === 1 ? 'person' : 'people'}</div>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">{callDuration(c, now)}</span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                {c.situation !== 'unknown' && <Badge className={SITUATION[c.situation].badge}>{situationLabel(c)}</Badge>}
                <span className={cn(c.status === 'active' && 'font-medium text-primary')}>{STATUS[c.status]}</span>
                {zone && zone.label !== c.address && <span>{zone.label}</span>}
              </div>
              {crew && (
                <p className="mt-2 text-xs font-medium text-blue-700">
                  {responders.find((r) => r.id === crew.crewId)?.name} · {crew.status === 'calling' ? 'calling crew…' : crew.status === 'en_route' ? `${etaMin(crew, now)} min away` : 'on scene'}
                </p>
              )}
              {last && <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{last.speaker === 'caller' ? 'Caller' : 'Agent'}: {last.text}</p>}
            </button>
          )
        })}
      </div>
    </div>
  ) : (
    <div className="h-full min-w-0 overflow-x-hidden overflow-y-auto">
      <div className="flex flex-col gap-3 p-4">
        {responders.length === 0 ? <div className="space-y-3">
          <p className="text-sm text-muted-foreground">Place four simulated crews on the map. Drag a marker to move a crew or select one to set a route.</p>
          <Button size="sm" onClick={onSimulate}>Simulate AI crews</Button>
        </div> : <div className="space-y-2 pb-1">
          <div className="text-sm font-medium">{responders.length} crews on the map</div>
          <Button size="sm" variant="outline" onClick={onStopSimulation}>Stop simulation</Button>
        </div>}
        {responders.map((r) => {
          const d = activeDispatch(dispatches, r.id)
          return (
            <button
              key={r.id}
              onClick={() => onSelect({ kind: 'crew', id: r.id })}
              aria-pressed={selection?.kind === 'crew' && selection.id === r.id}
              className="workspace-row"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1 truncate text-sm font-medium">
                    {r.name}
                    {r.wheelchair && <Accessibility className="size-3.5 text-muted-foreground" />}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">{CREW_KIND[r.kind]} · {r.seats} seats</div>
                </div>
                <Badge className={d?.status === 'calling' ? 'bg-sky-50 text-sky-900' : CREW_STATUS[r.status].badge}>
                  {d?.status === 'calling' ? 'Calling…' : CREW_STATUS[r.status].label}
                </Badge>
              </div>
              {d && (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <ArrowRight className="size-3 shrink-0" aria-hidden="true" /><span className="truncate">{d.target.label}{d.status === 'en_route' ? ` · ${etaMin(d, now)} min` : ''}</span>
                </p>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
