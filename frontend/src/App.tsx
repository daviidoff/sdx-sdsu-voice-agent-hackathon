import { useEffect, useMemo, useState } from 'react'
import { Flame, ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CallDetail } from '@/components/CallDetail'
import { CallList } from '@/components/CallList'
import { DisasterMap } from '@/components/DisasterMap'
import { crews } from '@/data/crews'
import { api, createFeed, toCall, toFacilities, toLines } from '@/lib/feed'
import type { Snapshot } from '@/lib/feed'
import type { Call, Selection, TranscriptLine, Zone, LatLng } from '@/types'

export default function App() {
  const feed = useMemo(() => createFeed(), [])
  const [snapshot, setSnapshot] = useState<Snapshot>()
  const [selection, setSelection] = useState<Selection>()
  const [connectionError, setConnectionError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const [drawing, setDrawing] = useState(false)
  const [draft, setDraft] = useState<Zone>()
  const [publishing, setPublishing] = useState(false)
  useEffect(() => feed.start((event) => {
    if (event.type === 'snapshot') { setSnapshot(event.snapshot); setConnectionError('') }
    if (event.type === 'connection') setConnectionError(event.error)
  }), [feed])
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const calls: Call[] = useMemo(() => snapshot?.calls.map(toCall) ?? [], [snapshot])
  const lines: Record<string, TranscriptLine[]> = useMemo(() => Object.fromEntries(snapshot?.calls.map((call) => [call.id, toLines(call)]) ?? []), [snapshot])
  const facilities = useMemo(() => toFacilities(snapshot?.facilities ?? []), [snapshot])
  const zones = snapshot?.zones ?? []
  const selectedCall = calls.find((call) => call.id === selection?.id) ?? (!selection ? calls.find((call) => call.status === 'active') ?? calls[0] : undefined)
  const active = calls.filter((call) => call.status === 'active')
  const select = (value: Selection) => {
    setSelection(value)
    setDraft(value.kind === 'zone' ? zones.find((zone) => zone.id === value.id) : undefined)
  }
  const drawZone = (sw: LatLng, ne: LatLng) => {
    setDraft({ id: crypto.randomUUID(), label: 'New response zone', area: '', level: 'unknown', instruction: '',
      polygon: [[ne[0], sw[1]], ne, [sw[0], ne[1]], sw] })
    setDrawing(false)
  }
  const publish = async () => {
    if (!draft) return
    setPublishing(true); setActionError('')
    try {
      const published = await api<Zone>('/api/dashboard/zones', draft)
      setDraft(published)
      setNotice(`Published version ${published.version}. Matching active voice sessions receive the instruction.`)
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Publish failed') }
    finally { setPublishing(false) }
  }
  const steer = async (text: string, mode: 'context' | 'say') => {
    if (!selectedCall) return
    setActionError(''); setNotice('')
    try { await feed.steer(selectedCall.id, text, mode); setNotice('Operator message queued. Delivery appears in the transcript.') }
    catch (error) { setActionError(error instanceof Error ? error.message : 'Send failed'); throw error }
  }
  return (
    <div className="flex h-dvh flex-col bg-muted/30 text-foreground">
      <header className="flex items-center gap-4 border-b bg-background px-4 py-3">
        <div className="flex size-9 items-center justify-center rounded-md bg-orange-600 text-white"><Flame className="size-5" /></div>
        <div><div className="text-sm font-semibold">Emergency OS</div><div className="text-xs text-muted-foreground">Voice coordination dashboard</div></div>
        <div className="ml-4 text-xs"><strong className="text-lg">{active.length}</strong> active calls · {active.filter((c) => c.situation === 'needs_help').length} need assistance</div>
        <div className="ml-auto flex items-center gap-3">
          <Badge variant="outline">{connectionError ? 'Disconnected · data may be stale' : snapshot ? 'Live backend · 1s refresh' : 'Connecting…'}</Badge>
          <a href={import.meta.env.DEV ? 'http://127.0.0.1:8000/?source=dashboard' : '/?source=dashboard'} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-md bg-primary px-3 py-2 text-xs text-primary-foreground">Open voice caller <ExternalLink className="size-3" /></a>
        </div>
      </header>
      {(connectionError || actionError || notice) && <div role={connectionError || actionError ? 'alert' : 'status'} className="border-b bg-amber-50 px-4 py-2 text-xs">{connectionError || actionError || notice}</div>}
      <div className="flex items-center gap-4 border-b bg-background px-4 py-2 text-xs">
        <span>{snapshot?.incidents.map((i) => `${i.name} (${i.status ?? 'status unknown'})`).join(' · ') || 'No incident records available'}</span>
        <span className="text-muted-foreground">{facilities.length} team contacts · {snapshot?.routes.length ?? 0} candidate routes · {calls.filter((c) => !c.position).length} calls without map coordinates</span>
        <button className="ml-auto underline" onClick={() => setDraft({ id: crypto.randomUUID(), label: 'Response zone', area: '', level: 'unknown', polygon: [], instruction: '' })}>Publish area instruction</button>
      </div>
      <main className="grid min-h-0 flex-1 grid-cols-[300px_1fr_400px]">
        <aside className="min-h-0 border-r bg-background">
          <CallList calls={calls} lines={lines} zones={zones} facilities={facilities} responders={crews} dispatches={[]} selection={selectedCall ? { kind: 'call', id: selectedCall.id } : selection} onSelect={select} now={now} />
        </aside>
        <section className="min-h-0">
          <DisasterMap calls={calls} zones={zones} facilities={facilities} responders={crews} dispatches={[]} now={now} selection={selection} onSelect={select} drawing={drawing} onDrawingChange={setDrawing} onZoneDrawn={drawZone} />
        </section>
        <aside className="min-h-0 overflow-auto border-l bg-background">
          {draft ? <div className="space-y-4 p-4">
            <div className="text-base font-semibold">Publish an operator instruction</div>
            <p className="text-xs text-muted-foreground">Instructions match the caller’s confirmed area name exactly. Drawn boundaries are for operator reference; no address geocoding is connected.</p>
            <label className="block text-xs">Zone name<input className="mt-1 w-full rounded border p-2" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} /></label>
            <label className="block text-xs">Confirmed area name<input className="mt-1 w-full rounded border p-2" placeholder="e.g. Mission Valley" value={draft.area ?? ''} onChange={(e) => setDraft({ ...draft, area: e.target.value })} /></label>
            <label className="block text-xs">Action<select className="mt-1 w-full rounded border p-2" value={draft.level} onChange={(e) => setDraft({ ...draft, level: e.target.value as Zone['level'] })}><option value="unknown">Await guidance</option><option value="evacuate">Evacuate</option><option value="warning">Warning</option><option value="shelter">Shelter in place</option></select></label>
            <label className="block text-xs">Operator instruction<textarea className="mt-1 w-full rounded border p-2" rows={5} value={draft.instruction} onChange={(e) => setDraft({ ...draft, instruction: e.target.value })} /></label>
            <Button disabled={publishing || !draft.area?.trim() || !draft.instruction.trim()} onClick={() => void publish()}>{publishing ? 'Publishing…' : 'Publish to voice agent'}</Button>
            <Button variant="ghost" onClick={() => { setDraft(undefined); setSelection(undefined) }}>Close</Button>
            {zones.map((z) => <button key={z.id} className="block text-xs underline" onClick={() => setDraft(z)}>{z.label} · v{z.version}</button>)}
          </div> : <CallDetail call={selectedCall} lines={selectedCall ? lines[selectedCall.id] ?? [] : []} zones={zones} responders={[]} dispatches={[]} now={now} onSteer={steer} onDispatch={() => {}} onSelectCrew={() => {}} />}
        </aside>
      </main>
    </div>
  )
}
