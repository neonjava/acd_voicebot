import {
  ApprovalRequest,
  AuditEvent,
  BrowserActionEvent,
  CaptureOutcome,
  ErrorEnvelope,
  EventEnvelope,
  ListenResponse,
  MockSessionResponse,
  SessionEventStreamResponse,
  SessionLifecycleState,
  SpeechResponse,
  TurnRequest,
  TurnResponse,
  WorkflowStep,
} from '../types/contracts';
import {
  validateApprovalRequest,
  validateCaptureOutcome,
  validateErrorEnvelope,
  validateMockSessionResponse,
  validateSessionEventStreamResponse,
  validateSessionLifecycleState,
  validateTurnResponse,
} from '../utils/validation';
import {
  baselineApprovalRequest,
  week2StreamingSessionResponse,
} from '../fixtures/baselineSession';

export interface EventStreamSubscription {
  unsubscribe: () => void;
}

export interface StreamEventsOptions {
  fromSequence?: number;
  onEvents: (events: EventEnvelope<unknown>[]) => void;
  onError?: (error: Error) => void;
  onReconnect?: (attempt: number, delayMs: number) => void;
  /** Called once when polling stops for good because the backend answered with a non-retryable error. */
  onStopped?: (error: Error) => void;
  initialDelayMs?: number;
  maxDelayMs?: number;
  pollIntervalMs?: number;
}

