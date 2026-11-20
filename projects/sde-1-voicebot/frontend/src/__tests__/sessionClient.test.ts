import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  HttpSessionClient,
  FixtureSessionClient,
  BackendError,
  NetworkError,
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

    it('reports DEPENDENCY_UNAVAILABLE when calling pause or resume without inventing fake routes', async () => {
      const client = new HttpSessionClient('/api/sessions/mock');

      await expect(client.pauseSession('sess-123')).rejects.toThrow(BackendError);
      try {
        await client.pauseSession('sess-123');
      } catch (e) {
        expect(e).toBeInstanceOf(BackendError);
        const err = e as BackendError;
        expect(err.code).toBe('DEPENDENCY_UNAVAILABLE');
        expect(err.details.dependency).toContain('pause/resume');
      }

      await expect(client.resumeSession('sess-123')).rejects.toThrow(BackendError);
      try {
        await client.resumeSession('sess-123');
      } catch (e) {
        expect(e).toBeInstanceOf(BackendError);
        const err = e as BackendError;
        expect(err.code).toBe('DEPENDENCY_UNAVAILABLE');
      }

      await expect(client.getSessionState('sess-123')).rejects.toThrow(BackendError);
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
  });
});
