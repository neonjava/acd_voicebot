import {
  ApprovalRequest,
  AuditEvent,
  BrowserAction,
  BrowserActionEventPayload,
  CaptureStatus,
  ErrorEnvelope,
  EventEnvelope,
  MockSessionResponse,
  SessionEventStreamResponse,
  SessionLifecycleState,
  TurnRequest,
  TurnResponse,
  WorkflowProposal,
} from '../types/contracts';
import {
  validateApprovalRequest,
  validateCaptureStatus,
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
  /** POST /api/sessions/{id}/turns (docs/contracts.md, Week 4). */
  createTurn?(sessionId: string, request: TurnRequest, signal?: AbortSignal): Promise<TurnResponse>;
  /** GET /api/sessions/{id}/capture. */
  getCaptureStatus?(sessionId: string, signal?: AbortSignal): Promise<CaptureStatus>;
  /** POST /api/sessions/{id}/listen with {"action": "start" | "stop"}. */
  setListening?(sessionId: string, action: 'start' | 'stop', signal?: AbortSignal): Promise<CaptureStatus>;
  /** GET /api/sessions/{id}/turns/{turn_id}/speech: WAV audio, or null when TTS is off (404). */
  getTurnSpeech?(sessionId: string, turnId: string, signal?: AbortSignal): Promise<Blob | null>;
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

  async createSession(signal?: AbortSignal): Promise<{ session_id: string; state: SessionLifecycleState }> {
    const payload = await this.send('/api/sessions', { method: 'POST', body: '{}', signal }, 'global', 'session create');
    if (!payload || typeof payload !== 'object' || typeof (payload as { session_id?: unknown }).session_id !== 'string') {
      throw new NetworkError('Backend returned a session without a session_id');
    }
    const p = payload as { session_id: string; state: unknown };
    return { session_id: p.session_id, state: validateSessionLifecycleState(p.state) };
  }

  async createTurn(sessionId: string, request: TurnRequest, signal?: AbortSignal): Promise<TurnResponse> {
    const payload = await this.send(
      `/api/sessions/${encodeURIComponent(sessionId)}/turns`,
      { method: 'POST', body: JSON.stringify(request), signal },
      sessionId,
      'turns'
    );
    return validateTurnResponse(payload, sessionId);
  }

  async getCaptureStatus(sessionId: string, signal?: AbortSignal): Promise<CaptureStatus> {
    const payload = await this.send(
      `/api/sessions/${encodeURIComponent(sessionId)}/capture`,
      { method: 'GET', signal },
      sessionId,
      'capture'
    );
    return validateCaptureStatus(payload, sessionId);
  }

  async setListening(sessionId: string, action: 'start' | 'stop', signal?: AbortSignal): Promise<CaptureStatus> {
    const payload = await this.send(
      `/api/sessions/${encodeURIComponent(sessionId)}/listen`,
      { method: 'POST', body: JSON.stringify({ action }), signal },
      sessionId,
      'listen'
    );
    return validateCaptureStatus(payload, sessionId);
  }

  async getTurnSpeech(sessionId: string, turnId: string, signal?: AbortSignal): Promise<Blob | null> {
    const url = this.resolveUrl(
      `/api/sessions/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/speech`
    );
    const headers = this.getHeaders();
    headers.Accept = 'audio/wav';
    let response: Response;
    try {
      response = await fetch(url, { method: 'GET', headers, signal });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') throw err;
      throw new NetworkError(`Failed to fetch speech from ${url}`);
    }
    if (response.status === 404) {
      // TTS_UNAVAILABLE (text-to-speech off) or the route is not there yet: no audio.
      return null;
    }
    if (!response.ok) {
      await this.readJson(response);
    }
    return response.blob();
  }

  /** Shared fetch for the Week 4 JSON routes: offline check, abort pass-through, error envelopes. */
  private async send(
    path: string,
    init: { method: string; body?: string; signal?: AbortSignal },
    sessionId: string,
    routeName: string
  ): Promise<unknown> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }
    const url = this.resolveUrl(path);
    let response: Response;
    try {
      response = await fetch(url, { ...init, headers: this.getHeaders() });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') throw err;
      throw new NetworkError(
        `Failed to reach ${url}: ${err instanceof Error ? err.message : 'network error'}`
      );
    }
    return this.readJson(response, {
      message: `The backend ${routeName} endpoint is not available yet (W5).`,
      dependency: `app.main (${routeName} endpoint)`,
      sessionId,
    });
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

      this.runMockBrowserTask(sessionId, appr);
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

  // -------------------------------------------------------------------------
  // Week 4 mock: a deterministic stand-in for W5's /turns and the browser
  // agent, so the companion can be demoed and tested without a backend.
  // Every reply is marked "(mock)" so it is never mistaken for a real answer.
  // -------------------------------------------------------------------------
  private turnCounter = 0;
  private captureState: CaptureStatus['state'] = 'idle';
  private tasks = new Map<string, { goal: string; startUrl: string }>();
  /** Delay between mock browser actions; 0 (tests) pushes them at once. */
  public actionDelayMs = 0;

  private pushEvent<T>(sessionId: string, eventType: string, producer: string, payload: T): void {
    this.events.push({
      event_id: `evt-${eventType}-${this.events.length}`,
      event_type: eventType,
      schema_version: '1.0',
      session_id: sessionId,
      correlation_id: `corr-${sessionId}`,
      timestamp: new Date().toISOString(),
      producer,
      payload,
    } as EventEnvelope<unknown>);
  }

  private captureStatus(sessionId: string): CaptureStatus {
    return {
      session_id: sessionId,
      state: this.captureState,
      source: 'mock',
      wake_required: true,
      wake_word: 'hey jarvis',
    };
  }

  async createSession(): Promise<{ session_id: string; state: SessionLifecycleState }> {
    this.currentSessionState = 'active';
    return { session_id: 'session-demo', state: 'active' };
  }

  async getCaptureStatus(sessionId: string): Promise<CaptureStatus> {
    return this.captureStatus(sessionId);
  }

  async setListening(sessionId: string, action: 'start' | 'stop'): Promise<CaptureStatus> {
    this.captureState = action === 'start' ? 'listening' : 'stopped';
    const status = this.captureStatus(sessionId);
    this.pushEvent(sessionId, 'audio.capture', 'audio', status);
    return status;
  }

  async getTurnSpeech(): Promise<Blob | null> {
    return null; // the mock has no text-to-speech
  }

  async createTurn(sessionId: string, request: TurnRequest): Promise<TurnResponse> {
    const text = request.text.trim();
    const lower = text.toLowerCase();
    const turnId = `turn-${++this.turnCounter}`;
    const base = { session_id: sessionId, turn_id: turnId, source_ids: [], approvals: [] };

    if (/\b(fail|error)\b/.test(lower)) {
      return { ...base, kind: 'error', error_code: 'DEPENDENCY_UNAVAILABLE' };
    }
    if (/\b(ram|memory)\b/.test(lower)) {
      const answer = '(mock) Chrome is using the most memory, about 3.1 GB.';
      return { ...base, kind: 'answer', answer, source_ids: ['system_stats'], spoken_text: answer };
    }
    if (/^close( it)?$/.test(lower)) {
      const clarify = 'Which app should I close?';
      return { ...base, kind: 'clarify', clarify, spoken_text: clarify };
    }
    if (/^(open|go to|search|play|find|check)\b/.test(lower) || /\b(browser|website|youtube|attendance)\b/.test(lower)) {
      const planId = `plan-${this.turnCounter}`;
      const startUrl = /youtube/.test(lower)
        ? 'https://www.youtube.com'
        : `https://www.google.com/search?q=${encodeURIComponent(text)}`;
      const proposal: WorkflowProposal = {
        proposal_id: planId,
        session_id: sessionId,
        correlation_id: `corr-${sessionId}`,
        summary: `Do this in your browser: ${text}`,
        steps: [
          {
            step_id: 'step-browser',
            tool_name: 'browser_task',
            arguments: { goal: text, start_url: startUrl },
            requires_approval: true,
          },
        ],
      };
      const approval: ApprovalRequest = {
        approval_id: `appr-${this.turnCounter}`,
        plan_id: planId,
        step_id: 'step-browser',
        session_id: sessionId,
        status: 'pending',
      };
      this.approvals.push(approval);
      this.tasks.set(planId, { goal: text, startUrl });
      return {
        ...base,
        kind: 'proposal',
        proposal,
        approvals: [{ ...approval }],
        spoken_text: 'I can do that in your browser. Approve to start.',
      };
    }
    const answer = `(mock) You said: "${text}". The real answer comes from the backend.`;
    return { ...base, kind: 'answer', answer, spoken_text: answer };
  }

  /** After one approval the mock agent acts in the "browser": the same events the real agent sends. */
  private runMockBrowserTask(sessionId: string, approval: ApprovalRequest): void {
    const task = this.tasks.get(approval.plan_id) ?? {
      goal: 'browser task',
      startUrl: 'https://www.google.com',
    };
    const n = { i: 0 };
    const act = (a: Omit<BrowserAction, 'action_id' | 'session_id'>): BrowserActionEventPayload => ({
      action: { action_id: `${approval.plan_id}-a${++n.i}`, session_id: sessionId, ...a },
      ok: true,
      error_code: null,
    });
    const steps: BrowserActionEventPayload[] = [
      act({ kind: 'navigate', url: task.startUrl }),
      act({ kind: 'read_page' }),
      act({ kind: 'click', ref: 'e12' }),
      act({ kind: 'read_page' }),
    ];
    const finish = () =>
      this.pushEvent<AuditEvent>(sessionId, 'workflow.audit', 'workflow', {
        sequence: this.events.length,
        kind: 'step_succeeded',
        plan_id: approval.plan_id,
        session_id: sessionId,
        step_id: approval.step_id,
        approval_id: approval.approval_id,
      });
    if (this.actionDelayMs <= 0) {
      steps.forEach((st) => this.pushEvent(sessionId, 'browser.action', 'browser', st));
      finish();
      return;
    }
    steps.forEach((st, i) =>
      setTimeout(() => this.pushEvent(sessionId, 'browser.action', 'browser', st), (i + 1) * this.actionDelayMs)
    );
    setTimeout(finish, (steps.length + 1) * this.actionDelayMs);
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
