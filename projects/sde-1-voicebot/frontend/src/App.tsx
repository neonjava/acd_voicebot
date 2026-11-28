import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  ApprovalRequest,
  AuditEvent,
  AudioChunkMetadata,
  BrowserActionEventPayload,
  CaptureStatus,
  CompanionState,
  ErrorEnvelope,
  EventEnvelope,
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
import {
  validateBrowserActionEvent,
  validateCaptureStatus,
  validateTurnResponse,
} from './utils/validation';
import { MockModeBanner } from './components/MockModeBanner';
import { PermissionControl } from './components/PermissionControl';
import { TranscriptTimeline } from './components/TranscriptTimeline';
import { AudioEventsSummary } from './components/AudioEventsSummary';
import { ScreenContextPanel } from './components/ScreenContextPanel';
import { StatusAlert, AppErrorState, formatErrorToState } from './components/StatusAlert';
import { ApprovalDialog } from './components/ApprovalDialog';
import { WorkflowProgressPanel } from './components/WorkflowProgressPanel';
import { Mascot, STATE_LABELS } from './components/Mascot';
import { PlanDecision, SpeechBubble, turnErrorMessage } from './components/SpeechBubble';
import { StepChips } from './components/StepChips';

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

const SUGGESTIONS = ['What is using the most RAM?', 'Open YouTube and play lo-fi music'];

const CLIENT_MODES: [ClientSourceMode, string][] = [
  ['http', 'Live Backend / Mock HTTP Proxy (/api/sessions/mock)'],
  ['fixture-week3', 'Synthetic Fixture (Week 3 Live Notch & Progress)'],
  ['fixture-week2', 'Synthetic Fixture (Week 2 Active Streaming)'],
  ['fixture-canonical', 'Synthetic Fixture (Canonical Backend)'],
];

