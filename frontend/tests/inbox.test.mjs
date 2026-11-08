import test from 'node:test'
import assert from 'node:assert/strict'
import { unreadMessages, replyStatus } from '../src/lib/inbox.ts'

test('read watermark cannot mark a later incoming question as read', () => {
  const call = { events: [
    { id: '2', type: 'operator.requested' },
    { id: '4', type: 'operator.requested' },
    { id: '5', type: 'operator.read', payload: { through_event_id: 2 } },
  ] }
  assert.equal(unreadMessages(call), 1)
  call.events.push({ id: '6', type: 'operator.read', payload: { through_event_id: 4 } })
  assert.equal(unreadMessages(call), 0)
})

test('reply status uses its own delivery receipt and never claims caller heard it', () => {
  const call = { status: 'active', events: [{ type: 'steering.acknowledged', payload: { event_id: '9' } }] }
  assert.match(replyStatus(call, '8'), /Queued/)
  assert.match(replyStatus(call, '9'), /caller hearing unconfirmed/)
  assert.match(replyStatus({ ...call, status: 'ended' }, '8'), /ended before context delivery/)
})
