import {type Conversation as VoiceSession} from '@elevenlabs/client';
import {waitForStartup} from './startup.ts';
import {voiceContext} from './voice-context.ts';
import './style.css';
type Config={voice_configured:boolean;daytona_configured:boolean};
type Entry={id?:string|number;role?:string;text?:string;message?:string;created_at?:string};
type CallEvent={id:string|number;call_id:string;type:string;payload:Record<string,unknown>|null;created_at:string};
type Instruction={zone_id:string;name?:string;action:string;text:string;version?:number};
type Call={id:string;status:string;mode:string;revision:number;created_at?:string;assessment:Record<string,unknown>;instruction?:Instruction|null;events?:CallEvent[];transcript?:Entry[]};
const debug=new URLSearchParams(location.search).get('debug')==='1',mode='elevenlabs',selected='dashboard';
let config:Config|undefined,call:Call|undefined,voice:VoiceSession|undefined,stream:EventSource|undefined;
let busy=false,booting=true,micMuted=false,audioMuted=false,voiceState='Ready to call',streamState='Waiting for a call',error='',notice='';
let seen=new Set<string>(),delivered=new Set<string>(),pendingContext=new Map<string,CallEvent>(),refreshVersion=0,startup:AbortController|undefined,startupStage='',voiceRestartRequired=false,generation=0;
const channel=new BroadcastChannel('emergencyos-live-call');
const windowId=sessionStorage.getItem('emergencyos-window-id')??crypto.randomUUID(),expectedOwner=new URLSearchParams(location.search).get('owner');
sessionStorage.setItem('emergencyos-window-id',windowId);
const $=<T extends HTMLElement>(selector:string)=>document.querySelector<T>(selector)!;
const escape=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const paths:Record<string,string>={phone:'<path d="M7 3H4a1 1 0 0 0-1 1c0 9.4 7.6 17 17 17a1 1 0 0 0 1-1v-3l-5-2-2 2a15 15 0 0 1-7-7l2-2-2-5Z"/>',mic:'<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',speaker:'<path d="m11 4-6 5H2v6h3l6 5V4Zm4 4a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',wave:'<path d="M3 10v4m4-7v10m5-14v18m5-14v10m4-7v4"/>',arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',window:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M8 9v11"/>',signal:'<path d="M4 17v3m5-7v7m5-11v11m5-15v15"/>',battery:'<rect x="2" y="7" width="18" height="10" rx="2"/><path d="M23 10v4"/><path d="M5 10h12v4H5z" fill="currentColor" stroke="none"/>'};
const svg=(name:string)=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]??''}</svg>`;
const active=()=>!!call&&!['ended','completed','failed'].includes(call.status);
async function api<T>(path:string,body?:unknown):Promise<T>{const response=await fetch(path,{signal:AbortSignal.timeout(15_000),headers:{'Content-Type':'application/json'},...(body===undefined?{}:{method:'POST',body:JSON.stringify(body)})});if(!response.ok){let message=`Request failed (${response.status})`;try{const data=await response.json();message=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail??data);}catch{}throw new Error(message);}return response.json();}
function showError(err:unknown){error=err instanceof Error?err.message:String(err);renderStatus();}
function announceCall(){if(!debug)channel.postMessage({type:'call.changed',owner:windowId,call_id:call?.id??null,status:call?.status,voice_state:voiceState});}
function syncView(){renderCall();announceCall();}
async function refresh(){if(!call)return;const id=call.id,version=++refreshVersion,snapshot=await api<Call>(`/api/calls/${id}`);if(call?.id===id&&version===refreshVersion){call=snapshot;syncView();flushContext();}}
async function watchCall(id:string){if(call?.id===id)return;const version=++refreshVersion;const next=await api<Call>(`/api/calls/${encodeURIComponent(id)}`);if(version!==refreshVersion)return;stream?.close();seen=new Set();call=next;renderCall();connectEvents();}
channel.onmessage=event=>{const data=event.data;if(data.type==='request.current'&&!debug)announceCall();if(data.type==='call.changed'&&debug&&data.call_id&&(!expectedOwner||data.owner===expectedOwner)&&(!active()||data.status==='active'||data.call_id===call?.id)){voiceState=data.voice_state??voiceState;void watchCall(String(data.call_id)).catch(showError);}};
function flushContext(){
  if(debug||!voice||!call||!active())return;
  for(const [key,event]of pendingContext){
    if(delivered.has(key)){pendingContext.delete(key);continue;}
    const context=voiceContext(event,call);
    if(!context){pendingContext.delete(key);continue;}
    // Context is deliberately not sent as a fabricated user utterance. ElevenLabs
    // uses it on the next conversational turn; the UI must not promise interruption.
    voice.sendContextualUpdate(context);
    delivered.add(key);pendingContext.delete(key);
    const payload=event.payload??{};
    if(event.type==='steering.queued'&&payload.id)void api(`/api/calls/${call.id}/steering/${encodeURIComponent(String(payload.id))}/ack`,{status:'context_delivered'}).catch(showError);
  }
}
function connectEvents(){stream?.close();if(!call)return;const bound=call.id;stream=new EventSource(`/api/calls/${bound}/events`);stream.onopen=()=>{streamState='Connected';renderStatus();void refresh().catch(showError);};stream.onerror=()=>{streamState='Reconnecting';renderStatus();};stream.onmessage=event=>{try{const incoming=JSON.parse(event.data)as CallEvent,key=String(incoming.id??event.lastEventId);if(call?.id!==bound||seen.has(key))return;seen.add(key);if(incoming.type==='call.ended'){const session=voice;voice=undefined;startup?.abort(new Error('The call was ended.'));stream?.close();streamState='Call ended';if(session)void session.endSession().catch(showError);void refresh().catch(showError);return;}if(!debug&&['assessment.updated','instruction.updated','job.completed','job.failed','steering.queued'].includes(incoming.type))pendingContext.set(key,incoming);void refresh().catch(showError);}catch(err){showError(err);}};}
function compactToolResult(result:Call){return {assessment:result.assessment,instruction:result.instruction,status:result.status,revision:result.revision};}
function transcript():Entry[]{return call?.transcript??(call?.events??[]).filter(e=>e.type==='transcript'&&e.payload).map(e=>({id:e.id,role:String(e.payload!.role),text:String(e.payload!.text??''),created_at:e.created_at}));}
function renderShell(){document.body.className=debug?'debug-page':'phone-page';if(!debug){$('#app').innerHTML=`<header class="phone-header"><a class="brand" href="/"><span>EmergencyOS</span></a><a id="open-debug" href="/?debug=1&owner=${windowId}" target="emergencyos-debug" class="debug-link">${svg('window')}<span>Open debug</span></a><a href="/dashboard/" target="emergencyos-dashboard" class="debug-link">Dashboard</a></header><main class="phone-stage"><section class="iphone" aria-label="911 test call"><div class="side-button left-one"></div><div class="side-button left-two"></div><div class="side-button right-one"></div><div class="screen"><div class="ios-status"><span id="clock">9:41</span><div class="island"></div><span class="status-icons">${svg('signal')}${svg('battery')}</span></div><div class="call-heading"><p id="voice-state">Ready to call</p><h1>911</h1><p class="call-name">Emergency Services</p></div><div class="voice-visual" id="voice-visual" aria-hidden="true">${'<span></span>'.repeat(9)}</div><div class="call-controls"><div><button id="mic-toggle" class="control-circle" aria-label="Mute microphone" aria-pressed="false">${svg('mic')}</button><span id="mic-label">mute</span></div><div><button id="audio-toggle" class="control-circle" aria-label="Mute speaker" aria-pressed="false">${svg('speaker')}</button><span id="audio-label">speaker</span></div></div><div class="primary-action"><button id="call-toggle" class="call-button" aria-label="Call 911 test line">${svg('phone')}</button><span id="call-label">Call</span></div><div class="phone-disclaimer"><span class="test-dot"></span>Test call · no emergency connection</div><div class="home-indicator"></div></div></section><div id="notice" class="notice" role="status" hidden></div><div id="error" class="error" role="alert" hidden></div><p id="configuration-note" class="configuration-note"></p></main>`;
$('#open-debug').onclick=e=>{const popup=window.open(`/?debug=1&owner=${windowId}`,'emergencyos-debug','popup=yes,width=1120,height=900');if(popup){e.preventDefault();popup.focus();}};$('#call-toggle').onclick=()=>{if(startup){startup.abort(new Error('Connection cancelled.'));return;}if(voiceRestartRequired){location.reload();return;}void(active()?endCall():startCall());};$('#mic-toggle').onclick=()=>{if(!voice)return;micMuted=!micMuted;voice.setMicMuted(micMuted);renderCall();};$('#audio-toggle').onclick=()=>{if(!voice)return;audioMuted=!audioMuted;voice.setVolume({volume:audioMuted?0:1});renderCall();};
}else{$('#app').innerHTML=`<div class="debug-shell"><header class="debug-header"><a href="/" target="emergencyos-phone" class="brand"><span>EmergencyOS</span></a><span class="debug-title">Live call inspector</span><span id="event-status" class="connection-status">Waiting for a call</span></header><main><div class="debug-intro"><div><p class="eyebrow">OPERATOR WORKSPACE</p><h1>Behind the conversation.</h1><p id="call-id">Start a voice call in the phone window.</p></div><button id="end-call" class="secondary-button">End active call</button></div><div class="debug-grid"><section class="panel transcript-panel"><div class="panel-heading"><h2>Live transcript</h2><span id="transcript-count">0 messages</span></div><div id="transcript" class="transcript" role="log" aria-live="polite"></div></section><div class="context-column"><section class="panel"><div class="panel-heading"><h2>Collected information</h2><span id="call-status">Standby</span></div><dl id="facts" class="facts"></dl></section><section class="panel"><div class="panel-heading"><h2>Current instruction</h2></div><div id="instruction"></div></section><section class="panel"><div class="panel-heading"><h2>Background work</h2></div><div id="job-status"></div></section></div></div><section class="panel steering-panel"><div><h2>Steer the agent</h2><p>Delivered as context. This does not confirm the caller heard it.</p></div><form id="steering-form"><label class="sr-only" for="steering">Operator steering</label><input id="steering" placeholder="Ask whether anyone needs mobility assistance" autocomplete="off"><button type="submit">Send context ${svg('arrow')}</button></form><div id="steering-status"></div></section><section class="panel"><h2>Dashboard instructions</h2><p>Manage zones and publish instructions in the dashboard. This inspector shows the instruction currently attached to the call.</p><a href="/dashboard/" target="emergencyos-dashboard" class="secondary-button">Open dashboard</a></section><details class="panel event-panel"><summary>Event log <span id="event-count">0 events</span></summary><div id="events"></div></details><div id="notice" class="notice" role="status" hidden></div><div id="error" class="error" role="alert" hidden></div><footer id="integrations"></footer></main></div>`;$('#steering-form').onsubmit=e=>{e.preventDefault();void sendSteering();};$('#end-call').onclick=()=>{if(call)void api(`/api/calls/${call.id}/end`,{}).then(refresh).catch(showError);};}renderCall();}
function renderCall(){if(!debug){$('#voice-state').textContent=startup?startupStage:busy?'Ending call…':active()?(micMuted?'Microphone muted':voiceState):call?'Call ended':'Ready to call';$('#voice-visual').classList.toggle('active',!!voice);$('#voice-visual').classList.toggle('muted',micMuted);const button=$<HTMLButtonElement>('#call-toggle');button.disabled=(busy&&!startup)||booting||!config?.voice_configured;button.classList.toggle('end',active()||!!startup);button.classList.toggle('connecting',!!startup);const label=startup?'Cancel':voiceRestartRequired?'Reload':busy?'Ending…':active()?'End call':'Call';button.setAttribute('aria-label',label==='Call'?'Call 911 test line':label);$('#call-label').textContent=label;$<HTMLButtonElement>('#mic-toggle').disabled=!voice;$<HTMLButtonElement>('#audio-toggle').disabled=!voice;$('#mic-toggle').setAttribute('aria-pressed',String(micMuted));$('#audio-toggle').setAttribute('aria-pressed',String(audioMuted));$('#mic-label').textContent=micMuted?'unmute':'mute';$('#audio-label').textContent=audioMuted?'unmute audio':'speaker';$('#configuration-note').textContent=booting?'Connecting…':!config?.voice_configured?'An ElevenLabs agent must be configured before calling.':'';
}else{const rows=transcript(),facts=call?.assessment??{};$('#call-id').textContent=call?`Call ${call.id}`:'Start a voice call in the phone window.';$('#call-status').textContent=call?.status??'Standby';$<HTMLButtonElement>('#end-call').disabled=!active();$('#facts').innerHTML=[['Current location',facts.location],['Can evacuate',facts.can_evacuate===true?'Yes':facts.can_evacuate===false?'Needs assistance':null],['People',facts.people_count],['Mobility needs',facts.mobility_needs],['Wheelchair users',facts.wheelchair_users],['Transport',facts.transport_needed===true?'Requested':facts.transport_needed===false?'Not needed':null]].map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value??'Not yet confirmed')}</dd></div>`).join('');$('#instruction').innerHTML=call?.instruction?`<span class="instruction-label">${escape(call.instruction.action)} · Version ${escape(call.instruction.version??'—')}</span><p>${escape(call.instruction.text)}</p>`:'<p class="empty-copy">The caller’s location determines the applicable instruction.</p>';const log=$('#transcript'),bottom=log.scrollHeight-log.scrollTop-log.clientHeight<90;log.innerHTML=rows.length?rows.map(entry=>`<article class="message ${entry.role==='user'?'user':'agent'}"><div class="avatar">${entry.role==='user'?'Y':svg('wave')}</div><div class="message-content"><div class="message-meta"><strong>${entry.role==='user'?'Caller':'EmergencyOS'}</strong><time>${entry.created_at?escape(new Date(entry.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})):''}</time></div><p>${escape(entry.text??entry.message)}</p></div></article>`).join(''):`<div class="empty-state">${svg('wave')}<h3>Waiting for a conversation</h3><p>The phone window owns the live microphone.<br>Transcripts and updates appear here.</p></div>`;if(bottom)log.scrollTop=log.scrollHeight;$('#transcript-count').textContent=`${rows.length} messages`;$<HTMLButtonElement>('#steering-form button').disabled=!active();$<HTMLInputElement>('#steering').disabled=!active();const steering=(call?.events??[]).filter(e=>e.type.startsWith('steering.')).at(-1);$('#steering-status').textContent=steering?steering.type==='steering.acknowledged'?'Sent to voice context · spoken acknowledgment not confirmed':'Steering queued for the phone window':'';const events=call?.events??[];$('#event-count').textContent=`${events.length} events`;$('#events').innerHTML=events.slice(-60).reverse().map(event=>`<div class="event"><time>${escape(new Date(event.created_at).toLocaleTimeString())}</time><strong>${escape(event.type)}</strong><pre>${escape(JSON.stringify(event.payload,null,2))}</pre></div>`).join('');renderJob();}renderStatus();}
function renderJob(){const jobs=(call?.events??[]).filter(event=>event.type.startsWith('job.'));const latest=jobs.filter(event=>event.payload?.revision===call?.revision).at(-1)??jobs.at(-1),container=$('#job-status');if(!latest){container.innerHTML='<p class="empty-copy">Protocol checks and assistance planning will appear here.</p>';return;}const payload=latest.payload??{},result=(payload.result??payload)as Record<string,unknown>,stale=payload.revision!==call?.revision;const titles:Record<string,string>={'job.started':'Checking protocols…','job.completed':'Protocol check complete','job.failed':'Protocol check failed','job.discarded':'Previous result superseded'};const names:Record<string,string>={people_count:'Confirm total group size',location:'Confirm current location',can_evacuate_or_transport_needed:'Confirm evacuation ability',wheelchair_users:'Confirm wheelchair user count'};const missing=Array.isArray(result.missing_fields)?result.missing_fields.map(value=>names[String(value)]??String(value).replaceAll('_',' ')).join(' · '):'';const candidate=result.proposed_candidate as Record<string,unknown>|undefined;container.innerHTML=`<div class="job-heading"><strong>${escape(stale?'Previous result · superseded':titles[latest.type]??latest.type)}</strong><span>${escape(result.provider==='daytona'?'Daytona':result.provider==='local-demo'?'Local simulation':'Worker')}</span></div>${!stale&&result.summary?`<p>${escape(result.summary)}</p>`:''}${!stale&&candidate?`<p class="proposal">Candidate only · ${escape(Array.isArray(candidate.vehicle_ids)?candidate.vehicle_ids.join(', '):'transport resource')} · ${escape(candidate.passenger_capacity)} seats · not dispatched</p>`:''}${!stale&&missing?`<p>Still needed: ${escape(missing)}</p>`:''}${latest.type==='job.failed'?`<p>${escape(payload.error??'Background check unavailable.')}</p>`:''}`;}
function renderStatus(){$('#notice').textContent=notice;$('#notice').hidden=!notice;$('#error').textContent=error;$('#error').hidden=!error;if(debug){$('#event-status').textContent=streamState;$('#integrations').textContent=`ElevenLabs ${config?.voice_configured?'configured':'not configured'} · Daytona ${config?.daytona_configured?'configured':'local simulation'}`;}else $('#clock').textContent=new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}).replace(/\s?[AP]M/i,'');}
async function sendSteering(){const input=$<HTMLInputElement>('#steering'),text=input.value.trim();if(!text||!call||!active())return;try{await api(`/api/calls/${call.id}/steering`,{text});input.value='';notice='Steering queued for the live agent.';await refresh();}catch(err){showError(err);}}
async function startCall() {
  busy = true; error = ''; notice = ''; micMuted=false;audioMuted=false;seen = new Set();delivered=new Set();pendingContext=new Map(); renderCall();
  const currentGeneration=++generation;const attempt = new AbortController(); let deadline: ReturnType<typeof setTimeout>|undefined, sdkStarted=false;
  const stage = (text:string) => {startupStage=text;renderCall();};
  if(mode==='elevenlabs')startup=attempt;
  try {
    if(mode==='elevenlabs'){
      stage('Allow microphone access');
      const microphone=await waitForStartup(navigator.mediaDevices.getUserMedia({audio:true}),attempt.signal,stream=>stream.getTracks().forEach(track=>track.stop()));
      microphone.getTracks().forEach(track=>track.stop());
      deadline=setTimeout(()=>attempt.abort(new Error('Voice connection timed out after 45 seconds.')),45_000);
      stage('Preparing the call…');
    }
    call = await waitForStartup(api<Call>('/api/calls', {mode,scenario_id:selected}),attempt.signal,async abandonedCall=>{await api(`/api/calls/${abandonedCall.id}/end`,{});}); announceCall(); connectEvents();
    if(attempt.signal.aborted)throw attempt.signal.reason;
    if (mode === 'elevenlabs') {
      const boundCallId = call.id;
      stage('Authorizing voice…');
      const auth = await waitForStartup(api<{signed_url?: string; agent_id?: string}>(`/api/voice/session?call_id=${encodeURIComponent(boundCallId)}`),attempt.signal);
      const { Conversation } = await waitForStartup(import('@elevenlabs/client'),attempt.signal);
      if(attempt.signal.aborted)throw attempt.signal.reason;
      const transcriptVersions = new Map<string,string>();
      let transcriptQueue = Promise.resolve();
      const persistTranscript = (role:string, text:string, eventId:number, responseId?:string, correction=false) => {
        const key = `${role}:${responseId ?? eventId}`;
        if(transcriptVersions.get(key)===text) return;
        const replace = correction || transcriptVersions.has(key); transcriptVersions.set(key,text);
        transcriptQueue = transcriptQueue.then(async()=>{await api(`/api/calls/${boundCallId}/transcript`,{role,text,segment_id:key,replace});await refresh();}).catch(showError);
      };
      const options = {
        connectionType: 'websocket' as const,
        dynamicVariables: {call_id:boundCallId},
        onMessage: (message: {message:string;role:string;event_id:number;response_id?:string}) => {
          if(attempt.signal.aborted||generation!==currentGeneration)return;
          persistTranscript(message.role === 'user' ? 'user' : 'agent',message.message,message.event_id,message.response_id);
        },
        onAgentResponseCorrection: (correction:{corrected_agent_response:string;event_id:number;response_id?:string}) => {if(!attempt.signal.aborted&&generation===currentGeneration)persistTranscript('agent',correction.corrected_agent_response,correction.event_id,correction.response_id,true);},
        onModeChange: ({mode: voiceMode}:{mode:string}) => {if(attempt.signal.aborted||generation!==currentGeneration)return;voiceState = voiceMode === 'speaking' ? 'EmergencyOS is speaking' : micMuted ? 'Microphone muted' : 'Listening to you'; renderCall(); },
        onError: (message:string) => {if(!attempt.signal.aborted&&generation===currentGeneration)showError(message);},
        onDisconnect: () => {if(generation!==currentGeneration||call?.id!==boundCallId)return;voiceState = 'Voice disconnected'; voice = undefined; stream?.close(); streamState='Voice disconnected'; if (!busy && call?.id === boundCallId && active()) void api<Call>(`/api/calls/${boundCallId}/end`, {}).then(result => {call=result; renderCall();}).catch(showError); },
        clientTools: {
          message_operator: async (parameters: Record<string,unknown>) => {
            try { return JSON.stringify(await api(`/api/calls/${boundCallId}/operator-messages`, parameters)); }
            catch { return JSON.stringify({status:'unconfirmed',notice:'Could not confirm delivery to the operator. Do not say the message was sent or flagged. Retry with the same request_id.'}); }
          },
          check_operator_messages: async () => JSON.stringify(await api(`/api/calls/${boundCallId}/operator-messages`)),
          confirm_location: async (parameters: Record<string,unknown>) => JSON.stringify(await api(`/api/calls/${boundCallId}/resolve`, {location:parameters.location})),
          update_assessment: async (parameters: Record<string,unknown>) => JSON.stringify(compactToolResult(await api<Call>(`/api/calls/${boundCallId}/assessment`, parameters))),
          request_assistance: async (parameters: Record<string,unknown>) => JSON.stringify(compactToolResult(await api<Call>(`/api/calls/${boundCallId}/assessment`, {...parameters,transport_needed:true}))),
        },
      };
      stage('Connecting voice and audio…');sdkStarted=true;
      if (auth.signed_url) voice = await waitForStartup(Conversation.startSession({...options,signedUrl:auth.signed_url}),attempt.signal,session=>session.endSession());
      else if (auth.agent_id) voice = await waitForStartup(Conversation.startSession({...options,agentId:auth.agent_id}),attempt.signal,session=>session.endSession());
      else throw new Error('No ElevenLabs session credentials were returned.');
      if(selected==='dashboard') voice.sendContextualUpdate('Shared dashboard records, not caller speech. Preserve simulation labels and do not treat candidate routes as approved guidance: '+JSON.stringify(await api('/api/dashboard/context')));
      voiceState = 'Listening to you';flushContext();
    }
  } catch (err) {if(sdkStarted&&attempt.signal.aborted){voiceRestartRequired=true;notice='Reload before retrying voice to release any pending microphone or connection.';}showError(err);stream?.close();streamState='Not connected';const failedSession=voice;voice=undefined;if(failedSession){try{await failedSession.endSession();}catch{}}if (call && active()) { try {call=await api<Call>(`/api/calls/${call.id}/end`, {});} catch {} } }
  finally {if(deadline)clearTimeout(deadline);startup=undefined;busy=false; syncView();}
}
async function endCall() {
  busy=true; renderCall();
  try { const session=voice; voice=undefined; if(session) await session.endSession(); if(call) call=await api<Call>(`/api/calls/${call.id}/end`, {}); stream?.close(); streamState='Call ended';  }
  catch(err) {showError(err);} finally {busy=false; renderCall();}
}

renderShell();
void api<Config>('/api/config').then(c=>{config=c;}).catch(showError).finally(()=>{booting=false;renderCall();});
if(debug){
  channel.postMessage({type:'request.current'});
  if(!expectedOwner)void api<{calls:Call[]}|Call[]>('/api/calls').then(result=>{if(call)return;const calls=Array.isArray(result)?result:result.calls;const latest=calls.filter(item=>item.mode==='elevenlabs'&&item.status==='active').at(0);if(latest)void watchCall(latest.id).catch(showError);}).catch(showError);
}else setInterval(renderStatus,30_000);
window.addEventListener('beforeunload',()=>{if(!debug&&call&&active())navigator.sendBeacon(`/api/calls/${call.id}/end`,new Blob(['{}'],{type:'application/json'}));stream?.close();channel.close();if(!debug)void voice?.endSession();});
