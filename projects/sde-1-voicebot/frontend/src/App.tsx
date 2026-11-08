import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  AudioChunkMetadata,
  ErrorEnvelope,
  EventEnvelope,
  MockSessionResponse,
  SessionLifecycleState,
  SimulatedPermissionState,
  TranscriptSegment,
} from './types/contracts';
import {
  SessionClient,
  HttpSessionClient,
  FixtureSessionClient,
} from './services/sessionClient';
import { baselineSessionResponse, week2StreamingSessionResponse } from './fixtures/baselineSession';
import { TranscriptAccumulator } from './utils/transcriptAccumulator';
import { MockModeBanner } from './components/MockModeBanner';
import { PermissionControl } from './components/PermissionControl';
import { TranscriptTimeline } from './components/TranscriptTimeline';
import { AudioEventsSummary } from './components/AudioEventsSummary';
import { ScreenContextPanel } from './components/ScreenContextPanel';
import { StatusAlert, AppErrorState, formatErrorToState } from './components/StatusAlert';

export type SessionUiState =
  | 'idle'
  | 'connecting'
  | 'active'
  | 'paused'
  | 'stopping'
  | 'completed'
  | 'failed'
  | 'expired';

export type ClientSourceMode = 'http' | 'fixture-week2' | 'fixture-canonical';

export interface AppProps {
  customClient?: SessionClient;
}

