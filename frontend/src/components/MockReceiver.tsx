import { useEffect, useRef, useState } from 'react'
import type { Conversation } from '@elevenlabs/client'
import { api } from '@/lib/feed'
import { waitForStartup } from '@/lib/voice-startup'
import { deliverReceiverMessage } from '@/lib/contacts'
import type { ContactSession } from '@/lib/contacts'
import { Button } from './ui/button'

export function MockReceiver({ session, onClose }: { session: ContactSession; onClose: () => void }) {
  const voice = useRef<Conversation | null>(null)
  const alive = useRef(true)
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const [status, setStatus] = useState('Ready to answer as the clinic')
  const [error, setError] = useState('')
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [started, setStarted] = useState(false)
  const [muted, setMuted] = useState(false)
  const [text, setText] = useState('')
  const [messages, setMessages] = useState<{ key: string; role: string; text: string }[]>([])
  const starting = useRef(false)
  const ended = useRef(false)
  const startup = useRef<AbortController | null>(null)
  const prefix = `/api/contacts/sessions/${session.id}`
  const close = async () => {
    if (ended.current) return
    ended.current = true; alive.current = false; startup.current?.abort(new Error('Connection cancelled'))
    await voice.current?.endSession().catch(() => {})
    await queue.current.catch(() => {})
    await api(prefix + '/end', { status: connected ? 'completed' : 'cancelled' }).catch(() => {})
    onClose()
  }
  useEffect(() => {
    alive.current = true
    const unload = () => navigator.sendBeacon(prefix + '/end', new Blob([JSON.stringify({ status: 'failed' })], { type: 'application/json' }))
    window.addEventListener('beforeunload', unload)
    return () => { alive.current = false; startup.current?.abort(new Error('Receiver closed')); window.removeEventListener('beforeunload', unload); void voice.current?.endSession(); }
  }, [prefix])
  const sendText = async () => {
    if (!voice.current || busy || !text.trim()) return
    const message = text; setBusy(true); setError('')
    try {
      await deliverReceiverMessage(message, async (value) => {
        const key = 'typed:' + crypto.randomUUID()
        const pending = queue.current.catch(() => {}).then(() => api(prefix + '/transcript', { id: key, role: 'user', text: value }))
        queue.current = pending
        await pending
        setMessages((current) => [...current, { key, role: 'user', text: value }])
      }, (value) => voice.current?.sendUserMessage(value))
      setText('')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const answer = async (textOnly = false) => {
    if (starting.current) return
    starting.current = true; setBusy(true); setError(''); setStatus(textOnly ? 'Connecting text test…' : 'Allow microphone access…')
    let created = false
    const attempt = new AbortController(); startup.current = attempt
    let deadline: ReturnType<typeof setTimeout> | undefined
    try {
      if (!textOnly) {
        const media = await waitForStartup(navigator.mediaDevices.getUserMedia({ audio: true }), attempt.signal, (media) => media.getTracks().forEach((t) => t.stop()))
        media.getTracks().forEach((t) => t.stop())
      }
      if (!alive.current) return
      deadline = setTimeout(() => attempt.abort(new Error('Voice connection timed out. Close this attempt and start another Demo Clinic Call.')), 45000)
      created = true; setStarted(true)
      const auth = await waitForStartup(api<{ signed_url: string; dynamic_variables: Record<string, string> }>(prefix + '/voice', {}), attempt.signal)
      if (!alive.current || attempt.signal.aborted) { await api(prefix + '/end', { status: 'cancelled' }); return }
      const { Conversation } = await waitForStartup(import('@elevenlabs/client'), attempt.signal)
      const persist = (role: 'user' | 'agent', text: string, key: string) => {
        if (!alive.current || attempt.signal.aborted) return
        setMessages((current) => [...current.filter((m) => m.key !== key), { key, role, text }])
        const pending = queue.current.catch(() => {}).then(() => api(prefix + '/transcript', { id: key, role, text }))
        queue.current = pending
        void pending.catch((e) => setError(String(e)))
      }
      const options = {
        signedUrl: auth.signed_url, connectionType: 'websocket' as const, textOnly,
        dynamicVariables: auth.dynamic_variables,
        onMessage: (message: { message: string; role: string; event_id: number; response_id?: string }) => {
          const role = message.role === 'user' ? 'user' as const : 'agent' as const
          persist(role, message.message, `${role}:${message.response_id ?? message.event_id}`)
        },
        onAgentResponseCorrection: (message: { corrected_agent_response: string; event_id: number; response_id?: string }) => persist('agent', message.corrected_agent_response, `agent:${message.response_id ?? message.event_id}`),
        onModeChange: ({ mode }: { mode: string }) => { if (alive.current) setStatus(mode === 'speaking' ? 'Outreach agent speaking' : 'Listening to the receiver') },
        onError: (message: string) => { if (alive.current) setError(message) },
        onDisconnect: () => {
          if (!alive.current || ended.current) return
          ended.current = true; setConnected(false); setStatus('Demo call ended'); voice.current = null
          void queue.current.then(() => api(prefix + '/end', { status: 'completed' })).catch((e) => setError(String(e)))
        },
        clientTools: {
          get_clinic_context: async () => {
            try { return JSON.stringify(await api(prefix + '/context')) }
            catch { return JSON.stringify({ error: 'Current clinic guidance unavailable. Do not invent an instruction; tell the clinic coordinator review is needed.' }) }
          },
          record_contact_report: async (parameters: Record<string, unknown>) => {
            try { await queue.current; return JSON.stringify(await api(prefix + '/report', parameters)) }
            catch (e) { return JSON.stringify({ saved: false, error: String(e), instruction: 'Use an exact receiver transcript quote and retry. Do not claim the report was saved.' }) }
          },
        },
      }
      const connectedVoice = await waitForStartup(Conversation.startSession(options), attempt.signal, (late) => late.endSession())
      if (!alive.current || ended.current) { await connectedVoice.endSession(); return }
      voice.current = connectedVoice
      await api(prefix + '/connected', {})
      setConnected(true); setStatus(textOnly ? 'Text test connected' : 'Demo call connected · you are the clinic')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Voice connection failed'); setStatus('Connection failed')
      await voice.current?.endSession().catch(() => {}); voice.current = null
      if (created) { await api(prefix + '/end', { status: 'failed' }).catch(() => {}); setStarted(true) }
    } finally { if (deadline) clearTimeout(deadline); startup.current = null; starting.current = false; setBusy(false) }
  }
  return <div role="dialog" aria-modal="true" aria-label="Demo Clinic Call" className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/45 p-6">
    <div className="flex max-h-[90vh] w-full max-w-xl flex-col gap-4 overflow-y-auto rounded-xl bg-background p-6 shadow-xl">
      <div><p className="text-xs uppercase text-blue-700">Demo Clinic Call · browser role-play</p><h2 className="mt-2 text-lg font-semibold">{session.facility_name}</h2><p className="text-sm" role="status">{status}</p></div>
      <p className="text-sm">You are the clinic. Answer as reception or a staff member: describe the situation, patients needing help, and missing transport or supplies. The outreach agent listens first, then explains the published exercise guidance.</p>
      <p className="text-xs text-muted-foreground">Use fictional patient details. No clinic phone number is dialed. Your transcript and reported needs appear in the dashboard.</p>
      {error && <p role="alert" className="rounded bg-red-50 p-2 text-sm">{error}</p>}
      {!started && <div className="flex gap-2"><Button disabled={busy} onClick={() => void answer()}>Answer with microphone</Button><Button variant="outline" disabled={busy} onClick={() => void answer(true)}>Answer as text test</Button></div>}
      <div className="min-h-16 space-y-2 overflow-y-auto rounded border p-3 text-sm">{messages.map((m) => <div key={m.key}><strong>{m.role === 'user' ? 'You · receiver' : 'Outreach agent'}: </strong>{m.text}</div>)}</div>
      {connected && <><form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void sendText() }}><input aria-label="Receiver message" className="min-w-0 flex-1 rounded border p-2 text-sm" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type as the receptionist…" /><Button type="submit" disabled={busy || !text.trim()}>Send</Button></form><Button variant="outline" onClick={() => { voice.current?.setMicMuted(!muted); setMuted(!muted) }}>{muted ? 'Unmute microphone' : 'Mute microphone'}</Button></>}
      <Button variant="destructive" onClick={() => { if (ended.current) onClose(); else void close() }}>{connected ? 'End demo call' : 'Close'}</Button>
    </div>
  </div>
}