export interface SessionClient {
  startMockSession(signal?: AbortSignal): Promise<MockSessionResponse>;
  createSession?(signal?: AbortSignal): Promise<{ session_id: string; state: SessionLifecycleState }>;
  pauseSession?(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState>;
  resumeSession?(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState>;
  stopSession?(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState>;
  getSessionState?(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState>;
  getEvents?(sessionId: string, fromSequence?: number, signal?: AbortSignal): Promise<SessionEventStreamResponse>;
  getPendingApprovals?(sessionId: string, signal?: AbortSignal): Promise<ApprovalRequest[]>;
  decideApproval?(sessionId: string, approvalId: string, decision: 'approve' | 'reject', signal?: AbortSignal): Promise<ApprovalRequest>;
  createTurn?(turnRequest: TurnRequest, signal?: AbortSignal): Promise<TurnResponse>;
  getCaptureStatus?(signal?: AbortSignal): Promise<CaptureOutcome>;
  triggerListen?(signal?: AbortSignal): Promise<ListenResponse>;
  synthesizeSpeech?(text: string, signal?: AbortSignal): Promise<SpeechResponse>;
  subscribeToEvents?(
    sessionId: string,
    options: StreamEventsOptions,
    signal?: AbortSignal
  ): EventStreamSubscription;
}

export class BackendError extends Error {
  public readonly code: string;
  public readonly retryable: boolean;
  public readonly correlationId: string;
  public readonly details: Record<string, string>;
  /** HTTP status of the response that carried the envelope, when known. */
  public readonly status?: number;
  /** Delay the backend asked for in its Retry-After header (HTTP 429), in milliseconds. */
  public readonly retryAfterMs?: number;

  constructor(envelope: ErrorEnvelope, meta: { status?: number; retryAfterMs?: number } = {}) {
    super(envelope.message_safe_for_user);
    this.name = 'BackendError';
    this.code = envelope.code;
    this.retryable = envelope.retryable;
    this.correlationId = envelope.correlation_id;
    this.details = envelope.details_redacted;
    this.status = meta.status;
    this.retryAfterMs = meta.retryAfterMs;
  }
}

/** Upper bound on a single Retry-After wait so a bad header cannot stall the UI forever. */
export const MAX_RETRY_AFTER_MS = 5 * 60 * 1000;

/**
 * Parse an HTTP Retry-After header (delta-seconds or HTTP-date) into milliseconds.
 * Returns undefined when the header is missing or malformed.
 */
export function parseRetryAfterMs(value: string | null | undefined, nowMs: number = Date.now()): number | undefined {
  if (value === null || value === undefined) return undefined;
  const text = value.trim();
  if (text === '') return undefined;
  if (/^\d+$/.test(text)) {
    return Number(text) * 1000;
  }
  const at = Date.parse(text);
  if (Number.isNaN(at)) return undefined;
  return Math.max(0, at - nowMs);
}

interface MissingEndpointInfo {
  message: string;
  dependency: string;
  sessionId: string;
}

export class NetworkError extends Error {
  public readonly status?: number;
  public readonly isOffline?: boolean;

  constructor(message: string, status?: number, isOffline = false) {
    super(message);
    this.name = 'NetworkError';
    this.status = status;
    this.isOffline = isOffline;
  }
}

export interface HttpSessionClientOptions {
  endpoint?: string;
  token?: string | (() => string | null | undefined);
}

export class HttpSessionClient implements SessionClient {
  private readonly endpoint: string;
  private readonly tokenProvider?: string | (() => string | null | undefined);

  constructor(options?: string | HttpSessionClientOptions) {
    if (typeof options === 'string') {
      this.endpoint = options;
    } else {
      this.endpoint = options?.endpoint || '/api/sessions/mock';
      this.tokenProvider = options?.token;
    }
  }

  /**
   * Requests always go to the page's own origin (/api/...): the Vite dev proxy in
   * development and the Electron app:// protocol in the packaged app forward them
   * to the backend. A cross-origin URL would need CORS, which the backend does not
   * offer, so the Bearer-authenticated preflight would fail.
   */
  public resolveUrl(path: string): string {
    return path;
  }

  private getAuthToken(): string | null {
    if (typeof this.tokenProvider === 'function') {
      const t = this.tokenProvider();
      return t || null;
    }
    if (typeof this.tokenProvider === 'string' && this.tokenProvider.length > 0) {
      return this.tokenProvider;
    }
    if (typeof window !== 'undefined' && window.voicebot?.getToken) {
      const t = window.voicebot.getToken();
      return t || null;
    }
    return null;
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
    const token = this.getAuthToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
  }

  /**
   * Read a JSON response. Non-2xx answers become a BackendError built from the
   * ErrorEnvelope (with the HTTP status and any Retry-After delay). When
   * `missingEndpoint` is given, a 501, or a 404 that is not a domain error such as
   * SESSION_NOT_FOUND (FastAPI reports an unknown route as HTTP_404), means the
   * route is not available yet and is reported as DEPENDENCY_UNAVAILABLE.
   */
  private async readJson(response: Response, missingEndpoint?: MissingEndpointInfo): Promise<unknown> {
    let payload: unknown;
    let parsed = true;
    try {
      payload = await response.json();
    } catch {
      parsed = false;
    }

    if (response.ok) {
      if (!parsed) {
        throw new NetworkError(`Backend returned invalid JSON (HTTP ${response.status})`, response.status);
      }
      return payload;
    }

    let envelope: ErrorEnvelope | null = null;
    if (parsed) {
      try {
        envelope = validateErrorEnvelope(payload);
      } catch {
        envelope = null;
      }
    }

    if (
      missingEndpoint &&
      (response.status === 501 ||
        (response.status === 404 && (envelope === null || envelope.code === 'HTTP_404')))
    ) {
      throw new BackendError(
        {
          code: 'DEPENDENCY_UNAVAILABLE',
          message_safe_for_user: missingEndpoint.message,
          retryable: true,
          correlation_id: `corr-${missingEndpoint.sessionId}`,
          details_redacted: { dependency: missingEndpoint.dependency, status: String(response.status) },
        },
        { status: response.status }
      );
    }

    if (envelope) {
      throw new BackendError(envelope, {
        status: response.status,
        retryAfterMs:
          response.status === 429 ? parseRetryAfterMs(response.headers?.get?.('Retry-After') ?? null) : undefined,
      });
    }

    if (!parsed) {
      throw new NetworkError(`Backend returned invalid JSON (HTTP ${response.status})`, response.status);
    }
    throw new NetworkError(`Request failed with HTTP ${response.status}`, response.status);
  }

  async startMockSession(signal?: AbortSignal): Promise<MockSessionResponse> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }

    const targetUrl = this.resolveUrl(this.endpoint);
    let response: Response;
    try {
      response = await fetch(targetUrl, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({}),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      const message = err instanceof Error ? err.message : 'Unknown network failure';
      throw new NetworkError(`Failed to reach backend at ${targetUrl}: ${message}`);
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new NetworkError(
        `Backend returned invalid JSON (HTTP ${response.status} ${response.statusText})`,
        response.status
      );
    }

    if (!response.ok) {
      try {
        const errorEnv = validateErrorEnvelope(payload);
        throw new BackendError(errorEnv);
      } catch (validationErr) {
        if (validationErr instanceof BackendError) {
          throw validationErr;
        }
        throw new NetworkError(
          `Request failed with HTTP ${response.status}: ${response.statusText}`,
          response.status
        );
      }
    }

    return validateMockSessionResponse(payload);
  }

  async pauseSession(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState> {
    return this.postLifecycleAction(sessionId, 'pause', signal);
  }

  async resumeSession(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState> {
    return this.postLifecycleAction(sessionId, 'resume', signal);
  }

  async stopSession(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState> {
    return this.postLifecycleAction(sessionId, 'stop', signal);
  }

  private async postLifecycleAction(
    sessionId: string,
    action: 'pause' | 'resume' | 'stop',
    signal?: AbortSignal
  ): Promise<SessionLifecycleState> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }

    const url = this.resolveUrl(`/api/sessions/${encodeURIComponent(sessionId)}/${action}`);
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({}),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to reach backend at ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = await this.readJson(response, {
      message:
        `Backend ${action} lifecycle endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.`,
      dependency: `app.main (${action} endpoint)`,
      sessionId,
    });

    const stateObj = payload as { state: unknown };
    return validateSessionLifecycleState(stateObj.state);
  }

  async getSessionState(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }

    const url = this.resolveUrl(`/api/sessions/${encodeURIComponent(sessionId)}`);
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to reach backend at ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = await this.readJson(response, {
      message:
        'Backend session query endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      dependency: 'app.main (session query endpoint)',
      sessionId,
    });

    const stateObj = payload as { state: unknown };
    return validateSessionLifecycleState(stateObj.state);
  }

  async getEvents(sessionId: string, fromSequence = 0, signal?: AbortSignal): Promise<SessionEventStreamResponse> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }

    const url = this.resolveUrl(`/api/sessions/${encodeURIComponent(sessionId)}/events?from_sequence=${fromSequence}`);
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to fetch events from ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = await this.readJson(response);
    return validateSessionEventStreamResponse(payload);
  }

  async getPendingApprovals(sessionId: string, signal?: AbortSignal): Promise<ApprovalRequest[]> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }

