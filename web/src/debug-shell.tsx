import { renderToStaticMarkup } from 'react-dom/server';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { VoiceIcon } from './phone-shell.tsx';

export function debugShell() {
  return renderToStaticMarkup(
    <div className="debug-shell">
      <header className="debug-header">
        <a href="/" target="emergencyos-phone" className="brand">EmergencyOS</a>
        <nav className="phone-nav" aria-label="Operator tools">
          <Button asChild variant="outline" className="nav-link">
            <a href="/dashboard/" target="emergencyos-dashboard">Dashboard</a>
          </Button>
        </nav>
      </header>
      <main>
        <div className="debug-intro">
          <div>
            <h1>Call inspector</h1>
            <p id="call-id">Start a voice call in the phone window.</p>
          </div>
          <Button id="end-call" variant="outline" className="end-call-button" disabled>End call</Button>
        </div>
        <div className="debug-grid">
          <Card className="panel transcript-panel">
            <div className="panel-heading">
              <h2>Live transcript</h2>
              <span id="event-status" role="status">Waiting for a call</span>
            </div>
            <div id="transcript" className="transcript" role="log" aria-live="polite" />
          </Card>
          <div className="context-column">
            <Card className="panel">
              <div className="panel-heading"><h2>Caller details</h2><span id="call-status" /></div>
              <p className="empty-copy" id="facts-placeholder">Caller details appear during a call.</p>
              <dl id="facts" className="facts" hidden />
            </Card>
            <Card className="panel">
              <div className="panel-heading"><h2>Current instruction</h2></div>
              <div id="instruction" />
            </Card>
            <Card className="panel">
              <div className="panel-heading"><h2>Background work</h2></div>
              <div id="job-status" />
            </Card>
          </div>
        </div>
        <Card className="panel steering-panel">
          <div>
            <h2>Steer the agent</h2>
            <p>Ask the agent to respond aloud during the call.</p>
          </div>
          <form id="steering-form">
            <label className="sr-only" htmlFor="steering">Operator steering</label>
            <Input id="steering" className="h-auto" placeholder="Ask whether anyone needs mobility assistance" autoComplete="off" />
            <Button type="submit" className="steering-submit" disabled>
              <span id="steering-label">Send</span>
              <VoiceIcon>
                <path d="M5 12h14m-6-6 6 6-6 6" />
              </VoiceIcon>
            </Button>
          </form>
          <div id="steering-status" />
        </Card>
        <details className="panel event-panel">
          <summary>Event log <span id="event-count" /></summary>
          <div id="events" />
        </details>
        <div id="notice" className="notice" role="status" hidden />
        <div id="error" className="error" role="alert" hidden />
        <footer id="integrations" />
      </main>
    </div>,
  );
}
