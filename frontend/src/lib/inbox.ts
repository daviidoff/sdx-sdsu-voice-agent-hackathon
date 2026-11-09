import type { BackendCall } from './feed'

export function inboxMessages(call: BackendCall) {
  return call.events.filter((e) => e.type === 'operator.requested' || e.type === 'steering.queued')
}

export function unreadMessages(call: BackendCall) {
  const through = Math.max(0, ...call.events.filter((e) => e.type === 'operator.read').map((e) => Number(e.payload?.through_event_id ?? 0)))
  return call.events.filter((e) => e.type === 'operator.requested' && Number(e.id) > through).length
}

export function replyStatus(call: BackendCall, eventId: string) {
  if (call.events.some((e) => e.type === 'steering.acknowledged' && e.payload?.event_id === eventId && e.payload?.status === 'response_requested')) return 'Immediate voice response requested · caller hearing unconfirmed'
  if (call.events.some((e) => e.type === 'steering.acknowledged' && e.payload?.event_id === eventId)) return 'Sent to agent context · caller hearing unconfirmed'
  return call.status === 'ended' ? 'Call ended before context delivery was confirmed' : 'Queued · awaiting voice connection'
}
