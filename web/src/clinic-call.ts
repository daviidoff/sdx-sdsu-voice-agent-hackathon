import type {Conversation as VoiceSession} from '@elevenlabs/client';
import {phoneShell, renderPhoneCall} from './phone-shell.tsx';
import {waitForStartup} from './startup.ts';

type Session = {id: string; status: string; facility_name: string};
type Clinic = {id: string; name: string; voice_configured: boolean};
const terminal = (status: string) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(status);

export async function mountClinicPhone(facilityId: string, loadVoice = () => import('@elevenlabs/client')) {
  const $ = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
  let clinic: Clinic | undefined, session: Session | undefined, voice: VoiceSession | undefined;
  let startup: AbortController | undefined, busy = false, muted = false, quiet = false, speaking = false;
  let loadingClinic = true;
  let state = 'Loading clinic…', error = '', owned = false, generation = 0, reloadRequired = false;
  let transcriptQueue: Promise<unknown> = Promise.resolve();
  let poll: ReturnType<typeof setInterval> | undefined;
  const prefix = (id: string) => `/api/contacts/sessions/${encodeURIComponent(id)}`;
  async function api<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(path, {signal: AbortSignal.timeout(15000), headers: {'Content-Type': 'application/json'},
      ...(body === undefined ? {} : {method: 'POST', body: JSON.stringify(body)})});
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    }
    return response.json();
  }
  function render() {
    $('#error').textContent = error; $('#error').hidden = !error;
    $('#configuration-note').textContent = !clinic ? '' : !clinic.voice_configured
      ? 'The clinic outreach agent needs configuration.' : 'Play the clinic receptionist. The dashboard shows the transcript and reported needs.';
    const ending = busy && !startup;
    renderPhoneCall({
      status: ending ? 'Ending call…' : voice && muted && !speaking ? 'Microphone muted' : state,
      label: startup ? 'Cancel' : reloadRequired ? 'Reload' : ending || voice ? 'End call' : 'Respond as clinic',
      disabled: !clinic?.voice_configured || ending,
      phase: loadingClinic ? 'loading' : startup ? 'connecting' : ending ? 'ending' : voice ? 'active' : 'idle',
      speaking,
      audioReady: !!voice && !startup && !ending,
      micMuted: muted,
      speakerMuted: quiet,
    });
  }
  const showError = (e: unknown) => {error = e instanceof Error ? e.message : String(e); render();};
  async function finish(status: 'completed' | 'failed' | 'cancelled' = 'completed') {
    if (busy && !startup) return;
    const closing = session, shouldEnd = owned;
    busy = true; ++generation; startup?.abort(new Error('Connection cancelled.')); clearInterval(poll);
    const closingVoice = voice; voice = undefined; render();
    try {
      await closingVoice?.endSession();
    } catch (e) {showError(e);}
    try {
      await transcriptQueue.catch(() => {});
      if (closing && shouldEnd) session = await api<Session>(prefix(closing.id) + '/end', {status});
    } catch (e) {showError(e);}
    finally {owned = false; busy = false; state = 'Call ended'; render();}
  }
  async function start() {
    if (busy || voice || !clinic) return;
    busy = true; error = ''; muted = false; quiet = false; speaking = false; session = undefined; owned = false;
    transcriptQueue = Promise.resolve();
    const attempt = new AbortController(), current = ++generation; startup = attempt;
    let deadline: ReturnType<typeof setTimeout> | undefined, sdkStarted = false;
    const stage = (value: string) => {state = value; render();};
    try {
      stage('Allow microphone access');
      const media = await waitForStartup(navigator.mediaDevices.getUserMedia({audio: true}), attempt.signal,
        late => late.getTracks().forEach(track => track.stop()));
      media.getTracks().forEach(track => track.stop());
      deadline = setTimeout(() => attempt.abort(new Error('Voice connection timed out.')), 45000);
      stage('Preparing clinic call…');
      session = await waitForStartup(api<Session>(`/api/contacts/${encodeURIComponent(facilityId)}/demo-call`, {}), attempt.signal);
      const id = session.id, path = prefix(id);
      // Ownership starts only after this tab successfully claims the voice session.
      // A second tab receiving a 409 must never end the first tab's conversation.
      const auth = await waitForStartup(api<{signed_url: string; dynamic_variables: Record<string, string>}>(path + '/voice', {}),
        attempt.signal, async () => {await api(path + '/end', {status: 'cancelled'});});
      owned = true;
      const {Conversation} = await waitForStartup(loadVoice(), attempt.signal);
      let readyResolve!: () => void;
      const ready = new Promise<void>(resolve => {readyResolve = resolve;});
      const persist = (role: string, text: string, key: string) => {
        if (generation !== current || attempt.signal.aborted) return;
        const pending = transcriptQueue.catch(() => {}).then(() => api(path + '/transcript', {id: key, role, text}));
        transcriptQueue = pending; void pending.catch(showError);
      };
      stage('Connecting outreach agent…'); sdkStarted = true;
      voice = await waitForStartup(Conversation.startSession({
        signedUrl: auth.signed_url, connectionType: 'websocket', dynamicVariables: auth.dynamic_variables,
        onMessage: (message: {role: string; message: string; event_id: number; response_id?: string}) => {
          const role = message.role === 'user' ? 'user' : 'agent';
          persist(role, message.message, `${role}:${message.response_id ?? message.event_id}`);
        },
        onAgentResponseCorrection: (message: {corrected_agent_response: string; event_id: number; response_id?: string}) => persist('agent', message.corrected_agent_response, `agent:${message.response_id ?? message.event_id}`),
        onModeChange: ({mode}) => {
          if (generation !== current || attempt.signal.aborted) return;
          speaking = mode === 'speaking';
          if (!startup) stage(speaking ? 'Outreach agent speaking' : 'Listening to the clinic');
        },
        onError: message => {if (generation === current) showError(message);},
        onDisconnect: () => {
          if (generation !== current || attempt.signal.aborted) return;
          if (startup) {attempt.abort(new Error('Voice disconnected while connecting.')); return;}
          void finish('completed');
        },
        clientTools: {
          get_clinic_context: async () => {
            try {return JSON.stringify(await api(path + '/context'));}
            catch {return JSON.stringify({error: 'Current guidance unavailable. Ask for coordinator review; do not invent instructions.'});}
          },
          record_contact_report: async parameters => {
            try {await waitForStartup(ready, attempt.signal); await transcriptQueue; return JSON.stringify(await api(path + '/report', parameters));}
            catch {return JSON.stringify({saved: false, instruction: 'Report not saved. Use an exact receiver quote and retry; do not claim success.'});}
          },
        },
      }), attempt.signal, late => late.endSession());
      session = await waitForStartup(api<Session>(path + '/connected', {}), attempt.signal);
      readyResolve(); stage(speaking ? 'Outreach agent speaking' : 'Listening to the clinic');
      let polling = false;
      poll = setInterval(() => {
        if (polling || generation !== current) return;
        polling = true;
        void api<Session>(path).then(latest => {
          if (generation === current && terminal(latest.status)) void finish('completed');
        }).catch(showError).finally(() => {polling = false;});
      }, 2000);
    } catch (e) {
      if (sdkStarted && attempt.signal.aborted) reloadRequired = true;
      attempt.abort(e);
      showError(e); state = 'Call not connected';
      ++generation;
      const failed = voice; voice = undefined;
      await failed?.endSession().catch(() => {});
      if (session && owned) await api(prefix(session.id) + '/end', {status: 'failed'}).catch(showError);
      owned = false;
    } finally {clearTimeout(deadline); startup = undefined; busy = false; render();}
  }
  function shell(name: string) {
    document.title = `${name} — Clinic outreach call`;
    document.body.className = 'phone-page clinic-phone';
    $('#app').innerHTML = phoneShell({clinicName: name});
    $('#call-toggle').onclick = () => {
      if (startup) {startup.abort(new Error('Connection cancelled.')); return;}
      if (reloadRequired) {location.reload(); return;}
      void (voice ? finish() : start());
    };
    $('#mic-toggle').onclick = () => {if (voice) {muted = !muted; voice.setMicMuted(muted); render();}};
    $('#audio-toggle').onclick = () => {if (voice) {quiet = !quiet; voice.setVolume({volume: quiet ? 0 : 1}); render();}};
    render();
  }
  shell('Clinic outreach');
  try {
    clinic = await api<Clinic>(`/api/contacts/${encodeURIComponent(facilityId)}/demo-call`);
    loadingClinic = false;
    state = clinic.voice_configured ? 'Incoming outreach call' : 'Voice unavailable';
    shell(clinic.name);
  } catch (e) {loadingClinic = false; state = 'Clinic unavailable'; showError(e);}
  window.addEventListener('beforeunload', () => {
    ++generation; startup?.abort(); clearInterval(poll);
    if (session && owned) navigator.sendBeacon(prefix(session.id) + '/end', new Blob([JSON.stringify({status: voice ? 'completed' : 'cancelled'})], {type: 'application/json'}));
    void voice?.endSession();
  });
}
