import type { ReactNode } from 'react'
import { Accessibility, Phone, Truck, Building2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { activeDispatch, etaMin } from '@/lib/dispatch'
import { byPriority, callDuration, zoneFor } from '@/lib/geo'
import { cn } from '@/lib/utils'
import type { Call, Dispatch, Facility, Responder, Selection, TranscriptLine, Zone } from '@/types'
import { CREW_KIND, CREW_STATUS, SITUATION, STATUS, situationLabel } from './labels'

export function CallList({
  calls,
  facilities,
  lines,
  zones,
  responders,
  dispatches,
  selection,
  onSelect,
  now,
  tab, onTabChange, contactsContent, onSimulate, onStopSimulation,
}: {
  onSimulate: () => void; onStopSimulation: () => void
  tab: string; onTabChange: (tab: string) => void; contactsContent?: ReactNode
  calls: Call[]
  facilities: Facility[]
  lines: Record<string, TranscriptLine[]>
  zones: Zone[]
  responders: Responder[]
  dispatches: Dispatch[]
  selection?: Selection
  onSelect: (s: Selection) => void
  now: number
}) {
  const sorted = [...calls].sort(byPriority)
  return (
    <Tabs value={tab} onValueChange={onTabChange} className="flex h-full min-h-0 flex-col gap-0">
      <div className="hidden">
        <TabsList className="w-full">
          <TabsTrigger value="calls" className="gap-1.5"><Phone className="size-3.5" /><span>Calls</span><span className="tab-count">{calls.length}</span></TabsTrigger>
          <TabsTrigger value="crews" className="gap-1.5" title={`${responders.length} crews`}><Truck className="size-3.5" /><span>Crews</span></TabsTrigger>
          <TabsTrigger value="contacts" className="gap-1.5"><Building2 className="size-3.5" />Contacts</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="calls" className="min-h-0 min-w-0 flex-1">
        <div className="h-full min-w-0 overflow-x-hidden overflow-y-auto">
          <div className="flex min-w-0 flex-col gap-2 p-3">
            <p className="text-xs text-muted-foreground">{calls.filter((c) => c.status !== 'resolved' && c.status !== 'ended').length} active · {calls.filter((c) => c.status === 'resolved' || c.status === 'ended').length} ended</p>
            {!sorted.length && <p className="p-3 text-sm text-muted-foreground">No calls yet. Open the voice caller to begin.</p>}
            {sorted.map((c) => {
              const last = lines[c.id]?.findLast((l) => l.speaker === 'caller' || l.speaker === 'agent')
              const zone = zoneFor(c.position, zones)
              const crew = dispatches.find((d) => d.status !== 'done' && d.target.kind === 'call' && d.target.id === c.id)
              return (
                <button
                  key={c.id}
                  onClick={() => onSelect({ kind: 'call', id: c.id })}
                  className={cn(
                    'w-full min-w-0 rounded-lg border bg-card p-3 text-left transition hover:bg-muted/60',
                    selection?.kind === 'call' && selection.id === c.id && 'border-teal-600 bg-teal-50/50 ring-1 ring-teal-600/15',
                    (c.status === 'resolved' || c.status === 'ended') && 'border-dashed',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{c.callerName}</div>
                      <div className="truncate text-xs text-muted-foreground">{c.address} · {c.people ?? 'Unknown'} {c.people === 1 ? 'person' : 'people'}</div>
                    </div>
                    <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{callDuration(c, now)}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge className={SITUATION[c.situation].badge}>{situationLabel(c)}</Badge>
                    <Badge variant="outline">{STATUS[c.status]}</Badge>
                    {zone && <Badge variant="secondary">{zone.label}</Badge>}
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
        </div>
      </TabsContent>
      <TabsContent value="crews" className="min-h-0 min-w-0 flex-1">
        <div className="h-full min-w-0 overflow-x-hidden overflow-y-auto">
          <div className="flex flex-col gap-2 p-3">
            {responders.length === 0 ? <div className="space-y-3 rounded-lg border border-dashed p-4">
              <h3 className="text-sm font-semibold">No crews yet</h3>
              <p className="text-xs text-muted-foreground">Spread four simulated crews across the area. Drag their map markers to reposition them, or select a crew to set a route.</p>
              <Button size="sm" onClick={onSimulate}>Simulate AI crews</Button>
            </div> : <div className="space-y-2 rounded-lg border bg-teal-50 p-3">
              <div className="text-sm font-medium">Simulation running · {responders.length} crews</div>
              <p className="text-xs text-muted-foreground">Drag any crew on the map to move it. Dropping restarts its patrol and cancels its current simulated route.</p>
              <Button size="sm" variant="outline" onClick={onStopSimulation}>Stop simulation</Button>
            </div>}
            {responders.map((r) => {
              const d = activeDispatch(dispatches, r.id)
              return (
                <button
                  key={r.id}
                  onClick={() => onSelect({ kind: 'crew', id: r.id })}
                  className={cn(
                    'w-full min-w-0 rounded-lg border bg-card p-3 text-left transition hover:bg-muted/60',
                    selection?.kind === 'crew' && selection.id === r.id && 'border-teal-600 bg-teal-50/50 ring-1 ring-teal-600/15',
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
        </div>
      </TabsContent>
      <TabsContent value="contacts" className="min-h-0 min-w-0 flex-1">
        {contactsContent ?? <>
        <div className="h-full min-w-0 overflow-x-hidden overflow-y-auto">
          <div className="flex flex-col gap-2 p-3">
            <p className="text-xs text-muted-foreground">Team records and discovered facilities. Select a contact to inspect numbers and sources. Availability remains unconfirmed.</p>
            {facilities.map((f) => {
              const zone = f.position && zoneFor(f.position, zones)
              return (
                <button key={f.id} onClick={() => onSelect({ kind: 'facility', id: f.id })} className={cn("rounded-lg border bg-card p-3 text-left hover:bg-muted/60", selection?.id === f.id && "border-blue-600 ring-1 ring-blue-600")}>
                  <div className="text-sm font-medium">{f.name}</div>
                  <div className="text-xs text-muted-foreground">{f.type.replaceAll('_', ' ')}{f.area ? ` · ${f.area}` : ''}{f.mobilitySupport ? ` · ${f.mobilitySupport.replaceAll('_', ' ')}` : ''}</div>
                  <div className="mt-1.5 flex items-center gap-1.5 text-xs">
                    <Phone className="size-3" /> {f.contact || (f.discovery?.phone_candidates.length ? 'Multiple candidates · review' : 'Phone not found')}
                    {zone && <Badge variant="secondary" className="ml-auto">{zone.label}</Badge>}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
              </>}
      </TabsContent>
    </Tabs>
  )
}
