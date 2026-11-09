import { useState } from 'react'
import { api } from '@/lib/feed'
import type { ContactWorkflow } from '@/lib/contacts'
import { statusLabel } from '@/lib/contacts'
import type { Facility } from '@/types'
import { Button } from './ui/button'
import { FacilitySymbol } from './map-symbols'
import { PhoneCall } from 'lucide-react'
import { FacilityDetail } from './FacilityDetail'

export function ContactReview({ facility: f, workflow, onError }: { facility: Facility; workflow: ContactWorkflow; onError: (message: string) => void }) {
  const [busy, setBusy] = useState(false)
  const sessions = workflow.sessions.filter((s) => s.facility_id === f.id)
  const session = sessions[0]
  const action = async (fn: () => Promise<unknown>) => { setBusy(true); onError(''); try { await fn() } catch (e) { onError(e instanceof Error ? e.message : 'Contact action failed') } finally { setBusy(false) } }
  const current = session && !['completed', 'failed', 'cancelled', 'interrupted'].includes(session.status) ? session : undefined
  return <div className="h-full overflow-y-auto">
    <section className="space-y-3 border-b p-4 text-sm">
      <div className="flex items-center gap-3"><FacilitySymbol type={f.type} /><div><p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Selected contact</p><h2 className="text-lg font-semibold tracking-tight">{f.name}</h2></div></div>
      <p className="text-xs">Play the clinic in a live conversation with the outreach agent. It asks about your situation and people needing help, then explains the published exercise guidance.</p>
      {f.discovery && <a href={`${import.meta.env.DEV ? 'http://127.0.0.1:8000/' : '/'}?clinic=${encodeURIComponent(f.id)}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"><PhoneCall className="size-3.5" />Open clinic caller ↗</a>}
      <p className="text-xs text-muted-foreground">Opens the phone in a new tab. Press “Respond as clinic” to speak with the outreach agent.</p>
      {!f.discovery && <p className="text-xs">Find this facility with the crawler to start a call.</p>}
      {current && <><p className="rounded bg-blue-50 p-2 text-xs">{statusLabel(current.status)}</p>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void action(() => api(`/api/contacts/sessions/${current.id}/end`, { status: 'cancelled' }))}>Cancel call</Button>
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
