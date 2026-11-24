import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  ApprovalRequest,
  AuditEvent,
  AudioChunkMetadata,
  BrowserActionEvent,
  CaptureOutcome,
  ErrorEnvelope,
  EventEnvelope,
  MascotState,
  MockSessionResponse,
  SessionLifecycleState,
  SimulatedPermissionState,
  TranscriptSegment,
  TurnResponse,
} from './types/contracts';
import {
  SessionClient,
  HttpSessionClient,
  FixtureSessionClient,
  EventStreamSubscription,
} from './services/sessionClient';
import {
  baselineApprovalRequest,
  baselineSessionResponse,
  week2StreamingSessionResponse,
  week3NotchSessionResponse,
} from './fixtures/baselineSession';
import { TranscriptAccumulator } from './utils/transcriptAccumulator';
import { MockModeBanner } from './components/MockModeBanner';
import { PermissionControl } from './components/PermissionControl';
import { TranscriptTimeline } from './components/TranscriptTimeline';
import { AudioEventsSummary } from './components/AudioEventsSummary';
import { ScreenContextPanel } from './components/ScreenContextPanel';
import { StatusAlert, AppErrorState, formatErrorToState } from './components/StatusAlert';
import { ApprovalDialog } from './components/ApprovalDialog';
import { WorkflowProgressPanel } from './components/WorkflowProgressPanel';
import { Mascot } from './components/Mascot';
import { SpeechBubble } from './components/SpeechBubble';

export type SessionUiState =
  | 'idle'
  | 'connecting'
  | 'active'
  | 'paused'
  | 'stopping'
  | 'completed'
  | 'failed'
  | 'expired';

export type ClientSourceMode = 'http' | 'fixture-week3' | 'fixture-week2' | 'fixture-canonical';

export interface AppProps {
  customClient?: SessionClient;
  initialExpanded?: boolean;
}

function getStatusColor(uiState: SessionUiState, backendState: SessionLifecycleState | null): string {
  if (uiState === 'failed') return '#ef4444';
  if (backendState === 'paused' || uiState === 'paused') return '#f59e0b';
  if (uiState === 'connecting' || uiState === 'stopping') return '#3b82f6';
  if (backendState === 'active' || uiState === 'active') return '#10b981';
  if (backendState === 'completed' || uiState === 'completed') return '#10b981';
  return '#94a3b8';
}

