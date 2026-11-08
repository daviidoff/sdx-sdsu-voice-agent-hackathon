import { useState } from 'react'
import { api } from '@/lib/feed'
import type { ContactWorkflow, ContactSession } from '@/lib/contacts'
import { statusLabel } from '@/lib/contacts'
import type { Facility } from '@/types'
import { Button } from './ui/button'
import { FacilityDetail } from './FacilityDetail'

export function ContactReview({ facility: f, workflow, onReceive, onError }: { facility: Facility; workflow: ContactWorkflow; onReceive: (s: ContactSession) => void; onError: (message: string) => void }) {
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const sessions = workflow.sessions.filter((s) => s.facility_id === f.id)
  const session = sessions[0]
  const candidates = [...new Set(f.discovery?.phone_candidates.map((p) => p.number + (p.extension ? ` ext. ${p.extension}` : '')) ?? [])]
  const selected = phone || (candidates.length === 1 ? candidates[0] : '')
  const action = async (fn: () => Promise<unknown>) => { setBusy(true); onError(''); try { await fn() } catch (e) { onError(e instanceof Error ? e.message : 'Contact action failed') } finally { setBusy(false) } }
  const current = session && !['completed', 'failed', 'cancelled', 'interrupted'].includes(session.status) ? session : undefined
  return <div className="h-full overflow-y-auto">
    <section className="space-y-3 border-b p-4 text-sm">
      <h2 className="font-semibold">Review & mock outreach</h2>
      <p className="text-xs">{f.name} · no real telephone call</p>
      {!current && <><label className="block text-xs">Phone candidate<select aria-label="Phone candidate" className="mt-1 w-full rounded border p-2" value={selected} onChange={(e) => setPhone(e.target.value)}><option value="">Select a number to review</option>{candidates.map((p) => <option key={p}>{p}</option>)}</select></label><Button size="sm" disabled={busy || !selected || f.discovery?.flags.includes('listed_closed')} onClick={() => void action(() => api(`/api/contacts/${f.id}/approve`, { phone: selected }))}>Approve mock call</Button></>}
      {current && <><p className="rounded bg-blue-50 p-2 text-xs">{statusLabel(current.status)} · {current.phone}</p>
        {current.status === 'approved' && <div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => onReceive(current)}>Act as receiver</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void action(() => api(`/api/contacts/sessions/${current.id}/simulate`, {}))}>Run scripted mock</Button></div>}
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void action(() => api(`/api/contacts/sessions/${current.id}/end`, { status: 'cancelled' }))}>Cancel mock call</Button>
      </>}
      {sessions.map((s) => { const report = workflow.reports.find((r) => r.session_id === s.id); const verified = workflow.reviews.some((v) => v.id === s.id); return <details key={s.id} open={s.id === session?.id} className="rounded border p-3"><summary>{statusLabel(s.status)} · {s.mode === 'scripted_mock' ? 'Scripted mock' : 'Browser role-play'} · {new Date(s.created_at).toLocaleTimeString()}</summary>
        {report && <div className="my-3 space-y-2"><h3 className="font-semibold">Reported by {report.facility_name}</h3><p>{report.content.summary}</p><blockquote className="border-l-2 pl-2 text-xs">“{report.content.source_quote}”</blockquote>
          {report.content.needs.map((n, i) => <div className="rounded border bg-amber-50 p-2 text-xs" key={i}><strong>Reported need · awaiting review</strong><p>{n.description}</p><p>{n.people_count ?? 'Unknown number of'} people · {n.location || 'Location unconfirmed'} · {n.urgency}</p></div>)}
          <p className="text-xs">{verified ? 'Operator verified reception in this mock conversation.' : report.content.reception_confirmed ? 'Receiver says they are reception; not independently verified.' : 'Reception identity unconfirmed.'}</p>
          {!verified && report.content.reception_confirmed && <Button size="sm" variant="outline" disabled={busy} onClick={() => void action(() => api(`/api/contacts/sessions/${s.id}/verify-reception`, {}))}>Confirm reception after review</Button>}
        </div>}
        {s.status === 'completed' && !report && <p className="mt-2 text-xs text-amber-800">Call ended without a structured report. Review the transcript; no assistance outcome inferred.</p>}
        <div className="mt-3 max-h-72 space-y-2 overflow-y-auto text-xs">{s.transcript.map((t) => <div key={t.id + t.role} className="rounded bg-muted p-2"><strong>{t.role === 'user' ? 'Receiver' : 'Outreach agent'}</strong><p>{t.text}</p></div>)}</div>
      </details> })}
    </section>
    <FacilityDetail facility={f} />
  </div>
}
