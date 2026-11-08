import type { Call, Feed, FeedEvent, TranscriptLine, Zone, Facility } from '@/types'

export interface BackendEvent {
  id: string; call_id: string; type: string; payload: Record<string, unknown> | null; created_at: string
}
export interface BackendCall {
  id: string; status: string; mode: string; scenario_id: string; created_at: string
  assessment: { location?: string; people_count?: number; can_evacuate?: boolean; transport_needed?: boolean; mobility_needs?: string; wheelchair_users?: number }
  instruction?: { zone_id?: string; text?: string; version?: number; source?: string }
  events: BackendEvent[]
}
export interface Snapshot {
  calls: BackendCall[]; zones: Zone[]; facilities: Record<string, unknown>[]
  incidents: Record<string, unknown>[]; routes: Record<string, unknown>[]; updated_at: string
}

export async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000) })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(typeof detail.detail === 'string' ? detail.detail : `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function toCall(raw: BackendCall): Call {
  const a = raw.assessment
  return { id: raw.id, callerName: `${raw.mode === 'elevenlabs' ? 'Voice' : 'Simulation'} · ${raw.id.slice(0, 8)}`,
    phone: 'Browser call', address: a.location || 'Location not confirmed', position: undefined,
    people: a.people_count ?? null, situation: a.transport_needed === true || a.can_evacuate === false ? 'needs_help' : a.can_evacuate === true ? 'can_leave' : 'unknown',
    mobility: a.mobility_needs || 'Mobility needs not confirmed', status: raw.status === 'ended' ? 'ended' : 'active',
    startedAt: Date.parse(raw.created_at), instruction: raw.instruction, mode: raw.mode,
    wheelchairUsers: a.wheelchair_users, scenarioId: raw.scenario_id }
}

export function toLines(raw: BackendCall): TranscriptLine[] {
  return raw.events.flatMap((e): TranscriptLine[] => {
    const p = e.payload ?? {}
    let speaker: TranscriptLine['speaker'] = 'system'
    let text = ''
    if (e.type === 'transcript') { speaker = p.role === 'user' ? 'caller' : 'agent'; text = String(p.text ?? '') }
    else if (e.type === 'steering.queued') { speaker = 'steer'; text = `Queued: ${p.text}` }
    else if (e.type === 'steering.acknowledged') text = 'Operator message delivered to agent context; spoken acknowledgement unconfirmed.'
    else if (e.type === 'instruction.updated') text = e.payload ? `Instruction v${p.version ?? '—'}: ${p.text}` : 'Previous instruction cleared.'
    else if (e.type === 'call.ended') text = 'Call ended. Assistance outcome remains unconfirmed.'
    else if (e.type === 'job.started') text = 'Background analysis started.'
    else if (e.type === 'job.failed' || e.type === 'job.discarded') text = String(p.message ?? p.reason)
    else if (e.type === 'job.completed') {
      const result = (p.result ?? {}) as Record<string, unknown>
      const candidate = result.proposed_candidate as { vehicle_ids?: string[] } | undefined
      text = `Background analysis (${result.provider ?? 'worker'}): ${String(result.status ?? '').replaceAll('_', ' ')}. ${result.summary ?? ''}`
      if (Array.isArray(result.missing_fields) && result.missing_fields.length) text += ` Still needed: ${result.missing_fields.join(', ').replaceAll('_', ' ')}.`
      if (candidate) text += ` Candidate: ${candidate.vehicle_ids?.join(', ') ?? 'unconfirmed'}. Not dispatched.`
      if (Array.isArray(result.unmet_needs)) text += ` ${result.unmet_needs.join(' ')}`
    }
    if (!text) return []
    return [{ id: e.id, callId: raw.id, speaker, text, at: Date.parse(e.created_at) }]
  })
}

export function toFacilities(rows: Record<string, unknown>[]): Facility[] {
  return rows.map((f) => ({ id: String(f.id), name: String(f.name), type: String(f.type ?? 'facility'),
    area: String(f.area ?? ''), contact: String(f.contact ?? ''),
    position: typeof (f.latitude ?? f.lat) === 'number' && typeof (f.longitude ?? f.lng) === 'number' ? [Number(f.latitude ?? f.lat), Number(f.longitude ?? f.lng)] : undefined,
    mobilitySupport: Array.isArray(f.mobility_support) ? f.mobility_support.join(', ') : String(f.mobility_support ?? ''),
    simulated: f.simulated === true }))
}

export function createFeed(): Feed {
  return {
    source: 'backend',
    start(onEvent: (e: FeedEvent) => void) {
      let stopped = false
      let timer: ReturnType<typeof setTimeout> | undefined
      const controller = new AbortController()
      const poll = async () => {
        try {
          const snapshot = await api<Snapshot>('/api/dashboard/snapshot', undefined, controller.signal)
          if (!stopped) onEvent({ type: 'snapshot', snapshot })
        } catch (error) {
          if (!stopped) onEvent({ type: 'connection', error: error instanceof Error ? error.message : 'Backend unavailable' })
        } finally {
          if (!stopped) timer = setTimeout(poll, 1000)
        }
      }
      void poll()
      return () => { stopped = true; controller.abort(); clearTimeout(timer) }
    },
    async steer(callId, text, mode) {
      await api(`/api/calls/${encodeURIComponent(callId)}/steering`, { text: mode === 'say' ? `At the next appropriate opportunity, tell the caller: ${text}` : text })
    },
  }
}
