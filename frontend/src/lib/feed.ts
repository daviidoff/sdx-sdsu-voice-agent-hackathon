// Where the dashboard's live data comes from.
// - No Supabase env vars → fake feed that replays a scripted demo.
// - VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY set → Supabase tables + realtime.
import { createClient } from '@supabase/supabase-js'
import { initialCalls, initialLines, script } from '@/data/fake'
import type { Call, Feed, FeedEvent, TranscriptLine } from '@/types'

let lineSeq = 0
const lineId = () => `line-${++lineSeq}`

export function createFakeFeed(): Feed {
  return {
    source: 'fake',
    start(onEvent) {
      const calls = new Map(initialCalls.map((c) => [c.id, { ...c }]))
      for (const call of calls.values()) onEvent({ type: 'call', call })
      const t = Date.now()
      initialLines.forEach(([callId, speaker, text], i) =>
        onEvent({ type: 'line', line: { id: lineId(), callId, speaker, text, at: t - (initialLines.length - i) * 20_000 } }),
      )
      const timers = script.map((step) =>
        setTimeout(() => {
          if (step.kind === 'line') {
            onEvent({ type: 'line', line: { id: lineId(), callId: step.callId, speaker: step.speaker, text: step.text, at: Date.now() } })
          } else if (step.kind === 'call') {
            const call: Call = { ...step.call, startedAt: Date.now() }
            calls.set(call.id, call)
            onEvent({ type: 'call', call })
          } else {
            const call = calls.get(step.callId)
            if (call) {
              call.status = step.status
              onEvent({ type: 'call', call: { ...call } })
            }
          }
        }, step.at * 1000),
      )
      return () => timers.forEach(clearTimeout)
    },
    async steer(callId, text, mode) {
      console.info('[fake feed] steer', { callId, text, mode })
    },
  }
}

// Supabase tables the dashboard expects (snake_case columns):
//   calls(id text pk, caller_name, phone, address, lat float8, lng float8, people int,
//         situation text, mobility text, status text, started_at timestamptz)
//   transcript_lines(id text pk, call_id text, speaker text, text text, created_at timestamptz)
//   steering(id bigint generated, call_id text, text text, mode text, created_at timestamptz default now())
// Realtime must be enabled on calls and transcript_lines.
type CallRow = { id: string; caller_name: string; phone: string; address: string; lat: number; lng: number; people: number; situation: Call['situation']; mobility: string; status: Call['status']; started_at: string }
type LineRow = { id: string; call_id: string; speaker: TranscriptLine['speaker']; text: string; created_at: string }

const toCall = (r: CallRow): Call => ({
  id: r.id, callerName: r.caller_name, phone: r.phone, address: r.address, position: [r.lat, r.lng],
  people: r.people, situation: r.situation, mobility: r.mobility, status: r.status, startedAt: Date.parse(r.started_at),
})
const toLine = (r: LineRow): TranscriptLine => ({ id: r.id, callId: r.call_id, speaker: r.speaker, text: r.text, at: Date.parse(r.created_at) })

export function createSupabaseFeed(url: string, key: string): Feed {
  const supabase = createClient(url, key)
  return {
    source: 'supabase',
    start(onEvent: (e: FeedEvent) => void) {
      let stopped = false
      void (async () => {
        const [{ data: calls }, { data: lines }] = await Promise.all([
          supabase.from('calls').select('*').order('started_at'),
          supabase.from('transcript_lines').select('*').order('created_at'),
        ])
        if (stopped) return
        for (const row of (calls ?? []) as CallRow[]) onEvent({ type: 'call', call: toCall(row) })
        for (const row of (lines ?? []) as LineRow[]) onEvent({ type: 'line', line: toLine(row) })
      })()
      const channel = supabase
        .channel('dashboard')
        .on('postgres_changes', { event: '*', schema: 'public', table: 'calls' }, (p) => {
          if (p.new && 'id' in p.new) onEvent({ type: 'call', call: toCall(p.new as CallRow) })
        })
        .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'transcript_lines' }, (p) => {
          onEvent({ type: 'line', line: toLine(p.new as LineRow) })
        })
        .subscribe()
      return () => {
        stopped = true
        void supabase.removeChannel(channel)
      }
    },
    async steer(callId, text, mode) {
      const { error } = await supabase.from('steering').insert({ call_id: callId, text, mode })
      if (error) throw error
    },
  }
}

export function createFeed(): Feed {
  const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
  const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
  return url && key ? createSupabaseFeed(url, key) : createFakeFeed()
}
