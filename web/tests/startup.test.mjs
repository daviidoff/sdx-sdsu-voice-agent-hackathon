import test from 'node:test';
import assert from 'node:assert/strict';
import {waitForStartup} from '../src/startup.ts';

test('a cancelled pending session rejects promptly and disposes a late connection', async()=>{
  let finish; let disposed=false;
  const pending=new Promise(resolve=>{finish=resolve;});
  const controller=new AbortController();
  const result=waitForStartup(pending,controller.signal,()=>{disposed=true;});
  controller.abort(new Error('Connection cancelled'));
  await assert.rejects(result,/Connection cancelled/);
  finish({}); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(disposed,true);
});
test('a completed connection is retained even if the controller is later aborted',async()=>{
  const controller=new AbortController();let disposed=false;
  assert.equal(await waitForStartup(Promise.resolve('session'),controller.signal,()=>{disposed=true;}),'session');
  controller.abort();assert.equal(disposed,false);
});
test('provider rejection is surfaced without waiting for the deadline',async()=>{
  await assert.rejects(waitForStartup(Promise.reject(new Error('Provider unavailable')),new AbortController().signal),/Provider unavailable/);
});
