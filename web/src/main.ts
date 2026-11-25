import {type Conversation as VoiceSession} from '@elevenlabs/client';
import {waitForStartup} from './startup.ts';
import {voiceContext, operatorTurnMessage, OperatorTurnGuard} from './voice-context.ts';
import './style.css';
import {phoneShell, renderPhoneCall} from './phone-shell.tsx';
import {debugShell} from './debug-shell.tsx';
import {mountClinicPhone} from './clinic-call.ts';
type Config={voice_configured:boolean;daytona_configured:boolean};
type Entry={id?:string|number;role?:string;text?:string;message?:string;created_at?:string};
type CallEvent={id:string|number;call_id:string;type:string;payload:Record<string,unknown>|null;created_at:string};
type Instruction={zone_id:string;name?:string;action:string;text:string;version?:number};
type Call={id:string;status:string;mode:string;revision:number;created_at?:string;assessment:Record<string,unknown>;instruction?:Instruction|null;events?:CallEvent[];transcript?:Entry[]};
const debug=new URLSearchParams(location.search).get('debug')==='1',mode='elevenlabs',selected='dashboard';
let config:Config|undefined,call:Call|undefined,voice:VoiceSession|undefined,stream:EventSource|undefined;
let busy=false,booting=true,micMuted=false,audioMuted=false,voiceSpeaking=false,voiceState='Ready to call',streamState='Waiting for a call',error='',notice='';
let seen=new Set<string>(),delivered=new Set<string>(),pendingContext=new Map<string,CallEvent>(),refreshVersion=0,startup:AbortController|undefined,startupStage='',voiceRestartRequired=false,generation=0;
let operatorTurns = new OperatorTurnGuard();
let steeringPending = false, inspectorEndPending = false;
const channel=new BroadcastChannel('emergencyos-live-call');
const windowId=sessionStorage.getItem('emergencyos-window-id')??crypto.randomUUID(),expectedOwner=new URLSearchParams(location.search).get('owner');
sessionStorage.setItem('emergencyos-window-id',windowId);
const $=<T extends HTMLElement>(selector:string)=>document.querySelector<T>(selector)!;
const escape=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const waveIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10v4m4-7v10m5-14v18m5-14v10m4-7v4"/></svg>';
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
    voice.sendContextualUpdate(context);
    const operatorMessage=operatorTurnMessage(event,call);
    if(operatorMessage){
      // Explicit operator attribution; never persist the SDK's user-role echo as caller speech.
      operatorTurns.sentMessage(operatorMessage);
      voice.sendUserMessage(operatorMessage);
    }
    delivered.add(key);pendingContext.delete(key);
    const payload=event.payload??{};
    if(event.type==='steering.queued'&&payload.id)void api(`/api/calls/${call.id}/steering/${encodeURIComponent(String(payload.id))}/ack`,{status:operatorMessage?'response_requested':'context_delivered'}).catch(showError);
  }
}
function connectEvents(){stream?.close();if(!call)return;const bound=call.id;stream=new EventSource(`/api/calls/${bound}/events`);stream.onopen=()=>{streamState='Connected';renderStatus();void refresh().catch(showError);};stream.onerror=()=>{streamState='Reconnecting';renderStatus();};stream.onmessage=event=>{try{const incoming=JSON.parse(event.data)as CallEvent,key=String(incoming.id??event.lastEventId);if(call?.id!==bound||seen.has(key))return;seen.add(key);if(incoming.type==='call.ended'){const session=voice;voice=undefined;startup?.abort(new Error('The call was ended.'));stream?.close();streamState='Call ended';if(session)void session.endSession().catch(showError);void refresh().catch(showError);return;}if(!debug&&['assessment.updated','instruction.updated','job.completed','job.failed','steering.queued'].includes(incoming.type))pendingContext.set(key,incoming);void refresh().catch(showError);}catch(err){showError(err);}};}
function compactToolResult(result:Call){return {assessment:result.assessment,instruction:result.instruction,status:result.status,revision:result.revision};}
function transcript():Entry[]{return call?.transcript??(call?.events??[]).filter(e=>e.type==='transcript'&&e.payload).map(e=>({id:e.id,role:String(e.payload!.role),text:String(e.payload!.text??''),created_at:e.created_at}));}
function renderShell(){document.body.className=debug?'debug-page':'phone-page';if(!debug){$('#app').innerHTML=phoneShell({windowId});
$('#open-debug').onclick=e=>{const popup=window.open(`/?debug=1&owner=${windowId}`,'emergencyos-debug','popup=yes,width=1120,height=900');if(popup){e.preventDefault();popup.focus();}};$('#call-toggle').onclick=()=>{if(startup){startup.abort(new Error('Connection cancelled.'));return;}if(voiceRestartRequired){location.reload();return;}void(active()?endCall():startCall());};$('#mic-toggle').onclick=()=>{if(!voice)return;micMuted=!micMuted;voice.setMicMuted(micMuted);renderCall();};$('#audio-toggle').onclick=()=>{if(!voice)return;audioMuted=!audioMuted;voice.setVolume({volume:audioMuted?0:1});renderCall();};
}else{$('#app').innerHTML=debugShell();$('#steering-form').onsubmit=e=>{e.preventDefault();void sendSteering();};$('#end-call').onclick=()=>{void endCallFromInspector();};}renderCall();}
function renderCall(){if(!debug){
  const inCall = active(), ending = busy && !startup;
  renderPhoneCall({
    status: booting ? 'Checking voice availability…' : !config?.voice_configured ? 'Voice unavailable'
      : startup ? startupStage : ending ? 'Ending call…' : inCall ? (micMuted && !voiceSpeaking ? 'Microphone muted' : voiceState)
      : call ? 'Call ended' : 'Ready to call',
    label: startup ? 'Cancel' : voiceRestartRequired ? 'Reload' : inCall || ending ? 'End call' : 'Call 911 test line',
    disabled: ending || booting || !config?.voice_configured,
    phase: booting ? 'loading' : startup ? 'connecting' : ending ? 'ending' : inCall ? 'active' : 'idle',
    speaking: !!voice && voiceSpeaking,
    audioReady: !!voice && !startup && !ending,
    micMuted,
    speakerMuted: audioMuted,
  });
  $('#configuration-note').textContent = !booting && !config?.voice_configured ? 'Configure an ElevenLabs agent to enable test calls.' : '';
}else{const rows=transcript(),facts=call?.assessment??{};$('#call-id').textContent=call?`Call ${call.id}`:'Start a voice call in the phone window.';$('#call-status').textContent=call?.status??'';$<HTMLButtonElement>('#end-call').disabled=!active()||inspectorEndPending;$('#end-call').textContent=inspectorEndPending?'Ending…':'End call';$('#facts').hidden=!call;$('#facts-placeholder').hidden=!!call;$('#facts').innerHTML=call?[['Current location',facts.location],['Can evacuate',facts.can_evacuate===true?'Yes':facts.can_evacuate===false?'Needs assistance':null],['People',facts.people_count],['Mobility needs',facts.mobility_needs],['Wheelchair users',facts.wheelchair_users],['Transport',facts.transport_needed===true?'Requested':facts.transport_needed===false?'Not needed':null]].map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value??'Not yet confirmed')}</dd></div>`).join(''):'';$('#instruction').innerHTML=call?.instruction?`<span class="instruction-label">${escape(call.instruction.action)} · Version ${escape(call.instruction.version??'—')}</span><p>${escape(call.instruction.text)}</p>`:'<p class="empty-copy">The caller’s location determines the applicable instruction.</p>';const log=$('#transcript'),bottom=log.scrollHeight-log.scrollTop-log.clientHeight<90;log.innerHTML=rows.length?rows.map(entry=>`<article class="message ${entry.role==='user'?'user':'agent'}"><div class="avatar">${entry.role==='user'?'Y':waveIcon}</div><div class="message-content"><div class="message-meta"><strong>${entry.role==='user'?'Caller':'EmergencyOS'}</strong><time>${entry.created_at?escape(new Date(entry.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})):''}</time></div><p>${escape(entry.text??entry.message)}</p></div></article>`).join(''):`<div class="empty-state">${waveIcon}<p>Messages appear here as the caller and agent speak.</p></div>`;if(bottom)log.scrollTop=log.scrollHeight;$<HTMLButtonElement>('#steering-form button').disabled=!active()||steeringPending;$('#steering-label').textContent=steeringPending?'Sending…':'Send';$<HTMLInputElement>('#steering').disabled=!active()||steeringPending;const steering=(call?.events??[]).filter(e=>e.type.startsWith('steering.')).at(-1);$('#steering-status').textContent=steering?steering.type==='steering.acknowledged'?(steering.payload?.status==='response_requested'?'Spoken response requested · caller hearing not confirmed':'Sent to voice context · spoken acknowledgment not confirmed'):'Steering queued for the phone window':'';const events=call?.events??[];$('#event-count').textContent=events.length?`${events.length} ${events.length === 1 ? 'event' : 'events'}`:'';$('#events').innerHTML=events.slice(-60).reverse().map(event=>`<div class="event"><time>${escape(new Date(event.created_at).toLocaleTimeString())}</time><strong>${escape(event.type)}</strong><pre>${escape(JSON.stringify(event.payload,null,2))}</pre></div>`).join('');renderJob();}renderStatus();}
function renderJob(){const jobs=(call?.events??[]).filter(event=>event.type.startsWith('job.'));const latest=jobs.filter(event=>event.payload?.revision===call?.revision).at(-1)??jobs.at(-1),container=$('#job-status');if(!latest){container.innerHTML='<p class="empty-copy">Protocol checks and assistance planning will appear here.</p>';return;}const payload=latest.payload??{},result=(payload.result??payload)as Record<string,unknown>,stale=payload.revision!==call?.revision;const titles:Record<string,string>={'job.started':'Checking protocols…','job.completed':'Protocol check complete','job.failed':'Protocol check failed','job.discarded':'Previous result superseded'};const names:Record<string,string>={people_count:'Confirm total group size',location:'Confirm current location',can_evacuate_or_transport_needed:'Confirm evacuation ability',wheelchair_users:'Confirm wheelchair user count'};const missing=Array.isArray(result.missing_fields)?result.missing_fields.map(value=>names[String(value)]??String(value).replaceAll('_',' ')).join(' · '):'';const candidate=result.proposed_candidate as Record<string,unknown>|undefined;container.innerHTML=`<div class="job-heading"><strong>${escape(stale?'Previous result · superseded':titles[latest.type]??latest.type)}</strong><span>${escape(result.provider==='daytona'?'Daytona':result.provider==='local-demo'?'Local simulation':'Worker')}</span></div>${!stale&&result.summary?`<p>${escape(result.summary)}</p>`:''}${!stale&&candidate?`<p class="proposal">Candidate only · ${escape(Array.isArray(candidate.vehicle_ids)?candidate.vehicle_ids.join(', '):'transport resource')} · ${escape(candidate.passenger_capacity)} seats · not dispatched</p>`:''}${!stale&&missing?`<p>Still needed: ${escape(missing)}</p>`:''}${latest.type==='job.failed'?`<p>${escape(payload.error??'Background check unavailable.')}</p>`:''}`;}
function renderStatus(){$('#notice').textContent=notice;$('#notice').hidden=!notice;$('#error').textContent=error;$('#error').hidden=!error;if(debug){const connection=$('#event-status');if(connection.textContent!==streamState)connection.textContent=streamState;$('#integrations').textContent=`ElevenLabs ${config?.voice_configured?'configured':'not configured'} · Daytona ${config?.daytona_configured?'configured':'local simulation'}`;}}
async function sendSteering() {
  const input = $<HTMLInputElement>('#steering'), message = input.value.trim();
  if (!message || !call || !active() || steeringPending) return;
  steeringPending = true;
  notice = error = '';
  renderCall();
  try {
    await api(`/api/calls/${call.id}/steering`, {text: message});
    input.value = '';
    notice = 'Steering queued for the live agent.';
    await refresh();
  } catch (err) {
    showError(err);
  } finally {
    steeringPending = false;
    renderCall();
  }
}
async function endCallFromInspector() {
  if (!call || !active() || inspectorEndPending) return;
  inspectorEndPending = true;
  notice = error = '';
  renderCall();
  try {
    await api(`/api/calls/${call.id}/end`, {});
    await refresh();
  } catch (err) {
    showError(err);
  } finally {
    inspectorEndPending = false;
    renderCall();
  }
}
async function startCall() {
  busy = true; error = ''; notice = ''; operatorTurns=new OperatorTurnGuard(); micMuted=false;audioMuted=false;voiceSpeaking=false;seen = new Set();delivered=new Set();pendingContext=new Map();
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
          if(message.role==='user'&&!operatorTurns.callerMessage(message.message))return;
          persistTranscript(message.role === 'user' ? 'user' : 'agent',message.message,message.event_id,message.response_id);
        },
        onAgentResponseCorrection: (correction:{corrected_agent_response:string;event_id:number;response_id?:string}) => {if(!attempt.signal.aborted&&generation===currentGeneration)persistTranscript('agent',correction.corrected_agent_response,correction.event_id,correction.response_id,true);},
        onModeChange: ({mode: voiceMode}:{mode:string}) => {if(attempt.signal.aborted||generation!==currentGeneration)return;voiceSpeaking = voiceMode === 'speaking'; voiceState = voiceSpeaking ? 'EmergencyOS is speaking' : 'Listening to you'; renderCall(); },
        onError: (message:string) => {if(!attempt.signal.aborted&&generation===currentGeneration)showError(message);},
        onDisconnect: () => {if(generation!==currentGeneration||call?.id!==boundCallId)return;voiceState = 'Voice disconnected'; voice = undefined; stream?.close(); streamState='Voice disconnected'; if (!busy && call?.id === boundCallId && active()) void api<Call>(`/api/calls/${boundCallId}/end`, {}).then(result => {call=result; renderCall();}).catch(showError); },
        clientTools: {
          message_operator: async (parameters: Record<string,unknown>) => {
            try { return JSON.stringify(await api(`/api/calls/${boundCallId}/operator-messages`, parameters)); }
            catch { return JSON.stringify({status:'unconfirmed',notice:'Could not confirm delivery to the operator. Do not say the message was sent or flagged. Retry with the same request_id.'}); }
          },
          check_operator_messages: async () => JSON.stringify(await api(`/api/calls/${boundCallId}/operator-messages`)),
          propose_location: async (parameters: Record<string,unknown>) => {
            await transcriptQueue;
            if(!operatorTurns.canRecordCallerFacts())return JSON.stringify({error:'An operator message is not a caller location report.'});
            const result = await api<Call & {pending_location?:string;reported_zone?:unknown}>(`/api/calls/${boundCallId}/location-proposal`, {location:parameters.location});
            return JSON.stringify({...compactToolResult(result),pending_location:result.pending_location,reported_zone:result.reported_zone});
          },
          confirm_location: async (parameters: Record<string,unknown>) => {
            await transcriptQueue;
            if(!operatorTurns.canRecordCallerFacts()&&parameters.location!==call?.assessment.location)return JSON.stringify({error:'Operator instructions are not a caller location confirmation. Ask the caller before changing location.'});
            const instruction = await api<Instruction>(`/api/calls/${boundCallId}/resolve`, {location: parameters.location});
            const followup = instruction.action === 'evacuate' && call?.assessment.can_evacuate == null
              ? 'Relay the published instruction first. If the caller has no more urgent concern and has not said whether they can leave, ask only whether they can leave on their own. Wait for their answer before asking about transport or headcount.'
              : undefined;
            return JSON.stringify({...instruction, followup});
          },
          update_assessment: async (parameters: Record<string,unknown>) => {
            if (!operatorTurns.canRecordCallerFacts()) {
              return JSON.stringify({error: 'No new caller-confirmed facts. Relay the operator message; do not record it as caller evidence.'});
            }
            const result = compactToolResult(await api<Call>(`/api/calls/${boundCallId}/assessment`, parameters));
            const followup = parameters.can_evacuate === false && result.assessment.transport_needed == null
              ? 'If the caller asked for assistance and the kind of help is still unknown, call message_operator with their request now. Wait for its receipt, then ask what help they need if they can continue. Leave transport unknown.'
              : undefined;
            return JSON.stringify({...result, followup});
          },
          request_assistance: async (parameters: Record<string,unknown>) => operatorTurns.canRecordCallerFacts()?JSON.stringify(compactToolResult(await api<Call>(`/api/calls/${boundCallId}/assessment`, {...parameters,transport_needed:true}))):JSON.stringify({error:'An operator message is not a new caller transport request.'}),
        },
      };
      stage('Connecting voice and audio…');sdkStarted=true;
      if (auth.signed_url) voice = await waitForStartup(Conversation.startSession({...options,signedUrl:auth.signed_url}),attempt.signal,session=>session.endSession());
      else if (auth.agent_id) voice = await waitForStartup(Conversation.startSession({...options,agentId:auth.agent_id}),attempt.signal,session=>session.endSession());
      else throw new Error('No ElevenLabs session credentials were returned.');
      if(selected==='dashboard') voice.sendContextualUpdate('Shared dashboard records, not caller speech. Preserve simulation labels and do not treat candidate routes as approved guidance: '+JSON.stringify(await api('/api/dashboard/context')));
      if (!voiceSpeaking) voiceState = 'Listening to you';
      flushContext();
    }
  } catch (err) {if(sdkStarted&&attempt.signal.aborted){voiceRestartRequired=true;notice='Reload before retrying voice to release any pending microphone or connection.';}showError(err);stream?.close();streamState='Not connected';const failedSession=voice;voice=undefined;if(failedSession){try{await failedSession.endSession();}catch{}}if (call && active()) { try {call=await api<Call>(`/api/calls/${call.id}/end`, {});} catch {} } }
  finally {if(deadline)clearTimeout(deadline);startup=undefined;busy=false; syncView();}
}
async function endCall() {
  busy=true; renderCall();
  try { const session=voice; voice=undefined; if(session) await session.endSession(); if(call) call=await api<Call>(`/api/calls/${call.id}/end`, {}); stream?.close(); streamState='Call ended';  }
  catch(err) {showError(err);} finally {busy=false; renderCall();}
}

const clinicId = new URLSearchParams(location.search).get('clinic');
if (clinicId !== null) {
  channel.close();
  void mountClinicPhone(clinicId);
} else {
renderShell();
void api<Config>('/api/config').then(c=>{config=c;}).catch(showError).finally(()=>{booting=false;renderCall();});
if(debug){
  channel.postMessage({type:'request.current'});
  if(!expectedOwner)void api<{calls:Call[]}|Call[]>('/api/calls').then(result=>{if(call)return;const calls=Array.isArray(result)?result:result.calls;const latest=calls.filter(item=>item.mode==='elevenlabs'&&item.status==='active').at(0);if(latest)void watchCall(latest.id).catch(showError);}).catch(showError);
}
window.addEventListener('beforeunload',()=>{if(!debug&&call&&active())navigator.sendBeacon(`/api/calls/${call.id}/end`,new Blob(['{}'],{type:'application/json'}));stream?.close();channel.close();if(!debug)void voice?.endSession();});

}
