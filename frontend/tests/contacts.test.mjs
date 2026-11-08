import assert from 'node:assert/strict'
import test from 'node:test'
import { deliverReceiverMessage, sanDiegoFacility } from '../src/lib/contacts.ts'

test('receiver text is persisted before sending to the agent', async () => {
  const events = []
  await deliverReceiverMessage('  Two people need help  ', async (text) => { await Promise.resolve(); events.push(['saved', text]) }, (text) => events.push(['sent', text]))
  assert.deepEqual(events, [['saved', 'Two people need help'], ['sent', 'Two people need help']])
})
test('a failed transcript save prevents an unattributed agent turn', async () => {
  let sent = false
  await assert.rejects(deliverReceiverMessage('Need help', async () => { throw new Error('offline') }, () => { sent = true }))
  assert.equal(sent, false)
})
test('Berlin example contacts do not move the San Diego operational map', () => {
  assert.equal(sanDiegoFacility({ incidentId: 'berlin-arkonaplatz-discovery-test', position: [52.537,13.4] }), false)
  assert.equal(sanDiegoFacility({ incidentId: 'san-diego-demo', position: [32.74,-117.14] }), true)
})
