import { useState } from 'react'
import { Search, Building2, FileText, Phone, ChevronRight, LoaderCircle } from 'lucide-react'
import { FacilitySymbol } from './map-symbols'
import { api } from '@/lib/feed'
import { statusLabel } from '@/lib/contacts'
import type { ContactWorkflow, SearchJob } from '@/lib/contacts'
import type { Facility, Zone } from '@/types'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Button } from './ui/button'

const contactPanes = [
  { id: 'search', label: 'Search', icon: Search },
  { id: 'contacts', label: 'Results', icon: Building2 },
  { id: 'reports', label: 'Reports', icon: FileText },
] as const

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
  const searching = busy || running
  const found = facilities.filter((f) => (!job || job.facility_ids.includes(f.id)) && `${f.name} ${f.contact} ${f.type}`.toLowerCase().includes(query.toLowerCase()))
  const action = async (fn: () => Promise<void>) => { setBusy(true); onError(''); try { await fn() } catch (e) { onError(e instanceof Error ? e.message : 'Contact action failed') } finally { setBusy(false) } }
  const start = (ids = selected.map((z) => z.id), source = provider) => action(async () => {
    const result = await api<SearchJob>('/api/contacts/searches', { id: crypto.randomUUID(), label: `San Diego · ${ids.length} instruction area${ids.length === 1 ? '' : 's'}`, provider: source, zone_ids: ids })
    onSearchSelect(result.id)
  })
  return <div className="h-full space-y-5 overflow-y-auto p-4 text-sm leading-relaxed">
    <div className="segmented-control" role="group" aria-label="Contact views">
      {contactPanes.map(({ id, label, icon: Icon }) => <button aria-pressed={pane === id} key={id} onClick={() => setPane(id)}><Icon className="size-3.5" aria-hidden="true" />{label}</button>)}
    </div>
    {pane === 'search' && <>
      <section className="space-y-3" aria-labelledby="contact-search-title">
        <div className="flex flex-wrap items-baseline justify-between gap-x-2">
          <h3 id="contact-search-title" className="text-balance text-base font-semibold tracking-tight">Find contacts by area</h3>
          {!!selectable.length && <div className="flex gap-2 text-xs font-medium text-primary">
            <button type="button" className="hover:underline disabled:text-muted-foreground" disabled={selected.length === selectable.length} onClick={() => onZonesSelect(selectable.map((z) => z.id))}>Select all</button>
            {!!selected.length && <button type="button" className="hover:underline" onClick={() => onZonesSelect([])}>Clear</button>}
          </div>}
        </div>
        {!zones.length && <p className="text-sm text-muted-foreground">Draw an instruction zone on the map to begin.</p>}
        {!!zones.length && <div className="divide-y rounded-lg border">
          {zones.map((z) => <label key={z.id} className="flex gap-2.5 px-3 py-2.5 text-sm first:rounded-t-lg last:rounded-b-lg has-[[aria-checked=true]]:bg-accent">
            <Checkbox className="mt-0.5" aria-label={`Select ${z.label} (${z.level})`} disabled={z.polygon.length < 3} checked={selectedZoneIds.includes(z.id)} onCheckedChange={(checked) => onZonesSelect(checked === true ? [...selectedZoneIds, z.id] : selectedZoneIds.filter((id) => id !== z.id))} />
            <span className="min-w-0"><strong className="block text-pretty leading-snug">{z.label}</strong><span className="block text-xs text-muted-foreground">{z.polygon.length < 3 ? 'Map boundary required' : z.level.replaceAll('_', ' ')}</span></span>
          </label>)}
        </div>}
        <label className="block text-xs font-medium">Search source<NativeSelect className="mt-1.5 w-full" selectClassName="h-9 bg-background" value={provider} onChange={(e) => setProvider(e.target.value as 'osm' | 'mock')}><NativeSelectOption value="osm">Live search</NativeSelectOption><NativeSelectOption value="mock">Demo contacts</NativeSelectOption></NativeSelect></label>
        <Button className="h-9 w-full" disabled={searching || !selected.length} aria-busy={searching} onClick={() => void start()}>
          {searching ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" /> : <Search aria-hidden="true" />}
          {searching ? 'Searching areas…' : selected.length ? `Search ${selected.length} area${selected.length === 1 ? '' : 's'}` : 'Search selected areas'}
        </Button>
      </section>
      {job && <section className="space-y-2 border-t pt-4 text-xs" aria-labelledby="search-progress-title">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h4 id="search-progress-title" className="text-sm font-semibold">Search progress</h4><span role="status" className="text-muted-foreground">{statusLabel(job.status)}</span></div>
        {job.error && <p role="alert" className="text-red-800">{job.error}</p>}
        {['failed', 'partial', 'interrupted'].includes(job.status) && <><p className="text-muted-foreground">{job.error_codes?.join(', ') || (job.status === 'failed' ? 'The discovery service did not return results.' : 'Some results may be missing.')}</p><Button size="sm" variant="outline" disabled={searching || !selected.length} onClick={() => void start(selected.map((z) => z.id), job.provider)}>Retry selected areas</Button></>}
        {!!job.facility_ids.length && <Button size="sm" variant="outline" onClick={() => setPane('contacts')}>Review {job.facility_ids.length} contacts<ChevronRight aria-hidden="true" /></Button>}
        {['completed', 'partial'].includes(job.status) && !job.facility_ids.length && <p>No mapped contacts found in these areas.</p>}
        {(!!job.zones?.length || Object.keys(job.workers).length > 0) && <details className="space-y-2 rounded-lg bg-muted p-3">
          <summary className="cursor-pointer font-medium">Search details</summary>
          {job.zones?.map((z) => <p key={z.id}>{z.label} · searched version {z.version}</p>)}
          {Object.values(job.workers).map((w) => <div key={w.id} className="border-t pt-2"><span>{w.kind === 'website' ? 'Website worker' : 'Search worker'} · {w.label.replaceAll('_', ' ')}</span><div className="text-muted-foreground">{statusLabel(w.status)}{w.error_code ? ` · ${w.error_code}` : ''}{w.records !== undefined ? ` · ${w.records} records` : ''}</div></div>)}
        </details>}
      </section>}
      {!!workflow.searches.length && <section className="space-y-2 border-t pt-4" aria-labelledby="search-history-title">
        <h4 id="search-history-title" className="font-semibold">Previous searches</h4>
        {workflow.searches.map((j) => <button key={j.id} className="workspace-row" aria-pressed={j.id === searchId} onClick={() => { onSearchSelect(j.id); if (j.zone_ids) onZonesSelect(j.zone_ids.filter((id) => selectable.some((z) => z.id === id))) }}>
          <strong className="block text-sm">{j.label}</strong><span className="block text-xs text-muted-foreground">{j.provider === 'mock' ? 'Demo' : 'Live'} · {statusLabel(j.status)} · {new Date(j.created_at).toLocaleTimeString()}</span>
        </button>)}
      </section>}
    </>}
    {pane === 'contacts' && <>
      <Input aria-label="Filter contacts" className="h-auto p-2 text-xs md:text-xs" placeholder="Find a contact…" value={query} onChange={(e) => setQuery(e.target.value)} />
      {!!found.length && <p className="text-xs text-muted-foreground">{found.length} {found.length === 1 ? 'contact' : 'contacts'} · Results may be incomplete</p>}
      <div className="space-y-2">
        {found.map((f) => { const session = workflow.sessions.find((s) => s.facility_id === f.id); return <button key={f.id} onClick={() => onSelect(f.id)} className="workspace-row space-y-2"><div className="flex items-center gap-2.5"><FacilitySymbol type={f.type} /><div className="min-w-0 flex-1"><strong className="block text-sm leading-snug">{f.name}</strong><div className="mt-0.5 text-xs text-muted-foreground">{f.type.replaceAll('_', ' ')}</div></div><ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" /></div><div className="flex items-center gap-1.5 text-xs text-muted-foreground"><Phone className="size-3" aria-hidden="true" />{f.contact || (f.discovery?.phone_candidates.length ? 'Choose a phone candidate' : 'No phone found')}</div>{session && <div className="text-xs text-primary">{statusLabel(session.status)}</div>}</button> })}
      </div>
      {!found.length && <p className="text-muted-foreground">{query ? 'No contacts match this filter.' : 'Run a contact search or select an earlier search.'}</p>}
    </>}
    {pane === 'reports' && <>
      {!workflow.reports.length && <p className="text-muted-foreground">Reports from clinic role-plays will appear here.</p>}
      <div className="space-y-2">{workflow.reports.map((r) => <button key={r.id} onClick={() => onSelect(r.facility_id)} className="workspace-row space-y-1"><strong>{r.facility_name}</strong><div>{r.content.summary}</div><div className="text-xs text-muted-foreground">{r.content.needs.length} reported needs · {r.source === 'scripted_mock' ? 'Scripted mock' : 'Browser role-play'}</div><div className="text-xs text-muted-foreground">{workflow.reviews.some((v) => v.id === r.id) ? 'Reception verified by operator in mock' : 'Reception identity awaiting review'}</div><time className="text-xs text-muted-foreground">{new Date(r.recorded_at).toLocaleString()}</time></button>)}</div>
    </>}
  </div>
}
