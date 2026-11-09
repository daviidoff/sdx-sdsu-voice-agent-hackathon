import type { Call, Responder } from '@/types'

export const SITUATION: Record<Call['situation'], { label: string; color: string; badge: string }> = {
  unknown: { label: 'Needs unconfirmed', color: '#64748b', badge: 'bg-slate-100 text-slate-700' },
  trapped: { label: 'Trapped', color: '#dc2626', badge: 'bg-red-50 text-red-800' },
  needs_help: { label: 'Needs help', color: '#d97706', badge: 'bg-amber-50 text-amber-900' },
  can_leave: { label: 'Can leave', color: '#16a34a', badge: 'bg-emerald-50 text-emerald-800' },
}

export const STATUS: Record<Call['status'], string> = {
  ended: 'Call ended',
  active: 'On call',
  instructed: 'Instructed',
  help_assigned: 'Help assigned',
  resolved: 'Resolved',
}

export const CREW_KIND: Record<Responder['kind'], string> = {
  engine: 'Fire engine',
  ambulance: 'Ambulance',
  wheelchair_van: 'Wheelchair van',
}

export const CREW_STATUS: Record<Responder['status'], { label: string; badge: string }> = {
  available: { label: 'Available', badge: 'bg-slate-900 text-white' },
  en_route: { label: 'En route', badge: 'bg-blue-600 text-white' },
  on_scene: { label: 'On scene', badge: 'bg-violet-600 text-white' },
}

/** A transport request is not a confirmed mobility limitation or a dispatch. */
export function situationLabel(call: Call): string {
  if (call.transportNeeded === true) return 'Transport requested'
  if (call.canEvacuate === false) return 'Cannot leave independently'
  return SITUATION[call.situation].label
}
