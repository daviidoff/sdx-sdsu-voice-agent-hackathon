import { useEffect, useRef, useState } from 'react'
import { Inbox, X, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/feed'
import type { BackendCall } from '@/lib/feed'
import { inboxMessages, unreadMessages, replyStatus } from '@/lib/inbox'

export function OperatorInbox({ calls, onClose, embedded = false }: { calls: BackendCall[]; onClose: () => void; embedded?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { if (!embedded) dialog.current?.showModal() }, [embedded])
  const threads = calls.filter((call) => inboxMessages(call).length).sort((a, b) =>
    Number(inboxMessages(b).at(-1)?.id) - Number(inboxMessages(a).at(-1)?.id))
  const [selected, setSelected] = useState<string>()
  const call = threads.find((item) => item.id === selected) ?? threads[0]
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [includeTranscript, setIncludeTranscript] = useState(true)
  const latestRequest = call?.events.findLast((e) => e.type === 'operator.requested')?.id
  const callId = call?.id
  useEffect(() => { if (!selected && callId) setSelected(callId) }, [selected, callId])
  useEffect(() => {
    if (!callId || !latestRequest) return
    void api(`/api/calls/${encodeURIComponent(callId)}/inbox/read`, { through_event_id: Number(latestRequest) })
      .catch((e: Error) => setError(e.message))
  }, [callId, latestRequest])
  const send = async () => {
    if (!call || busy || !drafts[call.id]?.trim()) return
    const id = call.id
    setBusy(true); setError('')
    try {
      await api(`/api/calls/${encodeURIComponent(id)}/steering`, { text: drafts[id].trim() })
      setDrafts((previous) => ({ ...previous, [id]: '' }))
    } catch (e) { setError(e instanceof Error ? e.message : 'Reply failed') }
    finally { setBusy(false) }
  }
  const chooseInstruction = async (zoneId: string) => {
    if (!call || busy) return
    setBusy(true); setError('')
    try { await api(`/api/calls/${encodeURIComponent(call.id)}/operator-instruction`, { zone_id: zoneId, revision: call.revision }) }
    catch (e) { setError(e instanceof Error ? e.message : 'Selection failed') }
    finally { setBusy(false) }
  }
  const content = <>
    <div className="mx-auto flex h-full max-w-6xl flex-col overflow-hidden bg-background">
      {!embedded && <header className="flex items-center gap-3 border-b px-5 py-4">
        <Inbox className="size-5" /><div className="flex-1"><h2 id="inbox-title" className="font-semibold">Operator inbox</h2><p className="text-xs text-muted-foreground">Agent requests, call history and operator replies</p></div>
        <Button variant="ghost" size="icon" aria-label="Close inbox" autoFocus disabled={busy} onClick={onClose}><X className="size-4" /></Button>
      </header>}
      {error && <div role="alert" className="border-b bg-red-50 px-5 py-2 text-sm text-red-800">{error}</div>}
      <div className={`grid min-h-0 flex-1 grid-rows-[minmax(80px,25%)_1fr] ${embedded ? '' : 'sm:grid-cols-[260px_1fr] sm:grid-rows-1'}`}>
        <nav aria-label="Inbox conversations" className="min-h-0 overflow-y-auto border-r bg-muted/20 p-2">
          {!threads.length && <p className="p-4 text-sm text-muted-foreground">No messages yet. Agent requests and zone conflicts will appear here.</p>}
          {threads.map((thread) => <button key={thread.id} disabled={busy} aria-current={call?.id === thread.id ? 'true' : undefined}
            onClick={() => { setSelected(thread.id); setError('') }} className={`mb-2 w-full rounded-lg border p-3 text-left ${call?.id === thread.id ? 'border-primary bg-background' : 'border-transparent hover:bg-muted'}`}>
            <div className="flex items-center gap-2 text-sm font-medium"><span className="truncate">{thread.assessment.location || 'Location unconfirmed'}</span>{unreadMessages(thread) > 0 && <span className="ml-auto rounded-full bg-orange-600 px-2 text-xs text-white">{unreadMessages(thread)} unread</span>}</div>
            <div className="mt-1 text-xs text-muted-foreground">Call {thread.id.slice(0, 8)} · {thread.status}</div>
            <p className="mt-2 line-clamp-2 text-xs">{String(inboxMessages(thread).at(-1)?.payload?.text ?? '')}</p>
          </button>)}
        </nav>
        {call ? <section className="flex min-h-0 min-w-0 flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b px-5 py-3 text-sm"><strong>{call.assessment.location || 'Location unconfirmed'}</strong><span className="text-xs text-muted-foreground">{call.status === 'ended' ? 'Ended call · history retained' : 'Active call'}</span>
            <label className="ml-auto flex items-center gap-2 text-xs"><input type="checkbox" checked={includeTranscript} onChange={(e) => setIncludeTranscript(e.target.checked)} />Show call transcript</label></div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4" role="log" aria-label="Conversation history">
            {call.events.filter((e) => ['operator.requested', 'steering.queued'].includes(e.type) || (includeTranscript && e.type === 'transcript')).map((event) => {
              const operator = event.type === 'steering.queued', request = event.type === 'operator.requested'
              return <article key={event.id} className={`mb-3 rounded-lg border p-3 ${operator ? 'ml-6 border-blue-200 bg-blue-50' : request ? 'border-amber-200 bg-amber-50' : 'border-transparent bg-muted/30'}`}>
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><strong>{operator ? 'Operator → agent' : request ? event.payload?.source === 'backend' ? 'Zone conflict → operator' : 'Agent → operator' : event.payload?.role === 'user' ? 'Caller' : 'Voice agent'}</strong><time>{new Date(event.created_at).toLocaleTimeString()}</time></div>
                <p className="whitespace-pre-wrap break-words text-sm">{String(event.payload?.text ?? '')}</p>
                {(operator || request) && <p className="mt-2 text-xs text-muted-foreground">{operator ? replyStatus(call, event.id) : `Saved in inbox · message ${event.id}`}</p>}
              </article>
            })}
            {call.status !== 'ended' && call.instruction?.match_status === 'overlapping_zones' && <div className="space-y-2 rounded-lg border border-amber-300 p-3">
              <h3 className="text-sm font-semibold">Resolve conflicting zones for this call</h3><p className="text-xs text-muted-foreground">Select the applicable published instruction. New zone versions or location changes require a fresh decision.</p>
              {call.instruction.matching_zones?.map((zone) => <div key={zone.id} className="rounded border p-3"><strong className="text-sm">{zone.label} · v{zone.version}</strong><p className="my-2 whitespace-pre-wrap text-sm">{zone.text}</p><Button size="sm" disabled={busy} onClick={() => void chooseInstruction(zone.id)}>Use {zone.label} for this call</Button></div>)}
            </div>}
            {call.instruction?.match_status === 'operator_resolved' && <p className="rounded border bg-green-50 p-3 text-sm">Operator-selected instruction: {call.instruction.text}</p>}
          </div>
          <form className="space-y-2 border-t p-4" onSubmit={(event) => { event.preventDefault(); void send() }}>
            <label className="block text-xs font-medium" htmlFor="operator-reply">Reply to agent</label>
            <div className="flex gap-2"><textarea id="operator-reply" rows={2} maxLength={10000} className="min-w-0 flex-1 rounded-md border p-2 text-sm" disabled={busy || call.status === 'ended'} value={drafts[call.id] ?? ''} onChange={(e) => setDrafts({ ...drafts, [call.id]: e.target.value })} placeholder="Answer the agent’s question or provide guidance…" /><Button type="submit" disabled={busy || call.status === 'ended' || !drafts[call.id]?.trim()}><Send className="size-4" />{busy ? 'Sending…' : 'Send reply'}</Button></div>
            <p className="text-xs text-muted-foreground">{call.status === 'ended' ? 'This call has ended. Replies cannot reach the caller.' : 'Replies enter the live agent’s context for its next turn. Context delivery does not confirm the caller heard it.'}</p>
          </form>
        </section> : <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">Incoming requests will appear here with their conversation history.</div>}
      </div>
    </div>
  </>
  return embedded ? content : <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }} className="fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none bg-black/40 p-2 text-foreground sm:p-6" aria-labelledby="inbox-title">{content}</dialog>
}
