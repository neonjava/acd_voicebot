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
  });
});
