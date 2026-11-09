import { useState } from 'react'
import { Search, Building2, FileText, Phone, ArrowUpRight } from 'lucide-react'
import { FacilitySymbol } from './map-symbols'
import { api } from '@/lib/feed'
import { statusLabel } from '@/lib/contacts'
import type { ContactWorkflow, SearchJob } from '@/lib/contacts'
import type { Facility, Zone } from '@/types'
import { Button } from './ui/button'

export function ContactPanel({ workflow, facilities, zones, selectedZoneIds, onZonesSelect, onSelect, onSearchSelect, searchId, onError }: {
  workflow: ContactWorkflow; facilities: Facility[]; zones: Zone[]; selectedZoneIds: string[]; onZonesSelect: (ids: string[]) => void
  onSelect: (id: string) => void; onSearchSelect: (id: string) => void; searchId?: string; onError: (message: string) => void
}) {
  const [pane, setPane] = useState<'search' | 'contacts' | 'reports'>('search')
  const [provider, setProvider] = useState<'osm' | 'mock'>('osm')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const job = workflow.searches.find((j) => j.id === searchId)
  const selectable = zones.filter((z) => z.polygon.length >= 3)
  const selected = selectable.filter((z) => selectedZoneIds.includes(z.id))
  const running = workflow.searches.some((j) => ['queued', 'running'].includes(j.status))
  const found = facilities.filter((f) => (!job || job.facility_ids.includes(f.id)) && `${f.name} ${f.contact} ${f.type}`.toLowerCase().includes(query.toLowerCase()))
  const action = async (fn: () => Promise<void>) => { setBusy(true); onError(''); try { await fn() } catch (e) { onError(e instanceof Error ? e.message : 'Contact action failed') } finally { setBusy(false) } }
  const start = (ids = selected.map((z) => z.id), source = provider) => action(async () => {
    const result = await api<SearchJob>('/api/contacts/searches', { id: crypto.randomUUID(), label: `San Diego · ${ids.length} instruction area${ids.length === 1 ? '' : 's'}`, provider: source, zone_ids: ids })
    onSearchSelect(result.id)
  })
  return <div className="contact-panel h-full space-y-4 overflow-y-auto p-4 text-xs leading-relaxed">
    <div className="flex gap-1 rounded-lg bg-muted/70 p-1">{(['search', 'contacts', 'reports'] as const).map((p) => { const Icon = { search: Search, contacts: Building2, reports: FileText }[p]; return <button aria-pressed={pane === p} className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 capitalize transition ${pane === p ? 'bg-white font-medium text-teal-800 shadow-sm' : 'text-muted-foreground hover:text-foreground'}`} key={p} onClick={() => setPane(p)}><Icon className="size-3.5" />{p}</button> })}</div>
    {pane === 'search' && <>
      <h3 className="text-sm font-semibold">Contact search</h3>
      <p>Select areas to find local contacts.</p>
      <div className="flex gap-2"><Button size="sm" variant="outline" disabled={!selectable.length} onClick={() => onZonesSelect(selectable.map((z) => z.id))}>Select all areas</Button><Button size="sm" variant="ghost" onClick={() => onZonesSelect([])}>Clear</Button></div>
      {!zones.length && <p>Draw a zone on the map to begin.</p>}
      {zones.map((z) => <label key={z.id} className={`flex gap-3 rounded-xl border p-3 transition ${selectedZoneIds.includes(z.id) ? 'border-teal-600 bg-teal-50/60' : 'hover:bg-muted/50'}`}>
        <input type="checkbox" className="mt-1 accent-teal-700" aria-label={`Select ${z.label} (${z.level})`} disabled={z.polygon.length < 3} checked={selectedZoneIds.includes(z.id)} onChange={(e) => onZonesSelect(e.target.checked ? [...selectedZoneIds, z.id] : selectedZoneIds.filter((id) => id !== z.id))} />
        <span><strong>{z.label}</strong><span className="my-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{z.level.replaceAll('_', ' ')} · v{z.version}</span><span className="block text-muted-foreground">{z.polygon.length < 3 ? 'Add a map boundary' : z.instruction}</span></span>
      </label>)}
      <p>{selected.length} instruction areas selected</p>
      <label className="block">Search source<select aria-label="Search source" className="mt-1 w-full rounded border bg-background p-2" value={provider} onChange={(e) => setProvider(e.target.value as 'osm' | 'mock')}><option value="osm">Live search</option><option value="mock">Demo contacts</option></select></label>
      <Button size="sm" disabled={busy || running || !selected.length} onClick={() => void start()}><Search className="size-3.5" />{running ? 'Searching…' : `Search ${selected.length} area${selected.length === 1 ? '' : 's'}`}</Button>
      {job && <div className="space-y-2"><h4 className="font-semibold">Research progress</h4>{job.error && <p role="alert">{job.error}</p>}
        {['failed', 'partial', 'interrupted'].includes(job.status) && <><p className="text-muted-foreground">{job.error_codes?.join(', ') || (job.status === 'failed' ? 'The discovery service did not return results.' : 'Some results may be missing.')}</p><Button size="sm" variant="outline" disabled={busy || running || !selected.length} onClick={() => void start(selected.map((z) => z.id), job.provider)}>Retry selected areas</Button></>}
        {job.zones?.map((z) => <p key={z.id}>{z.label} · searched version {z.version}</p>)}
        <p className="text-muted-foreground">Search results may be incomplete.</p>
        {Object.values(job.workers).map((w) => <div key={w.id} className="rounded border p-2"><span className={w.status === 'running' ? 'text-blue-700' : ''}>{w.kind === 'website' ? 'Website worker' : 'Search worker'} · {w.label.replaceAll('_', ' ')}</span><div>{statusLabel(w.status)}{w.error_code ? ` · ${w.error_code}` : ''}{w.records !== undefined ? ` · ${w.records} records` : ''}</div></div>)}
        {!!job.facility_ids.length && <Button size="sm" onClick={() => setPane('contacts')}>Review {job.facility_ids.length} contacts</Button>}
        {['completed', 'partial'].includes(job.status) && !job.facility_ids.length && <p>No mapped contacts found inside the selected instruction areas.</p>}
      </div>}
      {workflow.searches.map((j) => <button key={j.id} className={`block w-full rounded border p-2 text-left ${j.id === searchId ? 'border-blue-600' : ''}`} onClick={() => { onSearchSelect(j.id); if (j.zone_ids) onZonesSelect(j.zone_ids.filter((id) => selectable.some((z) => z.id === id))) }}>
        <strong>{j.label}</strong><div>{j.provider === 'mock' ? 'Fixture research' : 'Live research'} · {statusLabel(j.status)}</div><div>{j.status === 'failed' ? 'Search unavailable · no results received' : `${j.summary?.leads_returned ?? j.facility_ids.length} contacts`} · {new Date(j.created_at).toLocaleTimeString()}</div>{j.status === 'failed' && j.error && <p className="mt-1 text-red-700">{j.error}</p>}
      </button>)}
    </>}
    {pane === 'contacts' && <>
      <input aria-label="Filter contacts" className="w-full rounded border p-2" placeholder="Find a contact…" value={query} onChange={(e) => setQuery(e.target.value)} />
      <p>{found.length} contacts · {workflow.sessions.filter((s) => ['dialing', 'connecting', 'connected', 'queued'].includes(s.status)).length} calls active</p>
      {found.map((f) => { const session = workflow.sessions.find((s) => s.facility_id === f.id); return <button key={f.id} onClick={() => onSelect(f.id)} className="block w-full space-y-2 rounded-xl border p-3 text-left transition hover:border-teal-500 hover:bg-teal-50/30"><div className="flex items-start gap-2.5"><FacilitySymbol type={f.type} /><div className="min-w-0 flex-1"><strong className="block text-sm leading-snug">{f.name}</strong><div className="mt-1 text-muted-foreground">{f.type.replaceAll('_', ' ')}</div></div><ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground" /></div><div className="flex items-center gap-1.5 text-muted-foreground"><Phone className="size-3" />{f.contact || (f.discovery?.phone_candidates.length ? 'Choose a phone candidate' : 'No phone found')}</div><div className="text-blue-700">{session ? statusLabel(session.status) : 'Not contacted'}</div></button> })}
      {!found.length && <p>Run a contact search or select an earlier search.</p>}
    </>}
    {pane === 'reports' && <><h3 className="text-sm font-semibold">Who reported what</h3><p>Reported needs from conversations.</p>
      {!workflow.reports.length && <p>No conversation reports yet.</p>}
      {workflow.reports.map((r) => <button key={r.id} onClick={() => onSelect(r.facility_id)} className="block w-full space-y-2 rounded border p-3 text-left"><strong>{r.facility_name}</strong><div>{r.content.summary}</div><div>{r.content.needs.length} reported needs · {r.source === 'scripted_mock' ? 'Scripted mock' : 'Browser role-play'}</div><div>{workflow.reviews.some((v) => v.id === r.id) ? 'Reception verified by operator in mock' : 'Reception identity awaiting review'}</div><time>{new Date(r.recorded_at).toLocaleString()}</time></button>)}
    </>}
  </div>
}
