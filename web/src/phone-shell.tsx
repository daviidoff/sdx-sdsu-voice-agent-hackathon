import type { ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Button } from '@/components/ui/button';

export function VoiceIcon({ children }: { children: ReactNode }) {
  return <svg className="size-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

/** Shared phone screen. The voice controllers own its live DOM state after mounting. */
export function phoneShell({ windowId = '', clinicName }: { windowId?: string; clinicName?: string } = {}) {
  const callLabel = clinicName ? 'Respond as clinic' : 'Call 911 test line';
  return renderToStaticMarkup(<>
    <header className="phone-header">
      <a className="brand" href="/">EmergencyOS</a>
      <nav className="phone-nav" aria-label="Operator tools">
        {!clinicName && <Button asChild variant="ghost" className="nav-link">
          <a id="open-debug" href={`/?debug=1&owner=${encodeURIComponent(windowId)}`} target="emergencyos-debug">Call inspector</a>
        </Button>}
        <Button asChild variant="outline" className="nav-link">
          <a href="/dashboard/" target="emergencyos-dashboard">Dashboard</a>
        </Button>
      </nav>
    </header>
    <main className="phone-stage">
      <section className="iphone" aria-labelledby="call-title">
        <div className="screen">
          <div className="call-heading">
            <h1 id="call-title">{clinicName || '911 test call'}</h1>
            <p className="phone-disclaimer">{clinicName ? 'Clinic role-play. No clinic is dialed.' : 'Browser demo. No emergency connection.'}</p>
          </div>
          <div className="call-feedback">
            <div className="voice-visual loading" id="voice-visual" aria-hidden="true">
              {Array.from({ length: 7 }, (_, index) => <span key={index} />)}
            </div>
            <p id="voice-state" role="status">{clinicName ? 'Loading clinic…' : 'Checking voice availability…'}</p>
          </div>
          <div className="call-actions">
            <Button id="call-toggle" type="button" className="call-button" disabled>
              <VoiceIcon><path d="M7 3H4a1 1 0 0 0-1 1c0 9.4 7.6 17 17 17a1 1 0 0 0 1-1v-3l-5-2-2 2a15 15 0 0 1-7-7l2-2-2-5Z" /></VoiceIcon>
              <span id="call-label">{callLabel}</span>
            </Button>
            <div className="call-controls">
              <Button id="mic-toggle" type="button" variant="secondary" className="audio-control" aria-label="Mute microphone" aria-pressed={false} disabled>
                <VoiceIcon><rect x="9" y="2" width="6" height="13" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" /></VoiceIcon>
                <span id="mic-label">Microphone</span>
              </Button>
              <Button id="audio-toggle" type="button" variant="secondary" className="audio-control" aria-label="Mute speaker" aria-pressed={false} disabled>
                <VoiceIcon><path d="m11 4-6 5H2v6h3l6 5V4Zm4 4a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" /></VoiceIcon>
                <span id="audio-label">Speaker</span>
              </Button>
            </div>
          </div>
        </div>
      </section>
      <div className="call-messages">
        <div id="notice" className="notice" role="status" hidden />
        <div id="error" className="error" role="alert" hidden />
        <p id="configuration-note" className="configuration-note" role="status" />
      </div>
    </main>
  </>);
}

type PhoneCallView = {
  status: string;
  label: string;
  disabled: boolean;
  phase: 'idle' | 'loading' | 'connecting' | 'active' | 'ending';
  speaking: boolean;
  audioReady: boolean;
  micMuted: boolean;
  speakerMuted: boolean;
};

export function renderPhoneCall(view: PhoneCallView) {
  const $ = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
  const status = $('#voice-state');
  if (status.textContent !== view.status) status.textContent = view.status;

  const visual = $('#voice-visual');
  visual.classList.toggle('loading', ['loading', 'connecting', 'ending'].includes(view.phase));
  visual.classList.toggle('active', view.phase === 'active');
  visual.classList.toggle('speaking', view.phase === 'active' && view.speaking && !view.speakerMuted);
  visual.classList.toggle('muted', view.micMuted && !view.speaking);

  const button = $<HTMLButtonElement>('#call-toggle');
  button.disabled = view.disabled;
  button.classList.toggle('end', view.phase === 'active' || view.phase === 'ending');
  $('#call-label').textContent = view.label;

  const microphone = $<HTMLButtonElement>('#mic-toggle');
  microphone.disabled = !view.audioReady;
  microphone.setAttribute('aria-pressed', String(view.micMuted));
  $('#mic-label').textContent = view.micMuted ? 'Mic muted' : 'Microphone';

  const speaker = $<HTMLButtonElement>('#audio-toggle');
  speaker.disabled = !view.audioReady;
  speaker.setAttribute('aria-pressed', String(view.speakerMuted));
  $('#audio-label').textContent = view.speakerMuted ? 'Speaker muted' : 'Speaker';
}
