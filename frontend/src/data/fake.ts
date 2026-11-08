// All fake. Map area: North Park / City Heights, San Diego. No real people, calls or fire.
import facilitiesRaw from '../../../data/facilities?raw'
import type { Call, Facility, FireStage, Responder, Zone } from '@/types'

export const MAP_CENTER: [number, number] = [32.7525, -117.1145]
export const MAP_ZOOM = 15

// Team's shared fake facilities (data/facilities). Accepts one object or an array.
function loadTeamFacilities(): Facility[] {
  try {
    const parsed = JSON.parse(facilitiesRaw)
    const list = Array.isArray(parsed) ? parsed : [parsed]
    return list.map((f) => ({
      id: f.id,
      name: f.name,
      type: f.type,
      position: [f.latitude, f.longitude],
      contact: f.contact,
      mobilitySupport: f.mobility_support,
      accessible: f.accessible,
    }))
  } catch {
    return []
  }
}

export const facilities: Facility[] = [
  ...loadTeamFacilities(),
  { id: 'facility-101', name: 'Westside Community Shelter', type: 'shelter', position: [32.7488, -117.1312], contact: '555-0140', accessible: true },
  { id: 'facility-102', name: 'Juniper Elementary (shelter)', type: 'school', position: [32.7436, -117.1205], contact: '555-0152', accessible: true },
  { id: 'facility-103', name: 'Oak Grove Memory Care', type: 'memory_care', position: [32.7562, -117.1172], contact: '555-0117', mobilitySupport: 'stretcher_transport_needed', accessible: true },
  { id: 'facility-104', name: 'Canyon View Dialysis Center', type: 'clinic', position: [32.7517, -117.1078], contact: '555-0163', accessible: true },
]

export const initialResponders: Responder[] = [
  { id: 'r-engine-14', name: 'Engine 14', kind: 'engine', position: [32.7451, -117.1298], status: 'available', wheelchair: false, seats: 4 },
  { id: 'r-medic-7', name: 'Medic 7', kind: 'ambulance', position: [32.7478, -117.1362], status: 'available', wheelchair: false, seats: 2 },
  { id: 'r-van-3', name: 'Wheelchair Van 3', kind: 'wheelchair_van', position: [32.7419, -117.1158], status: 'available', wheelchair: true, seats: 6 },
  { id: 'r-van-5', name: 'Wheelchair Van 5', kind: 'wheelchair_van', position: [32.7398, -117.1349], status: 'available', wheelchair: true, seats: 6 },
  { id: 'r-engine-22', name: 'Engine 22', kind: 'engine', position: [32.7612, -117.1251], status: 'available', wheelchair: false, seats: 4 },
]

// Already moving when the dashboard opens, so the map is live from the start.
export const initialMission = { crewId: 'r-engine-22', facilityId: 'facility-103', label: 'Structure protection — Oak Grove Memory Care' }

// Fake fire: now, and two forecast stages spreading south-west with the wind.
export const fireStages: FireStage[] = [
  {
    label: '+2 h forecast',
    polygon: [[32.7628, -117.1032], [32.7641, -117.0975], [32.7559, -117.0958], [32.7489, -117.1031], [32.7478, -117.1121], [32.7536, -117.1158], [32.7598, -117.1112]],
  },
  {
    label: '+1 h forecast',
    polygon: [[32.7621, -117.1031], [32.7628, -117.0985], [32.7567, -117.0975], [32.7522, -117.1032], [32.7524, -117.1088], [32.7572, -117.1101]],
  },
  {
    label: 'Fire now',
    polygon: [[32.7612, -117.1036], [32.7617, -117.0995], [32.7575, -117.0989], [32.7553, -117.1028], [32.7571, -117.1062]],
  },
]

// Areas marked by emergency services, each with its own instruction for callers inside it.
export const initialZones: Zone[] = [
  {
    id: 'A',
    label: 'Zone A — Evacuate now',
    level: 'evacuate',
    polygon: [[32.7655, -117.1135], [32.7655, -117.0940], [32.7530, -117.0940], [32.7530, -117.1135]],
    instruction: 'Leave now. Head west on University Ave to the Westside Community Shelter. Do not use 30th St north of Upas.',
  },
  {
    id: 'B',
    label: 'Zone B — Evacuation warning',
    level: 'warning',
    polygon: [[32.7530, -117.1240], [32.7530, -117.0940], [32.7440, -117.0940], [32.7440, -117.1240]],
    instruction: 'Get ready to leave. Pack medications and documents. If you need help leaving, stay on the line so we can send a crew.',
  },
]

const minute = 60_000
const t0 = Date.now()

