// Execute the actual browser context filter; don't duplicate its freshness policy.
import { pathToFileURL } from 'node:url';
const { voiceContext } = await import(process.env.EVAL_CONTEXT_MODULE
  ? pathToFileURL(process.env.EVAL_CONTEXT_MODULE).href
  : '../web/src/voice-context.ts');
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { events, call } = JSON.parse(input);
process.stdout.write(JSON.stringify(events.map(event => voiceContext(event, call) ?? null)));