export const App: React.FC<AppProps> = ({ customClient, initialExpanded }) => {
  // Determine if running inside Electron desktop shell
  const isElectronApp = typeof window !== 'undefined' && Boolean(window.voicebot?.isElectron);

  // In Electron, default to collapsed notch unless initialExpanded is explicitly specified.
  // In tests and web browser, default to expanded so all controls are immediately active.
  const [isExpanded, setIsExpanded] = useState<boolean>(() => {
    if (initialExpanded !== undefined) return initialExpanded;
    return !isElectronApp;
  });

  // Track backend sidecar readiness before allowing the first start in Electron desktop app
  const [isBackendReady, setIsBackendReady] = useState<boolean>(() => {
    if (!isElectronApp) return true;
    return Boolean(window.voicebot?.isBackendReady?.());
  });

  const [uiState, setUiState] = useState<SessionUiState>('idle');
  const [statusMessage, setStatusMessage] = useState<string | null>(() => {
    if (isElectronApp && !Boolean(window.voicebot?.isBackendReady?.())) {
      return 'Waiting for backend service to become ready...';
    }
    return 'Ready to start session.';
  });
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

  // Week 3 Workflow & Approvals State
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);

  // Week 4 Companion & Mascot State
  const [mascotState, setMascotState] = useState<MascotState>('idle');
  const [userQuery, setUserQuery] = useState<string>('');
  const [turnResponse, setTurnResponse] = useState<TurnResponse | null>(null);
  const [stepActions, setStepActions] = useState<BrowserActionEvent[]>([]);
  const [inputText, setInputText] = useState<string>('');
  const [reducedMotion, setReducedMotion] = useState<boolean>(() => {
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    return false;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mql = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  // Track active session token, abort controller, and seen event IDs for deduplication
  const currentSessionTokenRef = useRef<number>(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const seenEventIdsRef = useRef<Set<string>>(new Set());
  const activeSubscriptionRef = useRef<EventStreamSubscription | null>(null);

  // Stable client instances maintained across Start -> Pause -> Resume
  const defaultClientsRef = useRef<{
    http?: HttpSessionClient;
    'fixture-week3'?: FixtureSessionClient;
    'fixture-week2'?: FixtureSessionClient;
    'fixture-canonical'?: FixtureSessionClient;
  }>({});

  const toggleExpanded = useCallback((force?: boolean) => {
    setIsExpanded((prev) => {
      const next = force !== undefined ? force : !prev;
      if (typeof window !== 'undefined' && window.voicebot?.setWindowExpanded) {
        window.voicebot.setWindowExpanded(next);
      }
      return next;
    });
  }, []);

  // A pending approval lives in the expanded notch: open it so the request is seen
  // (and its dialog is reachable by keyboard and screen readers) even when the
  // notch was collapsed when the approval arrived.
  // Expand once per new approval, so the user can still collapse the notch.
  const pendingApprovalId = pendingApproval?.approval_id ?? null;
  useEffect(() => {
    if (pendingApprovalId) {
      toggleExpanded(true);
    }
  }, [pendingApprovalId, toggleExpanded]);

  // Listen to backend readiness in Electron
  useEffect(() => {
    if (!isElectronApp) return;
    if (window.voicebot?.isBackendReady?.()) {
      setIsBackendReady(true);
      setStatusMessage('Backend service ready.');
      return;
    }
    if (window.voicebot?.onBackendReady) {
      const unsub = window.voicebot.onBackendReady(() => {
        setIsBackendReady(true);
        setStatusMessage('Backend service ready.');
      });
      return () => {
        if (unsub) unsub();
      };
    }
  }, [isElectronApp]);

  // Clean up active subscription on unmount
  useEffect(() => {
    return () => {
      if (activeSubscriptionRef.current) {
        activeSubscriptionRef.current.unsubscribe();
        activeSubscriptionRef.current = null;
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, []);

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
      if (clientMode === 'fixture-week3') {
        defaultClientsRef.current[clientMode] = new FixtureSessionClient(
          week3NotchSessionResponse,
          0,
          'active',
          [baselineApprovalRequest]
        );
      } else if (clientMode === 'fixture-week2') {
        defaultClientsRef.current[clientMode] = new FixtureSessionClient(week2StreamingSessionResponse);
      } else if (clientMode === 'fixture-canonical') {
        defaultClientsRef.current[clientMode] = new FixtureSessionClient(baselineSessionResponse);
      } else {
        defaultClientsRef.current[clientMode] = new HttpSessionClient();
      }
    }
    return defaultClientsRef.current[clientMode]!;
  }, [customClient, clientMode]);

  const handleTurnSubmit = useCallback(
    async (query: string) => {
      if (!query.trim()) return;
      const trimmed = query.trim();
      setUserQuery(trimmed);
      setMascotState('thinking');
      setStatusMessage(`Processing request: "${trimmed}"`);
      setError(null);

      const client = getClient();
      const currentSid = sessionId || 'session-demo';

      try {
        if (client.createTurn) {
          const response = await client.createTurn({
            text: trimmed,
            session_id: currentSid,
            context_enabled: screenContextEnabled,
          });
          setTurnResponse(response);

          if ('spoken_text' in response && response.spoken_text && client.synthesizeSpeech) {
            try {
              await client.synthesizeSpeech(response.spoken_text);
            } catch {
              // non-blocking
            }
          }

          if (response.kind === 'proposal') {
            if (response.requires_approval && response.approval_id) {
              setPendingApproval({
                approval_id: response.approval_id,
                plan_id: response.plan_id,
                step_id: response.steps[0]?.step_id || 'step-1',
                session_id: currentSid,
                status: 'pending',
              });
              setMascotState('idle');
              setStatusMessage('Proposal requires approval before execution.');
            } else {
              setMascotState('done');
              setStatusMessage('Plan proposed.');
            }
          } else if (response.kind === 'answer') {
            setMascotState('done');
            setStatusMessage(response.text);
            setTimeout(() => {
              setMascotState((curr) => (curr === 'done' ? 'idle' : curr));
            }, 2500);
          } else if (response.kind === 'clarify') {
            setMascotState('idle');
            setStatusMessage(response.question);
          } else if (response.kind === 'error') {
            setMascotState('idle');
            setError({
              type: 'backend',
              title: 'Request Failed',
              message: response.message,
              code: response.code || 'TURN_ERROR',
            });
            setStatusMessage(`Error: ${response.message}`);
          }
        } else {
          setMascotState('done');
          setTurnResponse({
            kind: 'answer',
            text: `Echo: "${trimmed}".`,
            session_id: currentSid,
          });
        }
      } catch (err) {
        setMascotState('idle');
        const formatted = formatErrorToState(err);
        setError(formatted);
        setStatusMessage(`Request error: ${formatted.message}`);
      }
    },
    [sessionId, screenContextEnabled, getClient]
  );

  const handleListenTrigger = useCallback(async () => {
    setMascotState('listening');
    setStatusMessage('Listening ("Hey Jarvis")...');
    const client = getClient();
    try {
      if (client.triggerListen) {
        const res = await client.triggerListen();
        if (res.wake_word_detected) {
          setStatusMessage('Wake word "Hey Jarvis" detected. Ready for your request.');
        }
      }
    } catch {
      // non-blocking
    }
  }, [getClient]);

  const handleStart = useCallback(async () => {
    // A previous session's live poller (for example one left after a failure) must
    // not keep running next to the new session's poller.
    if (activeSubscriptionRef.current) {
      activeSubscriptionRef.current.unsubscribe();
      activeSubscriptionRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // Clear prior session results, errors and audit progress immediately
    setSegments([]);
    setRevisionCounts(new Map());
    setAudioEvents([]);
    setAuditEvents([]);
    setPendingApproval(null);
    seenEventIdsRef.current.clear();
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
        return;
      }

      setSessionId(response.session_id);
      setBackendSessionState(response.state);

      // Accumulate transcript events and check for transcript errors
      const accumulator = new TranscriptAccumulator(response.session_id);
      const audioChunks: EventEnvelope<AudioChunkMetadata>[] = [];
      const audits: AuditEvent[] = [];
      let transcriptErrorEnvelope: ErrorEnvelope | null = null;

      for (const evt of response.events) {
        // Enforce deduplication
        if (seenEventIdsRef.current.has(evt.event_id)) {
          continue;
        }
        seenEventIdsRef.current.add(evt.event_id);

        if (evt.event_type === 'transcript.segment') {
          accumulator.add(evt.payload as TranscriptSegment);
        } else if (evt.event_type === 'audio.chunk') {
          audioChunks.push(evt as EventEnvelope<AudioChunkMetadata>);
        } else if (evt.event_type === 'workflow.audit') {
          audits.push(evt.payload as AuditEvent);
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
      setAuditEvents(audits);

      // Check for pending approvals
      if (client.getPendingApprovals) {
        try {
          const pending = await client.getPendingApprovals(response.session_id, abortController.signal);
          if (sessionToken === currentSessionTokenRef.current && pending.length > 0) {
            setPendingApproval(pending[0]);
          }
        } catch {
          // Non-blocking if approvals endpoint is not configured
        }
      }

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

      const sid = response.session_id;
      switch (response.state) {
        case 'active':
          setUiState('active');
          setStatusMessage(`Session ${sid} active. Processing events...`);
          // Live event stream subscription with capped exponential backoff and refresh approvals on audit events
          if (client.subscribeToEvents) {
            const sub = client.subscribeToEvents(
              response.session_id,
              {
                fromSequence: seenEventIdsRef.current.size,
                onEvents: (streamEventsList) => {
                  if (sessionToken !== currentSessionTokenRef.current) return;
                  let hasNewSegs = false;
                  let hasNewAuds = false;
                  let streamTranscriptError: ErrorEnvelope | null = null;
                  const newAuds: AuditEvent[] = [];
                  const newAudio: EventEnvelope<AudioChunkMetadata>[] = [];

                  for (const evt of streamEventsList) {
                    if (seenEventIdsRef.current.has(evt.event_id)) continue;
                    seenEventIdsRef.current.add(evt.event_id);

                    if (evt.event_type === 'transcript.segment') {
                      accumulator.add(evt.payload as TranscriptSegment);
                      hasNewSegs = true;
                    } else if (evt.event_type === 'audio.chunk') {
                      newAudio.push(evt as EventEnvelope<AudioChunkMetadata>);
                    } else if (evt.event_type === 'workflow.audit') {
                      newAuds.push(evt.payload as AuditEvent);
                      hasNewAuds = true;
                    } else if (evt.event_type === 'transcript.error') {
                      streamTranscriptError = evt.payload as ErrorEnvelope;
                    } else if (evt.event_type === 'browser.action') {
                      const action = evt.payload as BrowserActionEvent;
                      setStepActions((prev) => {
                        const idx = prev.findIndex((a) => a.action_id === action.action_id);
                        if (idx >= 0) {
                          const copy = [...prev];
                          copy[idx] = action;
                          return copy;
                        }
                        return [...prev, action];
                      });
                      if (action.status === 'running') {
                        setMascotState('working');
                      } else if (action.status === 'completed') {
                        setMascotState('done');
                      }
                    } else if (evt.event_type === 'audio.capture') {
                      const cap = evt.payload as CaptureOutcome;
                      if (cap.status === 'captured') {
                        // active frame captured
                      }
                    } else if (evt.event_type === 'assistant.turn') {
                      const turn = evt.payload as TurnResponse;
                      setTurnResponse(turn);
                      if (turn.kind === 'proposal' && turn.requires_approval && turn.approval_id) {
                        setPendingApproval({
                          approval_id: turn.approval_id,
                          plan_id: turn.plan_id,
                          step_id: turn.steps[0]?.step_id || 'step-1',
                          session_id: response.session_id,
                          status: 'pending',
                        });
                      }
                    }
                  }

                  if (streamTranscriptError) {
                    // The session failed: stop polling it.
                    activeSubscriptionRef.current?.unsubscribe();
                    activeSubscriptionRef.current = null;
                    setError({
                      type: 'backend',
                      title: 'Transcript Error',
                      message: streamTranscriptError.message_safe_for_user,
                      code: streamTranscriptError.code,
                      correlationId: streamTranscriptError.correlation_id,
                      retryable: streamTranscriptError.retryable,
                    });
                    setUiState('failed');
                    setStatusMessage(`Session transcription failed: ${streamTranscriptError.message_safe_for_user}`);
                    return;
                  }

                  if (hasNewSegs) {
                    const updatedSegs = accumulator.getSegments();
                    setSegments(updatedSegs);
                    const revMap = new Map<string, number>();
                    for (const s of updatedSegs) {
                      revMap.set(s.segment_id, accumulator.getRevisionCount(s.segment_id));
                    }
                    setRevisionCounts(revMap);
                  }
                  if (newAudio.length > 0) {
                    setAudioEvents((prev) => [...prev, ...newAudio]);
                  }
                  if (hasNewAuds && newAuds.length > 0) {
                    setAuditEvents((prev) => {
                      const next = [...prev];
                      for (const a of newAuds) {
                        const dup = next.some(
                          (existing) =>
                            (existing.approval_id && existing.approval_id === a.approval_id && existing.kind === a.kind) ||
                            (existing.sequence === a.sequence && existing.step_id === a.step_id && existing.kind === a.kind)
                        );
                        if (!dup) next.push(a);
                      }
                      return next;
                    });

                    // Refresh approvals when audit events arrive
                    if (client.getPendingApprovals) {
                      client.getPendingApprovals(response.session_id).then((pending) => {
                        if (sessionToken === currentSessionTokenRef.current && pending.length > 0) {
                          setPendingApproval(pending[0]);
                        }
                      }).catch(() => {});
                    }
                  }
                },
                onReconnect: (attempt, delayMs) => {
                  if (sessionToken !== currentSessionTokenRef.current) return;
                  setStatusMessage(`Connection lost. Reconnecting (attempt ${attempt}, retry in ${delayMs}ms)...`);
                },
                onStopped: (stopError) => {
                  if (sessionToken !== currentSessionTokenRef.current) return;
                  activeSubscriptionRef.current = null;
                  const formatted = formatErrorToState(stopError);
                  setError(formatted);
                  setUiState(formatted.code === 'SESSION_EXPIRED' ? 'expired' : 'failed');
                  setStatusMessage(`Live updates stopped: ${formatted.message}`);
                },
              },
              abortController.signal
            );
            activeSubscriptionRef.current = sub;
          }
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
          setStatusMessage(`Session ${sid} failed on the backend.`);
          break;
        case 'expired':
          setUiState('expired');
          setStatusMessage(`Session ${sid} expired before it could complete. Start a new session.`);
          break;
        case 'stopping':
          setUiState('stopping');
          setStatusMessage(`Session ${sid} is stopping. It has not completed yet; Start stays disabled until it ends.`);
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
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      setBackendSessionState(verifiedState);
      setUiState('paused');
      setStatusMessage(`Session ${sessionId} successfully paused.`);
      setError(null);
    } catch (err) {
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
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
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      setBackendSessionState(verifiedState);
      setUiState('active');
      setStatusMessage(`Session ${sessionId} successfully resumed.`);
      setError(null);
    } catch (err) {
      if (requestToken !== currentSessionTokenRef.current) {
        return;
      }
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
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
    currentSessionTokenRef.current++;

    if (activeSubscriptionRef.current) {
      activeSubscriptionRef.current.unsubscribe();
      activeSubscriptionRef.current = null;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setBackendSessionState(null);
    setPendingApproval(null);
    setUiState('idle');
    setIsTransitioning(false);
    setStatusMessage('Session stopped by user. Late events ignored.');
  }, []);

  // Replay missed events after a disconnect without duplicates, paginating until has_more is false
  const handleReconnect = useCallback(async () => {
    if (!sessionId) return;
    const client = getClient();
    if (!client.getEvents) return;

    const sessionToken = currentSessionTokenRef.current;
    setStatusMessage('Reconnecting to event stream...');
    try {
      let fromSequence = seenEventIdsRef.current.size;
      let hasMore = true;
      let transcriptErrorEnvelope: ErrorEnvelope | null = null;
      const newAudits: AuditEvent[] = [];
      const newAudioChunks: EventEnvelope<AudioChunkMetadata>[] = [];
      let hasNewSegments = false;

      const accumulator = new TranscriptAccumulator(sessionId);
      for (const seg of segments) {
        accumulator.add(seg);
      }

      while (hasMore) {
        const streamRes = await client.getEvents(sessionId, fromSequence);
        if (sessionToken !== currentSessionTokenRef.current) return;

        if (!streamRes.events || streamRes.events.length === 0) {
          break;
        }

        for (const evt of streamRes.events) {
          if (seenEventIdsRef.current.has(evt.event_id)) {
            // Strictly deduplicate missed / replayed events
            continue;
          }
          seenEventIdsRef.current.add(evt.event_id);

          if (evt.event_type === 'transcript.segment') {
            accumulator.add(evt.payload as TranscriptSegment);
            hasNewSegments = true;
          } else if (evt.event_type === 'audio.chunk') {
            newAudioChunks.push(evt as EventEnvelope<AudioChunkMetadata>);
          } else if (evt.event_type === 'workflow.audit') {
            newAudits.push(evt.payload as AuditEvent);
          } else if (evt.event_type === 'transcript.error') {
            transcriptErrorEnvelope = evt.payload as ErrorEnvelope;
          } else if (evt.event_type === 'browser.action') {
            const action = evt.payload as BrowserActionEvent;
            setStepActions((prev) => {
              const idx = prev.findIndex((a) => a.action_id === action.action_id);
              if (idx >= 0) {
                const copy = [...prev];
                copy[idx] = action;
                return copy;
              }
              return [...prev, action];
            });
            if (action.status === 'running') {
              setMascotState('working');
            } else if (action.status === 'completed') {
              setMascotState('done');
            }
          } else if (evt.event_type === 'assistant.turn') {
            const turn = evt.payload as TurnResponse;
            setTurnResponse(turn);
          }
        }

        fromSequence = streamRes.from_sequence + streamRes.events.length;
        hasMore = Boolean(streamRes.has_more);
      }

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

      if (hasNewSegments) {
        const updatedSegs = accumulator.getSegments();
        setSegments(updatedSegs);
        // Recompute revisionCounts from accumulator after replay
        const revMap = new Map<string, number>();
        for (const seg of updatedSegs) {
          revMap.set(seg.segment_id, accumulator.getRevisionCount(seg.segment_id));
        }
        setRevisionCounts(revMap);
      }
      if (newAudioChunks.length > 0) {
        setAudioEvents((prev) => [...prev, ...newAudioChunks]);
      }
      if (newAudits.length > 0) {
        setAuditEvents((prev) => {
          const next = [...prev];
          for (const na of newAudits) {
            const exists = next.some(
              (a) =>
                (a.approval_id && a.approval_id === na.approval_id && a.kind === na.kind) ||
                (a.step_id && a.step_id === na.step_id && a.kind === na.kind && a.sequence === na.sequence)
            );
            if (!exists) next.push(na);
          }
          return next;
        });

        // Refresh pending approvals if new audits arrived
        if (client.getPendingApprovals) {
          try {
            const pending = await client.getPendingApprovals(sessionId);
            if (sessionToken === currentSessionTokenRef.current && pending.length > 0) {
              setPendingApproval(pending[0]);
            }
          } catch {
            // non-blocking
          }
        }
      }

      setStatusMessage('Reconnected and replayed event stream with zero duplicates.');
    } catch (err) {
      if (sessionToken !== currentSessionTokenRef.current) return;
      const formatted = formatErrorToState(err);
      setError(formatted);
      setStatusMessage(`Reconnection failed: ${formatted.message}`);
    }
  }, [sessionId, segments, getClient]);

  const handleApprove = useCallback(
    async (approvalId: string) => {
      const sid = sessionId || 'session-demo';
      const requestSessionToken = currentSessionTokenRef.current;
      const client = getClient();
      if (!client.decideApproval) return;

      setMascotState('working');
      try {
        const updated = await client.decideApproval(sid, approvalId, 'approve');
        if (requestSessionToken !== currentSessionTokenRef.current) {
          return;
        }

        if (updated.status !== 'approved') {
          setError({
            type: 'backend',
            title: 'Approval Decision Mismatch',
            message: `Expected approval status 'approved' but received '${updated.status}'. Dialog kept open.`,
            code: 'STATUS_MISMATCH',
          });
          setMascotState('idle');
          return;
        }

        setPendingApproval(null);
        setStatusMessage(`Approval granted for step ${updated.step_id}.`);

        setMascotState('done');
        setTimeout(() => {
          setMascotState((c) => (c === 'done' ? 'idle' : c));
        }, 3000);

        // Do not mark a synthetic event ID as seen: the seen-set size is the replay
        // from_sequence, so a fake entry would skip one real event on reconnect.
        // A replayed decision event is de-duplicated by approval_id + kind below.
        setAuditEvents((prev) => {
          const exists = prev.some(
            (a) => a.approval_id === updated.approval_id && a.kind === 'approval_granted'
          );
          if (exists) return prev;
          return [
            ...prev,
            {
              sequence: prev.length,
              kind: 'approval_granted',
              plan_id: updated.plan_id,
              session_id: sid,
              step_id: updated.step_id,
              approval_id: updated.approval_id,
            },
          ];
        });
      } catch (err) {
        if (requestSessionToken !== currentSessionTokenRef.current) return;
        setMascotState('idle');
        const formatted = formatErrorToState(err);
        setError(formatted);
      }
    },
    [sessionId, getClient]
  );

  const handleReject = useCallback(
    async (approvalId: string) => {
      const sid = sessionId || 'session-demo';
      const requestSessionToken = currentSessionTokenRef.current;
      const client = getClient();
      if (!client.decideApproval) return;

      try {
        const updated = await client.decideApproval(sid, approvalId, 'reject');
        if (requestSessionToken !== currentSessionTokenRef.current) {
          return;
        }

        if (updated.status !== 'rejected') {
          setError({
            type: 'backend',
            title: 'Approval Rejection Mismatch',
            message: `Expected approval status 'rejected' but received '${updated.status}'. Dialog kept open.`,
            code: 'STATUS_MISMATCH',
          });
          return;
        }

        setPendingApproval(null);
        setMascotState('idle');
        setStatusMessage(`Approval rejected for step ${updated.step_id}. Step execution prevented.`);

        // See handleApprove: no synthetic seen IDs (they shift from_sequence).
        setAuditEvents((prev) => {
          const exists = prev.some(
            (a) => a.approval_id === updated.approval_id && a.kind === 'approval_rejected'
          );
          if (exists) return prev;
          return [
            ...prev,
            {
              sequence: prev.length,
              kind: 'approval_rejected',
              plan_id: updated.plan_id,
              session_id: sid,
              step_id: updated.step_id,
              approval_id: updated.approval_id,
            },
          ];
        });
      } catch (err) {
        if (requestSessionToken !== currentSessionTokenRef.current) return;
        const formatted = formatErrorToState(err);
        setError(formatted);
      }
    },
    [sessionId, getClient]
  );

  const isSessionInProgress =
    uiState === 'connecting' ||
    uiState === 'active' ||
    uiState === 'paused' ||
    uiState === 'stopping';

  // Keyboard shortcut support:
  // Alt+S: Start, Alt+P: Pause, Alt+R: Resume, Alt+X / Escape: Stop, Alt+N: Toggle Notch
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (isSessionInProgress) {
          e.preventDefault();
          handleStop();
        }
        return;
      }

      if (e.altKey && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault();
        toggleExpanded();
        return;
      }

      if (e.altKey && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        if (!isSessionInProgress) {
          handleStart();
        }
        return;
      }

      if (e.altKey && (e.key === 'p' || e.key === 'P')) {
        e.preventDefault();
        if (backendSessionState === 'active' && !isTransitioning) {
          handlePause();
        }
        return;
      }

      if (e.altKey && (e.key === 'r' || e.key === 'R')) {
        e.preventDefault();
        if (backendSessionState === 'paused' && !isTransitioning) {
          handleResume();
        }
        return;
      }

      if (e.altKey && (e.key === 'x' || e.key === 'X')) {
        e.preventDefault();
        if (isSessionInProgress) {
          handleStop();
        }
        return;
      }

      if (e.altKey && (e.key === 'l' || e.key === 'L')) {
        e.preventDefault();
        handleListenTrigger();
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    isSessionInProgress,
    backendSessionState,
    isTransitioning,
    handleStart,
    handlePause,
    handleResume,
    handleStop,
    toggleExpanded,
    handleListenTrigger,
  ]);

  const isStartDisabled = isSessionInProgress || (isElectronApp && !isBackendReady);
  const isPauseDisabled = backendSessionState !== 'active' || isTransitioning;
  const isResumeDisabled = backendSessionState !== 'paused' || isTransitioning;
  const isStopDisabled = !isSessionInProgress;

  // Latest caption text preview for collapsed notch
  const latestCaption = segments.length > 0 ? segments[segments.length - 1].text : null;

  return (
    <div
      className="voicebot-notch-root"
      style={{
        fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      {/* Collapsed Pill (Bottom-Right, 72×72 px) */}
      {!isExpanded && (
        <div
          data-testid="notch-pill"
          role="region"
          aria-label="Voicebot notch pill"
          title={latestCaption || `Jarvis Companion (${uiState})`}
          onClick={() => toggleExpanded(true)}
          style={{
            position: 'fixed',
            bottom: '16px',
            right: '16px',
            width: '72px',
            height: '72px',
            borderRadius: '50%',
            backgroundColor: '#090d16',
            border: `1px solid ${getStatusColor(uiState, backendSessionState)}`,
            boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            zIndex: 99999,
            color: '#f8fafc',
            userSelect: 'none',
            boxSizing: 'border-box',
          }}
        >
          <Mascot
            state={mascotState}
            reducedMotion={reducedMotion}
            size={52}
            onClick={() => toggleExpanded(true)}
          />
          {/* The expanded console's aria-live regions are unmounted while collapsed;
              keep status and errors announced from the pill. */}
          <span
            data-testid="notch-pill-live-status"
            role="status"
            aria-live="polite"
            style={{
              position: 'absolute',
              width: '1px',
              height: '1px',
              padding: 0,
              margin: '-1px',
              overflow: 'hidden',
              clip: 'rect(0, 0, 0, 0)',
              whiteSpace: 'nowrap',
              border: 0,
            }}
          >
            {error ? `${error.title}: ${error.message}` : statusMessage}
          </span>
          <button
            type="button"
            data-testid="notch-expand-button"
            aria-label="Expand notch"
            onClick={(e) => {
              e.stopPropagation();
              toggleExpanded(true);
            }}
            style={{
              position: 'absolute',
              bottom: '2px',
              right: '2px',
              background: 'rgba(15, 23, 42, 0.9)',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              borderRadius: '50%',
              color: '#38bdf8',
              cursor: 'pointer',
              padding: '2px',
              fontSize: '9px',
              lineHeight: 1,
            }}
            title="Expand companion (Alt+N)"
          >
            ▲
          </button>
        </div>
      )}

      {/* Expanded Companion Console (Max 380×320 px at Bottom-Right) */}
      {isExpanded && (
        <div
          data-testid="notch-expanded"
          role="region"
          aria-label="Voicebot notch console"
          style={{
            position: 'fixed',
            bottom: '16px',
            right: '16px',
            width: '100%',
            maxWidth: '380px',
            maxHeight: '320px',
            backgroundColor: '#090d16',
            border: '1px solid #334155',
            borderRadius: '16px',
            boxShadow: '0 12px 28px rgba(0, 0, 0, 0.75)',
            display: 'flex',
            flexDirection: 'column',
            overflowY: 'auto',
            zIndex: 99999,
            color: '#f8fafc',
            padding: '10px 12px',
            boxSizing: 'border-box',
          }}
        >
          {/* Header Row */}
          <header
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '6px',
              paddingBottom: '4px',
              borderBottom: '1px solid #1e293b',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Mascot state={mascotState} reducedMotion={reducedMotion} size={24} />
              <h2 style={{ margin: 0, fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>
                Jarvis Companion
              </h2>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <button
                type="button"
                data-testid="reconnect-button"
                onClick={handleReconnect}
                disabled={!sessionId}
                title="Reconnect and replay missed events"
                style={{
                  padding: '2px 6px',
                  fontSize: '10px',
                  backgroundColor: '#1e293b',
                  color: '#94a3b8',
                  border: '1px solid #334155',
                  borderRadius: '4px',
                  cursor: sessionId ? 'pointer' : 'not-allowed',
                }}
              >
                ↻ Reconnect
              </button>
              <button
                type="button"
                data-testid="notch-collapse-button"
                aria-label="Collapse notch"
                onClick={() => toggleExpanded(false)}
                style={{
                  background: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '4px',
                  color: '#94a3b8',
                  cursor: 'pointer',
                  padding: '2px 8px',
                  fontSize: '11px',
                }}
                title="Collapse companion (Alt+N)"
              >
                ▼
              </button>
            </div>
          </header>

          {/* Speech Bubble (User Query, Plan, Turn Response, Step Chips) */}
          <SpeechBubble
            userQuery={userQuery}
            turnResponse={turnResponse}
            stepActions={stepActions}
            pendingApproval={pendingApproval}
            onApprove={handleApprove}
            onReject={handleReject}
            isApproving={isTransitioning}
            reducedMotion={reducedMotion}
          />

          {/* Interactive Turn Input & Hey Jarvis Listen Trigger */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (inputText.trim()) {
                handleTurnSubmit(inputText);
                setInputText('');
              }
            }}
            style={{
              display: 'flex',
              gap: '6px',
              marginTop: '6px',
              marginBottom: '4px',
            }}
          >
            <input
              type="text"
              data-testid="turn-input"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="Type request or say 'hey jarvis'..."
              aria-label="Type request or say hey jarvis"
              style={{
                flex: 1,
                padding: '4px 8px',
                fontSize: '11px',
                borderRadius: '6px',
                background: '#0f172a',
                border: '1px solid #334155',
                color: '#f8fafc',
              }}
            />
            <button
              type="submit"
              data-testid="turn-submit"
              aria-label="Send request"
              style={{
                padding: '4px 10px',
                fontSize: '11px',
                borderRadius: '6px',
                background: '#0284c7',
                color: '#ffffff',
                border: 'none',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Send
            </button>
            <button
              type="button"
              data-testid="listen-button"
              aria-label="Listen (Hey Jarvis)"
              onClick={handleListenTrigger}
              title="Listen / Wake Word (Alt+L)"
              style={{
                padding: '4px 8px',
                fontSize: '11px',
                borderRadius: '6px',
                background: mascotState === 'listening' ? '#2563eb' : '#1e293b',
                color: '#38bdf8',
                border: '1px solid #38bdf8',
                cursor: 'pointer',
              }}
            >
              🎙️
            </button>
          </form>

          {/* Banner */}
          <MockModeBanner />

          {/* Status, Loading & Alerts */}
          <StatusAlert
            statusMessage={statusMessage}
            error={error}
            isLoading={uiState === 'connecting' || isTransitioning}
            isOffline={isOffline}
            onDismissError={() => setError(null)}
          />

          {/* Action Approval Dialog */}
          {pendingApproval && (
            <ApprovalDialog
              approval={pendingApproval}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          )}

          {/* Compact Control Buttons */}
          <div
            style={{
              display: 'flex',
              gap: '6px',
              flexWrap: 'wrap',
              margin: '8px 0',
            }}
          >
            <button
              type="button"
              data-testid="start-button"
              onClick={handleStart}
              disabled={isStartDisabled}
              title={isElectronApp && !isBackendReady ? 'Waiting for backend sidecar to be ready...' : undefined}
              aria-label="Start Session"
              style={{
                flex: 1,
                padding: '6px 10px',
                fontSize: '11px',
                fontWeight: 600,
                backgroundColor: isStartDisabled ? '#334155' : '#10b981',
                color: isStartDisabled ? '#64748b' : '#ffffff',
                border: 'none',
                borderRadius: '4px',
                cursor: isStartDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              Start
            </button>
            <button
              type="button"
              data-testid="pause-button"
              onClick={handlePause}
              disabled={isPauseDisabled}
              aria-label="Pause Session"
              style={{
                flex: 1,
                padding: '6px 10px',
                fontSize: '11px',
                fontWeight: 600,
                backgroundColor: isPauseDisabled ? '#334155' : '#f59e0b',
                color: isPauseDisabled ? '#64748b' : '#ffffff',
                border: 'none',
                borderRadius: '4px',
                cursor: isPauseDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              Pause
            </button>
            <button
              type="button"
              data-testid="resume-button"
              onClick={handleResume}
              disabled={isResumeDisabled}
              aria-label="Resume Session"
              style={{
                flex: 1,
                padding: '6px 10px',
                fontSize: '11px',
                fontWeight: 600,
                backgroundColor: isResumeDisabled ? '#334155' : '#3b82f6',
                color: isResumeDisabled ? '#64748b' : '#ffffff',
                border: 'none',
                borderRadius: '4px',
                cursor: isResumeDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              Resume
            </button>
            <button
              type="button"
              data-testid="stop-button"
              onClick={handleStop}
              disabled={isStopDisabled}
              aria-label="Stop Session"
              style={{
                flex: 1,
                padding: '6px 10px',
                fontSize: '11px',
                fontWeight: 600,
                backgroundColor: isStopDisabled ? '#334155' : '#ef4444',
                color: isStopDisabled ? '#64748b' : '#ffffff',
                border: 'none',
                borderRadius: '4px',
                cursor: isStopDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              Stop
            </button>
          </div>

          {/* Session State Indicators */}
          <div
            style={{
              display: 'flex',
              gap: '8px',
              padding: '4px 8px',
              backgroundColor: '#0f172a',
              borderRadius: '4px',
              fontSize: '10px',
              marginBottom: '8px',
              border: '1px solid #1e293b',
            }}
          >
            <span data-testid="ui-state-indicator" style={{ color: '#94a3b8' }}>
              UI: <strong style={{ color: '#e2e8f0' }}>{uiState}</strong>
            </span>
            <span style={{ color: '#334155' }}>|</span>
            <span data-testid="backend-state-indicator" style={{ color: '#94a3b8' }}>
              Backend:{' '}
              <strong style={{ color: backendSessionState ? '#38bdf8' : '#64748b' }}>
                {backendSessionState ?? 'not_started'}
              </strong>
            </span>
            {sessionId && (
              <>
                <span style={{ color: '#334155' }}>|</span>
                <span style={{ color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  ID: <code style={{ color: '#a78bfa' }}>{sessionId}</code>
                </span>
              </>
            )}
          </div>

          {/* Workflow Progress (workflow.audit events) */}
          <WorkflowProgressPanel auditEvents={auditEvents} />

          {/* Live Captions / Transcript Timeline */}
          <div style={{ margin: '6px 0' }}>
            <TranscriptTimeline
              segments={segments}
              isRevised={(id) => (revisionCounts.get(id) ?? 0) > 0}
              revisionCount={(id) => revisionCounts.get(id) ?? 0}
            />
          </div>

          {/* Privacy Settings / Screen-Context Panel (OFF by default) */}
          <ScreenContextPanel
            enabled={screenContextEnabled}
            onToggle={(enabled) => setScreenContextEnabled(enabled)}
            disabled={isSessionInProgress}
            transcriptSegments={segments}
          />

          {/* Audio Chunks Summary */}
          <div style={{ marginTop: '8px' }}>
            <AudioEventsSummary events={audioEvents} />
          </div>

          {/* Configuration controls */}
          <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <PermissionControl
              permission={permission}
              onChange={(newPerm) => {
                setPermission(newPerm);
                setError(null);
              }}
              disabled={isSessionInProgress}
            />

            {!customClient && (
              <fieldset
                style={{
                  border: '1px solid #334155',
                  borderRadius: '4px',
                  padding: '6px 8px',
                  backgroundColor: '#0f172a',
                  color: '#e2e8f0',
                  fontSize: '11px',
                }}
              >
                <legend style={{ fontWeight: 600, padding: '0 4px', fontSize: '10px', color: '#94a3b8' }}>
                  Client Source Mode
                </legend>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="clientMode"
                      value="http"
                      checked={clientMode === 'http'}
                      onChange={() => setClientMode('http')}
                      disabled={isSessionInProgress}
                    />
                    <span>Live Backend / Mock HTTP Proxy (/api/sessions/mock)</span>
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="clientMode"
                      value="fixture-week3"
                      checked={clientMode === 'fixture-week3'}
                      onChange={() => setClientMode('fixture-week3')}
                      disabled={isSessionInProgress}
                    />
                    <span>Synthetic Fixture (Week 3 Live Notch & Progress)</span>
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="clientMode"
                      value="fixture-week2"
                      checked={clientMode === 'fixture-week2'}
                      onChange={() => setClientMode('fixture-week2')}
                      disabled={isSessionInProgress}
                    />
                    <span>Synthetic Fixture (Week 2 Active Streaming)</span>
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="clientMode"
                      value="fixture-canonical"
                      checked={clientMode === 'fixture-canonical'}
                      onChange={() => setClientMode('fixture-canonical')}
                      disabled={isSessionInProgress}
                    />
                    <span>Synthetic Fixture (Canonical Backend)</span>
                  </label>
                </div>
              </fieldset>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
