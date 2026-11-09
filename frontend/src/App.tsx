import { useEffect, useMemo, useState } from 'react'
import { RadioTower, ExternalLink, Inbox, Phone, X, Map as MapIcon, PanelLeft, PanelRight, RotateCcw, Building2, MapPinned } from 'lucide-react'
import { OutreachOverview } from '@/components/OutreachOverview'
import { OperatorInbox } from '@/components/OperatorInbox'
import { unreadMessages } from '@/lib/inbox'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ContactPanel } from '@/components/ContactPanel'
import { ContactReview } from '@/components/ContactReview'
import { emptyWorkflow, sanDiegoFacility } from '@/lib/contacts'
import { WorkspacePanel } from '@/components/WorkspacePanel'
import { useZoneAutosave, zoneContent } from '@/hooks/useZoneAutosave'
import { CrewDetail } from '@/components/CrewDetail'
import { useCrewSimulation } from '@/hooks/useCrewSimulation'
import { CallDetail } from '@/components/CallDetail'
import { CallList } from '@/components/CallList'
import { DisasterMap } from '@/components/DisasterMap'
import { FireEditor } from '@/components/FireEditor'
import { api, createFeed, toCall, toFacilities, toLines } from '@/lib/feed'
import type { Snapshot } from '@/lib/feed'
import type { Call, Selection, TranscriptLine, Zone, LatLng, SimulatedFire } from '@/types'

