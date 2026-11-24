import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  HttpSessionClient,
  FixtureSessionClient,
  BackendError,
  NetworkError,
  parseRetryAfterMs,
} from '../services/sessionClient';
import { baselineSessionResponse, week2StreamingSessionResponse } from '../fixtures/baselineSession';
import { MalformedResponseError } from '../utils/validation';

describe('SessionClient implementations', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('FixtureSessionClient', () => {
    it('returns validated baseline canonical session response when provided', async () => {
      const client = new FixtureSessionClient(baselineSessionResponse);
      const res = await client.startMockSession();
      expect(res.session_id).toBe('session-demo');
      expect(res.mode).toBe('mock');
      expect(res.state).toBe('completed');
      expect(res.events).toHaveLength(2);
    });

    it('returns validated week2 streaming session response by default with active state', async () => {
      const client = new FixtureSessionClient();
      const res = await client.startMockSession();
      expect(res.session_id).toBe('session-week2-stream');
      expect(res.mode).toBe('mock');
      expect(res.state).toBe('active');
      expect(res.events.length).toBeGreaterThan(2);
    });

    it('validates custom fixture data and throws if malformed', async () => {
      const invalidFixture = { session_id: 'bad', state: 'invalid' };
      const client = new FixtureSessionClient(invalidFixture);
      await expect(client.startMockSession()).rejects.toThrow(MalformedResponseError);
    });

    it('aborts when signal is already cancelled', async () => {
      const controller = new AbortController();
      controller.abort();
      const client = new FixtureSessionClient(baselineSessionResponse, 100);
      await expect(client.startMockSession(controller.signal)).rejects.toThrow(/aborted/);
    });

    it('handles legal pause and resume transitions when active', async () => {
      const client = new FixtureSessionClient(week2StreamingSessionResponse);
      await client.startMockSession();
      expect(await client.getSessionState('sess-1')).toBe('active');

      // Legal: active -> paused
      const pausedState = await client.pauseSession('sess-1');
      expect(pausedState).toBe('paused');
      expect(await client.getSessionState('sess-1')).toBe('paused');

      // Legal: paused -> active
      const resumedState = await client.resumeSession('sess-1');
      expect(resumedState).toBe('active');
      expect(await client.getSessionState('sess-1')).toBe('active');
    });

    it('rejects illegal transitions according to backend LEGAL_TRANSITIONS', async () => {
      const client = new FixtureSessionClient(week2StreamingSessionResponse);
      await client.startMockSession();

      // Illegal: active -> active (calling resume when already active)
      await expect(client.resumeSession('sess-1')).rejects.toThrow(BackendError);

      // Transition to paused
      await client.pauseSession('sess-1');

      // Illegal: paused -> paused (calling pause when already paused)
      await expect(client.pauseSession('sess-1')).rejects.toThrow(BackendError);

      // Completed session cannot be paused
      const completedClient = new FixtureSessionClient(baselineSessionResponse);
      await completedClient.startMockSession();
      await expect(completedClient.pauseSession('sess-1')).rejects.toThrow(BackendError);
    });
  });

  describe('HttpSessionClient', () => {
    it('sends POST /api/sessions/mock with body {} and returns validated response', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        statusText: 'Created',
        json: async () => baselineSessionResponse,
      });
      globalThis.fetch = mockFetch;

      const client = new HttpSessionClient('/api/sessions/mock');
      const res = await client.startMockSession();

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/sessions/mock',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({}),
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
      expect(res.session_id).toBe('session-demo');
    });

    it('throws NetworkError when navigator reports offline', async () => {
      const originalOnLine = navigator.onLine;
      try {
        Object.defineProperty(navigator, 'onLine', {
          configurable: true,
          value: false,
        });

        const client = new HttpSessionClient('/api/sessions/mock');
        await expect(client.startMockSession()).rejects.toThrow(NetworkError);
        try {
          await client.startMockSession();
        } catch (e) {
          expect(e).toBeInstanceOf(NetworkError);
          expect((e as NetworkError).isOffline).toBe(true);
        }
      } finally {
        Object.defineProperty(navigator, 'onLine', {
          configurable: true,
          value: originalOnLine,
        });
      }
    });

    it('reports DEPENDENCY_UNAVAILABLE when calling pause, resume or getSessionState on 404 or 501', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({}),
      });
      const client = new HttpSessionClient('/api/sessions/mock');

      await expect(client.pauseSession('sess-123')).rejects.toThrow(BackendError);
      try {
        await client.pauseSession('sess-123');
      } catch (e) {
        expect(e).toBeInstanceOf(BackendError);
        const err = e as BackendError;
        expect(err.code).toBe('DEPENDENCY_UNAVAILABLE');
        expect(err.details.dependency).toContain('pause');
      }

      await expect(client.resumeSession('sess-123')).rejects.toThrow(BackendError);
      try {
        await client.resumeSession('sess-123');
      } catch (e) {
        expect(e).toBeInstanceOf(BackendError);
        const err = e as BackendError;
        expect(err.code).toBe('DEPENDENCY_UNAVAILABLE');
        expect(err.details.dependency).toContain('resume');
      }

      await expect(client.getSessionState('sess-123')).rejects.toThrow(BackendError);
      try {
        await client.getSessionState('sess-123');
      } catch (e) {
        expect(e).toBeInstanceOf(BackendError);
        const err = e as BackendError;
        expect(err.code).toBe('DEPENDENCY_UNAVAILABLE');
        expect(err.details.dependency).toContain('session query');
      }
    });

    it('parses backend ErrorEnvelope when response is not ok', async () => {
      const errorPayload = {
        code: 'SESSION_CREATION_FAILED',
        message_safe_for_user: 'Could not initialize mock session.',
        retryable: true,
        correlation_id: 'corr-test-422',
        details_redacted: { reason: 'capacity_exceeded' },
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: 'Unprocessable Entity',
        json: async () => errorPayload,
      });

      const client = new HttpSessionClient('/api/sessions/mock');
      await expect(client.startMockSession()).rejects.toThrow(BackendError);

      try {
        await client.startMockSession();
      } catch (e) {
        expect(e).toBeInstanceOf(BackendError);
        const err = e as BackendError;
        expect(err.code).toBe('SESSION_CREATION_FAILED');
        expect(err.correlationId).toBe('corr-test-422');
        expect(err.retryable).toBe(true);
      }
    });

    it('throws NetworkError when server returns non-envelope error or fails to parse JSON', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable',
        json: async () => {
          throw new Error('Unexpected token');
        },
      });

      const client = new HttpSessionClient('/api/sessions/mock');
      await expect(client.startMockSession()).rejects.toThrow(NetworkError);
    });

    it('throws NetworkError on network disconnect', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('Failed to fetch'));

      const client = new HttpSessionClient('/api/sessions/mock');
      await expect(client.startMockSession()).rejects.toThrow(NetworkError);
    });

    it('throws MalformedResponseError if 200 response fails schema validation', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({ session_id: 'bad', state: 'unknown' }),
      });

      const client = new HttpSessionClient('/api/sessions/mock');
      await expect(client.startMockSession()).rejects.toThrow(MalformedResponseError);
    });

    it('sends Authorization: Bearer <token> when launch token is provided', async () => {
      let capturedHeaders: Record<string, string> = {};
      globalThis.fetch = vi.fn().mockImplementation(async (_url, init) => {
        capturedHeaders = init?.headers as Record<string, string>;
        return {
          ok: true,
          status: 200,
          json: async () => baselineSessionResponse,
        };
      });

      const client = new HttpSessionClient({
        endpoint: '/api/sessions/mock',
        token: 'vbt-secret-token-12345678',
      });

      await client.startMockSession();
      expect(capturedHeaders['Authorization']).toBe('Bearer vbt-secret-token-12345678');
    });

    it('fetches events with from_sequence and approvals via HTTP client', async () => {
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes('/events?from_sequence=2')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              session_id: 'sess-1',
              from_sequence: 2,
              total_events: 2,
              has_more: false,
              events: [],
            }),
          };
        }
        if (url.includes('/approvals/appr-1')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              approval_id: 'appr-1',
              plan_id: 'plan-1',
              step_id: 'step-1',
              session_id: 'sess-1',
              status: 'rejected',
            }),
          };
        }
        if (url.includes('/approvals')) {
          return {
            ok: true,
            status: 200,
            json: async () => [
              {
                approval_id: 'appr-1',
                plan_id: 'plan-1',
                step_id: 'step-1',
                session_id: 'sess-1',
                status: 'pending',
              },
            ],
          };
        }
        return { ok: false, status: 404 };
      });

      const client = new HttpSessionClient();
      const eventsRes = await client.getEvents('sess-1', 2);
      expect(eventsRes.from_sequence).toBe(2);

      const approvals = await client.getPendingApprovals('sess-1');
      expect(approvals).toHaveLength(1);
      expect(approvals[0].approval_id).toBe('appr-1');

      const decision = await client.decideApproval('sess-1', 'appr-1', 'reject');
      expect(decision.status).toBe('rejected');
    });

    it('calls pause and resume endpoints over HTTP with Bearer token and validates returned state', async () => {
      const mockFetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
        expect(init?.headers).toMatchObject({
          Authorization: 'Bearer test-token-123',
        });

        if (url.endsWith('/pause')) {
          expect(init?.method).toBe('POST');
          return {
            ok: true,
            status: 200,
            json: async () => ({ session_id: 'sess-http-1', state: 'paused' }),
          };
        }
        if (url.endsWith('/resume')) {
          expect(init?.method).toBe('POST');
          return {
            ok: true,
            status: 200,
            json: async () => ({ session_id: 'sess-http-1', state: 'active' }),
          };
        }
        if (url.endsWith('/api/sessions/sess-http-1')) {
          expect(init?.method).toBe('GET');
          return {
            ok: true,
            status: 200,
            json: async () => ({ session_id: 'sess-http-1', state: 'active' }),
          };
        }
        return { ok: false, status: 404 };
      });
      globalThis.fetch = mockFetch;

      const client = new HttpSessionClient({
        token: 'test-token-123',
      });

      const paused = await client.pauseSession('sess-http-1');
      expect(paused).toBe('paused');

      const resumed = await client.resumeSession('sess-http-1');
      expect(resumed).toBe('active');

      const currentState = await client.getSessionState('sess-http-1');
      expect(currentState).toBe('active');
    });

    it('throws DEPENDENCY_UNAVAILABLE only when pause, resume, or getSessionState return 404 or 501', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({}),
      });

      const client = new HttpSessionClient();

      await expect(client.pauseSession('sess-missing')).rejects.toThrow(BackendError);
      try {
        await client.pauseSession('sess-missing');
      } catch (err) {
        expect(err).toBeInstanceOf(BackendError);
        expect((err as BackendError).code).toBe('DEPENDENCY_UNAVAILABLE');
      }

      await expect(client.resumeSession('sess-missing')).rejects.toThrow(BackendError);
      try {
        await client.resumeSession('sess-missing');
      } catch (err) {
        expect(err).toBeInstanceOf(BackendError);
        expect((err as BackendError).code).toBe('DEPENDENCY_UNAVAILABLE');
      }

      await expect(client.getSessionState('sess-missing')).rejects.toThrow(BackendError);
      try {
        await client.getSessionState('sess-missing');
      } catch (err) {
        expect(err).toBeInstanceOf(BackendError);
        expect((err as BackendError).code).toBe('DEPENDENCY_UNAVAILABLE');
      }
    });

    it('throws BackendError with DEPENDENCY_UNAVAILABLE when approvals endpoint returns 404 or 501', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({}),
      });

      const client = new HttpSessionClient();
      await expect(client.getPendingApprovals('sess-missing')).rejects.toThrow(BackendError);
      try {
        await client.getPendingApprovals('sess-missing');
      } catch (err) {
        expect(err).toBeInstanceOf(BackendError);
        expect((err as BackendError).code).toBe('DEPENDENCY_UNAVAILABLE');
      }

      await expect(client.decideApproval('sess-missing', 'appr-1', 'reject')).rejects.toThrow(BackendError);
      try {
        await client.decideApproval('sess-missing', 'appr-1', 'reject');
      } catch (err) {
        expect(err).toBeInstanceOf(BackendError);
        expect((err as BackendError).code).toBe('DEPENDENCY_UNAVAILABLE');
      }
    });

    // Behaviour change (review of #79): the Electron renderer must call the backend
    // same-origin (Vite proxy in dev, app:// protocol in production). An absolute
    // http://127.0.0.1:8000 URL is cross-origin and fails the CORS preflight.
    it('keeps API URLs same-origin even inside the Electron desktop shell', async () => {
      const client = new HttpSessionClient();
      expect(client.resolveUrl('http://custom-host:9000/api/mock')).toBe('http://custom-host:9000/api/mock');

      const originalVoicebot = (window as unknown as { voicebot?: unknown }).voicebot;
      (window as unknown as { voicebot?: unknown }).voicebot = {
        isElectron: true,
        getToken: () => 'vbt-test-token-123456',
        getBackendUrl: () => 'http://127.0.0.1:8000',
      };
      try {
        expect(client.resolveUrl('/api/sessions/mock')).toBe('/api/sessions/mock');

        const fetchMock = vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          json: async () => ({
            session_id: 'sess-1',
            from_sequence: 0,
            total_events: 0,
            has_more: false,
            events: [],
          }),
        });
        globalThis.fetch = fetchMock;
        await client.getEvents('sess-1', 3);
        expect(fetchMock.mock.calls[0][0]).toBe('/api/sessions/sess-1/events?from_sequence=3');
        expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer vbt-test-token-123456');
      } finally {
        (window as unknown as { voicebot?: unknown }).voicebot = originalVoicebot;
      }
    });

    it('reports a real SESSION_NOT_FOUND 404 envelope instead of DEPENDENCY_UNAVAILABLE', async () => {
      const notFound = {
        code: 'SESSION_NOT_FOUND',
        message_safe_for_user: 'Session was not found: sess-gone',
        retryable: false,
        correlation_id: 'corr-404',
        details_redacted: { session_id: 'sess-gone' },
      };
      globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => notFound });
      const client = new HttpSessionClient();
      for (const call of [
        () => client.pauseSession('sess-gone'),
        () => client.resumeSession('sess-gone'),
        () => client.getSessionState('sess-gone'),
        () => client.getPendingApprovals('sess-gone'),
      ]) {
        const err = await call().catch((e) => e);
        expect(err).toBeInstanceOf(BackendError);
        expect((err as BackendError).code).toBe('SESSION_NOT_FOUND');
        expect((err as BackendError).message).toBe('Session was not found: sess-gone');
        expect((err as BackendError).status).toBe(404);
      }

      // An unknown route (FastAPI reports HTTP_404) still means the endpoint is missing.
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ ...notFound, code: 'HTTP_404', message_safe_for_user: 'Not Found' }),
      });
      const missing = await client.pauseSession('sess-1').catch((e) => e);
      expect((missing as BackendError).code).toBe('DEPENDENCY_UNAVAILABLE');
    });

    it('parses Retry-After as seconds or HTTP-date', () => {
      expect(parseRetryAfterMs('30')).toBe(30000);
      expect(parseRetryAfterMs(null)).toBeUndefined();
      expect(parseRetryAfterMs('soon')).toBeUndefined();
      const now = Date.parse('2026-01-01T00:00:00Z');
      expect(parseRetryAfterMs('Thu, 01 Jan 2026 00:00:05 GMT', now)).toBe(5000);
      expect(parseRetryAfterMs('Thu, 01 Jan 2026 00:00:00 GMT', now + 1000)).toBe(0);
    });

    it('waits for the 429 Retry-After delay before polling events again', async () => {
      vi.useFakeTimers();
      try {
        const rateLimited = {
          code: 'RATE_LIMITED',
          message_safe_for_user: 'Rate limit exceeded. Please retry later.',
          retryable: true,
          correlation_id: 'corr-429',
          details_redacted: { retry_after: '7' },
        };
        const fetchMock = vi.fn().mockImplementation(async () => {
          if (fetchMock.mock.calls.length === 1) {
            return {
              ok: false,
              status: 429,
              headers: { get: (name: string) => (name.toLowerCase() === 'retry-after' ? '7' : null) },
              json: async () => rateLimited,
            };
          }
          return {
            ok: true,
            status: 200,
            json: async () => ({ session_id: 's', from_sequence: 0, total_events: 0, has_more: false, events: [] }),
          };
        });
        globalThis.fetch = fetchMock;

        const reconnects: { attempt: number; delayMs: number }[] = [];
        const sub = new HttpSessionClient().subscribeToEvents('s', {
          initialDelayMs: 500,
          maxDelayMs: 3000,
          pollIntervalMs: 1000,
          onEvents: () => {},
          onReconnect: (attempt, delayMs) => reconnects.push({ attempt, delayMs }),
        });

        await vi.advanceTimersByTimeAsync(10);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(reconnects).toEqual([{ attempt: 1, delayMs: 7000 }]);

        // Without Retry-After the poller would retry after 500 ms (and keep hitting the limiter).
        await vi.advanceTimersByTimeAsync(6900);
        expect(fetchMock).toHaveBeenCalledTimes(1);

        await vi.advanceTimersByTimeAsync(200);
        expect(fetchMock).toHaveBeenCalledTimes(2);
        sub.unsubscribe();
      } finally {
        vi.useRealTimers();
      }
    });

    it('stops polling on a non-retryable backend error such as 401 AUTH_REQUIRED', async () => {
      vi.useFakeTimers();
      try {
        const fetchMock = vi.fn().mockResolvedValue({
          ok: false,
          status: 401,
          json: async () => ({
            code: 'AUTH_REQUIRED',
            message_safe_for_user: 'Authentication required.',
            retryable: false,
            correlation_id: 'corr-401',
            details_redacted: {},
          }),
        });
        globalThis.fetch = fetchMock;
        const stopped: BackendError[] = [];
        const reconnects: number[] = [];
        const sub = new HttpSessionClient().subscribeToEvents('s', {
          onEvents: () => {},
          onReconnect: (attempt) => reconnects.push(attempt),
          onStopped: (err) => stopped.push(err as BackendError),
        });

        await vi.advanceTimersByTimeAsync(60000);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(reconnects).toEqual([]);
        expect(stopped).toHaveLength(1);
        expect(stopped[0].code).toBe('AUTH_REQUIRED');
        expect(stopped[0].status).toBe(401);
        sub.unsubscribe();
      } finally {
        vi.useRealTimers();
      }
    });

    it('subscribes to live event stream with automatic pagination and capped exponential backoff on failure', async () => {
      let callCount = 0;
      const mockFetch = vi.fn().mockImplementation(async () => {
        callCount++;
        if (callCount === 1) {
          // First call: returns page 1 with has_more: true
          return {
            ok: true,
            status: 200,
            json: async () => ({
              session_id: 'sess-stream',
              from_sequence: 0,
              total_events: 2,
              has_more: true,
              events: [
                {
                  event_id: 'evt-1',
                  event_type: 'transcript.segment',
                  schema_version: '1.0',
                  session_id: 'sess-stream',
                  correlation_id: 'corr-1',
                  timestamp: '2026-01-01T00:00:00Z',
                  producer: 'transcription',
                  payload: {
                    segment_id: 'seg-1',
                    session_id: 'sess-stream',
                    sequence_id: 0,
                    start_ms: 0,
                    end_ms: 500,
                    text: 'Hello',
                    confidence: 0.95,
                    language: 'en',
                    is_final: false,
                  },
                },
              ],
            }),
          };
        }
        if (callCount === 2) {
          // Second call: network failure to test backoff reconnect
          throw new Error('Network timeout');
        }
        // Subsequent calls
        return {
          ok: true,
          status: 200,
          json: async () => ({
            session_id: 'sess-stream',
            from_sequence: 1,
            total_events: 2,
            has_more: false,
            events: [],
          }),
        };
      });
      globalThis.fetch = mockFetch;

      const client = new HttpSessionClient();
      const receivedEvents: unknown[] = [];
      const reconnectAttempts: { attempt: number; delayMs: number }[] = [];

      const sub = client.subscribeToEvents('sess-stream', {
        initialDelayMs: 20,
        maxDelayMs: 50,
        pollIntervalMs: 50,
        onEvents: (evts) => receivedEvents.push(...evts),
        onReconnect: (attempt, delayMs) => reconnectAttempts.push({ attempt, delayMs }),
      });

      // Wait briefly for pagination and reconnect attempt
      await new Promise((r) => setTimeout(r, 120));
      sub.unsubscribe();

      expect(receivedEvents.length).toBeGreaterThanOrEqual(1);
      expect(reconnectAttempts.length).toBeGreaterThanOrEqual(1);
      expect(reconnectAttempts[0].attempt).toBe(1);
      expect(reconnectAttempts[0].delayMs).toBeLessThanOrEqual(50);
    });
  });

  describe('FixtureSessionClient Week 3 features', () => {
    it('supports getEvents replay with from_sequence', async () => {
      const client = new FixtureSessionClient();
      const res0 = await client.getEvents('sess-test', 0);
      expect(res0.from_sequence).toBe(0);
      expect(res0.events.length).toBeGreaterThan(0);

      const res2 = await client.getEvents('sess-test', 2);
      expect(res2.from_sequence).toBe(2);
      expect(res2.events.length).toBe(res0.events.length - 2);
    });

    it('proves rejecting approval never triggers step execution', async () => {
      const initialApproval = {
        approval_id: 'appr-risk-1',
        plan_id: 'plan-risk',
        step_id: 'step-delete-database',
        session_id: 'sess-risk',
        status: 'pending' as const,
      };

      const client = new FixtureSessionClient(undefined, 0, 'active', [initialApproval]);
      expect(client.getExecutionCount()).toBe(0);

      const pending = await client.getPendingApprovals('sess-risk');
      expect(pending).toHaveLength(1);

      // Reject the approval
      const rejected = await client.decideApproval('sess-risk', 'appr-risk-1', 'reject');
      expect(rejected.status).toBe('rejected');

      // Crucial requirement: Rejecting NEVER triggers execution!
      expect(client.getExecutionCount()).toBe(0);

      // Cannot decide already-decided approval
      await expect(client.decideApproval('sess-risk', 'appr-risk-1', 'approve')).rejects.toThrow(
        BackendError
      );
      expect(client.getExecutionCount()).toBe(0);
    });

    it('generates deterministic event IDs for approval decision audit events', async () => {
      const initialApproval = {
        approval_id: 'appr-det-1',
        plan_id: 'plan-1',
        step_id: 'step-1',
        session_id: 'sess-det',
        status: 'pending' as const,
      };

      const emptyFixture = {
        session_id: 'sess-det',
        state: 'active' as const,
        mode: 'mock' as const,
        events: [],
      };
      const client = new FixtureSessionClient(emptyFixture, 0, 'active', [initialApproval]);
      await client.decideApproval('sess-det', 'appr-det-1', 'reject');
      const events = await client.getEvents('sess-det');
      const auditEvt = events.events.find(
        (e) => e.event_type === 'workflow.audit' && (e.payload as { kind: string }).kind === 'approval_rejected'
      );
      expect(auditEvt).toBeDefined();
      expect(auditEvt?.event_id).toBe('evt-audit-decision-appr-det-1-rejected');
    });

    it('FixtureSessionClient handles Week 4 Demo Mode scripted turns, browser task approval and rejection', async () => {
      const client = new FixtureSessionClient();

      // Normal flow: request -> answer
      const ramTurn = await client.createTurn({ text: "what's using the most ram?" });
      expect(ramTurn.kind).toBe('answer');
      if (ramTurn.kind === 'answer') {
        expect(ramTurn.text).toContain('3.1 GB');
        expect(ramTurn.sources?.[0].locator).toBe('system_stats.memory');
        expect(ramTurn.spoken_text).toBe('Chrome, about 3.1 GB.');
      }

      // Clarify flow
      const clarifyTurn = await client.createTurn({ text: 'close it' });
      expect(clarifyTurn.kind).toBe('clarify');
      if (clarifyTurn.kind === 'clarify') {
        expect(clarifyTurn.question).toContain('Chrome');
      }

      // Error flow
      const errorTurn = await client.createTurn({ text: 'simulate error' });
      expect(errorTurn.kind).toBe('error');

      // Browser task proposal flow
      const proposalTurn = await client.createTurn({ text: 'open my attendance page' });
      expect(proposalTurn.kind).toBe('proposal');
      if (proposalTurn.kind === 'proposal') {
        expect(proposalTurn.requires_approval).toBe(true);
        expect(proposalTurn.approval_id).toBeDefined();
        const approvalId = proposalTurn.approval_id!;

        // Approve the browser task
        const decided = await client.decideApproval('session-demo', approvalId, 'approve');
        expect(decided.status).toBe('approved');
        expect(client.getExecutionCount()).toBe(1);

        // Verify browser.action events emitted in order
        const stream = await client.getEvents('session-demo');
        const actions = stream.events.filter((e) => e.event_type === 'browser.action');
        expect(actions).toHaveLength(3);
        expect((actions[0].payload as any).label).toBe('Read page');
        expect((actions[1].payload as any).label).toBe('Click Attendance');
        expect((actions[2].payload as any).label).toBe('Read results');
      }

      // Rejection flow guarantees zero execution
      const rejectClient = new FixtureSessionClient();
      const p2 = await rejectClient.createTurn({ text: 'open attendance portal' });
      if (p2.kind === 'proposal') {
        const rejected = await rejectClient.decideApproval('session-demo', p2.approval_id!, 'reject');
        expect(rejected.status).toBe('rejected');
        expect(rejectClient.getExecutionCount()).toBe(0);

        const st = await rejectClient.getEvents('session-demo');
        const browserActions = st.events.filter((e) => e.event_type === 'browser.action');
        expect(browserActions).toHaveLength(0);
      }

      // Capture status toggle
      expect((await client.getCaptureStatus()).status).toBe('disabled');
      client.setCaptureEnabled(true);
      expect((await client.getCaptureStatus()).status).toBe('captured');
      expect((await client.getCaptureStatus()).capture_enabled).toBe(true);

      // Listen and speech synthesis
      const listenRes = await client.triggerListen();
      expect(listenRes.status).toBe('listening');
      expect(listenRes.wake_word_detected).toBe(true);

      const speechRes = await client.synthesizeSpeech('Hello from Jarvis');
      expect(speechRes.spoken_text).toBe('Hello from Jarvis');
    });

    it('HttpSessionClient calls /api/turns, /api/capture, /api/listen, and /api/speech with Bearer token', async () => {
      const fetchMock = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes('/api/turns')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              kind: 'answer',
              text: 'Chrome, about 3.1 GB.',
              spoken_text: 'Chrome, about 3.1 GB.',
            }),
          };
        }
        if (url.includes('/api/capture')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              status: 'captured',
              frame_id: 'frame-test-1',
              capture_enabled: true,
            }),
          };
        }
        if (url.includes('/api/listen')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              status: 'listening',
              wake_word_detected: true,
            }),
          };
        }
        if (url.includes('/api/speech')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              spoken_text: 'Spoken reply',
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      });
      globalThis.fetch = fetchMock;

      const client = new HttpSessionClient({ token: 'test-bearer-token' });

      const turn = await client.createTurn({ text: 'Test query' });
      expect(turn.kind).toBe('answer');
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/turns',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer test-bearer-token',
          }),
        })
      );

      const capture = await client.getCaptureStatus();
      expect(capture.status).toBe('captured');

      const listen = await client.triggerListen();
      expect(listen.status).toBe('listening');

      const speech = await client.synthesizeSpeech('Spoken reply');
      expect(speech.spoken_text).toBe('Spoken reply');
    });
  });
});
