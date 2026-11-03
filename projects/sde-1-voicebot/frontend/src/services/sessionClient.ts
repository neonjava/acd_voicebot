import {
  ErrorEnvelope,
  MockSessionResponse,
  SessionLifecycleState,
} from '../types/contracts';
import {
  validateErrorEnvelope,
  validateMockSessionResponse,
  validateSessionLifecycleState,
} from '../utils/validation';
import { week2StreamingSessionResponse } from '../fixtures/baselineSession';

export interface SessionClient {
  startMockSession(signal?: AbortSignal): Promise<MockSessionResponse>;
  pauseSession?(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState>;
  resumeSession?(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState>;
  getSessionState?(sessionId: string, signal?: AbortSignal): Promise<SessionLifecycleState>;
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

export class HttpSessionClient implements SessionClient {
  constructor(private readonly endpoint: string = '/api/sessions/mock') {}

  async startMockSession(signal?: AbortSignal): Promise<MockSessionResponse> {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      throw new NetworkError('Network is offline. Cannot reach backend.', undefined, true);
    }

    let response: Response;
    try {
      response = await fetch(this.endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({}),
        signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      const message = err instanceof Error ? err.message : 'Unknown network failure';
      throw new NetworkError(`Failed to reach backend at ${this.endpoint}: ${message}`);
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

  async pauseSession(sessionId: string): Promise<SessionLifecycleState> {
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

  async resumeSession(sessionId: string): Promise<SessionLifecycleState> {
    throw new BackendError({
      code: 'DEPENDENCY_UNAVAILABLE',
      message_safe_for_user:
        'Backend pause/resume lifecycle endpoints are not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      retryable: true,
      correlation_id: `corr-${sessionId}`,
      details_redacted: { dependency: 'app.main (pause/resume endpoints)' },
    });
  }

  async getSessionState(_sessionId: string): Promise<SessionLifecycleState> {
    throw new BackendError({
      code: 'DEPENDENCY_UNAVAILABLE',
      message_safe_for_user:
        'Backend session query endpoint is not yet implemented upstream by W5 in app.main. Awaiting backend integration.',
      retryable: true,
      correlation_id: `corr-${_sessionId}`,
      details_redacted: { dependency: 'app.main (session query endpoint)' },
    });
  }
}

export class FixtureSessionClient implements SessionClient {
  private currentSessionState: SessionLifecycleState = 'active';

  constructor(
    private readonly fixture: unknown = week2StreamingSessionResponse,
    private readonly delayMs: number = 0,
    initialState?: SessionLifecycleState
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

    // Always validate runtime data
    const validated = validateMockSessionResponse(structuredClone(this.fixture));
    this.currentSessionState = validated.state;
    return validated;
  }

  async pauseSession(_sessionId: string): Promise<SessionLifecycleState> {
    // Follow backend/app/sessions/service.py LEGAL_TRANSITIONS: active -> paused
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
    // Follow backend/app/sessions/service.py LEGAL_TRANSITIONS: paused -> active
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

  async getSessionState(_sessionId: string): Promise<SessionLifecycleState> {
    return this.currentSessionState;
  }

  setSessionState(state: SessionLifecycleState): void {
    this.currentSessionState = validateSessionLifecycleState(state);
  }
}
