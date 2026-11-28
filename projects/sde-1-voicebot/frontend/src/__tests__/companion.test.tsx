import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { App } from '../App';
import { FixtureSessionClient, SessionClient } from '../services/sessionClient';
import { Mascot } from '../components/Mascot';
import { StepChips, describeAction } from '../components/StepChips';
import { SpeechBubble, describeStep, turnErrorMessage } from '../components/SpeechBubble';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { BrowserActionEventPayload, TurnResponse } from '../types/contracts';
import { week3NotchSessionResponse } from '../fixtures/baselineSession';

const turnBase = { session_id: 'session-demo', turn_id: 'turn-1', source_ids: [], approvals: [] };

let actionSeq = 0;
function act(kind: BrowserActionEventPayload['action']['kind'], extra: Record<string, unknown> = {}, ok = true) {
  return {
    action: { action_id: `a-${kind}-${++actionSeq}`, session_id: 's', kind, ...extra },
    ok,
    error_code: ok ? null : 'ELEMENT_NOT_FOUND',
  } as BrowserActionEventPayload;
}

function sendTurn(text: string) {
  fireEvent.change(screen.getByTestId('turn-input'), { target: { value: text } });
  fireEvent.click(screen.getByTestId('turn-submit'));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Companion glyph (thread knot)', () => {
  it('reflects every companion state and reduced motion', () => {
    for (const st of ['idle', 'listening', 'thinking', 'working', 'done', 'error'] as const) {
      const { unmount } = render(<Mascot state={st} />);
      const knot = screen.getByTestId('companion-knot');
      expect(knot).toHaveAttribute('data-state', st);
      expect(knot).toHaveClass(`knot-${st}`);
      unmount();
    }
    render(<Mascot state="thinking" reducedMotion />);
    expect(screen.getByTestId('companion-knot')).toHaveClass('reduced-motion');
  });
});

