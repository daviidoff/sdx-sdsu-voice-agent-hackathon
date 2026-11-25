import test from 'node:test';
import assert from 'node:assert/strict';
import {voiceContext} from '../src/voice-context.ts';

const call = {id: 'current', revision: 7, assessment: {location: 'San Diego International Airport', people_count: 2},
  instruction: {zone_id: 'airport-zone', version: 3, action: 'evacuate', text: 'Current published instruction'}};

test('a replayed operator zone selection cannot reinstate superseded guidance', () => {
  const event = {call_id: 'current', type: 'steering.queued', payload: {text: 'Selected guidance', instruction: {...call.instruction, version: 2}}};
  assert.equal(voiceContext(event, call), undefined);
  event.payload.instruction = call.instruction;
  assert.match(voiceContext(event, call), /Selected guidance/);
});

test('location correction forwards current facts instead of the old event payload', () => {
  const text = voiceContext({call_id: 'current', type: 'assessment.updated', payload: {location: 'The zoo'}}, call);
  assert.match(text, /San Diego International Airport/);
  assert.doesNotMatch(text, /The zoo/);
  assert.match(text, /Do not ask again/);
});

test('only current instruction is forwarded and it takes priority over intake', () => {
  assert.equal(voiceContext({call_id: 'current', type: 'instruction.updated', payload: {zone_id: 'airport-zone', version: 2}}, call), undefined);
  const text = voiceContext({call_id: 'current', type: 'instruction.updated', payload: {zone_id: 'airport-zone', version: 3}}, call);
  assert.match(text, /Current published instruction/);
  assert.match(text, /before returning to a pending intake question/);
});

test('cleared guidance is relayed, but late clear cannot override a new instruction', () => {
  const event = {call_id: 'current', type: 'instruction.updated', payload: null};
  assert.equal(voiceContext(event, call), undefined);
  assert.match(voiceContext(event, {...call, instruction: null}), /Previous location-specific guidance is cleared/);
});

test('old jobs and events from another call never enter voice context', () => {
  assert.equal(voiceContext({call_id: 'previous', type: 'steering.queued', payload: {text: 'Old caller'}}, call), undefined);
  assert.equal(voiceContext({call_id: 'current', type: 'job.completed', payload: {revision: 6}}, call), undefined);
  assert.match(voiceContext({call_id: 'current', type: 'job.completed', payload: {revision: 7, result: 'current'}}, call), /current/);
});

test('a background headcount request leaves the caller’s immediate help request first', () => {
  const event = {call_id: call.id, type: 'job.completed', payload: {revision: 7, result: {missing_fields: ['people_count']}}};
  const context = voiceContext(event, {...call, assessment: {can_evacuate: false}});
  assert.match(context, /operator planning/);
  assert.match(context, /current request first/);
  assert.match(context, /people_count/);
});

// Operator messages use the supported turn trigger but are never caller evidence.
import {operatorTurnMessage, OperatorTurnGuard} from '../src/voice-context.ts';

test('explicit steering requests a spoken operator turn and background facts do not', () => {
  const event={call_id:'current',type:'steering.queued',payload:{id:'operator-1',text:'Ask whether pets are present.'}};
  const text=operatorTurnMessage(event,call);
  assert.match(text,/OPERATOR CONTROL MESSAGE/);
  assert.match(text,/not caller speech/);
  assert.match(text,/immediate spoken response/);
  assert.match(text,/Ask whether pets are present/);
  assert.equal(operatorTurnMessage({...event,call_id:'other'},call),undefined);
  assert.equal(operatorTurnMessage({...event,type:'assessment.updated'},call),undefined);
});

test('operator echoes cannot enter caller transcript or unlock caller fact writes', () => {
  const guard=new OperatorTurnGuard();
  assert.equal(guard.canRecordCallerFacts(),true);
  guard.sentMessage('operator envelope');
  assert.equal(guard.canRecordCallerFacts(),false);
  assert.equal(guard.callerMessage('operator envelope'),false);
  assert.equal(guard.canRecordCallerFacts(),false);
  assert.equal(guard.callerMessage('There are two of us'),true);
  assert.equal(guard.canRecordCallerFacts(),true);
  assert.equal(guard.callerMessage('operator envelope'),false);
  assert.equal(guard.canRecordCallerFacts(),true);
});
