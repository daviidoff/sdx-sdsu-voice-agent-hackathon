import type { Call, Feed, FeedEvent, TranscriptLine, Zone, Facility, DiscoveryDetails, LocationResolution } from '@/types'

export interface BackendEvent {
  id: string; call_id: string; type: string; payload: Record<string, unknown> | null; created_at: string
}
export interface BackendCall {
  pending_location?: string
  revision: number
  id: string; status: string; mode: string; scenario_id: string; created_at: string; ended_at?: string
  assessment: { location?: string; people_count?: number | null; can_evacuate?: boolean | null; transport_needed?: boolean | null; mobility_needs?: string | null; wheelchair_users?: number | null
    location_resolution?: LocationResolution
  }
  instruction?: { zone_id?: string; text?: string; version?: number; source?: string; match_status?: string
    matching_zones?: { id: string; label: string; action: string; text: string; version: number }[] }
  current_spatial_instruction?: BackendCall['instruction']
  events: BackendEvent[]
}
export interface Snapshot {
  fires?: import('../types').SimulatedFire[]
  contact_workflow?: import('./contacts').ContactWorkflow
  calls: BackendCall[]; zones: Zone[]; facilities: Record<string, unknown>[]
  incidents: Record<string, unknown>[]; routes: Record<string, unknown>[]; updated_at: string
}

export async function api<T>(path: string, body?: unknown, signal?: AbortSignal, method?: 'DELETE'): Promise<T> {
  const response = await fetch(path, { method: method ?? (body === undefined ? 'GET' : 'POST'),
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
  const location = a.location_resolution
  const mapped = !raw.pending_location && location?.status === 'resolved' && (!location.query || location.query === a.location) && Number.isFinite(location.lat) && Number.isFinite(location.lng) && Math.abs(location.lat!) <= 90 && Math.abs(location.lng!) <= 180
  const ended = raw.ended_at ?? raw.events.findLast((e) => e.type === 'call.ended')?.created_at
  return { id: raw.id, callerName: `${raw.mode === 'elevenlabs' ? 'Voice' : 'Simulation'} · ${raw.id.slice(0, 8)}`,
    phone: 'Browser call', address: raw.pending_location ? `Confirmation pending: ${raw.pending_location}` : a.location || 'Location not confirmed', locationQuery: a.location || undefined, position: mapped ? [location!.lat!, location!.lng!] : undefined,
    people: a.people_count ?? null, situation: a.transport_needed === true || a.can_evacuate === false ? 'needs_help' : a.can_evacuate === true ? 'can_leave' : 'unknown',
    mobility: a.mobility_needs || 'Mobility needs not confirmed', status: raw.status === 'ended' ? 'ended' : 'active',
    startedAt: Date.parse(raw.created_at), endedAt: ended ? Date.parse(ended) : undefined, transportNeeded: a.transport_needed ?? undefined, canEvacuate: a.can_evacuate ?? undefined, instruction: raw.instruction, mode: raw.mode,
    wheelchairUsers: a.wheelchair_users ?? undefined, scenarioId: raw.scenario_id, locationResolution: location, currentSpatialInstruction: raw.current_spatial_instruction }
}

export function toLines(raw: BackendCall): TranscriptLine[] {
  return raw.events.flatMap((e): TranscriptLine[] => {
    const p = e.payload ?? {}
    let speaker: TranscriptLine['speaker'] = 'system'
    let text = ''
    if (e.type === 'transcript') { speaker = p.role === 'user' ? 'caller' : 'agent'; text = String(p.text ?? '') }
    else if (e.type === 'steering.queued') { speaker = 'steer'; text = `Queued: ${p.text}` }
    else if (e.type === 'operator.requested') { text = `Sent to operator inbox: ${p.text}` }
    else if (e.type === 'steering.acknowledged') text = p.status === 'response_requested' ? 'Operator message sent; immediate voice response requested. Caller hearing unconfirmed.' : 'Operator message delivered to agent context; spoken acknowledgement unconfirmed.'
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
    simulated: f.simulated === true, address: typeof f.address === 'string' ? f.address : undefined,
    discovery: f.discovery as DiscoveryDetails | undefined, incidentId: f.incident_id as string | undefined,
    updatedAt: f.updated_at as string | undefined, runId: f.run_id as string | undefined }))
}

export function createFeed(): Feed {
  return {
    source: 'backend',
    start(onEvent: (e: FeedEvent) => void) {
      let stopped = false
      let timer: ReturnType<typeof setTimeout> | undefined
      const controller = new AbortController()
      let previousContent: string | undefined
      const poll = async () => {
        try {
          const snapshot = await api<Snapshot>('/api/dashboard/snapshot', undefined, controller.signal)
          const content = JSON.stringify({ ...snapshot, updated_at: undefined })
          if (!stopped && content !== previousContent) {
            previousContent = content
            onEvent({ type: 'snapshot', snapshot })
          }
        } catch (error) {
          previousContent = undefined
          if (!stopped) onEvent({ type: 'connection', error: error instanceof Error ? error.message : 'Backend unavailable' })
        } finally {
          if (!stopped) timer = setTimeout(poll, 1000)
        }
      }
      void poll()
      return () => { stopped = true; controller.abort(); clearTimeout(timer) }
    },
    async steer(callId, text, mode) {
      await api(`/api/calls/${encodeURIComponent(callId)}/steering`, { text: mode === 'say' ? `Tell the caller immediately: ${text}` : text })
    },
  }
}