describe('StepChips (browser.action events)', () => {
  it('labels each action kind without revealing typed text', () => {
    const s = { action_id: 'a', session_id: 's' };
    expect(describeAction({ ...s, kind: 'navigate', url: 'https://www.youtube.com/results?q=x' })).toBe(
      'Open youtube.com'
    );
    expect(describeAction({ ...s, kind: 'read_page' })).toBe('Read page');
    expect(describeAction({ ...s, kind: 'click', ref: 'e12' })).toBe('Click e12');
    expect(describeAction({ ...s, kind: 'type', ref: 'e3', text: 'hunter2' })).toBe('Type 7 characters');
    expect(describeAction({ ...s, kind: 'press_key', key: 'Enter' })).toBe('Press Enter');
    expect(describeAction({ ...s, kind: 'scroll', scroll_y: -400 })).toBe('Scroll up');
  });

  it('marks the newest chip in progress while running, and failures with their code', () => {
    const items = [act('navigate', { url: 'https://example.com' }), act('click', { ref: 'e1' })];
    const { rerender } = render(<StepChips actions={items} running />);
    const chips = screen.getAllByRole('listitem');
    expect(chips[0]).toHaveAttribute('data-status', 'done');
    expect(chips[1]).toHaveAttribute('data-status', 'active');

    rerender(<StepChips actions={items} running={false} />);
    expect(screen.getAllByRole('listitem')[1]).toHaveAttribute('data-status', 'done');

    rerender(<StepChips actions={[act('click', { ref: 'e9' }, false)]} running />);
    const failed = screen.getByRole('listitem');
    expect(failed).toHaveAttribute('data-status', 'failed');
    expect(failed).toHaveTextContent('ELEMENT_NOT_FOUND');
  });

  it('renders nothing before the first action', () => {
    const { container } = render(<StepChips actions={[]} running />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('SpeechBubble (TurnResponse)', () => {
  it('shows an answer with its sources and a clarifying question', () => {
    const answer: TurnResponse = { ...turnBase, kind: 'answer', answer: 'Chrome, 3.1 GB.', source_ids: ['system_stats'] };
    const { rerender } = render(<SpeechBubble userQuery="what uses ram?" turnResponse={answer} />);
    expect(screen.getByTestId('turn-user')).toHaveTextContent('what uses ram?');
    expect(screen.getByTestId('turn-answer')).toHaveTextContent('Chrome, 3.1 GB.');
    expect(within(screen.getByRole('list', { name: 'Sources' })).getByText('system_stats')).toBeInTheDocument();

    rerender(<SpeechBubble turnResponse={{ ...turnBase, kind: 'clarify', clarify: 'Which app?' }} />);
    expect(screen.getByTestId('turn-clarify')).toHaveTextContent('Which app?');
  });

  it('describes plan steps in plain words and shows the approval decision', () => {
    const proposal: TurnResponse = {
      ...turnBase,
      kind: 'proposal',
      proposal: {
        proposal_id: 'p1',
        session_id: 'session-demo',
        correlation_id: 'c',
        summary: 'Play lo-fi on YouTube',
        steps: [
          {
            step_id: 's1',
            tool_name: 'browser_task',
            arguments: { goal: 'play lo-fi', start_url: 'https://www.youtube.com' },
            requires_approval: true,
          },
        ],
      },
    };
    const { rerender } = render(<SpeechBubble turnResponse={proposal} />);
    expect(screen.getByRole('list', { name: 'Plan' })).toHaveTextContent('Browser task on youtube.com · needs your OK');
    rerender(<SpeechBubble turnResponse={proposal} planDecision="approved" />);
    expect(screen.getByRole('list', { name: 'Plan' })).toHaveTextContent('· approved');
    expect(
      describeStep({ step_id: 'x', tool_name: 'close_app', arguments: { app: 'Chrome' }, requires_approval: true })
    ).toBe('Close Chrome');
  });

  it('maps error codes to safe messages', () => {
    expect(turnErrorMessage('BROWSER_NOT_CONNECTED')).toMatch(/extension is not connected/);
    expect(turnErrorMessage('WEIRD')).toBe('Something went wrong (WEIRD).');
  });
});

describe('ApprovalDialog (one approval per task)', () => {
  const approval = { approval_id: 'appr-1', plan_id: 'p1', step_id: 's1', session_id: 'sess', status: 'pending' as const };

  it('explains what one approval covers, traps focus and rejects on Escape without stopping the session', () => {
    const onReject = vi.fn();
    const windowKeys = vi.fn();
    window.addEventListener('keydown', windowKeys);
    render(
      <ApprovalDialog approval={approval} onApprove={vi.fn()} onReject={onReject} task={{ goal: 'g', site: 'youtube.com' }} />
    );
    expect(screen.getByRole('dialog', { name: /Action Approval Required/ })).toHaveTextContent(
      /One approval covers this task on youtube\.com/
    );
    const approve = screen.getByRole('button', { name: /approve/i });
    const reject = screen.getByRole('button', { name: /reject/i });
    expect(document.activeElement).toBe(approve);
    fireEvent.keyDown(approve, { key: 'Tab' });
    expect(document.activeElement).toBe(reject);
    fireEvent.keyDown(reject, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(approve);
    fireEvent.keyDown(approve, { key: 'Escape' });
    expect(onReject).toHaveBeenCalledWith('appr-1');
    // Escape is handled by the dialog; it must not reach the window (where it would stop the session).
    expect(windowKeys.mock.calls.filter(([e]) => (e as KeyboardEvent).key === 'Escape')).toHaveLength(0);
    window.removeEventListener('keydown', windowKeys);
  });
});

describe('Companion end to end (App + FixtureSessionClient)', () => {
  it('answers a question with its source', async () => {
    render(<App customClient={new FixtureSessionClient()} initialExpanded />);
    sendTurn('what is using the most ram?');
    await waitFor(() =>
      expect(screen.getByTestId('turn-answer')).toHaveTextContent(/Chrome is using the most memory/)
    );
    expect(screen.getByText('system_stats')).toBeInTheDocument();
    expect(screen.getByTestId('companion-state')).toHaveTextContent('Done');
  });

  it('runs a browser task after one approval and shows each action as a chip', async () => {
    const client = new FixtureSessionClient(week3NotchSessionResponse, 0, 'active', []);
    render(<App customClient={client} initialExpanded />);
    sendTurn('open youtube and play lo-fi');

    const dialog = await screen.findByTestId('approval-dialog');
    expect(dialog).toHaveTextContent(/on youtube\.com/);
    expect(client.getExecutionCount()).toBe(0);
    expect(screen.queryByRole('list', { name: 'Browser steps' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('approval-approve-button'));
    await waitFor(() => expect(screen.getByText('Task finished.')).toBeInTheDocument());
    const chips = within(screen.getByRole('list', { name: 'Browser steps' })).getAllByRole('listitem');
    expect(chips.map((c) => c.textContent?.replace(/\s*\((done|in progress)\)$/, ''))).toEqual([
      'Open youtube.com',
      'Read page',
      'Click e12',
      'Read page',
    ]);
    expect(chips.every((c) => c.getAttribute('data-status') === 'done')).toBe(true);
    expect(client.getExecutionCount()).toBe(1);
    expect(screen.getByRole('list', { name: 'Plan' })).toHaveTextContent('approved');
    expect(screen.getByTestId('companion-state')).toHaveTextContent('Done');
  });

  it('a rejected task runs nothing', async () => {
    const client = new FixtureSessionClient(week3NotchSessionResponse, 0, 'active', []);
    render(<App customClient={client} initialExpanded />);
    sendTurn('open my attendance page');
    await screen.findByTestId('approval-dialog');
    fireEvent.click(screen.getByTestId('approval-reject-button'));
    await waitFor(() => expect(screen.queryByTestId('approval-dialog')).not.toBeInTheDocument());
    expect(screen.getByText(/Step execution prevented/)).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Browser steps' })).not.toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Plan' })).toHaveTextContent('rejected');
    expect(client.getExecutionCount()).toBe(0);
  });

  it('shows an error turn as a safe alert with its code', async () => {
    render(<App customClient={new FixtureSessionClient()} initialExpanded />);
    sendTurn('simulate an error');
    const alert = await screen.findByTestId('error-alert');
    expect(alert).toHaveTextContent(turnErrorMessage('DEPENDENCY_UNAVAILABLE'));
    expect(alert).toHaveTextContent('Code: DEPENDENCY_UNAVAILABLE');
    expect(screen.getByTestId('companion-state')).toHaveTextContent('Needs attention');
  });

  it('opens one session for the conversation and sends turns to it', async () => {
    const createSession = vi.fn().mockResolvedValue({ session_id: 'sess-42', state: 'active' });
    const createTurn = vi.fn().mockImplementation(async (sid: string, req: { text: string }) => ({
      session_id: sid,
      turn_id: `t-${req.text}`,
      kind: 'answer',
      answer: `echo ${req.text}`,
      source_ids: [],
      approvals: [],
    }));
    const client = { startMockSession: vi.fn(), createSession, createTurn } as unknown as SessionClient;
    render(<App customClient={client} initialExpanded />);
    sendTurn('one');
    await screen.findByText('echo one');
    sendTurn('two');
    await screen.findByText('echo two');
    expect(createSession).toHaveBeenCalledTimes(1);
    expect(createTurn.mock.calls.map((c) => [c[0], c[1]])).toEqual([
      ['sess-42', { text: 'one' }],
      ['sess-42', { text: 'two' }],
    ]);
  });

  it('the knot toggles listening through the listen route', async () => {
    const client = new FixtureSessionClient();
    const spy = vi.spyOn(client, 'setListening');
    render(<App customClient={client} initialExpanded />);
    const knot = screen.getByTestId('listen-button');
    fireEvent.click(knot);
    await waitFor(() => expect(knot).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.getByTestId('companion-state')).toHaveTextContent('Listening');
    fireEvent.click(knot);
    await waitFor(() => expect(knot).toHaveAttribute('aria-pressed', 'false'));
    expect(spy.mock.calls.map((c) => c[1])).toEqual(['start', 'stop']);
  });

  it('Alt+N collapses to the knot and back; Alt+L listens', async () => {
    render(<App customClient={new FixtureSessionClient()} initialExpanded />);
    fireEvent.keyDown(window, { altKey: true, key: 'n' });
    await waitFor(() => expect(screen.getByTestId('notch-pill')).toBeInTheDocument());
    expect(within(screen.getByTestId('notch-pill')).getByTestId('companion-knot')).toBeInTheDocument();
    fireEvent.keyDown(window, { altKey: true, key: 'n' });
    await waitFor(() => expect(screen.getByTestId('notch-expanded')).toBeInTheDocument());
    fireEvent.keyDown(window, { altKey: true, key: 'l' });
    await waitFor(() => expect(screen.getByText(/Listening \("Hey Jarvis"\)/)).toBeInTheDocument());
  });

  it('keeps session controls in a details section and screen context off by default', () => {
    render(<App customClient={new FixtureSessionClient()} initialExpanded />);
    const toggle = screen.getByRole('button', { name: 'Session details' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('screen-context-toggle')).toHaveAttribute('aria-checked', 'false');
  });
});
