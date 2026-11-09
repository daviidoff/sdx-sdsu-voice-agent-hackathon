import type { Zone, Facility } from '@/types'
export interface SearchJob {
  id: string; label: string; provider: 'osm' | 'mock'; zone_ids?: string[]; zones?: Zone[]; error_codes?: string[]; status: string; facility_ids: string[]
  created_at: string; error?: string; summary?: { leads_returned: number; leads_with_phone: number; tasks_failed: number }
  workers: Record<string, { id: string; kind: string; label: string; status: string; records?: number; error_code?: string }>
}
export interface ContactSession {
  id: string; facility_id: string; facility_name: string; phone: string; status: string; mode?: string; mock: true
  approved_at: string; created_at: string; identity_status: string
  transcript: { id: string; role: 'user' | 'agent'; text: string; at: string }[]
}
export interface AssistanceNeed { description: string; location?: string; people_count?: number; urgency: string }
export interface ContactReport {
  id: string; session_id: string; facility_id: string; facility_name: string; recorded_at: string; source: string
  content: { summary: string; reception_confirmed: boolean; receptionist_name?: string; source_quote: string; needs: AssistanceNeed[] }
}
export interface ContactWorkflow {
  searches: SearchJob[]; sessions: ContactSession[]; reports: ContactReport[]
  reviews: { id: string; identity_status: string; verified_at: string }[]; mock_only: true
}
export const emptyWorkflow: ContactWorkflow = { searches: [], sessions: [], reports: [], reviews: [], mock_only: true }
export const sanDiegoFacility = (f: Facility) => f.incidentId === 'san-diego-demo' || (!f.incidentId && (!f.position || (f.position[0] > 32.45 && f.position[0] < 33.2 && f.position[1] > -117.65 && f.position[1] < -116.7)))
export const statusLabel = (value: string) => ({ approved: 'Ready · awaiting clinic', queued: 'Mock agent queued', dialing: 'Simulating ringing', connecting: 'Connecting browser voice', connected: 'Demo call active', completed: 'Completed', partial: 'Completed with gaps', interrupted: 'Interrupted · retry needed' }[value] || value.replaceAll('_', ' '))

// Typed SDK messages do not emit user-transcript events. Persist before sending,
// so the agent's report tool can resolve its quote against the saved receiver text.
export async function deliverReceiverMessage(text: string, persist: (text: string) => Promise<unknown>, send: (text: string) => void) {
  const message = text.trim()
  if (!message) return
  await persist(message)
  send(message)
}