// Calls already in progress when the dashboard opens.
export const initialCalls: Call[] = [
  {
    id: 'call-1042',
    callerName: 'Robert Chen',
    phone: '555-0188',
    address: '3245 Ivy Ln',
    position: [32.7568, -117.1094],
    people: 2,
    situation: 'trapped',
    mobility: 'Wife uses a power wheelchair; car will not start',
    status: 'active',
    startedAt: t0 - 3 * minute,
  },
  {
    id: 'call-1039',
    callerName: 'Sunrise Assisted Living (front desk)',
    phone: '555-0101',
    address: '4010 Florida St',
    position: [32.75, -117.12],
    people: 14,
    situation: 'needs_help',
    mobility: '6 residents need wheelchair transport',
    status: 'active',
    startedAt: t0 - 6 * minute,
  },
]

export const initialLines: [string, 'caller' | 'agent' | 'system', string][] = [
  ['call-1039', 'agent', 'Emergency line. This is an automated assistant working with dispatch. What is your address?'],
  ['call-1039', 'caller', 'Sunrise Assisted Living, 4010 Florida Street. We have fourteen residents here.'],
  ['call-1039', 'agent', '4010 Florida Street, fourteen residents. Is that correct?'],
  ['call-1039', 'caller', 'Yes. Six of them need wheelchair transport. We only have one van.'],
  ['call-1039', 'system', 'Located in Zone B — Evacuation warning.'],
  ['call-1042', 'agent', 'Emergency line. This is an automated assistant working with dispatch. What is your address?'],
  ['call-1042', 'caller', '3245 Ivy Lane. There is smoke everywhere.'],
]

// Scripted events that play after the dashboard opens: [seconds after start, event].
export type Scripted =
  | { at: number; kind: 'line'; callId: string; speaker: 'caller' | 'agent' | 'system'; text: string }
  | { at: number; kind: 'call'; call: Omit<Call, 'startedAt'> }
  | { at: number; kind: 'status'; callId: string; status: Call['status'] }

export const script: Scripted[] = [
  { at: 2, kind: 'line', callId: 'call-1042', speaker: 'agent', text: '3245 Ivy Lane. How many people are with you, and can everyone walk?' },
  { at: 5, kind: 'line', callId: 'call-1042', speaker: 'caller', text: 'Just me and my wife. She uses a power wheelchair and our car will not start.' },
  { at: 7, kind: 'line', callId: 'call-1042', speaker: 'system', text: 'Located in Zone A — Evacuate now. Marked as trapped.' },
  { at: 9, kind: 'line', callId: 'call-1042', speaker: 'agent', text: 'Thank you. Stay inside near your front door. I am asking dispatch for a vehicle that can carry the wheelchair.' },
  { at: 10, kind: 'call', call: { id: 'call-1047', callerName: 'Aisha Johnson', phone: '555-0172', address: '3612 Upas St', position: [32.7547, -117.1121], people: 3, situation: 'can_leave', mobility: 'Two kids, has a car', status: 'active' } },
  { at: 11, kind: 'line', callId: 'call-1047', speaker: 'agent', text: 'Emergency line. This is an automated assistant working with dispatch. What is your address?' },
  { at: 13, kind: 'line', callId: 'call-1047', speaker: 'caller', text: '3612 Upas Street. I can see flames over the canyon. Do we need to leave?' },
  { at: 15, kind: 'line', callId: 'call-1047', speaker: 'system', text: 'Located in Zone A — Evacuate now.' },
  { at: 16, kind: 'line', callId: 'call-1039', speaker: 'agent', text: 'You are in an evacuation warning area. Please get residents ready to leave. I am flagging your six wheelchair transports to dispatch.' },
  { at: 18, kind: 'line', callId: 'call-1047', speaker: 'agent', text: 'Yes, leave now. Head west on University Avenue to the Westside Community Shelter. Do not use 30th Street north of Upas.' },
  { at: 20, kind: 'status', callId: 'call-1047', status: 'instructed' },
  { at: 21, kind: 'line', callId: 'call-1047', speaker: 'caller', text: 'West on University, got it. We are leaving now.' },
  { at: 23, kind: 'call', call: { id: 'call-1051', callerName: 'Linda Park', phone: '555-0129', address: '4155 Kansas St', position: [32.7486, -117.1103], people: 1, situation: 'needs_help', mobility: '82, lives alone, no car', status: 'active' } },
  { at: 24, kind: 'line', callId: 'call-1051', speaker: 'agent', text: 'Emergency line. This is an automated assistant working with dispatch. What is your address?' },
  { at: 26, kind: 'line', callId: 'call-1051', speaker: 'caller', text: '4155 Kansas Street. I got an alert on my phone but I do not drive anymore.' },
  { at: 28, kind: 'line', callId: 'call-1051', speaker: 'system', text: 'Located in Zone B — Evacuation warning.' },
  { at: 29, kind: 'line', callId: 'call-1051', speaker: 'agent', text: 'You are not in immediate danger, but please get ready. Is there someone who could pick you up?' },
  { at: 31, kind: 'status', callId: 'call-1047', status: 'resolved' },
  { at: 32, kind: 'line', callId: 'call-1051', speaker: 'caller', text: 'My son is in Chula Vista. Maybe an hour away.' },
]
