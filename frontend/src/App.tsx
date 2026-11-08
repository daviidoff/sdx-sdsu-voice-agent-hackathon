import { useEffect, useMemo, useState } from 'react'
import { Flame, ExternalLink, Inbox } from 'lucide-react'
import { OperatorInbox } from '@/components/OperatorInbox'
import { unreadMessages } from '@/lib/inbox'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ContactPanel } from '@/components/ContactPanel'
import { ContactReview } from '@/components/ContactReview'
import { MockReceiver } from '@/components/MockReceiver'
import { emptyWorkflow, sanDiegoFacility } from '@/lib/contacts'
import type { ContactSession } from '@/lib/contacts'
import { DiscoveryImport } from '@/components/DiscoveryImport'
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
  const [tab, setTab] = useState('contacts')
  const [contactPolygon, setContactPolygon] = useState<LatLng[]>([])
  const [contactDrawing, setContactDrawing] = useState(false)
  const [searchId, setSearchId] = useState<string>()
  const [receiver, setReceiver] = useState<ContactSession>()
  const workflow = snapshot?.contact_workflow ?? emptyWorkflow
  const changeTab = (value: string) => { setTab(value); setContactDrawing(false); setDrawing(false); setDraft(undefined); setSelection(undefined) }
  const [deleting, setDeleting] = useState(false)
  const [inboxOpen, setInboxOpen] = useState(false)
  const unread = snapshot?.calls.reduce((count, call) => count + unreadMessages(call), 0) ?? 0
  useEffect(() => feed.start((event) => {
    if (event.type === 'snapshot') { setSnapshot(event.snapshot); setConnectionError('') }
    if (event.type === 'connection') setConnectionError(event.error)
  }), [feed])
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const calls: Call[] = useMemo(() => snapshot?.calls.map(toCall) ?? [], [snapshot])
  const lines: Record<string, TranscriptLine[]> = useMemo(() => Object.fromEntries(snapshot?.calls.map((call) => [call.id, toLines(call)]) ?? []), [snapshot])
  const facilities = useMemo(() => toFacilities(snapshot?.facilities ?? []).filter(sanDiegoFacility), [snapshot])
  const zones = snapshot?.zones ?? []
  const selectedCall = calls.find((call) => call.id === selection?.id) ?? (!selection && tab !== 'contacts' ? calls.find((call) => call.status === 'active') ?? calls[0] : undefined)
  const selectedFacility = selection?.kind === 'facility' ? facilities.find((f) => f.id === selection.id) : undefined
  const effectiveSelection = selectedCall ? { kind: 'call' as const, id: selectedCall.id } : selection
  const active = calls.filter((call) => call.status === 'active')
  const select = (value: Selection) => {
    if (publishing || deleting) return
    setSelection(value)
    if (value.kind === 'facility') setTab('contacts')
    if (value.kind === 'call') setTab('calls')
    setDraft(value.kind === 'zone' ? zones.find((zone) => zone.id === value.id) : undefined)
  }
  const drawZone = (polygon: LatLng[]) => {
    setDraft({ id: crypto.randomUUID(), label: 'New response zone', area: '', level: 'unknown', instruction: '',
      polygon })
    setDrawing(false)
  }
  const publish = async () => {
    if (!draft) return
    setPublishing(true); setActionError('')
    try {
      const published = await api<Zone>('/api/dashboard/zones', { ...draft, area: draft.area?.trim() || (draft.polygon.length ? draft.label : '') })
      setDraft(published)
      setNotice(`Published version ${published.version}. Matching active voice sessions receive the instruction.`)
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Publish failed') }
    finally { setPublishing(false) }
  }
  const deleteInstruction = async () => {
    if (!draft?.version || publishing || deleting) return
    const zone = draft
    setDeleting(true); setActionError(''); setNotice('')
    try {
      await api(`/api/dashboard/zones/${encodeURIComponent(zone.id)}`, undefined, undefined, 'DELETE')
      setSnapshot((current) => current ? { ...current, zones: current.zones.filter((item) => item.id !== zone.id) } : current)
      setDraft((current) => current?.id === zone.id ? undefined : current)
      setSelection((current) => current?.kind === 'zone' && current.id === zone.id ? undefined : current)
      setNotice(`Deleted instruction for ${zone.label}. Affected active calls receive updated guidance.`)
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Delete failed') }
    finally { setDeleting(false) }
  }
  const refreshLocation = async () => {
    if (!selectedCall) return
    setActionError(''); setNotice('')
    try {
      await api(`/api/dashboard/calls/${encodeURIComponent(selectedCall.id)}/geolocate`, {})
      setNotice(selectedCall.status === 'ended' ? 'Map lookup refreshed. The original call instruction and transcript are preserved.' : 'Location and applicable zone rechecked for the voice agent.')
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Location lookup failed'); throw error }
  }
  const steer = async (text: string, mode: 'context' | 'say') => {
    if (!selectedCall) return
    setActionError(''); setNotice('')
    try { await feed.steer(selectedCall.id, text, mode); setNotice('Operator message queued. Delivery appears in the transcript.') }
    catch (error) { setActionError(error instanceof Error ? error.message : 'Send failed'); throw error }
  }
  return (
    <div className="flex h-dvh min-h-0 flex-col overflow-hidden bg-muted/30 text-foreground">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-background px-4 py-2">
        <div className="flex size-9 items-center justify-center rounded-md bg-orange-600 text-white"><Flame className="size-5" /></div>
        <div><div className="text-sm font-semibold">Emergency OS</div><div className="text-xs text-muted-foreground">Voice coordination dashboard</div></div>
        <div className="hidden text-xs xl:block"><strong className="text-lg">{active.length}</strong> active calls · {active.filter((c) => c.situation === 'needs_help').length} need assistance</div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => setInboxOpen(true)}><Inbox className="size-4" />Inbox{unread > 0 && <span className="rounded-full bg-orange-600 px-2 text-xs text-white">{unread}</span>}</Button>
          <Badge variant="outline">{connectionError ? 'Disconnected · data may be stale' : snapshot ? 'Live backend · 1s refresh' : 'Connecting…'}</Badge>
          <a href={import.meta.env.DEV ? 'http://127.0.0.1:8000/?source=dashboard' : '/?source=dashboard'} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-md bg-primary px-3 py-2 text-xs text-primary-foreground">Open voice caller <ExternalLink className="size-3" /></a>
        </div>
      </header>
      {(connectionError || actionError || notice) && <div role={connectionError || actionError ? 'alert' : 'status'} className="border-b bg-amber-50 px-4 py-2 text-xs">{connectionError || actionError || notice}</div>}
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b bg-background px-4 py-2 text-xs">
        <span>{snapshot?.incidents.map((i) => `${i.name} (${i.status ?? 'status unknown'})`).join(' · ') || 'No incident records available'}</span>
        <span className="text-muted-foreground">{facilities.length} facility contacts · {snapshot?.routes.length ?? 0} candidate routes · {calls.filter((c) => !c.position).length} calls without map coordinates</span>
        {tab === 'contacts' && <DiscoveryImport onImported={setNotice} onError={setActionError} />}
        <button className="ml-auto underline" onClick={() => setDraft({ id: crypto.randomUUID(), label: 'Response zone', area: '', level: 'unknown', polygon: [], instruction: '' })}>Publish area instruction</button>
      </div>
      <main className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(180px,22%)_minmax(180px,1fr)_minmax(340px,38%)] overflow-hidden">
        <aside className="min-h-0 min-w-0 overflow-hidden border-r bg-background">
          <CallList calls={calls} lines={lines} zones={zones} facilities={facilities} responders={crews} dispatches={[]} selection={effectiveSelection} onSelect={select} now={now} tab={tab} onTabChange={changeTab}
            contactsContent={<ContactPanel workflow={workflow} facilities={facilities} polygon={contactPolygon} onPolygon={setContactPolygon} searchId={searchId} onSearchSelect={setSearchId} onDraw={() => { setContactDrawing(true); setDrawing(false); setDraft(undefined) }} onSelect={(id) => select({ kind: 'facility', id })} onError={setActionError} />} />
        </aside>
        <section className="min-h-0 min-w-0 overflow-hidden">
          <DisasterMap calls={calls} zones={zones} facilities={facilities} responders={crews} dispatches={[]} now={now} selection={effectiveSelection} onSelect={select} drawing={drawing} onDrawingChange={setDrawing} onZoneDrawn={drawZone} draftZone={draft} contactsActive={tab === 'contacts'} contactPolygon={contactPolygon} contactDrawing={contactDrawing} onContactDrawn={(points) => { setContactPolygon(points); setContactDrawing(false) }} onContactDrawingChange={setContactDrawing} />
        </section>
        <aside className="min-h-0 min-w-0 overflow-hidden border-l bg-background">
          {draft ? <div className="h-full space-y-4 overflow-y-auto p-4">
            <div className="text-base font-semibold">Publish an operator instruction</div>
            <p className="text-xs text-muted-foreground">Published map boundaries apply to resolved caller locations. Place markers are approximate map references, not device GPS. Without a boundary, the confirmed area name must match.</p>
            <p className="rounded border bg-muted/40 p-2 text-xs">{draft.version ? `Editing published version ${draft.version}. Changes take effect when published.` : 'Unpublished draft. Publish to apply this instruction to callers.'}</p>
            <label className="block text-xs">Zone name<input className="mt-1 w-full rounded border p-2" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} /></label>
            <label className="block text-xs">{draft.polygon.length ? 'Area label (optional for drawn zones)' : 'Confirmed area name'}<input className="mt-1 w-full rounded border p-2" placeholder="e.g. Mission Valley" value={draft.area ?? ''} onChange={(e) => setDraft({ ...draft, area: e.target.value })} /></label>
            <label className="block text-xs">Action<select className="mt-1 w-full rounded border p-2" value={draft.level} onChange={(e) => setDraft({ ...draft, level: e.target.value as Zone['level'] })}><option value="unknown">Await guidance</option><option value="evacuate">Evacuate</option><option value="warning">Warning</option><option value="shelter">Shelter in place</option></select></label>
            <label className="block text-xs">Operator instruction<textarea className="mt-1 w-full rounded border p-2" rows={5} value={draft.instruction} onChange={(e) => setDraft({ ...draft, instruction: e.target.value })} /></label>
            <Button disabled={publishing || deleting || (!draft.polygon.length && !draft.area?.trim()) || !draft.label.trim() || !draft.instruction.trim()} onClick={() => void publish()}>{publishing ? 'Publishing…' : draft.version ? 'Publish updated instruction' : 'Publish zone and instruction'}</Button>
            {draft.version && <div className="space-y-2 border-t pt-3">
              <p className="text-xs text-muted-foreground">Deleting removes this zone and its instruction from the map and updates affected active calls. Ended-call history is retained.</p>
              <Button variant="destructive" disabled={publishing || deleting} onClick={() => void deleteInstruction()}>{deleting ? 'Deleting…' : 'Delete instruction'}</Button>
            </div>}
            <Button variant="ghost" onClick={() => { setDraft(undefined); setSelection(undefined) }}>Close</Button>
            {zones.map((z) => <button key={z.id} className="block text-xs underline" onClick={() => setDraft(z)}>{z.label} · v{z.version}</button>)}
          </div> : selectedFacility ? <ContactReview key={selectedFacility.id} facility={selectedFacility} workflow={workflow} onReceive={setReceiver} onError={setActionError} /> : tab === 'contacts' ? <div className="space-y-4 p-5 text-sm"><h2 className="text-lg font-semibold">San Diego contact outreach</h2><p>Draw a contact area to start research, then review the discovered facilities and approve mock calls.</p><p>Use “Act as receiver” for a live browser conversation. Scripted mock calls run up to three at once.</p><p>{workflow.sessions.filter((s) => s.status === 'completed').length} completed mock conversations · {workflow.reports.reduce((n, r) => n + r.content.needs.length, 0)} reported assistance needs.</p><p>Reports show who said what and retain the original conversation. Reported needs are not added to the map.</p></div> : <CallDetail call={selectedCall} lines={selectedCall ? lines[selectedCall.id] ?? [] : []} zones={zones} responders={[]} dispatches={[]} now={now} onRefreshLocation={refreshLocation} onSteer={steer} onDispatch={() => {}} onSelectCrew={() => {}} />}
        </aside>
      </main>
      {inboxOpen && <OperatorInbox calls={snapshot?.calls ?? []} onClose={() => setInboxOpen(false)} />}
      {receiver && <MockReceiver key={receiver.id} session={receiver} onClose={() => setReceiver(undefined)} />}
    </div>
  )
}
