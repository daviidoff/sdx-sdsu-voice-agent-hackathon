import { useState } from 'react'
import { api } from '@/lib/feed'
import { demoPolygon, statusLabel } from '@/lib/contacts'
import type { ContactWorkflow, ContactSession, SearchJob } from '@/lib/contacts'
import type { Facility, LatLng } from '@/types'
import { Button } from './ui/button'

export function ContactPanel({ workflow, facilities, polygon, onPolygon, onDraw, onSelect, onSearchSelect, searchId, onError }: {
  workflow: ContactWorkflow; facilities: Facility[]; polygon: LatLng[]; onPolygon: (points: LatLng[]) => void
  onDraw: () => void; onSelect: (id: string) => void; onSearchSelect: (id: string) => void; searchId?: string; onError: (message: string) => void
}) {
  const [pane, setPane] = useState<'search' | 'contacts' | 'reports'>('search')
  const [provider, setProvider] = useState<'osm' | 'mock'>('osm')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const job = workflow.searches.find((j) => j.id === searchId)
  const running = workflow.searches.some((j) => ['queued', 'running'].includes(j.status))
  const found = facilities.filter((f) => (!job || job.facility_ids.includes(f.id)) && `${f.name} ${f.contact} ${f.type}`.toLowerCase().includes(query.toLowerCase()))
  const eligible = found.filter((f) => f.contact && f.discovery && !f.discovery.flags.includes('listed_closed'))
  const action = async (fn: () => Promise<void>) => { setBusy(true); onError(''); try { await fn() } catch (e) { onError(e instanceof Error ? e.message : 'Contact action failed') } finally { setBusy(false) } }
  const start = () => action(async () => {
    const result = await api<SearchJob>('/api/contacts/searches', { id: crypto.randomUUID(), label: 'San Diego contact search', provider, polygon })
    onSearchSelect(result.id)
  })
  const runAll = () => action(async () => {
    // This explicit operator action approves each single-number contact before simulating it.
    for (const f of eligible) {
      if (workflow.sessions.some((s) => s.facility_id === f.id && !['cancelled', 'failed', 'interrupted'].includes(s.status))) continue
      const session = await api<ContactSession>(`/api/contacts/${f.id}/approve`, { phone: f.contact })
      await api(`/api/contacts/sessions/${session.id}/simulate`, {})
    }
  })
  return <div className="h-full space-y-3 overflow-y-auto p-3 text-xs">
    <div className="flex gap-1">{(['search', 'contacts', 'reports'] as const).map((p) => <button className={`rounded px-2 py-1.5 capitalize ${pane === p ? 'bg-primary text-primary-foreground' : 'bg-muted'}`} key={p} onClick={() => setPane(p)}>{p}</button>)}</div>
    <div className="rounded border border-blue-200 bg-blue-50 p-2">San Diego · mock calls only. No real phone numbers are dialed.</div>
    {pane === 'search' && <>
      <h3 className="text-sm font-semibold">Contact search</h3>
      <p>Draw the area to research clinics, care homes, shelters and community contacts. Search boundaries appear only in Contacts.</p>
      <div className="flex flex-wrap gap-2"><Button size="sm" onClick={onDraw}>Draw contact area</Button><Button size="sm" variant="outline" onClick={() => onPolygon(demoPolygon)}>Use demo area</Button></div>
      <p>{polygon.length ? `${polygon.length} corners selected` : 'No area drawn yet'}</p>
      <label className="block">Discovery source<select aria-label="Discovery source" className="mt-1 w-full rounded border bg-background p-2" value={provider} onChange={(e) => setProvider(e.target.value as 'osm' | 'mock')}><option value="osm">Live OpenStreetMap + websites</option><option value="mock">Offline San Diego fixtures</option></select></label>
      <Button size="sm" disabled={busy || running || polygon.length < 3} onClick={() => void start()}>{running ? 'Research agents running…' : 'Search this area'}</Button>
      <p className="text-muted-foreground">Discovery finds public contacts. Review results before approving mock calls.</p>
      {workflow.searches.map((j) => <button key={j.id} className={`block w-full rounded border p-2 text-left ${j.id === searchId ? 'border-blue-600' : ''}`} onClick={() => { onSearchSelect(j.id); onPolygon(j.polygon) }}>
        <strong>{j.label}</strong><div>{j.provider === 'mock' ? 'Fixture research' : 'Live research'} · {statusLabel(j.status)}</div><div>{j.summary?.leads_returned ?? j.facility_ids.length} contacts · {new Date(j.created_at).toLocaleTimeString()}</div>
      </button>)}
      {job && <div className="space-y-2"><h4 className="font-semibold">Research progress</h4>{job.error && <p role="alert">{job.error}</p>}
        {Object.values(job.workers).map((w) => <div key={w.id} className="rounded border p-2"><span className={w.status === 'running' ? 'text-blue-700' : ''}>{w.kind === 'website' ? 'Website worker' : 'Search worker'} · {w.label.replaceAll('_', ' ')}</span><div>{statusLabel(w.status)}{w.records !== undefined ? ` · ${w.records} records` : ''}</div></div>)}
        {!!job.facility_ids.length && <Button size="sm" onClick={() => setPane('contacts')}>Review {job.facility_ids.length} contacts</Button>}
        {['completed', 'partial'].includes(job.status) && !job.facility_ids.length && <p>No mapped contacts found inside this polygon.</p>}
      </div>}
    </>}
    {pane === 'contacts' && <>
      <input aria-label="Filter contacts" className="w-full rounded border p-2" placeholder="Find a contact…" value={query} onChange={(e) => setQuery(e.target.value)} />
      <p>{found.length} contacts · {workflow.sessions.filter((s) => ['dialing', 'connecting', 'connected', 'queued'].includes(s.status)).length} mock agents active</p>
      <Button size="sm" variant="outline" disabled={busy || !eligible.length} onClick={() => void runAll()}>Approve ready contacts & run scripted mocks</Button>
      <p className="text-muted-foreground">Bulk action skips conflicts, closed listings and contacts already called. Choose a contact to act as its receiver instead.</p>
      {found.map((f) => { const session = workflow.sessions.find((s) => s.facility_id === f.id); return <button key={f.id} onClick={() => onSelect(f.id)} className="block w-full space-y-1 rounded border p-3 text-left hover:bg-muted"><strong className="block text-sm">{f.name}</strong><div>{f.type.replaceAll('_', ' ')}</div><div>{f.contact || (f.discovery?.phone_candidates.length ? 'Choose a phone candidate' : 'No phone found')}</div><div className="text-blue-700">{session ? statusLabel(session.status) : 'Not contacted · needs review'}</div></button> })}
      {!found.length && <p>Run a contact search or select an earlier search.</p>}
    </>}
    {pane === 'reports' && <><h3 className="text-sm font-semibold">Who reported what</h3><p>Mock reports retain their source conversation. Reported needs are available to other workflows through the needs API.</p>
      {!workflow.reports.length && <p>No conversation reports yet.</p>}
      {workflow.reports.map((r) => <button key={r.id} onClick={() => onSelect(r.facility_id)} className="block w-full space-y-2 rounded border p-3 text-left"><strong>{r.facility_name}</strong><div>{r.content.summary}</div><div>{r.content.needs.length} reported needs · {r.source === 'scripted_mock' ? 'Scripted mock' : 'Browser role-play'}</div><div>{workflow.reviews.some((v) => v.id === r.id) ? 'Reception verified by operator in mock' : 'Reception identity awaiting review'}</div><time>{new Date(r.recorded_at).toLocaleString()}</time></button>)}
    </>}
  </div>
}
