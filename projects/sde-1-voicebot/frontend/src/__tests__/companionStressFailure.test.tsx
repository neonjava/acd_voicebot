import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import { FixtureSessionClient } from '../services/sessionClient';
import { Mascot } from '../components/Mascot';
import { getCompanionBounds } from '../../electron/bounds';
import { validateEventEnvelope, validateTurnResponse, validateCaptureStatus } from '../utils/validation';
import { TurnResponse, CaptureStatus } from '../types/contracts';

describe('Week 4 Companion: Stress, Failure, Regression & Golden Test Suite', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('1. Stress Testing: Rapid Turn Submissions & Concurrent Interactions', () => {
    it('handles multiple rapid turn submissions without dropping state or crashing', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      const input = screen.getByTestId('turn-input');
      const submit = screen.getByTestId('turn-submit');

      // Submit first turn
      fireEvent.change(input, { target: { value: "what's using the most ram?" } });
      fireEvent.click(submit);

      await waitFor(() => {
        expect(screen.getByText('Chrome, about 3.1 GB.')).toBeInTheDocument();
      });

      // Submit second turn rapidly
      fireEvent.change(input, { target: { value: 'open my attendance page' } });
      fireEvent.click(submit);

      // Verify UI settles into the proposal turn without crashing
      await waitFor(() => {
        expect(screen.getByText(/Open attendance page/i)).toBeInTheDocument();
      });
      expect(screen.getByTestId('approval-dialog')).toBeInTheDocument();
    });

    it('tolerates repeated rapid clicks on Listen trigger button', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      const listenBtn = screen.getByTestId('listen-button');
      for (let i = 0; i < 5; i++) {
        fireEvent.click(listenBtn);
      }

      await waitFor(() => {
        expect(screen.getByText(/Listening \("Hey Jarvis"\)/i)).toBeInTheDocument();
      });
    });
  });

  describe('2. Failure & Resilience: Reconnect, Stream Errors & Network Recoveries', () => {
    it('surfaces backend failures gracefully on rejected turn request', async () => {
      const client = new FixtureSessionClient();
      vi.spyOn(client, 'createTurn').mockRejectedValueOnce(new Error('Network gateway timeout'));

      render(<App customClient={client} initialExpanded={true} />);

      const input = screen.getByTestId('turn-input');
      fireEvent.change(input, { target: { value: 'test network fail' } });
      fireEvent.click(screen.getByTestId('turn-submit'));

      await waitFor(() => {
        expect(screen.getAllByText(/Network gateway timeout/i).length).toBeGreaterThan(0);
        expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
      });
    });

    it('handles unexpected malformed JSON response safely in turn validator', () => {
      expect(() => validateTurnResponse(null)).toThrow('TurnResponse must be an object');
      expect(() => validateTurnResponse({})).toThrow('TurnResponse missing valid "kind"');
      expect(() => validateTurnResponse({ kind: 'unknown_kind' })).toThrow('Unknown TurnResponse kind');
      expect(() => validateTurnResponse({ kind: 'answer' })).toThrow('TurnAnswerResponse missing string "text"');
      expect(() => validateTurnResponse({ kind: 'proposal', plan_id: 'p1' })).toThrow('TurnProposalResponse missing string "summary"');
    });

    it('handles unexpected or invalid event envelope payloads gracefully', () => {
      expect(() => validateEventEnvelope(null, 'test-stream')).toThrow('Event envelope must be an object');
      expect(() => validateEventEnvelope({ event_type: 'invalid.event' }, 'test-stream')).toThrow('Event envelope missing valid "event_id"');
      expect(() =>
        validateEventEnvelope(
          {
            event_id: 'e1',
            event_type: 'browser.action',
            schema_version: '1.0',
            timestamp: '2026-11-24T00:00:00Z',
            session_id: 's1',
            correlation_id: 'c1',
            producer: 'p1',
            payload: { action_id: 'a1', session_id: 's1' }, // missing label
          },
          's1'
        )
      ).toThrow('BrowserActionEvent missing non-empty "label"');
    });

    it('validates capture status enum strictly', () => {
      const validStatuses: CaptureStatus[] = ['captured', 'disabled', 'throttled', 'rejected', 'exhausted'];
      validStatuses.forEach((status) => {
        expect(validateCaptureStatus(status)).toBe(status);
      });
      expect(() => validateCaptureStatus('invalid_status')).toThrow('Invalid capture status');
    });
  });

  describe('3. Multi-Monitor & Extreme Bounds Edge Cases', () => {
    it('calculates companion bounds correctly with negative monitor origins (left/top monitors)', () => {
      const display = {
        x: -1920,
        y: -1080,
        width: 1920,
        height: 1080,
      };

      // Collapsed: 72x72 at bottom-right
      const collapsed = getCompanionBounds(display, false);
      expect(collapsed).toEqual({
        x: -1920 + 1920 - 72, // -72
        y: -1080 + 1080 - 72, // -72
        width: 72,
        height: 72,
      });

      // Expanded: 380x320 at bottom-right
      const expanded = getCompanionBounds(display, true);
      expect(expanded).toEqual({
        x: -1920 + 1920 - 380, // -380
        y: -1080 + 1080 - 320, // -320
        width: 380,
        height: 320,
      });
    });

    it('clamps gracefully when display workArea is smaller than expanded bounds', () => {
      const smallDisplay = {
        x: 0,
        y: 0,
        width: 300,
        height: 250,
      };

      const expanded = getCompanionBounds(smallDisplay, true);
      expect(expanded.width).toBe(300);
      expect(expanded.height).toBe(250);
      expect(expanded.x).toBe(0);
      expect(expanded.y).toBe(0);
    });

    it('respects taskbar offsets when workArea differs from display bounds', () => {
      const displayWithTaskbar = {
        x: 0,
        y: 0,
        width: 1920,
        height: 1080,
        workArea: {
          x: 0,
          y: 0,
          width: 1920,
          height: 1040, // 40px taskbar at bottom
        },
      };

      const collapsed = getCompanionBounds(displayWithTaskbar, false);
      expect(collapsed.y).toBe(1040 - 72);
      expect(collapsed.x).toBe(1920 - 72);

      const expanded = getCompanionBounds(displayWithTaskbar, true);
      expect(expanded.y).toBe(1040 - 320);
      expect(expanded.x).toBe(1920 - 380);
    });
  });

  describe('4. Regression: Zero Execution Guarantee across Sequential Cycles', () => {
    it('guarantees execution count remains strictly 0 across repeated rejections', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      const input = screen.getByTestId('turn-input');
      const submit = screen.getByTestId('turn-submit');

      // Cycle 1: Request and reject
      fireEvent.change(input, { target: { value: 'open my attendance page' } });
      fireEvent.click(submit);

      await waitFor(() => {
        expect(screen.getByTestId('approval-dialog')).toBeInTheDocument();
      });

      const rejectBtns = screen.getAllByRole('button', { name: /reject/i });
      fireEvent.click(rejectBtns[0]);

      await waitFor(() => {
        expect(screen.queryByTestId('approval-dialog')).not.toBeInTheDocument();
      });
      expect(client.getExecutionCount()).toBe(0);
      expect(screen.getByText(/Step execution prevented/i)).toBeInTheDocument();

      // Cycle 2: Request again and reject via Escape key
      fireEvent.change(input, { target: { value: 'open my attendance page' } });
      fireEvent.click(submit);

      await waitFor(() => {
        expect(screen.getByTestId('approval-dialog')).toBeInTheDocument();
      });

      const dialogs = screen.getAllByRole('dialog');
      fireEvent.keyDown(dialogs[0], { key: 'Escape' });

      await waitFor(() => {
        expect(screen.queryByTestId('approval-dialog')).not.toBeInTheDocument();
      });
      expect(client.getExecutionCount()).toBe(0);
    });
  });

  describe('5. Golden UI & Mascot State Machine Tests', () => {
    it('renders all 5 mascot states with appropriate colors and accessibility aria labels', () => {
      const states = [
        { state: 'idle' as const, label: /Idle/i },
        { state: 'listening' as const, label: /Listening/i },
        { state: 'thinking' as const, label: /Thinking/i },
        { state: 'working' as const, label: /Working/i },
        { state: 'done' as const, label: /Done/i },
      ];

      states.forEach(({ state, label }) => {
        const { unmount } = render(<Mascot state={state} />);
        const mascot = screen.getByRole('status');
        expect(mascot).toHaveAttribute('aria-label', expect.stringMatching(label));
        unmount();
      });
    });

    it('renders answer with multiple source citations cleanly', async () => {
      const client = new FixtureSessionClient();
      const mockAnswer: TurnResponse = {
        kind: 'answer',
        text: 'System memory is currently 65% utilized.',
        sources: [
          { id: 's1', label: 'psutil', kind: 'system' },
          { id: 's2', label: 'system monitor', kind: 'system' },
          { id: 's3', label: 'Activity Tracer', kind: 'system' },
        ],
        spoken_text: 'System memory is sixty-five percent utilized.',
      };
      vi.spyOn(client, 'createTurn').mockResolvedValueOnce(mockAnswer);

      render(<App customClient={client} initialExpanded={true} />);

      const input = screen.getByTestId('turn-input');
      fireEvent.change(input, { target: { value: 'check ram utilization' } });
      fireEvent.click(screen.getByTestId('turn-submit'));

      await waitFor(() => {
        expect(screen.getByText('System memory is currently 65% utilized.')).toBeInTheDocument();
        expect(screen.getByText('psutil')).toBeInTheDocument();
        expect(screen.getByText('system monitor')).toBeInTheDocument();
        expect(screen.getByText('Activity Tracer')).toBeInTheDocument();
        expect(screen.getByText(/Spoken: "System memory is sixty-five percent utilized."/i)).toBeInTheDocument();
      });
    });
  });
});
