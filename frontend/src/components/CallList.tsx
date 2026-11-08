import { useEffect, useState } from 'react'
import { Accessibility, Phone } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { facilities } from '@/data/fake'
import { activeDispatch, etaMin } from '@/lib/dispatch'
import { byPriority, elapsed, zoneFor } from '@/lib/geo'
import { cn } from '@/lib/utils'
import type { Call, Dispatch, Responder, Selection, TranscriptLine, Zone } from '@/types'
import { CREW_KIND, CREW_STATUS, SITUATION, STATUS } from './labels'

export function CallList({
  calls,
  lines,
  zones,
  responders,
  dispatches,
  selection,
  onSelect,
  now,
}: {
  calls: Call[]
  lines: Record<string, TranscriptLine[]>
  zones: Zone[]
  responders: Responder[]
  dispatches: Dispatch[]
  selection?: Selection
  onSelect: (s: Selection) => void
  now: number
}) {
  const [tab, setTab] = useState('calls')
  // Follow the map: clicking a crew there opens the Crews tab, clicking a caller opens Calls.
  useEffect(() => {
    if (selection?.kind === 'crew') setTab('crews')
    if (selection?.kind === 'call') setTab('calls')
  }, [selection?.kind, selection?.id])

  const sorted = [...calls].sort(byPriority)
  const busy = dispatches.filter((d) => d.status !== 'done').length
  return (
    <Tabs value={tab} onValueChange={setTab} className="flex h-full min-h-0 flex-col gap-0">
      <div className="border-b px-3 py-2">
        <TabsList className="w-full">
          <TabsTrigger value="calls">Calls ({calls.filter((c) => c.status !== 'resolved').length})</TabsTrigger>
          <TabsTrigger value="crews">Crews ({busy}/{responders.length})</TabsTrigger>
          <TabsTrigger value="contacts">Contacts</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="calls" className="min-h-0 flex-1">
        <ScrollArea className="h-full">
          <div className="flex flex-col gap-2 p-3">
            {sorted.map((c) => {
              const last = lines[c.id]?.findLast((l) => l.speaker === 'caller' || l.speaker === 'agent')
              const zone = zoneFor(c.position, zones)
              const crew = dispatches.find((d) => d.status !== 'done' && d.target.kind === 'call' && d.target.id === c.id)
              return (
                <button
                  key={c.id}
                  onClick={() => onSelect({ kind: 'call', id: c.id })}
                  className={cn(
                    'rounded-lg border bg-card p-3 text-left transition hover:bg-muted/60',
                    selection?.kind === 'call' && selection.id === c.id && 'border-foreground/40 ring-2 ring-foreground/10',
                    c.status === 'resolved' && 'opacity-60',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{c.callerName}</div>
                      <div className="truncate text-xs text-muted-foreground">{c.address} · {c.people} {c.people === 1 ? 'person' : 'people'}</div>
                    </div>
                    <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{elapsed(c.startedAt, now)}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge className={SITUATION[c.situation].badge}>{SITUATION[c.situation].label}</Badge>
                    <Badge variant="outline">{STATUS[c.status]}</Badge>
                    {zone && <Badge variant="secondary">Zone {zone.id}</Badge>}
                    {c.status === 'active' && <span className="ml-auto size-2 animate-pulse rounded-full bg-red-500" title="Live" />}
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
        </ScrollArea>
      </TabsContent>
      <TabsContent value="crews" className="min-h-0 flex-1">
        <ScrollArea className="h-full">
          <div className="flex flex-col gap-2 p-3">
            <p className="text-xs text-muted-foreground">Click a crew to call it and send it to a caller. Fake crews.</p>
            {responders.map((r) => {
              const d = activeDispatch(dispatches, r.id)
              return (
                <button
                  key={r.id}
                  onClick={() => onSelect({ kind: 'crew', id: r.id })}
                  className={cn(
                    'rounded-lg border bg-card p-3 text-left transition hover:bg-muted/60',
                    selection?.kind === 'crew' && selection.id === r.id && 'border-foreground/40 ring-2 ring-foreground/10',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1 truncate text-sm font-medium">
                        {r.name}
                        {r.wheelchair && <Accessibility className="size-3.5 text-muted-foreground" />}
                      </div>
                      <div className="truncate text-xs text-muted-foreground">{CREW_KIND[r.kind]} · {r.seats} seats</div>
                    </div>
                    <Badge className={d?.status === 'calling' ? 'bg-sky-500 text-white' : CREW_STATUS[r.status].badge}>
                      {d?.status === 'calling' ? 'Calling…' : CREW_STATUS[r.status].label}
                    </Badge>
                  </div>
                  {d && (
                    <p className="mt-2 truncate text-xs text-blue-700">
                      → {d.target.label}{d.status === 'en_route' ? ` · ${etaMin(d, now)} min` : ''}
                    </p>
                  )}
                </button>
              )
            })}
          </div>
        </ScrollArea>
      </TabsContent>
      <TabsContent value="contacts" className="min-h-0 flex-1">
        <ScrollArea className="h-full">
          <div className="flex flex-col gap-2 p-3">
            <p className="text-xs text-muted-foreground">From the information search agent (opt-in registry and public directories). Fake data.</p>
            {facilities.map((f) => {
              const zone = zoneFor(f.position, zones)
              return (
                <div key={f.id} className="rounded-lg border bg-card p-3">
                  <div className="text-sm font-medium">{f.name}</div>
                  <div className="text-xs text-muted-foreground">{f.type.replaceAll('_', ' ')}{f.mobilitySupport ? ` · ${f.mobilitySupport.replaceAll('_', ' ')}` : ''}</div>
                  <div className="mt-1.5 flex items-center gap-1.5 text-xs">
                    <Phone className="size-3" /> {f.contact}
                    {zone && <Badge variant="secondary" className="ml-auto">Zone {zone.id}</Badge>}
                  </div>
                </div>
              )
            })}
          </div>
        </ScrollArea>
      </TabsContent>
    </Tabs>
  )
}