export default function App() {
  const simulation = useCrewSimulation()
  const { responders, dispatches } = simulation
  const [mapCenter, setMapCenter] = useState<LatLng>([32.7525, -117.1145])
  const feed = useMemo(() => createFeed(), [])
  const [snapshot, setSnapshot] = useState<Snapshot>()
  const [selection, setSelection] = useState<Selection>()
  const [connectionError, setConnectionError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const [draftFire, setDraftFire] = useState<SimulatedFire>()
  const [fireDrawing, setFireDrawing] = useState(false)
  const [savingFire, setSavingFire] = useState(false)
  const [drawing, setDrawing] = useState(false)
  const [draft, setDraft] = useState<Zone>()
  const [navigationOpen, setNavigationOpen] = useState(true)
  const [detailOpen, setDetailOpen] = useState(false)
  const [focusedPanel, setFocusedPanel] = useState('navigation')
  const [layoutReset, setLayoutReset] = useState(0)
  const autosave = useZoneAutosave((saved, submitted) => {
    setSnapshot((current) => current ? { ...current, zones: [...current.zones.filter((zone) => zone.id !== saved.id), saved] } : current)
    setDraft((current) => current?.id === saved.id ? zoneContent(current) === zoneContent(submitted) ? saved : { ...current, version: saved.version } : current)
  })
  const saveState = draft ? autosave.statuses[draft.id] : undefined
  const publishing = saveState?.saving || saveState?.status === 'pending'
  const editZone = (zone: Zone) => { setDraft(zone); autosave.schedule(zone) }
  const showDetails = () => { setDetailOpen(true); setFocusedPanel('details') }

  const [tab, setTab] = useState('contacts')
  const [contactZoneIds, setContactZoneIds] = useState<string[]>([])
  const [searchId, setSearchId] = useState<string>()
  const workflow = snapshot?.contact_workflow ?? emptyWorkflow
  const changeTab = (value: string) => { setTab(value); setDrawing(false); setFireDrawing(false); setNavigationOpen(true); setFocusedPanel('navigation') }
  const [deleting, setDeleting] = useState(false)
  const [inboxOpen, setInboxOpen] = useState(false)
  const unread = snapshot?.calls.reduce((count, call) => count + unreadMessages(call), 0) ?? 0
  useEffect(() => feed.start((event) => {
    if (event.type === 'snapshot') { setSnapshot(event.snapshot); setConnectionError('') }
    if (event.type === 'connection') setConnectionError(event.error)
  }), [feed])
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(timer) }, [])
  const calls: Call[] = useMemo(() => snapshot?.calls.map(toCall) ?? [], [snapshot])
  const lines: Record<string, TranscriptLine[]> = useMemo(() => Object.fromEntries(snapshot?.calls.map((call) => [call.id, toLines(call)]) ?? []), [snapshot])
  const facilities = useMemo(() => toFacilities(snapshot?.facilities ?? []).filter(sanDiegoFacility), [snapshot])
  const pendingDrafts = autosave.drafts
  const zones = snapshot?.zones ?? []
  const editableZones = [...zones.filter((zone) => !pendingDrafts.some((draft) => draft.id === zone.id)), ...pendingDrafts]
  const fires = snapshot?.fires ?? []
  const selectedCall = calls.find((call) => call.id === selection?.id) ?? (!selection && tab === 'calls' ? calls.find((call) => call.status === 'active') ?? calls[0] : undefined)
  const selectedCrew = selection?.kind === 'crew' ? responders.find((r) => r.id === selection.id) : undefined
  const selectedFacility = selection?.kind === 'facility' ? facilities.find((f) => f.id === selection.id) : undefined
  const effectiveSelection = selectedCall ? { kind: 'call' as const, id: selectedCall.id } : selection
  const active = calls.filter((call) => call.status === 'active')
  const select = (value: Selection) => {
    if (deleting || savingFire) return
    setDraftFire(value.kind === 'fire' ? fires.find((fire) => fire.id === value.id) : undefined)
    if (tab === 'contacts' && value.kind === 'zone') {
      setContactZoneIds((ids) => ids.includes(value.id) ? ids.filter((id) => id !== value.id) : [...ids, value.id])
      setDraft(undefined); setSelection(undefined); return
    }
    setSelection(value)
    showDetails()
    if (value.kind === 'facility') setTab('contacts')
    if (value.kind === 'crew') setTab('crews')
    if (value.kind === 'call') setTab('calls')
    setDraft(value.kind === 'zone' ? editableZones.find((zone) => zone.id === value.id) : undefined)
  }
  const addFire = () => {
    setDetailOpen(false); setNavigationOpen(false)
    setDraft(undefined); setSelection(undefined); setDrawing(false); setActionError(''); setNotice('')
    setDraftFire({ id: crypto.randomUUID(), label: `Demo fire ${fires.length + 1}`, polygon: [], simulated: true })
    setFireDrawing(true)
  }
  const saveFire = async () => {
    if (!draftFire || savingFire) return
    setSavingFire(true); setActionError('')
    try {
      const saved = await api<SimulatedFire>('/api/dashboard/fires', draftFire)
      setDraftFire(saved)
      setSnapshot((current) => current ? { ...current, fires: [...(current.fires ?? []).filter((fire) => fire.id !== saved.id), saved] } : current)
      setNotice(`${saved.label} saved. The simulated fire stays fixed on the map.`)
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Fire could not be saved') }
    finally { setSavingFire(false) }
  }
  const deleteFire = async () => {
    if (!draftFire?.updated_at || savingFire) return
    setSavingFire(true); setActionError('')
    try {
      await api(`/api/dashboard/fires/${encodeURIComponent(draftFire.id)}`, undefined, undefined, 'DELETE')
      setSnapshot((current) => current ? { ...current, fires: (current.fires ?? []).filter((fire) => fire.id !== draftFire.id) } : current)
      setDraftFire(undefined); setSelection(undefined); setNotice('Simulated fire deleted.')
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Fire could not be deleted') }
    finally { setSavingFire(false) }
  }
  const drawZone = (polygon: LatLng[]) => {
    editZone({ id: crypto.randomUUID(), label: 'New response zone', area: '', level: 'unknown', instruction: '',
      polygon })
    setDrawing(false)
    showDetails()
  }
  const deleteInstruction = async () => {
    if (!draft?.version || publishing || deleting) return
    const zone = draft
    setDeleting(true); setActionError(''); setNotice('')
    try {
      await api(`/api/dashboard/zones/${encodeURIComponent(zone.id)}`, undefined, undefined, 'DELETE')
      autosave.forget(zone.id)
      setSnapshot((current) => current ? { ...current, zones: current.zones.filter((item) => item.id !== zone.id) } : current)
      setDraft((current) => current?.id === zone.id ? undefined : current)
      setSelection((current) => current?.kind === 'zone' && current.id === zone.id ? undefined : current)
      setNotice(`${zone.label} removed.`)
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
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(''), 5000)
    return () => clearTimeout(timer)
  }, [notice])
  const openZone = (zone: Zone) => { setDraftFire(undefined); setDraft(pendingDrafts.find((draft) => draft.id === zone.id) ?? zone); setSelection({ kind: 'zone', id: zone.id }); showDetails() }
  const detailTitle = draftFire ? 'Fire simulation' : draft ? 'Area instruction' : selectedFacility ? 'Contact details' : selectedCrew ? 'Simulated crew' : 'Call details'
  return (
    <div className="dashboard-shell flex h-dvh min-h-0 flex-col overflow-hidden bg-muted/30 text-foreground">
      <header className="dashboard-header flex shrink-0 items-center gap-3 border-b bg-background px-4 py-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-teal-300"><RadioTower className="size-4" /></div>
        <div className="text-sm font-semibold tracking-tight">Emergency OS</div>
        <Badge variant="outline" className="gap-1.5 text-[10px]"><span className={`size-1.5 rounded-full ${connectionError ? 'bg-amber-500' : snapshot ? 'bg-emerald-500' : 'bg-zinc-400'}`} />{connectionError ? 'Offline' : snapshot ? 'Connected' : 'Connecting'}</Badge>
        <span className="hidden text-xs text-muted-foreground lg:block">{active.length} active calls · {active.filter((c) => c.situation === 'needs_help').length} need assistance</span>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => { setInboxOpen(true); setFocusedPanel('inbox') }}><Inbox className="size-4" /><span className="hidden sm:inline">Inbox</span>{unread > 0 && <span className="rounded-full bg-teal-700 px-1.5 text-xs text-white">{unread}</span>}</Button>
          <a href={import.meta.env.DEV ? 'http://127.0.0.1:8000/?source=dashboard' : '/?source=dashboard'} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs text-primary-foreground"><Phone className="size-3.5" /><span className="hidden sm:inline">Open </span>Voice caller <ExternalLink className="size-3" /></a>
        </div>
      </header>
      {(connectionError || actionError || notice) && <div role={connectionError || actionError ? 'alert' : 'status'} className="flex shrink-0 items-center gap-3 border-b bg-amber-50 px-4 py-2 text-xs"><span className="flex-1">{connectionError || actionError || notice}</span>{!connectionError && <button aria-label="Dismiss notification" onClick={() => { setActionError(''); setNotice('') }}><X className="size-4" /></button>}</div>}
      {Object.entries(autosave.statuses).filter(([, value]) => value.status === 'error').map(([id]) => <div key={id} role="alert" className="flex shrink-0 items-center justify-between bg-red-50 px-4 py-2 text-xs text-red-800"><span>Area changes could not be saved.</span><button className="underline" onClick={() => { const zone = editableZones.find((zone) => zone.id === id); if (zone) openZone(zone) }}>Review and retry</button></div>)}
      <nav aria-label="Workspace" className="workspace-toolbar flex flex-wrap shrink-0 items-center gap-1 border-b bg-background px-3 py-2">
        {['contacts', 'calls', 'crews', 'areas'].map((value) => <Button key={value} size="sm" variant={navigationOpen && tab === value ? 'secondary' : 'ghost'} aria-pressed={navigationOpen && tab === value} onClick={() => changeTab(value)}>{value === 'contacts' ? <Building2 className="size-3.5" /> : value === 'calls' ? <Phone className="size-3.5" /> : <MapPinned className="size-3.5" />}<span className="capitalize">{value}</span>{value === 'calls' ? <span className="text-muted-foreground">{calls.length}</span> : value === 'areas' ? <span className="text-muted-foreground">{zones.length}</span> : null}</Button>)}
        <span className="ml-auto hidden truncate px-3 text-xs text-muted-foreground xl:block">{snapshot?.incidents.map((i) => i.name).join(' · ')}</span>
        <div className="ml-auto flex items-center gap-1 xl:ml-0">
          <Button size="icon" variant="ghost" aria-label="Show map only" title="Show map only" onClick={() => { setNavigationOpen(false); setDetailOpen(false); setInboxOpen(false) }}><MapIcon className="size-4" /></Button>
          <Button size="icon" variant="ghost" aria-label="Toggle navigation panel" title="Navigation panel" aria-pressed={navigationOpen} onClick={() => { setNavigationOpen(!navigationOpen); setFocusedPanel(navigationOpen ? detailOpen ? 'details' : 'inbox' : 'navigation') }}><PanelLeft className="size-4" /></Button>
          <Button size="icon" variant="ghost" aria-label="Toggle details panel" title="Details panel" aria-pressed={detailOpen} onClick={() => { setDetailOpen(!detailOpen); setFocusedPanel(detailOpen ? navigationOpen ? 'navigation' : 'inbox' : 'details') }}><PanelRight className="size-4" /></Button>
          <Button size="icon" variant="ghost" className="hidden sm:inline-flex" aria-label="Reset workspace layout" title="Reset layout" onClick={() => { setLayoutReset((value) => value + 1); setNavigationOpen(true); setDetailOpen(false); setInboxOpen(false); setFocusedPanel('navigation') }}><RotateCcw className="size-4" /></Button>
        </div>
      </nav>
      <main className="relative isolate min-h-0 min-w-0 flex-1 overflow-hidden">
        <section aria-label="Incident map" className="absolute inset-0">
          <DisasterMap onMoveCrew={simulation.move} onCenterChange={setMapCenter} calls={calls} zones={zones} facilities={facilities} responders={responders} dispatches={dispatches} now={now} selection={effectiveSelection} onSelect={select} drawing={drawing} onDrawingChange={(value) => { setDrawing(value); if (value) { setNavigationOpen(false); setDetailOpen(false) }; if (value) { setDraftFire(undefined); setFireDrawing(false); setDraft(undefined) } }} onZoneDrawn={drawZone} draftZone={draft} contactsActive={tab === 'contacts'} contactZoneIds={contactZoneIds} fires={fires} draftFire={draftFire} fireDrawing={fireDrawing} onAddFire={addFire} onFireDrawn={(polygon) => { setDraftFire((current) => current ? { ...current, polygon } : current); setFireDrawing(false); showDetails() }} onFireDrawingCancel={() => setFireDrawing(false)} />
        </section>
        <WorkspacePanel title="Overview" open={navigationOpen} active={focusedPanel === 'navigation'} onFocus={() => setFocusedPanel('navigation')} onClose={() => { setNavigationOpen(false); setFocusedPanel(detailOpen ? 'details' : 'inbox') }} resetKey={layoutReset}>
          {tab === 'areas' ? <div className="space-y-3 p-3">
            <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">Area instructions</h3><span className="text-xs text-muted-foreground">{zones.length} active</span></div>
            {!editableZones.length && <p className="text-sm text-muted-foreground">Draw a zone on the map to add an instruction.</p>}
            {editableZones.map((zone) => <button key={zone.id} className="block w-full rounded-lg border p-3 text-left hover:bg-muted" onClick={() => openZone(zone)}><div className="flex items-center gap-2"><span className={`size-2 rounded-full ${zone.level === 'evacuate' ? 'bg-red-500' : zone.level === 'shelter' ? 'bg-blue-500' : 'bg-amber-500'}`} /><strong className="text-sm">{zone.label}</strong>{autosave.statuses[zone.id] && autosave.statuses[zone.id].status !== 'saved' && <span className="text-xs text-amber-700">{autosave.statuses[zone.id].status === 'error' ? 'Not saved' : 'Editing'}</span>}</div><p className="mt-2 line-clamp-3 text-xs text-muted-foreground">{zone.instruction}</p></button>)}
          </div> : <CallList calls={calls} lines={lines} zones={zones} facilities={facilities} responders={responders} dispatches={dispatches} selection={effectiveSelection} onSelect={select} now={now} tab={tab} onTabChange={changeTab}
            onSimulate={() => { simulation.start(mapCenter); setSelection(undefined); setDetailOpen(false) }} onStopSimulation={() => { simulation.stop(); if (selection?.kind === 'crew') { setSelection(undefined); setDetailOpen(false) } }}
            contactsContent={<ContactPanel workflow={workflow} facilities={facilities} zones={zones} selectedZoneIds={contactZoneIds} onZonesSelect={setContactZoneIds} searchId={searchId} onSearchSelect={setSearchId} onSelect={(id) => select({ kind: 'facility', id })} onError={setActionError} />} />}
        </WorkspacePanel>
        <WorkspacePanel title={detailTitle} side="right" open={detailOpen} active={focusedPanel === 'details'} onFocus={() => setFocusedPanel('details')} onClose={() => { setDetailOpen(false); setFocusedPanel(navigationOpen ? 'navigation' : 'inbox') }} resetKey={layoutReset}>
          {draftFire ? <FireEditor fire={draftFire} fires={fires} busy={savingFire} drawing={fireDrawing} onChange={setDraftFire} onDraw={() => { setFireDrawing(true); setDetailOpen(false); setNavigationOpen(false) }} onSave={() => void saveFire()} onDelete={() => void deleteFire()} onClose={() => setDetailOpen(false)} onSelect={(fire) => { setDraftFire(fire); setSelection({ kind: 'fire', id: fire.id }) }} /> : draft ? <div className="space-y-4 p-4">
            <div className="flex items-center justify-between gap-2"><h3 className="text-base font-semibold">{draft.label || 'Area instruction'}</h3><span role="status" className={`text-xs ${saveState?.status === 'error' ? 'text-red-700' : 'text-muted-foreground'}`}>{saveState?.status === 'saving' ? 'Saving…' : saveState?.status === 'pending' ? 'Unsaved changes…' : saveState?.status === 'error' ? 'Not saved' : saveState?.status === 'incomplete' || !draft.version ? 'Complete the fields to save' : 'Saved · live'}</span></div>
            <p className="text-xs text-muted-foreground">Changes save automatically and apply to matching callers.</p>
            {saveState?.status === 'error' && <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-xs"><p>{saveState.error}</p><Button size="sm" variant="outline" className="mt-2" onClick={() => autosave.retry(draft.id)}>Retry save</Button></div>}
            <label className="block text-xs">Zone name<input disabled={deleting} className="mt-1 w-full rounded border p-2 text-sm" value={draft.label} onChange={(e) => editZone({ ...draft, label: e.target.value })} /></label>
            <label className="block text-xs">{draft.polygon.length ? 'Area label' : 'Area name'}<input disabled={deleting} className="mt-1 w-full rounded border p-2 text-sm" placeholder="e.g. Mission Valley" value={draft.area ?? ''} onChange={(e) => editZone({ ...draft, area: e.target.value })} /></label>
            <label className="block text-xs">Action<select disabled={deleting} className="mt-1 w-full rounded border p-2 text-sm" value={draft.level} onChange={(e) => editZone({ ...draft, level: e.target.value as Zone['level'] })}><option value="unknown">Await guidance</option><option value="evacuate">Evacuate</option><option value="warning">Warning</option><option value="shelter">Shelter in place</option></select></label>
            <label className="block text-xs">Instruction<textarea disabled={deleting} className="mt-1 w-full rounded border p-2 text-sm" rows={5} placeholder="Enter the guidance for this area…" value={draft.instruction} onChange={(e) => editZone({ ...draft, instruction: e.target.value })} /></label>
            {draft.version && <Button variant="destructive" size="sm" disabled={publishing || deleting} onClick={() => void deleteInstruction()}>{deleting ? 'Deleting…' : 'Delete area'}</Button>}
          </div> : selectedCrew ? <CrewDetail key={selectedCrew.id} crew={selectedCrew} calls={calls} facilities={facilities} dispatches={dispatches} now={now} onDispatch={(call) => { if (call.position) void simulation.dispatch(selectedCrew.id, { kind: 'call', id: call.id, label: call.callerName, position: call.position }) }} onRoute={(facility) => { if (facility.position) void simulation.dispatch(selectedCrew.id, { kind: 'facility', id: facility.id, label: facility.name, position: facility.position }) }} onRelease={() => simulation.release(selectedCrew.id)} onSelectCall={(id) => select({ kind: 'call', id })} /> : selectedFacility ? <ContactReview key={selectedFacility.id} facility={selectedFacility} workflow={workflow} onError={setActionError} /> : selectedCall ? <CallDetail key={selectedCall.id} call={selectedCall} lines={lines[selectedCall.id] ?? []} zones={zones} responders={responders} dispatches={dispatches} now={now} onRefreshLocation={refreshLocation} onSteer={steer} onDispatch={(id) => { if (selectedCall.position) void simulation.dispatch(id, { kind: 'call', id: selectedCall.id, label: selectedCall.callerName, position: selectedCall.position }) }} onSelectCrew={(id) => select({ kind: 'crew', id })} /> : <OutreachOverview completed={workflow.sessions.filter((s) => s.status === 'completed').length} needs={workflow.reports.reduce((n, r) => n + r.content.needs.length, 0)} />}
        </WorkspacePanel>
        <WorkspacePanel title="Inbox" side="right" open={inboxOpen} active={focusedPanel === 'inbox'} onFocus={() => setFocusedPanel('inbox')} onClose={() => { setInboxOpen(false); setFocusedPanel(detailOpen ? 'details' : 'navigation') }} resetKey={layoutReset}>
          {inboxOpen && <OperatorInbox calls={snapshot?.calls ?? []} onClose={() => setInboxOpen(false)} embedded />}
        </WorkspacePanel>
      </main>
    </div>
  )
}
