import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import { FixtureSessionClient } from '../services/sessionClient';
import { Mascot } from '../components/Mascot';
import { StepChips } from '../components/StepChips';
import { SpeechBubble } from '../components/SpeechBubble';
import { TurnResponse } from '../types/contracts';

describe('Week 4 Companion: End-to-End Scenarios, A11y & Mascot States', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Mascot Component', () => {
    it('renders and reflects all 5 states: idle, listening, thinking, working, done', () => {
      const states = ['idle', 'listening', 'thinking', 'working', 'done'] as const;

      for (const st of states) {
        const { unmount } = render(<Mascot state={st} />);
        const mascotEl = screen.getByRole('status');
        expect(mascotEl).toHaveClass(`mascot-${st}`);
        expect(mascotEl).toHaveAttribute('aria-label', expect.stringContaining(st.charAt(0).toUpperCase() + st.slice(1)));
        unmount();
      }
    });

    it('respects prefers-reduced-motion by disabling animations', () => {
      render(<Mascot state="thinking" reducedMotion={true} />);
      const mascotEl = screen.getByRole('status');
      expect(mascotEl).toHaveClass('reduced-motion');
    });
  });

  describe('StepChips Component', () => {
    it('renders step chips in sequence with correct icons and status', () => {
      const steps = [
        { id: '1', label: 'Read page', status: 'completed' as const },
        { id: '2', label: 'Click Attendance', status: 'completed' as const },
        { id: '3', label: 'Read results', status: 'running' as const },
      ];

      render(<StepChips steps={steps} />);
      expect(screen.getByText('Read page')).toBeInTheDocument();
      expect(screen.getByText('Click Attendance')).toBeInTheDocument();
      expect(screen.getByText('Read results')).toBeInTheDocument();

      const chip1 = screen.getByTestId('step-chip-1');
      expect(chip1).toHaveClass('step-chip-completed');
      expect(chip1).toHaveTextContent('✓');

      const chip3 = screen.getByTestId('step-chip-3');
      expect(chip3).toHaveClass('step-chip-running');
      expect(chip3).toHaveTextContent('◌');
    });
  });

  describe('SpeechBubble Component', () => {
    it('renders answer with sources and spoken audio indicator', () => {
      const answer: TurnResponse = {
        kind: 'answer',
        text: 'Chrome, about 3.1 GB.',
        sources: [{ id: 'src-1', label: 'psutil (system stats)', kind: 'system', locator: 'mem' }],
        spoken_text: 'Chrome, about 3.1 GB.',
      };

      render(<SpeechBubble userQuery="what's using the most ram?" turnResponse={answer} />);

      expect(screen.getByText(/what's using the most ram\?/i)).toBeInTheDocument();
      expect(screen.getByText('Chrome, about 3.1 GB.')).toBeInTheDocument();
      expect(screen.getByText('psutil (system stats)')).toBeInTheDocument();
      expect(screen.getByText(/Spoken: "Chrome, about 3.1 GB."/i)).toBeInTheDocument();
    });

    it('traps focus in task approval dialog and supports Escape to reject', () => {
      const onApprove = vi.fn();
      const onReject = vi.fn();

      const approval = {
        approval_id: 'appr-1',
        plan_id: 'plan-1',
        step_id: 'step-click',
        session_id: 'sess-1',
        status: 'pending' as const,
      };

      const proposal: TurnResponse = {
        kind: 'proposal',
        plan_id: 'plan-1',
        summary: 'Open attendance page and submit query',
        steps: [
          { step_id: 's1', tool_name: 'open_url', arguments: {}, requires_approval: false },
          { step_id: 's2', tool_name: 'click_element', arguments: {}, requires_approval: true },
        ],
        requires_approval: true,
        approval_id: 'appr-1',
      };

      render(
        <SpeechBubble
          turnResponse={proposal}
          pendingApproval={approval}
          onApprove={onApprove}
          onReject={onReject}
        />
      );

      const approveBtn = screen.getByRole('button', { name: /approve/i });
      const rejectBtn = screen.getByRole('button', { name: /reject/i });

      // Focus should be set on approve button
      expect(document.activeElement).toBe(approveBtn);

      // Press Tab to cycle to reject button
      fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Tab' });
      expect(document.activeElement).toBe(rejectBtn);

      // Press Tab on reject button cycles back to approve button (focus trap)
      fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Tab' });
      expect(document.activeElement).toBe(approveBtn);

      // Press Escape triggers reject
      fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
      expect(onReject).toHaveBeenCalledWith('appr-1');
    });
  });

  describe('End-to-End Companion Scenarios via App', () => {
    it('Scenario 1: Normal flow (request -> answer with sources & spoken audio)', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      // Type a query in the companion turn input
      const input = screen.getByTestId('turn-input');
      fireEvent.change(input, { target: { value: "what's using the most ram?" } });
      fireEvent.click(screen.getByTestId('turn-submit'));

      // Verify answer with sources is displayed
      await waitFor(() => {
        expect(screen.getByText('Chrome, about 3.1 GB.')).toBeInTheDocument();
      });
      expect(screen.getByText('psutil (system stats)')).toBeInTheDocument();
      expect(screen.getByText(/Spoken: "Chrome, about 3.1 GB."/i)).toBeInTheDocument();
    });

    it('Scenario 2: Browser task proposal approved and executed with live step chips', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      // Request browser task
      const input = screen.getByTestId('turn-input');
      fireEvent.change(input, { target: { value: 'open my attendance page' } });
      fireEvent.click(screen.getByTestId('turn-submit'));

      // Proposal with one task approval dialog is shown
      await waitFor(() => {
        expect(screen.getByText(/Open attendance page, click Attendance link, and read results/i)).toBeInTheDocument();
        expect(screen.getByTestId('approval-dialog')).toBeInTheDocument();
      });

      // Approve the browser task
      fireEvent.click(screen.getByTestId('approval-approve-button'));

      // Approval dialog closes and step execution begins
      await waitFor(() => {
        expect(screen.queryByTestId('approval-dialog')).not.toBeInTheDocument();
      });

      // Verify client execution count increased to 1
      expect(client.getExecutionCount()).toBe(1);

      // Step chips update from browser.action events
      await waitFor(() => {
        expect(screen.getByText(/Approval granted/i)).toBeInTheDocument();
      });
    });

    it('Scenario 3: Rejected approval strictly prevents any execution', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      // Request task
      const input = screen.getByTestId('turn-input');
      fireEvent.change(input, { target: { value: 'open attendance portal' } });
      fireEvent.click(screen.getByTestId('turn-submit'));

      await waitFor(() => {
        expect(screen.getByTestId('approval-dialog')).toBeInTheDocument();
      });

      // Reject the approval
      fireEvent.click(screen.getByTestId('approval-reject-button'));

      await waitFor(() => {
        expect(screen.queryByTestId('approval-dialog')).not.toBeInTheDocument();
      });

      // Crucial guarantee: execution count is strictly ZERO!
      expect(client.getExecutionCount()).toBe(0);
      expect(screen.getByText(/Step execution prevented/i)).toBeInTheDocument();
    });

    it('Scenario 4: Hey Jarvis Listen trigger sets listening mascot state', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      // Trigger Listen via button
      const listenBtn = screen.getByTestId('listen-button');
      fireEvent.click(listenBtn);

      await waitFor(() => {
        expect(screen.getByText(/Listening \("Hey Jarvis"\)/i)).toBeInTheDocument();
      });
    });

    it('Scenario 5: Keyboard shortcuts Alt+N (toggle companion) and Alt+L (listen)', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      // Alt+N toggles collapsed companion
      fireEvent.keyDown(window, { altKey: true, key: 'n' });
      await waitFor(() => {
        expect(screen.getByTestId('notch-pill')).toBeInTheDocument();
      });

      // Alt+N toggles back to expanded
      fireEvent.keyDown(window, { altKey: true, key: 'n' });
      await waitFor(() => {
        expect(screen.getByTestId('notch-expanded')).toBeInTheDocument();
      });

      // Alt+L triggers listen
      fireEvent.keyDown(window, { altKey: true, key: 'l' });
      await waitFor(() => {
        expect(screen.getByText(/Listening \("Hey Jarvis"\)/i)).toBeInTheDocument();
      });
    });

    it('Scenario 6: Privacy settings toggle is visible and OFF by default', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      const toggle = screen.getByTestId('screen-context-toggle');
      expect(toggle).toBeInTheDocument();
      expect(toggle).toHaveAttribute('aria-checked', 'false');
      expect(screen.getByTestId('screen-context-disabled-message')).toBeInTheDocument();

      // Toggle ON
      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute('aria-checked', 'true');
      expect(screen.getByTestId('screen-context-active-content')).toBeInTheDocument();
    });

    it('Scenario 7: Offline and error recovery feedback', async () => {
      const client = new FixtureSessionClient();
      render(<App customClient={client} initialExpanded={true} />);

      // Trigger error turn
      const input = screen.getByTestId('turn-input');
      fireEvent.change(input, { target: { value: 'simulate failure' } });
      fireEvent.click(screen.getByTestId('turn-submit'));

      await waitFor(() => {
        expect(screen.getAllByText(/Could not connect to service/i).length).toBeGreaterThan(0);
        expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
      });
    });
  });
});