    const url = this.resolveUrl(`/api/sessions/${encodeURIComponent(sessionId)}/approvals`);
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to get approvals from ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = await this.readJson(response, {
      message:
        'Backend approvals endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      dependency: 'app.main (approvals endpoint)',
      sessionId,
    });

    if (!Array.isArray(payload)) {
      throw new NetworkError('Approvals response must be an array');
    }

    return payload.map((item) => validateApprovalRequest(item, sessionId));
  }

  async decideApproval(
    sessionId: string,
    approvalId: string,
    decision: 'approve' | 'reject',
    signal?: AbortSignal
  ): Promise<ApprovalRequest> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }

    const url = this.resolveUrl(`/api/sessions/${encodeURIComponent(sessionId)}/approvals/${encodeURIComponent(approvalId)}`);
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({ decision }),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to post approval decision to ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = await this.readJson(response, {
      message:
        'Backend approvals endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      dependency: 'app.main (approvals endpoint)',
      sessionId,
    });

    return validateApprovalRequest(payload, sessionId);
  }

  async createTurn(turnRequest: TurnRequest, signal?: AbortSignal): Promise<TurnResponse> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }
    const url = this.resolveUrl('/api/turns');
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(turnRequest),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to post turn to ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = await this.readJson(response, {
      message: 'Backend turns endpoint is not yet implemented upstream in app.main.',
      dependency: 'app.main (turns endpoint)',
      sessionId: turnRequest.session_id || 'unknown',
    });

    return validateTurnResponse(payload);
  }

  async getCaptureStatus(signal?: AbortSignal): Promise<CaptureOutcome> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }
    const url = this.resolveUrl('/api/capture');
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to get capture status from ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = await this.readJson(response, {
      message: 'Backend capture endpoint is not yet implemented upstream in app.main.',
      dependency: 'app.main (capture endpoint)',
      sessionId: 'global',
    });

    return validateCaptureOutcome(payload);
  }

  async triggerListen(signal?: AbortSignal): Promise<ListenResponse> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }
    const url = this.resolveUrl('/api/listen');
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({}),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to trigger listen at ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = (await this.readJson(response, {
      message: 'Backend listen endpoint is not yet implemented upstream in app.main.',
      dependency: 'app.main (listen endpoint)',
      sessionId: 'global',
    })) as { status?: string; wake_word_detected?: boolean; session_id?: string };

    return {
      status: payload.status === 'idle' ? 'idle' : 'listening',
      wake_word_detected: Boolean(payload.wake_word_detected ?? true),
      session_id: payload.session_id,
    };
  }

  async synthesizeSpeech(text: string, signal?: AbortSignal): Promise<SpeechResponse> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }
    const url = this.resolveUrl('/api/speech');
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({ text }),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new NetworkError(`Failed to post speech synthesis to ${url}: ${err instanceof Error ? err.message : 'network error'}`);
    }

    const payload = (await this.readJson(response, {
      message: 'Backend speech endpoint is not yet implemented upstream in app.main.',
      dependency: 'app.main (speech endpoint)',
      sessionId: 'global',
    })) as { audio_url?: string; spoken_text?: string; duration_ms?: number };

    return {
      audio_url: payload.audio_url,
      spoken_text: payload.spoken_text || text,
      duration_ms: payload.duration_ms,
    };
  }

  subscribeToEvents(
    sessionId: string,
    options: StreamEventsOptions,
    signal?: AbortSignal
  ): EventStreamSubscription {
    let active = true;
    let attempt = 0;
    let currentSeq = options.fromSequence ?? 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let abortController: AbortController | null = null;
    const initialDelayMs = options.initialDelayMs ?? 500;
    const maxDelayMs = options.maxDelayMs ?? 3000;
    const pollIntervalMs = options.pollIntervalMs ?? 1000;

    const poll = async () => {
      if (!active || signal?.aborted) return;
      abortController = new AbortController();

      try {
        const res = await this.getEvents(sessionId, currentSeq, abortController.signal);
        if (!active || signal?.aborted) return;
        attempt = 0; // reset exponential backoff counter on success
        if (res.events && res.events.length > 0) {
          currentSeq += res.events.length;
          options.onEvents(res.events);
        }
        if (res.has_more) {
          // Replay pagination: continue fetching immediately until has_more is false
          timer = setTimeout(poll, 0);
        } else {
          timer = setTimeout(poll, pollIntervalMs);
        }
      } catch (err) {
        if (!active || signal?.aborted) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;

        // A non-retryable backend answer (401 AUTH_REQUIRED, 404 SESSION_NOT_FOUND,
        // 410 SESSION_EXPIRED, ...) will not change by polling again: stop for good.
        if (err instanceof BackendError && !err.retryable) {
          active = false;
          timer = null;
          options.onError?.(err);
          options.onStopped?.(err);
          return;
        }

        attempt++;
        let delayMs = Math.min(initialDelayMs * Math.pow(2, attempt - 1), maxDelayMs);
        // Honour the backend's rate limiter (429 Retry-After) instead of retrying early.
        if (err instanceof BackendError && err.retryAfterMs !== undefined) {
          delayMs = Math.max(delayMs, Math.min(err.retryAfterMs, MAX_RETRY_AFTER_MS));
        }
        if (options.onReconnect) {
          options.onReconnect(attempt, delayMs);
        }
        if (options.onError) {
          options.onError(err instanceof Error ? err : new Error(String(err)));
        }
        timer = setTimeout(poll, delayMs);
      }
    };

    timer = setTimeout(poll, 0);

    const unsubscribe = () => {
      active = false;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
    };

    if (signal) {
      signal.addEventListener('abort', unsubscribe);
    }

    return { unsubscribe };
  }
}

