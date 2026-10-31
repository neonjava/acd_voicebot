import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  AudioChunkMetadata,
  ErrorEnvelope,
  EventEnvelope,
  MockSessionResponse,
  SimulatedPermissionState,
  TranscriptSegment,
} from './types/contracts';
import {
  SessionClient,
  HttpSessionClient,
  FixtureSessionClient,
} from './services/sessionClient';
import { TranscriptAccumulator } from './utils/transcriptAccumulator';
import { MockModeBanner } from './components/MockModeBanner';
import { PermissionControl } from './components/PermissionControl';
import { TranscriptTimeline } from './components/TranscriptTimeline';
import { AudioEventsSummary } from './components/AudioEventsSummary';
import { StatusAlert, AppErrorState, formatErrorToState } from './components/StatusAlert';

export type SessionUiState =
  | 'idle'
  | 'connecting'
  | 'active'
  | 'stopping'
  | 'completed'
  | 'failed';

export interface AppProps {
  customClient?: SessionClient;
}

export const App: React.FC<AppProps> = ({ customClient }) => {
  const [uiState, setUiState] = useState<SessionUiState>('idle');
  const [statusMessage, setStatusMessage] = useState<string | null>('Ready to start session.');
  const [error, setError] = useState<AppErrorState | null>(null);
  const [permission, setPermission] = useState<SimulatedPermissionState>('granted');
  const [clientMode, setClientMode] = useState<'http' | 'fixture'>('http');
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [audioEvents, setAudioEvents] = useState<EventEnvelope<AudioChunkMetadata>[]>([]);

  // Track active session token and abort controller to ignore late responses after Stop
  const currentSessionTokenRef = useRef<number>(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const getClient = useCallback((): SessionClient => {
    if (customClient) {
      return customClient;
    }
    if (clientMode === 'fixture') {
      return new FixtureSessionClient();
    }
    return new HttpSessionClient();
  }, [customClient, clientMode]);

  const handleStart = useCallback(async () => {
    // Clear prior session results and errors immediately
    setSegments([]);
    setAudioEvents([]);
    setSessionId(null);
    setError(null);

    // Enforce simulated microphone permissions without calling getUserMedia()
    if (permission === 'denied') {
      setError({
        type: 'permission',
        title: 'Microphone Permission Denied',
        message: 'Simulated microphone access is denied. Please switch to "Granted" or "Prompt" to proceed.',
        code: 'SIMULATED_MIC_DENIED',
      });
      setStatusMessage('Session start aborted: simulated microphone denied.');
      setUiState('failed');
      return;
    }

    if (permission === 'unavailable') {
      setError({
        type: 'permission',
        title: 'Microphone Hardware Unavailable',
        message: 'Simulated microphone hardware was not detected. Change permission state to test.',
        code: 'SIMULATED_MIC_UNAVAILABLE',
      });
      setStatusMessage('Session start aborted: microphone unavailable.');
      setUiState('failed');
      return;
    }

    // In 'prompt' state, simulate user granting access
    if (permission === 'prompt') {
      setStatusMessage('Simulated prompt: user allowed microphone access.');
    }

    // Increment session token to invalidate any previous runs
    const sessionToken = ++currentSessionTokenRef.current;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setUiState('connecting');
    setStatusMessage('Connecting to mock voicebot session...');

    try {
      const client = getClient();
      const response: MockSessionResponse = await client.startMockSession(abortController.signal);

      // Check if session was stopped or superseded while request was in-flight
      if (sessionToken !== currentSessionTokenRef.current) {
        // Late response received after Stop — strictly ignore it
        return;
      }

      setSessionId(response.session_id);
      setUiState('active');
      setStatusMessage(`Session ${response.session_id} active. Processing events...`);

      // Accumulate transcript events and check for transcript errors
      const accumulator = new TranscriptAccumulator(response.session_id);
      const audioChunks: EventEnvelope<AudioChunkMetadata>[] = [];
      let transcriptErrorEnvelope: ErrorEnvelope | null = null;

      for (const evt of response.events) {
        if (evt.event_type === 'transcript.segment') {
          accumulator.add(evt.payload as TranscriptSegment);
        } else if (evt.event_type === 'audio.chunk') {
          audioChunks.push(evt as EventEnvelope<AudioChunkMetadata>);
        } else if (evt.event_type === 'transcript.error') {
          transcriptErrorEnvelope = evt.payload as ErrorEnvelope;
        }
      }

      setSegments(accumulator.getSegments());
      setAudioEvents(audioChunks);

      // If transcript.error was received, surface it and report failure instead of success
      if (transcriptErrorEnvelope) {
        setError({
          type: 'backend',
          title: 'Transcript Error',
          message: transcriptErrorEnvelope.message_safe_for_user,
          code: transcriptErrorEnvelope.code,
          correlationId: transcriptErrorEnvelope.correlation_id,
          retryable: transcriptErrorEnvelope.retryable,
        });
        setUiState('failed');
        setStatusMessage(`Session transcription failed: ${transcriptErrorEnvelope.message_safe_for_user}`);
        return;
      }

      setUiState('completed');
      setStatusMessage(`Session ${response.session_id} completed successfully.`);
    } catch (err) {
      // If aborted or token no longer matches, ignore
      if (sessionToken !== currentSessionTokenRef.current) {
        return;
      }

      if (err instanceof DOMException && err.name === 'AbortError') {
        setStatusMessage('Session was stopped by user.');
        setUiState('idle');
        return;
      }

      const formatted = formatErrorToState(err);
      setError(formatted);
      setUiState('failed');
      setStatusMessage(`Session failed: ${formatted.message}`);
    }
  }, [permission, getClient]);

  const handleStop = useCallback(() => {
    // Invalidate the session token so in-flight requests are ignored
    currentSessionTokenRef.current++;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setUiState('idle');
    setStatusMessage('Session stopped by user. Late events ignored.');
  }, []);

  // Keyboard shortcut support (Alt+S for Start, Alt+X / Escape for Stop)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Escape stops active session
      if (e.key === 'Escape') {
        if (uiState === 'connecting' || uiState === 'active') {
          e.preventDefault();
          handleStop();
        }
        return;
      }

      // Alt+S triggers Start
      if (e.altKey && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        if (uiState !== 'connecting' && uiState !== 'active') {
          handleStart();
        }
        return;
      }

      // Alt+X triggers Stop
      if (e.altKey && (e.key === 'x' || e.key === 'X')) {
        e.preventDefault();
        if (uiState === 'connecting' || uiState === 'active') {
          handleStop();
        }
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [uiState, handleStart, handleStop]);

  const isStartDisabled = uiState === 'connecting' || uiState === 'active';
  const isStopDisabled = uiState !== 'connecting' && uiState !== 'active';

  return (
    <div
      className="voicebot-app"
      style={{
        maxWidth: '860px',
        margin: '0 auto',
        padding: '24px 16px',
        fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        color: '#212529',
      }}
    >
      <header style={{ marginBottom: '20px' }}>
        <h1 style={{ margin: '0 0 8px 0', fontSize: '1.75rem', fontWeight: 700 }}>
          Voicebot Console
        </h1>
        <p style={{ margin: 0, color: '#6c757d', fontSize: '0.95rem' }}>
          SDE 1 Voicebot mock session testing interface (Week 1).
        </p>
      </header>

      <main>
        {/* Banner */}
        <MockModeBanner />

        {/* Status Announcements & Alerts */}
        <StatusAlert
          statusMessage={statusMessage}
          error={error}
          onDismissError={() => setError(null)}
        />

        {/* Configuration & Controls */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '16px',
            marginBottom: '20px',
          }}
        >
          {/* Simulated Permission Control */}
          <PermissionControl
            permission={permission}
            onChange={(newPerm) => {
              setPermission(newPerm);
              setError(null);
            }}
            disabled={uiState === 'connecting' || uiState === 'active'}
          />

          {/* Client Mode Selector */}
          {!customClient && (
            <fieldset
              style={{
                border: '1px solid #ced4da',
                borderRadius: '6px',
                padding: '12px 16px',
                marginBottom: '20px',
              }}
            >
              <legend style={{ fontWeight: 600, padding: '0 6px', fontSize: '0.95rem' }}>
                Client Source
              </legend>
              <p style={{ margin: '0 0 10px 0', fontSize: '0.85rem', color: '#6c757d' }}>
                Toggle HTTP proxy (<code>/api/sessions/mock</code>) vs Fixture mode.
              </p>
              <div style={{ display: 'flex', gap: '16px' }}>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="client-mode"
                    value="http"
                    checked={clientMode === 'http'}
                    onChange={() => setClientMode('http')}
                    disabled={uiState === 'connecting' || uiState === 'active'}
                  />
                  <span>HTTP API (Vite proxy to :8000)</span>
                </label>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="client-mode"
                    value="fixture"
                    checked={clientMode === 'fixture'}
                    onChange={() => setClientMode('fixture')}
                    disabled={uiState === 'connecting' || uiState === 'active'}
                  />
                  <span>Synthetic Fixture</span>
                </label>
              </div>
            </fieldset>
          )}
        </div>

        {/* Action Controls */}
        <section
          aria-label="Session Controls"
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: '16px',
            padding: '16px',
            backgroundColor: '#f8f9fa',
            borderRadius: '6px',
            border: '1px solid #dee2e6',
          }}
        >
          <button
            type="button"
            data-testid="start-button"
            onClick={handleStart}
            disabled={isStartDisabled}
            aria-label="Start mock voicebot session"
            style={{
              padding: '10px 20px',
              fontSize: '1rem',
              fontWeight: 600,
              backgroundColor: isStartDisabled ? '#6c757d' : '#0d6efd',
              color: '#ffffff',
              border: 'none',
              borderRadius: '4px',
              cursor: isStartDisabled ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            {uiState === 'connecting' ? 'Connecting...' : 'Start Session'}
          </button>

          <button
            type="button"
            data-testid="stop-button"
            onClick={handleStop}
            disabled={isStopDisabled}
            aria-label="Stop mock voicebot session"
            style={{
              padding: '10px 20px',
              fontSize: '1rem',
              fontWeight: 600,
              backgroundColor: isStopDisabled ? '#e9ecef' : '#dc3545',
              color: isStopDisabled ? '#adb5bd' : '#ffffff',
              border: 'none',
              borderRadius: '4px',
              cursor: isStopDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            Stop Session
          </button>

          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span
              data-testid="ui-state-indicator"
              style={{
                fontSize: '0.85rem',
                padding: '4px 8px',
                borderRadius: '4px',
                backgroundColor:
                  uiState === 'completed'
                    ? '#d4edda'
                    : uiState === 'failed'
                    ? '#f8d7da'
                    : uiState === 'connecting' || uiState === 'active'
                    ? '#cce5ff'
                    : '#e2e3e5',
                color:
                  uiState === 'completed'
                    ? '#155724'
                    : uiState === 'failed'
                    ? '#721c24'
                    : uiState === 'connecting' || uiState === 'active'
                    ? '#004085'
                    : '#383d41',
                fontWeight: 600,
                textTransform: 'uppercase',
              }}
            >
              Status: {uiState}
            </span>
          </div>
        </section>

        {/* Keyboard accessibility hints */}
        <div style={{ marginTop: '8px', fontSize: '0.8rem', color: '#6c757d' }}>
          <span>Keyboard shortcuts: </span>
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Alt+S</kbd> Start |{' '}
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Alt+X</kbd> or{' '}
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Esc</kbd> Stop
        </div>

        {/* Active Session Info */}
        {sessionId && (
          <div style={{ marginTop: '16px', fontSize: '0.85rem', color: '#495057' }}>
            Session ID: <code>{sessionId}</code>
          </div>
        )}

        {/* Ordered Transcript Timeline */}
        <TranscriptTimeline segments={segments} />

        {/* Audio Events Summary */}
        <AudioEventsSummary events={audioEvents} />
      </main>
    </div>
  );
};

export default App;