function siteName(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
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
  // `?demo` in a plain browser starts on the synthetic fixture (no backend needed).
  const [clientMode, setClientMode] = useState<ClientSourceMode>(() =>
    typeof window !== 'undefined' && !window.voicebot?.isElectron && /[?&]demo\b/.test(window.location.search)
      ? 'fixture-week3'
      : 'http'
  );
  const [sessionId, setSessionIdState] = useState<string | null>(null);

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
  const [mascotState, setMascotState] = useState<CompanionState>('idle');
  const [userQuery, setUserQuery] = useState<string>('');
  const [turnResponse, setTurnResponse] = useState<TurnResponse | null>(null);
  const [stepActions, setStepActions] = useState<BrowserActionEventPayload[]>([]);
  const [taskRunning, setTaskRunning] = useState<boolean>(false);
  const [captureStatus, setCaptureStatus] = useState<CaptureStatus | null>(null);
  const [inputText, setInputText] = useState<string>('');
  const [showDetails, setShowDetails] = useState<boolean>(false);
  const sessionIdRef = useRef<string | null>(null);
  const taskWatchRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const taskSeenRef = useRef<Set<string>>(new Set());
  const activePlanRef = useRef<string | null>(null);
  const proposalPlanRef = useRef<string | null>(null);
  const [planDecision, setPlanDecision] = useState<PlanDecision>('pending');
  const scrollRef = useRef<HTMLDivElement | null>(null);
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
        const demo = new FixtureSessionClient(week3NotchSessionResponse, 0, 'active', [baselineApprovalRequest]);
        demo.actionDelayMs = 700; // pace the mock browser steps so they can be followed
        defaultClientsRef.current[clientMode] = demo;
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

  // Keep a ref in step with the session id so async turn handlers see the latest one.
  const setSessionId = useCallback((sid: string | null) => {
    sessionIdRef.current = sid;
    setSessionIdState(sid);
  }, []);

  /** Week 4 events (docs/contracts.md): returns true when the running browser task ended. */
  const applyLiveEvent = useCallback((evt: EventEnvelope<unknown>): boolean => {
    try {
      if (evt.event_type === 'browser.action') {
        const item = validateBrowserActionEvent(evt.payload, evt.session_id);
        setStepActions((prev) => {
          const idx = prev.findIndex((a) => a.action.action_id === item.action.action_id);
          if (idx >= 0) {
            const copy = [...prev];
            copy[idx] = item;
            return copy;
          }
          return [...prev, item];
        });
        setMascotState(item.ok ? 'working' : 'error');
        return false;
      }
      if (evt.event_type === 'audio.capture') {
        const status = validateCaptureStatus(evt.payload, evt.session_id);
        setCaptureStatus(status);
        if (status.state === 'listening' || status.state === 'capturing') {
          setMascotState((cur) => (cur === 'idle' || cur === 'done' ? 'listening' : cur));
        } else {
          setMascotState((cur) => (cur === 'listening' ? 'idle' : cur));
        }
        return false;
      }
      if (evt.event_type === 'assistant.turn') {
        const turn = validateTurnResponse(evt.payload, evt.session_id);
        setTurnResponse(turn);
        if (turn.kind === 'proposal' && turn.approvals.length > 0) {
          setPendingApproval(turn.approvals.find((a) => a.status === 'pending') ?? null);
        }
        return false;
      }
      if (evt.event_type === 'workflow.audit') {
        const audit = evt.payload as AuditEvent;
        const ended = ['step_succeeded', 'step_failed', 'step_timed_out', 'workflow_cancelled'];
        if (activePlanRef.current && audit.plan_id === activePlanRef.current && ended.includes(audit.kind)) {
          const ok = audit.kind === 'step_succeeded';
          setTaskRunning(false);
          setMascotState(ok ? 'done' : 'error');
          setStatusMessage(ok ? 'Task finished.' : `Task stopped (${audit.kind.replace(/_/g, ' ')}).`);
          activePlanRef.current = null;
          return true;
        }
      }
    } catch (err) {
      // A malformed live event is dropped, never rendered.
      setStatusMessage(`Ignored a malformed ${evt.event_type} event.`);
    }
    return false;
  }, []);

  const stopTaskWatch = useCallback(() => {
    if (taskWatchRef.current) {
      clearInterval(taskWatchRef.current);
      taskWatchRef.current = null;
    }
  }, []);

  /** Follow one approved browser task through the session event log until it ends (max 2 min). */
  const watchTask = useCallback(
    (sid: string) => {
      const client = getClient();
      if (!client.getEvents) return;
      stopTaskWatch();
      const startedAt = Date.now();
      let busy = false;
      const tick = async () => {
        if (busy) return;
        busy = true;
        try {
          const res = await client.getEvents!(sid, 0);
          let ended = false;
          for (const evt of res.events) {
            if (taskSeenRef.current.has(evt.event_id)) continue;
            taskSeenRef.current.add(evt.event_id);
            if (applyLiveEvent(evt)) ended = true;
          }
          if (ended || Date.now() - startedAt > 120_000) stopTaskWatch();
        } catch {
          stopTaskWatch();
        } finally {
          busy = false;
        }
      };
      void tick();
      taskWatchRef.current = setInterval(() => void tick(), 300);
    },
    [getClient, applyLiveEvent, stopTaskWatch]
  );

  useEffect(() => stopTaskWatch, [stopTaskWatch]);

  /** Turns need a session (POST /api/sessions/{id}/turns): reuse the current one or open one. */
  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionIdRef.current) return sessionIdRef.current;
    const client = getClient();
    if (client.createSession) {
      const created = await client.createSession();
      setSessionId(created.session_id);
      return created.session_id;
    }
    return 'session-demo';
  }, [getClient, setSessionId]);

  const playSpeech = useCallback(
    async (sid: string, turn: TurnResponse) => {
      const client = getClient();
      if (!turn.spoken_text || !client.getTurnSpeech) return;
      try {
        const wav = await client.getTurnSpeech(sid, turn.turn_id);
        if (!wav || typeof Audio === 'undefined' || typeof URL.createObjectURL !== 'function') return;
        const url = URL.createObjectURL(wav);
        const audio = new Audio(url);
        audio.onended = () => URL.revokeObjectURL(url);
        await audio.play();
      } catch {
        // Speech is optional; the reply is already on screen.
      }
    },
    [getClient]
  );

  const handleTurnSubmit = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed) return;
      setUserQuery(trimmed);
      setTurnResponse(null);
      setStepActions([]);
      setTaskRunning(false);
      setPendingApproval(null);
      setPlanDecision('pending');
      setMascotState('thinking');
      setStatusMessage('Thinking…');
      setError(null);

      const client = getClient();
      if (!client.createTurn) {
        setMascotState('error');
        setError({
          type: 'backend',
          title: 'Turns unavailable',
          message: 'This backend does not support conversation turns yet.',
          code: 'DEPENDENCY_UNAVAILABLE',
        });
        return;
      }
      try {
        const sid = await ensureSession();
        const turn = await client.createTurn(sid, { text: trimmed });
        setTurnResponse(turn);
        proposalPlanRef.current = turn.approvals[0]?.plan_id ?? null;
        void playSpeech(sid, turn);

        if (turn.kind === 'proposal') {
          const pending = turn.approvals.find((a) => a.status === 'pending') ?? null;
          setPendingApproval(pending);
          setMascotState('idle');
          setStatusMessage(pending ? 'Waiting for your approval.' : 'Plan ready.');
          if (!pending && turn.workflow) setMascotState('done');
        } else if (turn.kind === 'answer') {
          setMascotState('done');
          setStatusMessage(null);
        } else if (turn.kind === 'clarify') {
          setMascotState('idle');
          setStatusMessage(null);
        } else {
          setMascotState('error');
          setError({
            type: 'backend',
            title: 'Request failed',
            message: turnErrorMessage(turn.error_code ?? 'UNKNOWN'),
            code: turn.error_code ?? undefined,
          });
          setStatusMessage(null);
        }
      } catch (err) {
        setMascotState('error');
        const formatted = formatErrorToState(err);
        setError(formatted);
        setStatusMessage(null);
      }
    },
    [getClient, ensureSession, playSpeech]
  );

  /** The knot: start or stop listening for "Hey Jarvis" (POST /api/sessions/{id}/listen). */
  const handleListenTrigger = useCallback(async () => {
    const client = getClient();
    const listening = captureStatus?.state === 'listening' || captureStatus?.state === 'capturing';
    const action = listening ? 'stop' : 'start';
    if (action === 'start') {
      setMascotState('listening');
      setStatusMessage('Listening ("Hey Jarvis")...');
    }
    if (!client.setListening) return;
    try {
      const sid = await ensureSession();
      const status = await client.setListening(sid, action);
      setCaptureStatus(status);
      if (status.state === 'listening' || status.state === 'capturing') {
        setMascotState('listening');
        setStatusMessage('Listening ("Hey Jarvis")...');
      } else {
        setMascotState('idle');
        setStatusMessage('Stopped listening.');
      }
    } catch (err) {
      setMascotState('error');
      setError(formatErrorToState(err));
    }
  }, [getClient, ensureSession, captureStatus]);

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
                    } else if (
                      evt.event_type === 'browser.action' ||
                      evt.event_type === 'audio.capture' ||
                      evt.event_type === 'assistant.turn'
                    ) {
                      applyLiveEvent(evt);
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
          } else if (
            evt.event_type === 'browser.action' ||
            evt.event_type === 'audio.capture' ||
            evt.event_type === 'assistant.turn'
          ) {
            applyLiveEvent(evt);
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
      const sid = sessionIdRef.current || sessionId || 'session-demo';
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

        if (proposalPlanRef.current === updated.plan_id) {
          // One approval per task: the browser agent now runs; follow its actions.
          setPlanDecision('approved');
          activePlanRef.current = updated.plan_id;
          setStepActions([]);
          setTaskRunning(true);
          setMascotState('working');
          setStatusMessage('Approved. Working in your browser…');
          watchTask(sid);
        } else {
          setMascotState('done');
          setTimeout(() => {
            setMascotState((c) => (c === 'done' ? 'idle' : c));
          }, 3000);
        }

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
    [sessionId, getClient, watchTask]
  );

  const handleReject = useCallback(
    async (approvalId: string) => {
      const sid = sessionIdRef.current || sessionId || 'session-demo';
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
        if (proposalPlanRef.current === updated.plan_id) setPlanDecision('rejected');
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

  // Keep the newest part of the conversation (approval, step chips, status) in view.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && !showDetails) el.scrollTop = el.scrollHeight;
  }, [turnResponse, pendingApproval, stepActions, statusMessage, error, showDetails]);

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

  const isListening = captureStatus?.state === 'listening' || captureStatus?.state === 'capturing';
  const stateLabel = STATE_LABELS[mascotState];
  const proposalStep = turnResponse?.proposal?.steps.find((st) => st.tool_name === 'browser_task');
  const approvalTask =
    pendingApproval && proposalStep && pendingApproval.plan_id === proposalPlanRef.current
      ? { goal: proposalStep.arguments.goal ?? '', site: siteName(proposalStep.arguments.start_url) }
      : null;
  const isEmpty = !userQuery && !turnResponse && !pendingApproval && stepActions.length === 0;

  return (
    <div className={`voicebot-notch-root cmp-root${isElectronApp ? '' : ' cmp-browser'}`}>
      {!isExpanded && (
        <div
          data-testid="notch-pill"
          role="region"
          aria-label="Voicebot notch pill"
          className={`cmp-pill is-${mascotState}`}
          title={`Jarvis: ${stateLabel}${latestCaption ? ` (“${latestCaption}”)` : ''}`}
          onClick={() => toggleExpanded(true)}
        >
          <Mascot state={mascotState} reducedMotion={reducedMotion} size={56} />
          {/* The expanded console's live regions are unmounted while collapsed;
              keep status and errors announced from the pill. */}
          <span data-testid="notch-pill-live-status" role="status" aria-live="polite" className="sr-only">
            {error ? `${error.title}: ${error.message}` : statusMessage}
          </span>
          <button
            type="button"
            data-testid="notch-expand-button"
            aria-label="Expand notch"
            className="cmp-pill-button"
            onClick={(e) => {
              e.stopPropagation();
              toggleExpanded(true);
            }}
            title="Open Jarvis (Alt+N)"
          />
        </div>
      )}

      {isExpanded && (
        <div
          data-testid="notch-expanded"
          role="region"
          aria-label="Voicebot notch console"
          className={`cmp-card is-${mascotState}`}
        >
          <header className="cmp-head">
            <div className="cmp-id">
              <span className="cmp-name">Jarvis</span>
              <span className="cmp-state" data-testid="companion-state">
                <i aria-hidden="true" />
                {stateLabel}
              </span>
            </div>
            <div className="cmp-head-actions">
              {(clientMode !== 'http' || captureStatus?.source === 'mock') && <span className="cmp-tag">mock</span>}
              <button
                type="button"
                className={`cmp-icon${showDetails ? ' is-on' : ''}`}
                aria-label="Session details"
                aria-expanded={showDetails}
                aria-controls="cmp-details"
                onClick={() => setShowDetails((v) => !v)}
                title="Session details"
              >
                <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="3" cy="8" r="1.4" /><circle cx="8" cy="8" r="1.4" /><circle cx="13" cy="8" r="1.4" /></svg>
              </button>
              <button
                type="button"
                data-testid="notch-collapse-button"
                aria-label="Collapse notch"
                className="cmp-icon"
                onClick={() => toggleExpanded(false)}
                title="Minimise (Alt+N)"
              >
                <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
              </button>
            </div>
          </header>

          <div className="cmp-scroll" ref={scrollRef}>
            <section className={`cmp-convo${showDetails ? ' is-hidden' : ''}`} aria-label="Conversation">
              {isEmpty && (
                <div className="cmp-empty">
                  <p className="cmp-hint">Say “Hey Jarvis”, or type below.</p>
                  <div className="cmp-suggest">
                    {SUGGESTIONS.map((q) => (
                      <button key={q} type="button" className="cmp-suggestion" onClick={() => handleTurnSubmit(q)}>
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <SpeechBubble userQuery={userQuery} turnResponse={turnResponse} planDecision={planDecision} />

              {pendingApproval && (
                <ApprovalDialog
                  approval={pendingApproval}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  task={approvalTask}
                />
              )}

              <StepChips actions={stepActions} running={taskRunning} />

              <StatusAlert
                statusMessage={statusMessage}
                error={error}
                isLoading={uiState === 'connecting' || isTransitioning}
                isOffline={isOffline}
                onDismissError={() => setError(null)}
              />
            </section>

            <section
              id="cmp-details"
              className={`cmp-details${showDetails ? '' : ' is-hidden'}`}
              aria-label="Session details"
            >
              <MockModeBanner />

              <div className="cmp-controls">
                <button
                  type="button"
                  data-testid="start-button"
                  onClick={handleStart}
                  disabled={isStartDisabled}
                  title={isElectronApp && !isBackendReady ? 'Waiting for backend sidecar to be ready...' : undefined}
                  aria-label="Start Session"
                  className="btn btn-go"
                >
                  Start
                </button>
                <button
                  type="button"
                  data-testid="pause-button"
                  onClick={handlePause}
                  disabled={isPauseDisabled}
                  aria-label="Pause Session"
                  className="btn"
                >
                  Pause
                </button>
                <button
                  type="button"
                  data-testid="resume-button"
                  onClick={handleResume}
                  disabled={isResumeDisabled}
                  aria-label="Resume Session"
                  className="btn"
                >
                  Resume
                </button>
                <button
                  type="button"
                  data-testid="stop-button"
                  onClick={handleStop}
                  disabled={isStopDisabled}
                  aria-label="Stop Session"
                  className="btn btn-stop"
                >
                  Stop
                </button>
                <button
                  type="button"
                  data-testid="reconnect-button"
                  onClick={handleReconnect}
                  disabled={!sessionId}
                  title="Reconnect and replay missed events"
                  className="btn"
                >
                  Reconnect
                </button>
              </div>

              <div className="cmp-kv">
                <span data-testid="ui-state-indicator">
                  UI: <strong>{uiState}</strong>
                </span>
                <span data-testid="backend-state-indicator">
                  Backend: <strong>{backendSessionState ?? 'not_started'}</strong>
                </span>
                {sessionId && (
                  <span className="cmp-kv-id">
                    ID: <code>{sessionId}</code>
                  </span>
                )}
              </div>

              <WorkflowProgressPanel auditEvents={auditEvents} />
              <TranscriptTimeline
                segments={segments}
                isRevised={(id) => (revisionCounts.get(id) ?? 0) > 0}
                revisionCount={(id) => revisionCounts.get(id) ?? 0}
              />
              <ScreenContextPanel
                enabled={screenContextEnabled}
                onToggle={(enabled) => setScreenContextEnabled(enabled)}
                disabled={isSessionInProgress}
                transcriptSegments={segments}
              />
              <AudioEventsSummary events={audioEvents} />
              <PermissionControl
                permission={permission}
                onChange={(newPerm) => {
                  setPermission(newPerm);
                  setError(null);
                }}
                disabled={isSessionInProgress}
              />
              {!customClient && (
                <fieldset className="cmp-modes">
                  <legend>Client Source Mode</legend>
                  {CLIENT_MODES.map(([mode, label]) => (
                    <label key={mode}>
                      <input
                        type="radio"
                        name="clientMode"
                        value={mode}
                        checked={clientMode === mode}
                        onChange={() => setClientMode(mode)}
                        disabled={isSessionInProgress}
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                </fieldset>
              )}
            </section>
          </div>

          <form
            className="cmp-input"
            onSubmit={(e) => {
              e.preventDefault();
              if (inputText.trim()) {
                handleTurnSubmit(inputText);
                setInputText('');
              }
            }}
          >
            <input
              type="text"
              data-testid="turn-input"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="Ask Jarvis…"
              aria-label="Type request or say hey jarvis"
              maxLength={2000}
            />
            <button type="submit" data-testid="turn-submit" aria-label="Send request" className="cmp-send">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M8.5 4.5L12 8l-3.5 3.5" /></svg>
            </button>
            <button
              type="button"
              data-testid="listen-button"
              aria-label={isListening ? 'Stop listening' : 'Listen (Hey Jarvis)'}
              aria-pressed={isListening}
              onClick={handleListenTrigger}
              title={isListening ? 'Stop listening (Alt+L)' : 'Listen for “Hey Jarvis” (Alt+L)'}
              className="cmp-knot-button"
            >
              <Mascot state={mascotState} reducedMotion={reducedMotion} size={44} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
};

export default App;
