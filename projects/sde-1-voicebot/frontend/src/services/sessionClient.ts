import {
  ApprovalRequest,
  AuditEvent,
  ErrorEnvelope,
  EventEnvelope,
  MockSessionResponse,
  SessionEventStreamResponse,
  SessionLifecycleState,
} from '../types/contracts';
import {
  validateApprovalRequest,
  validateErrorEnvelope,
  validateMockSessionResponse,
  validateSessionEventStreamResponse,
  validateSessionLifecycleState,
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

  constructor(envelope: ErrorEnvelope) {
    super(envelope.message_safe_for_user);
    this.name = 'BackendError';
    this.code = envelope.code;
    this.retryable = envelope.retryable;
    this.correlationId = envelope.correlation_id;
    this.details = envelope.details_redacted;
  }
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

  public resolveUrl(path: string): string {
    if (path.startsWith('http://') || path.startsWith('https://')) {
      return path;
    }
    let baseUrl = '';
    if (typeof window !== 'undefined') {
      if (window.voicebot?.getBackendUrl) {
        baseUrl = window.voicebot.getBackendUrl();
      } else if (window.location && window.location.protocol === 'file:') {
        baseUrl = 'http://127.0.0.1:8000';
      }
    }
    if (baseUrl) {
      return `${baseUrl.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;
    }
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

  async pauseSession(sessionId: string, _signal?: AbortSignal): Promise<SessionLifecycleState> {
    // W5 has not published HTTP pause/resume endpoints in app/main yet.
    // In accordance with repository instructions:
    // Do not invent API routes; report dependency blocker to Hemanth.
    throw new BackendError({
      code: 'DEPENDENCY_UNAVAILABLE',
      message_safe_for_user:
        'Backend pause/resume lifecycle endpoints are not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      retryable: true,
      correlation_id: `corr-${sessionId}`,
      details_redacted: { dependency: 'app.main (pause/resume endpoints)' },
    });
  }

  async resumeSession(sessionId: string, _signal?: AbortSignal): Promise<SessionLifecycleState> {
    throw new BackendError({
      code: 'DEPENDENCY_UNAVAILABLE',
      message_safe_for_user:
        'Backend pause/resume lifecycle endpoints are not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      retryable: true,
      correlation_id: `corr-${sessionId}`,
      details_redacted: { dependency: 'app.main (pause/resume endpoints)' },
    });
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

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new NetworkError(`Backend returned invalid JSON (HTTP ${response.status})`, response.status);
    }

    if (!response.ok) {
      const errorEnv = validateErrorEnvelope(payload);
      throw new BackendError(errorEnv);
    }

    const stateObj = payload as { state: unknown };
    return validateSessionLifecycleState(stateObj.state);
  }

  async getSessionState(_sessionId: string, _signal?: AbortSignal): Promise<SessionLifecycleState> {
    throw new BackendError({
      code: 'DEPENDENCY_UNAVAILABLE',
      message_safe_for_user:
        'Backend session query endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      retryable: true,
      correlation_id: `corr-${_sessionId}`,
      details_redacted: { dependency: 'app.main (session query endpoint)' },
    });
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

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new NetworkError(`Backend returned invalid JSON (HTTP ${response.status})`, response.status);
    }

    if (!response.ok) {
      const errorEnv = validateErrorEnvelope(payload);
      throw new BackendError(errorEnv);
    }

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

    if (response.status === 404 || response.status === 501) {
      throw new BackendError({
        code: 'DEPENDENCY_UNAVAILABLE',
        message_safe_for_user:
          'Backend approvals endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
        retryable: true,
        correlation_id: `corr-${sessionId}`,
        details_redacted: { dependency: 'app.main (approvals endpoint)', status: String(response.status) },
      });
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new NetworkError(`Backend returned invalid JSON (HTTP ${response.status})`, response.status);
    }

    if (!response.ok) {
      const errorEnv = validateErrorEnvelope(payload);
      throw new BackendError(errorEnv);
    }

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

    if (response.status === 404 || response.status === 501) {
      throw new BackendError({
        code: 'DEPENDENCY_UNAVAILABLE',
        message_safe_for_user:
          'Backend approvals endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
        retryable: true,
        correlation_id: `corr-${sessionId}`,
        details_redacted: { dependency: 'app.main (approvals endpoint)', status: String(response.status) },
      });
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new NetworkError(`Backend returned invalid JSON (HTTP ${response.status})`, response.status);
    }

    if (!response.ok) {
      const errorEnv = validateErrorEnvelope(payload);
      throw new BackendError(errorEnv);
    }

    return validateApprovalRequest(payload, sessionId);
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

        attempt++;
        const delayMs = Math.min(initialDelayMs * Math.pow(2, attempt - 1), maxDelayMs);
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
      this.events = (fixture as { events: EventEnvelope<unknown>[] }).events;
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
    } else {
      // Rejecting NEVER triggers execution!
      // executionCount is strictly unchanged
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