export const App: React.FC<AppProps> = ({ customClient }) => {
  const [uiState, setUiState] = useState<SessionUiState>('idle');
  const [statusMessage, setStatusMessage] = useState<string | null>('Ready to start session.');
  const [error, setError] = useState<AppErrorState | null>(null);
  const [permission, setPermission] = useState<SimulatedPermissionState>('granted');
  const [clientMode, setClientMode] = useState<ClientSourceMode>('http');
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Actual backend session-state indicator (never assumed or optimistically faked)
  const [backendSessionState, setBackendSessionState] = useState<SessionLifecycleState | null>(null);

  // Screen-context panel toggle: OFF by default
  const [screenContextEnabled, setScreenContextEnabled] = useState<boolean>(false);

  // Offline status tracking
  const [isOffline, setIsOffline] = useState<boolean>(
    typeof navigator !== 'undefined' ? !navigator.onLine : false
  );

  // In-flight pause/resume transition flag for accessible loading feedback
  const [isTransitioning, setIsTransitioning] = useState<boolean>(false);

  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [revisionCounts, setRevisionCounts] = useState<Map<string, number>>(new Map());
  const [audioEvents, setAudioEvents] = useState<EventEnvelope<AudioChunkMetadata>[]>([]);

  // Track active session token and abort controller to ignore late responses after Stop
  const currentSessionTokenRef = useRef<number>(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Stable client instances maintained across Start -> Pause -> Resume
  const defaultClientsRef = useRef<{
    http?: HttpSessionClient;
    'fixture-week2'?: FixtureSessionClient;
    'fixture-canonical'?: FixtureSessionClient;
  }>({});

  // Listen to browser online/offline events
  useEffect(() => {
    const handleOnline = () => {
      setIsOffline(false);
      setStatusMessage('Network connection restored.');
    };
    const handleOffline = () => {
      setIsOffline(true);
      setStatusMessage('Network is offline.');
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  const getClient = useCallback((): SessionClient => {
    if (customClient) {
      return customClient;
    }
    if (!defaultClientsRef.current[clientMode]) {
      if (clientMode === 'fixture-week2') {
        defaultClientsRef.current[clientMode] = new FixtureSessionClient(week2StreamingSessionResponse);
      } else if (clientMode === 'fixture-canonical') {
        defaultClientsRef.current[clientMode] = new FixtureSessionClient(baselineSessionResponse);
      } else {
        defaultClientsRef.current[clientMode] = new HttpSessionClient();
      }
    }
    return defaultClientsRef.current[clientMode]!;
  }, [customClient, clientMode]);

  const handleStart = useCallback(async () => {
    // Clear prior session results and errors immediately
    setSegments([]);
    setRevisionCounts(new Map());
    setAudioEvents([]);
    setSessionId(null);
    setBackendSessionState(null);
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
      setBackendSessionState(response.state);

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

      const revMap = new Map<string, number>();
      for (const seg of accumulator.getSegments()) {
        revMap.set(seg.segment_id, accumulator.getRevisionCount(seg.segment_id));
      }
      setRevisionCounts(revMap);
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

      // Map every backend lifecycle state explicitly; only 'completed' reports success
      const sid = response.session_id;
      switch (response.state) {
        case 'active':
          setUiState('active');
          setStatusMessage(`Session ${sid} active. Processing events...`);
          break;
        case 'paused':
          setUiState('paused');
          setStatusMessage(`Session ${sid} is paused. Resume to continue.`);
          break;
        case 'completed':
          setUiState('completed');
          setStatusMessage(`Session ${sid} completed successfully.`);
          break;
        case 'failed':
          setUiState('failed');
          setStatusMessage(`Session ${sid} failed on the backend. No results were completed.`);
          break;
        case 'expired':
          setUiState('expired');
          setStatusMessage(`Session ${sid} expired before it could complete. Start a new session.`);
          break;
        case 'stopping':
          setUiState('stopping');
          setStatusMessage(`Session ${sid} is stopping. It has not completed yet.`);
          break;
        case 'created':
          setUiState('idle');
          setStatusMessage(`Session ${sid} was created but has not started yet.`);
          break;
        default: {
          const unhandled: never = response.state;
          throw new Error(`Unhandled session state: ${String(unhandled)}`);
        }
      }
    } catch (err) {
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

  const handlePause = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    const client = getClient();
    if (!client.pauseSession) {
      setError({
        type: 'backend',
        title: 'Feature Not Available',
        message: 'Current client does not support pause control.',
        code: 'NOT_SUPPORTED',
      });
      return;
    }

    const requestToken = currentSessionTokenRef.current;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setIsTransitioning(true);
    setStatusMessage(`Requesting backend pause for session ${sessionId}...`);
    try {
      const verifiedState = await client.pauseSession(sessionId, abortController.signal);
      // Strictly ignore delayed responses if session was stopped or superseded
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      // Strictly update backend state only from verified return value
      setBackendSessionState(verifiedState);
      setUiState('paused');
      setStatusMessage(`Session ${sessionId} successfully paused.`);
      setError(null);
    } catch (err) {
      // Strictly ignore delayed error if session was stopped or superseded
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      // Do NOT optimistically update backend state
      const formatted = formatErrorToState(err);
      setError(formatted);
      setStatusMessage(`Pause request failed: ${formatted.message}`);
    } finally {
      if (requestToken === currentSessionTokenRef.current) {
        setIsTransitioning(false);
      }
    }
  }, [sessionId, getClient]);

  const handleResume = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    const client = getClient();
    if (!client.resumeSession) {
      setError({
        type: 'backend',
        title: 'Feature Not Available',
        message: 'Current client does not support resume control.',
        code: 'NOT_SUPPORTED',
      });
      return;
    }

    const requestToken = currentSessionTokenRef.current;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setIsTransitioning(true);
    setStatusMessage(`Requesting backend resume for session ${sessionId}...`);
    try {
      const verifiedState = await client.resumeSession(sessionId, abortController.signal);
      // Strictly ignore delayed responses if session was stopped or superseded
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      // Strictly update backend state only from verified return value
      setBackendSessionState(verifiedState);
      setUiState('active');
      setStatusMessage(`Session ${sessionId} successfully resumed.`);
      setError(null);
    } catch (err) {
      // Strictly ignore delayed error if session was stopped or superseded
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      // Do NOT optimistically update backend state
      const formatted = formatErrorToState(err);
      setError(formatted);
      setStatusMessage(`Resume request failed: ${formatted.message}`);
    } finally {
      if (requestToken === currentSessionTokenRef.current) {
        setIsTransitioning(false);
      }
    }
  }, [sessionId, getClient]);

  const handleStop = useCallback(() => {
    // Invalidate the session token so in-flight requests (start, pause, resume) are ignored
    currentSessionTokenRef.current++;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // Do NOT show Backend: completed on local Stop — reset backend state on client abort
    setBackendSessionState(null);
    setUiState('idle');
    setIsTransitioning(false);
    setStatusMessage('Session stopped by user. Late events ignored.');
  }, []);

  // Keyboard shortcut support:
  // Alt+S: Start, Alt+P: Pause, Alt+R: Resume, Alt+X / Escape: Stop
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Escape stops active or paused session
      if (e.key === 'Escape') {
        if (uiState === 'connecting' || uiState === 'active' || uiState === 'paused') {
          e.preventDefault();
          handleStop();
        }
        return;
      }

      // Alt+S triggers Start
      if (e.altKey && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        if (uiState !== 'connecting' && uiState !== 'active' && uiState !== 'paused') {
          handleStart();
        }
        return;
      }

      // Alt+P triggers Pause
      if (e.altKey && (e.key === 'p' || e.key === 'P')) {
        e.preventDefault();
        if (backendSessionState === 'active' && !isTransitioning) {
          handlePause();
        }
        return;
      }

      // Alt+R triggers Resume
      if (e.altKey && (e.key === 'r' || e.key === 'R')) {
        e.preventDefault();
        if (backendSessionState === 'paused' && !isTransitioning) {
          handleResume();
        }
        return;
      }

      // Alt+X triggers Stop
      if (e.altKey && (e.key === 'x' || e.key === 'X')) {
        e.preventDefault();
        if (uiState === 'connecting' || uiState === 'active' || uiState === 'paused') {
          handleStop();
        }
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [uiState, backendSessionState, isTransitioning, handleStart, handlePause, handleResume, handleStop]);

  const isStartDisabled = uiState === 'connecting' || uiState === 'active' || uiState === 'paused';
  const isPauseDisabled = backendSessionState !== 'active' || isTransitioning;
  const isResumeDisabled = backendSessionState !== 'paused' || isTransitioning;
  const isStopDisabled =
    uiState !== 'connecting' &&
    uiState !== 'active' &&
    uiState !== 'paused';

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
          SDE 1 Voicebot mock session testing interface (Week 2).
        </p>
      </header>

      <main>
        {/* Banner */}
        <MockModeBanner />

        {/* Status Announcements, Loading Spinners & Alerts */}
        <StatusAlert
          statusMessage={statusMessage}
          error={error}
          isLoading={uiState === 'connecting' || isTransitioning}
          isOffline={isOffline}
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
            disabled={uiState === 'connecting' || uiState === 'active' || uiState === 'paused'}
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
                Select HTTP proxy (<code>/api/sessions/mock</code>) or Synthetic Fixtures.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="client-mode"
                    value="http"
                    checked={clientMode === 'http'}
                    onChange={() => setClientMode('http')}
                    disabled={uiState === 'connecting' || uiState === 'active' || uiState === 'paused'}
                  />
                  <span>HTTP API (Vite proxy to :8000)</span>
                </label>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="client-mode"
                    value="fixture-week2"
                    checked={clientMode === 'fixture-week2'}
                    onChange={() => setClientMode('fixture-week2')}
                    disabled={uiState === 'connecting' || uiState === 'active' || uiState === 'paused'}
                  />
                  <span>Synthetic Fixture (Week 2 Active Streaming)</span>
                </label>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="client-mode"
                    value="fixture-canonical"
                    checked={clientMode === 'fixture-canonical'}
                    onChange={() => setClientMode('fixture-canonical')}
                    disabled={uiState === 'connecting' || uiState === 'active' || uiState === 'paused'}
                  />
                  <span>Canonical Fixture (Week 1 Completed Run)</span>
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
            gap: '12px',
            padding: '16px',
            backgroundColor: '#f8f9fa',
            borderRadius: '6px',
            border: '1px solid #dee2e6',
          }}
        >
          {/* Start Button */}
          <button
            type="button"
            data-testid="start-button"
            onClick={handleStart}
            disabled={isStartDisabled}
            aria-label="Start mock voicebot session"
            style={{
              padding: '10px 18px',
              fontSize: '0.95rem',
              fontWeight: 600,
              backgroundColor: isStartDisabled ? '#6c757d' : '#0d6efd',
              color: '#ffffff',
              border: 'none',
              borderRadius: '4px',
              cursor: isStartDisabled ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            {uiState === 'connecting' ? 'Connecting...' : 'Start Session'}
          </button>

          {/* Pause Button */}
          <button
            type="button"
            data-testid="pause-button"
            onClick={handlePause}
            disabled={isPauseDisabled}
            aria-label="Pause voicebot session"
            style={{
              padding: '10px 18px',
              fontSize: '0.95rem',
              fontWeight: 600,
              backgroundColor: isPauseDisabled ? '#e9ecef' : '#ffc107',
              color: isPauseDisabled ? '#adb5bd' : '#000000',
              border: 'none',
              borderRadius: '4px',
              cursor: isPauseDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            Pause
          </button>

          {/* Resume Button */}
          <button
            type="button"
            data-testid="resume-button"
            onClick={handleResume}
            disabled={isResumeDisabled}
            aria-label="Resume voicebot session"
            style={{
              padding: '10px 18px',
              fontSize: '0.95rem',
              fontWeight: 600,
              backgroundColor: isResumeDisabled ? '#e9ecef' : '#198754',
              color: isResumeDisabled ? '#adb5bd' : '#ffffff',
              border: 'none',
              borderRadius: '4px',
              cursor: isResumeDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            Resume
          </button>

          {/* Stop Button */}
          <button
            type="button"
            data-testid="stop-button"
            onClick={handleStop}
            disabled={isStopDisabled}
            aria-label="Stop mock voicebot session"
            style={{
              padding: '10px 18px',
              fontSize: '0.95rem',
              fontWeight: 600,
              backgroundColor: isStopDisabled ? '#e9ecef' : '#dc3545',
              color: isStopDisabled ? '#adb5bd' : '#ffffff',
              border: 'none',
              borderRadius: '4px',
              cursor: isStopDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            Stop
          </button>

          {/* Indicators container */}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {/* UI Client State Indicator */}
            <span
              data-testid="ui-state-indicator"
              style={{
                fontSize: '0.8rem',
                padding: '4px 8px',
                borderRadius: '4px',
                backgroundColor:
                  uiState === 'completed'
                    ? '#d4edda'
                    : uiState === 'failed' || uiState === 'expired'
                    ? '#f8d7da'
                    : uiState === 'connecting' || uiState === 'active'
                    ? '#cce5ff'
                    : uiState === 'paused'
                    ? '#fff3cd'
                    : '#e2e3e5',
                color:
                  uiState === 'completed'
                    ? '#155724'
                    : uiState === 'failed' || uiState === 'expired'
                    ? '#721c24'
                    : uiState === 'connecting' || uiState === 'active'
                    ? '#004085'
                    : uiState === 'paused'
                    ? '#856404'
                    : '#383d41',
                fontWeight: 600,
                textTransform: 'uppercase',
              }}
            >
              UI: {uiState}
            </span>

            {/* Actual Backend Session State Indicator */}
            <span
              data-testid="backend-state-indicator"
              style={{
                fontSize: '0.8rem',
                padding: '4px 8px',
                borderRadius: '4px',
                border: '1px solid #ced4da',
                backgroundColor:
                  backendSessionState === 'active'
                    ? '#d1e7dd'
                    : backendSessionState === 'paused'
                    ? '#fff3cd'
                    : backendSessionState === 'completed'
                    ? '#e2e3e5'
                    : backendSessionState === 'failed' || backendSessionState === 'expired'
                    ? '#f8d7da'
                    : '#ffffff',
                color:
                  backendSessionState === 'active'
                    ? '#0f5132'
                    : backendSessionState === 'paused'
                    ? '#664d03'
                    : backendSessionState === 'completed'
                    ? '#41464b'
                    : backendSessionState === 'failed' || backendSessionState === 'expired'
                    ? '#842029'
                    : '#6c757d',
                fontWeight: 600,
                textTransform: 'uppercase',
              }}
            >
              Backend: {backendSessionState ?? 'not_started'}
            </span>
          </div>
        </section>

        {/* Keyboard accessibility hints */}
        <div style={{ marginTop: '8px', fontSize: '0.8rem', color: '#6c757d' }}>
          <span>Keyboard shortcuts: </span>
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Alt+S</kbd> Start |{' '}
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Alt+P</kbd> Pause |{' '}
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Alt+R</kbd> Resume |{' '}
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Alt+X</kbd> or{' '}
          <kbd style={{ padding: '2px 5px', border: '1px solid #ced4da', borderRadius: '3px' }}>Esc</kbd> Stop
        </div>

        {/* Active Session Info */}
        {sessionId && (
          <div style={{ marginTop: '16px', fontSize: '0.85rem', color: '#495057' }}>
            Session ID: <code>{sessionId}</code>
          </div>
        )}

        {/* Screen-context Panel (OFF by default) */}
        <ScreenContextPanel
          enabled={screenContextEnabled}
          onToggle={setScreenContextEnabled}
          transcriptSegments={segments}
        />

        {/* Ordered Transcript Timeline */}
        <TranscriptTimeline
          segments={segments}
          isRevised={(id) => (revisionCounts.get(id) ?? 0) > 0}
          revisionCount={(id) => revisionCounts.get(id) ?? 0}
        />

        {/* Audio Events Summary */}
        <AudioEventsSummary events={audioEvents} />
      </main>
    </div>
  );
};

export default App;
