// Shapes the dashboard works with. The fake feed and the Supabase feed both produce these.

export type LatLng = [number, number]

export type Situation = 'can_leave' | 'needs_help' | 'trapped' | 'unknown'
export type CallStatus = 'active' | 'instructed' | 'help_assigned' | 'resolved' | 'ended'
export type Speaker = 'caller' | 'agent' | 'steer' | 'system'

export interface TranscriptLine {
  id: string
  callId: string
  speaker: Speaker
  text: string
  at: number // ms since epoch
}

export interface Call {
  id: string
  callerName: string
  phone: string
  address: string
  locationQuery?: string
  position?: LatLng
  people: number | null
  situation: Situation
  mobility: string
  status: CallStatus
  startedAt: number
  endedAt?: number
  transportNeeded?: boolean
  canEvacuate?: boolean
  instruction?: { zone_id?: string; text?: string; version?: number; source?: string }
  currentSpatialInstruction?: { zone_id?: string; text?: string; version?: number; source?: string }
  locationResolution?: { status: string; query?: string; message?: string; display_name?: string; source?: string; source_url?: string; precision?: string; resolved_at?: string }
  mode?: string
  wheelchairUsers?: number
  scenarioId?: string
}

export interface DiscoveredPhone {
  number: string
  extension?: string
  raw?: string
  role?: string
  source_url?: string
}
export interface DiscoveryDetails {
  phone_candidates: DiscoveredPhone[]
  website?: string
  source_url?: string
  flags: string[]
  review_status: string
  evidence: { evidence_id: string; source: string; source_url?: string; retrieved_at: string; excerpt?: string; observed?: { osm_tags?: Record<string, string> } }[]
  website_enrichment?: { status: string; reason?: string; errors: { url: string; code: string }[] }
}

export interface Facility {
  id: string
  name: string
  type: string
  /** Missing when the team data has no coordinates yet: listed in Contacts, not drawn on the map. */
  position?: LatLng
  area?: string
  contact: string
  mobilitySupport?: string
  simulated?: boolean
  accessible?: boolean
  address?: string
  discovery?: DiscoveryDetails
  incidentId?: string
  updatedAt?: string
  runId?: string
}


export interface Responder {
  id: string
  name: string
  kind: 'engine' | 'ambulance' | 'wheelchair_van'
  position: LatLng // where it is when not driving
  status: 'available' | 'en_route' | 'on_scene'
  wheelchair: boolean // can carry a wheelchair user
  seats: number
}

export interface DispatchTarget {
  kind: 'call' | 'facility'
  id: string
  label: string
  position: LatLng
}

// A crew sent somewhere. Status moves: calling → en_route → on_scene → done.
export interface Dispatch {
  id: string
  crewId: string
  target: DispatchTarget
  status: 'calling' | 'en_route' | 'on_scene' | 'done'
  route: LatLng[] // road path from crew to target
  routeText: string // e.g. "via University Ave, 30th St"
  durationSec: number // real driving time
  acceptedAt?: number
  radio: TranscriptLine[] // agent ↔ crew call
}

export type Selection = { kind: 'call' | 'crew' | 'zone' | 'facility'; id: string }

export interface Zone {
  id: string
  label: string
  level: 'evacuate' | 'warning' | 'shelter' | 'unknown'
  polygon: LatLng[]
  instruction: string
  area?: string
  version?: number
}

export interface FireStage {
  label: string // e.g. "Now", "+1 h forecast"
  polygon: LatLng[]
}

export type FeedEvent =
  | { type: 'snapshot'; snapshot: import('./lib/feed').Snapshot }
  | { type: 'connection'; error: string }
  | { type: 'call'; call: Call }
  | { type: 'line'; line: TranscriptLine }

export interface Feed {
  /** Starts delivering events. Returns a function that stops it. */
  start(onEvent: (event: FeedEvent) => void): () => void
  /** Sends a steering instruction for a live call to the voice agent. */
  steer(callId: string, text: string, mode: 'context' | 'say'): Promise<void>
  readonly source: 'fake' | 'supabase' | 'backend'
}