export class FixtureSessionClient implements SessionClient {
  private currentSessionState: SessionLifecycleState = 'active';
  private events: EventEnvelope<unknown>[] = [];
  private approvals: ApprovalRequest[] = [];
  private executionCount = 0;

  constructor(
    private readonly fixture: unknown = week2StreamingSessionResponse,
    private readonly delayMs: number = 0,
    initialState?: SessionLifecycleState,
    initialApprovals: ApprovalRequest[] = [baselineApprovalRequest]
  ) {
    if (initialState) {
      this.currentSessionState = initialState;
    } else if (
      fixture &&
      typeof fixture === 'object' &&
      'state' in fixture &&
      typeof (fixture as { state: unknown }).state === 'string'
    ) {
      this.currentSessionState = (fixture as { state: SessionLifecycleState }).state;
    } else {
      this.currentSessionState = 'active';
    }

    if (
      fixture &&
      typeof fixture === 'object' &&
      'events' in fixture &&
      Array.isArray((fixture as { events: unknown }).events)
    ) {
      this.events = structuredClone((fixture as { events: EventEnvelope<unknown>[] }).events);
    }

    this.approvals = initialApprovals.map((a) => ({ ...a }));
  }

  async startMockSession(signal?: AbortSignal): Promise<MockSessionResponse> {
    if (signal?.aborted) {
      throw new DOMException('The user aborted a request.', 'AbortError');
    }

    if (this.delayMs > 0) {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => resolve(), this.delayMs);
        if (signal) {
          signal.addEventListener('abort', () => {
            clearTimeout(timer);
            reject(new DOMException('The user aborted a request.', 'AbortError'));
          });
        }
      });
    }

    const validated = validateMockSessionResponse(structuredClone(this.fixture));
    this.currentSessionState = validated.state;
    return validated;
  }

  async pauseSession(_sessionId: string): Promise<SessionLifecycleState> {
    if (this.currentSessionState !== 'active') {
      throw new BackendError({
        code: 'INVALID_SESSION_TRANSITION',
        message_safe_for_user: `Cannot transition session from ${this.currentSessionState} to paused.`,
        retryable: false,
        correlation_id: `corr-${_sessionId}`,
        details_redacted: {
          from_state: this.currentSessionState,
          target_state: 'paused',
        },
      });
    }
    this.currentSessionState = validateSessionLifecycleState('paused');
    return this.currentSessionState;
  }

  async resumeSession(_sessionId: string): Promise<SessionLifecycleState> {
    if (this.currentSessionState !== 'paused') {
      throw new BackendError({
        code: 'INVALID_SESSION_TRANSITION',
        message_safe_for_user: `Cannot transition session from ${this.currentSessionState} to active.`,
        retryable: false,
        correlation_id: `corr-${_sessionId}`,
        details_redacted: {
          from_state: this.currentSessionState,
          target_state: 'active',
        },
      });
    }
    this.currentSessionState = validateSessionLifecycleState('active');
    return this.currentSessionState;
  }

  async stopSession(_sessionId: string): Promise<SessionLifecycleState> {
    this.currentSessionState = validateSessionLifecycleState('completed');
    return this.currentSessionState;
  }

  async getSessionState(_sessionId: string): Promise<SessionLifecycleState> {
    return this.currentSessionState;
  }

  setSessionState(state: SessionLifecycleState): void {
    this.currentSessionState = validateSessionLifecycleState(state);
  }

  async getEvents(sessionId: string, fromSequence = 0): Promise<SessionEventStreamResponse> {
    const sliced = this.events.slice(fromSequence);
    return {
      session_id: sessionId,
      events: structuredClone(sliced),
      from_sequence: fromSequence,
      total_events: this.events.length,
      has_more: false,
    };
  }

  async getPendingApprovals(sessionId: string): Promise<ApprovalRequest[]> {
    return this.approvals.filter((a) => a.session_id === sessionId && a.status === 'pending');
  }

  async decideApproval(
    sessionId: string,
    approvalId: string,
    decision: 'approve' | 'reject'
  ): Promise<ApprovalRequest> {
    const appr = this.approvals.find((a) => a.approval_id === approvalId && a.session_id === sessionId);
    if (!appr) {
      throw new BackendError({
        code: 'APPROVAL_NOT_FOUND',
        message_safe_for_user: `Approval ${approvalId} not found`,
        retryable: false,
        correlation_id: `corr-${sessionId}`,
        details_redacted: { approval_id: approvalId },
      });
    }

    if (appr.status !== 'pending') {
      throw new BackendError({
        code: 'APPROVAL_ALREADY_DECIDED',
        message_safe_for_user: `Approval ${approvalId} was already ${appr.status}`,
        retryable: false,
        correlation_id: `corr-${sessionId}`,
        details_redacted: { approval_id: approvalId, status: appr.status },
      });
    }

    appr.status = decision === 'approve' ? 'approved' : 'rejected';

    if (decision === 'approve') {
      // Step may execute
      this.executionCount += 1;
      const auditEvt: EventEnvelope<AuditEvent> = {
        event_id: `evt-audit-decision-${appr.approval_id}-approved`,
        event_type: 'workflow.audit',
        schema_version: '1.0',
        session_id: sessionId,
        correlation_id: `corr-${sessionId}`,
        timestamp: new Date().toISOString(),
        producer: 'workflow',
        payload: {
          sequence: this.events.length,
          kind: 'approval_granted',
          plan_id: appr.plan_id,
          session_id: sessionId,
          step_id: appr.step_id,
          approval_id: appr.approval_id,
        },
      };
      this.events.push(auditEvt as EventEnvelope<unknown>);

      const browserEvts: EventEnvelope<BrowserActionEvent>[] = [
        {
          event_id: `evt-action-${appr.plan_id}-1`,
          event_type: 'browser.action',
          schema_version: '1.0',
          session_id: sessionId,
          correlation_id: `corr-${sessionId}`,
          timestamp: new Date().toISOString(),
          producer: 'browser',
          payload: {
            action_id: `act-${appr.plan_id}-1`,
            session_id: sessionId,
            step_id: 'step-nav',
            action_type: 'navigate',
            label: 'Read page',
            status: 'completed',
            target: 'https://portal.university.edu/attendance',
          },
        },
        {
          event_id: `evt-action-${appr.plan_id}-2`,
          event_type: 'browser.action',
          schema_version: '1.0',
          session_id: sessionId,
          correlation_id: `corr-${sessionId}`,
          timestamp: new Date().toISOString(),
          producer: 'browser',
          payload: {
            action_id: `act-${appr.plan_id}-2`,
            session_id: sessionId,
            step_id: 'step-click',
            action_type: 'click',
            label: 'Click Attendance',
            status: 'completed',
            target: '#submit-query',
          },
        },
        {
          event_id: `evt-action-${appr.plan_id}-3`,
          event_type: 'browser.action',
          schema_version: '1.0',
          session_id: sessionId,
          correlation_id: `corr-${sessionId}`,
          timestamp: new Date().toISOString(),
          producer: 'browser',
          payload: {
            action_id: `act-${appr.plan_id}-3`,
            session_id: sessionId,
            step_id: 'step-read',
            action_type: 'read',
            label: 'Read results',
            status: 'completed',
          },
        },
      ];
      for (const be of browserEvts) {
        this.events.push(be as EventEnvelope<unknown>);
      }
    } else {
      // Rejecting NEVER triggers execution!
      // executionCount is strictly unchanged; no browser actions are run
      const auditEvt: EventEnvelope<AuditEvent> = {
        event_id: `evt-audit-decision-${appr.approval_id}-rejected`,
        event_type: 'workflow.audit',
        schema_version: '1.0',
        session_id: sessionId,
        correlation_id: `corr-${sessionId}`,
        timestamp: new Date().toISOString(),
        producer: 'workflow',
        payload: {
          sequence: this.events.length,
          kind: 'approval_rejected',
          plan_id: appr.plan_id,
          session_id: sessionId,
          step_id: appr.step_id,
          approval_id: appr.approval_id,
        },
      };
      this.events.push(auditEvt as EventEnvelope<unknown>);
    }

    return structuredClone(appr);
  }

  private screenCaptureEnabled = false;

  setCaptureEnabled(enabled: boolean): void {
    this.screenCaptureEnabled = enabled;
  }

  isCaptureEnabled(): boolean {
    return this.screenCaptureEnabled;
  }

  async getCaptureStatus(): Promise<CaptureOutcome> {
    return {
      status: this.screenCaptureEnabled ? 'captured' : 'disabled',
      capture_enabled: this.screenCaptureEnabled,
      frame_id: this.screenCaptureEnabled ? 'frame-mock-demo-1' : null,
    };
  }

  async triggerListen(): Promise<ListenResponse> {
    return {
      status: 'listening',
      wake_word_detected: true,
      session_id: 'session-demo',
    };
  }

  async synthesizeSpeech(text: string): Promise<SpeechResponse> {
    return {
      spoken_text: text,
      duration_ms: 150,
    };
  }

  async createTurn(turnRequest: TurnRequest): Promise<TurnResponse> {
    const raw = (turnRequest.text || '').toLowerCase().trim();
    const sessionId = turnRequest.session_id || 'session-demo';

    if (raw.includes('fail') || raw.includes('error')) {
      return {
        kind: 'error',
        message: 'Could not connect to service.',
        code: 'SERVICE_UNAVAILABLE',
        retryable: true,
        session_id: sessionId,
      };
    }

    if (raw.includes('ram') || raw.includes('memory')) {
      return {
        kind: 'answer',
        text: 'Chrome, about 3.1 GB.',
        sources: [
          {
            id: 'src-ram-1',
            label: 'psutil (system stats)',
            kind: 'system',
            locator: 'system_stats.memory',
          },
        ],
        spoken_text: 'Chrome, about 3.1 GB.',
        session_id: sessionId,
      };
    }

    if (raw.includes('close it') || raw.includes('clarify') || raw === 'close') {
      return {
        kind: 'clarify',
        question: 'Do you mean close Chrome or close the active tab?',
        spoken_text: 'Do you mean close Chrome or close the active tab?',
        session_id: sessionId,
      };
    }

    if (
      raw.includes('attendance') ||
      raw.includes('browser') ||
      raw.includes('portal') ||
      raw.includes('open')
    ) {
      const planId = `plan-${Date.now()}`;
      const approvalId = `appr-${Date.now()}`;
      const steps: WorkflowStep[] = [
        {
          step_id: 'step-nav',
          tool_name: 'open_url',
          arguments: { url: 'https://portal.university.edu/attendance' },
          requires_approval: false,
        },
        {
          step_id: 'step-click',
          tool_name: 'click_element',
          arguments: { selector: '#attendance-link' },
          requires_approval: true,
        },
        {
          step_id: 'step-read',
          tool_name: 'read_page',
          arguments: { target: 'results_table' },
          requires_approval: false,
        },
      ];

      const appr: ApprovalRequest = {
        approval_id: approvalId,
        plan_id: planId,
        step_id: 'step-click',
        session_id: sessionId,
        status: 'pending',
      };
      this.approvals.push(appr);

      return {
        kind: 'proposal',
        plan_id: planId,
        summary: 'Open attendance page, click Attendance link, and read results',
        steps,
        requires_approval: true,
        approval_id: approvalId,
        spoken_text: 'I planned the attendance check. It needs your approval to proceed.',
        session_id: sessionId,
      };
    }

    return {
      kind: 'answer',
      text: `I understand: "${turnRequest.text}". Ready to assist.`,
      spoken_text: `I understand: "${turnRequest.text}". Ready to assist.`,
      session_id: sessionId,
    };
  }

  getExecutionCount(): number {
    return this.executionCount;
  }

  subscribeToEvents(
    sessionId: string,
    options: StreamEventsOptions,
    signal?: AbortSignal
  ): EventStreamSubscription {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let currentSeq = options.fromSequence ?? 0;

    const run = async () => {
      if (!active || signal?.aborted) return;
      try {
        const res = await this.getEvents(sessionId, currentSeq);
        if (!active || signal?.aborted) return;
        if (res.events.length > 0) {
          currentSeq += res.events.length;
          options.onEvents(res.events);
        }
      } catch (err) {
        if (options.onError && err instanceof Error) {
          options.onError(err);
        }
      }
    };

    timer = setTimeout(run, this.delayMs || 10);

    return {
      unsubscribe: () => {
        active = false;
        if (timer) clearTimeout(timer);
      },
    };
  }
}
