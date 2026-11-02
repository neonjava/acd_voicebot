import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import { App } from '../App';
import { SessionClient, BackendError } from '../services/sessionClient';
import { MockSessionResponse } from '../types/contracts';
import { baselineSessionResponse, week2StreamingSessionResponse } from '../fixtures/baselineSession';

describe('Voicebot App Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders initial UI with Mock Mode banner, Start/Stop/Pause/Resume buttons, and permission controls', () => {
    render(<App />);

    expect(screen.getByRole('region', { name: /mock mode notice/i })).toBeInTheDocument();
    expect(screen.getByText(/MOCK MODE:/i)).toBeInTheDocument();
    expect(screen.getByText(/No getUserMedia/i)).toBeInTheDocument();

    const startBtn = screen.getByTestId('start-button');
    const pauseBtn = screen.getByTestId('pause-button');
    const resumeBtn = screen.getByTestId('resume-button');
    const stopBtn = screen.getByTestId('stop-button');

    expect(startBtn).toBeEnabled();
    expect(pauseBtn).toBeDisabled();
    expect(resumeBtn).toBeDisabled();
    expect(stopBtn).toBeDisabled();

    // Backend state indicator starts at not_started
    expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: not_started/i);

    // Screen context switch exists and is OFF by default
    const screenSwitch = screen.getByTestId('screen-context-toggle');
    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');

    expect(screen.getByTestId('timeline-empty-message')).toBeInTheDocument();
    expect(screen.getByText(/Ready to start session/i)).toBeInTheDocument();
  });

  it('starts session, renders ordered transcript timeline and audio metadata', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(baselineSessionResponse),
    };

    render(<App customClient={mockClient} />);

    const startBtn = screen.getByTestId('start-button');
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/completed/i);
    });

    expect(mockClient.startMockSession).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: completed/i);

    // Verify transcript timeline
    expect(screen.getByText('Hello from the mock voicebot.')).toBeInTheDocument();
    expect(screen.getByText('[0ms – 1000ms]')).toBeInTheDocument();
    expect(screen.getByText('Final')).toBeInTheDocument();
    expect(screen.getByText(/Confidence: 100%/i)).toBeInTheDocument();

    // Verify audio events summary
    expect(screen.getByText(/event-audio-0/i)).toBeInTheDocument();
    expect(screen.getByText(/16000Hz \| 32000 bytes/i)).toBeInTheDocument();
  });

  it('handles active session with pause and resume controls and verifies actual backend state indicators', async () => {
    let currentState: 'active' | 'paused' = 'active';

    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(week2StreamingSessionResponse),
      pauseSession: vi.fn().mockImplementation(async () => {
        currentState = 'paused';
        return 'paused';
      }),
      resumeSession: vi.fn().mockImplementation(async () => {
        currentState = 'active';
        return 'active';
      }),
      getSessionState: vi.fn().mockImplementation(async () => currentState),
    };

    render(<App customClient={mockClient} />);

    // Start active session
    fireEvent.click(screen.getByTestId('start-button'));

    await waitFor(() => {
      expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: active/i);
    });

    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/UI: active/i);

    const pauseBtn = screen.getByTestId('pause-button');
    const resumeBtn = screen.getByTestId('resume-button');
    expect(pauseBtn).toBeEnabled();
    expect(resumeBtn).toBeDisabled();

    // Click Pause
    fireEvent.click(pauseBtn);

    await waitFor(() => {
      expect(mockClient.pauseSession).toHaveBeenCalledWith('session-week2-stream');
    });

    expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: paused/i);
    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/UI: paused/i);
    expect(pauseBtn).toBeDisabled();
    expect(resumeBtn).toBeEnabled();

    // Click Resume
    fireEvent.click(resumeBtn);

    await waitFor(() => {
      expect(mockClient.resumeSession).toHaveBeenCalledWith('session-week2-stream');
    });

    expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: active/i);
    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/UI: active/i);
    expect(pauseBtn).toBeEnabled();
    expect(resumeBtn).toBeDisabled();
  });

  it('does not falsely update backend state when pause fails (e.g. DEPENDENCY_UNAVAILABLE)', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(week2StreamingSessionResponse),
      pauseSession: vi.fn().mockRejectedValue(
        new BackendError({
          code: 'DEPENDENCY_UNAVAILABLE',
          message_safe_for_user: 'Backend pause endpoint unavailable.',
          retryable: true,
          correlation_id: 'corr-dep-test',
          details_redacted: { dependency: 'app.main' },
        })
      ),
    };

    render(<App customClient={mockClient} />);

    // Start active session
    fireEvent.click(screen.getByTestId('start-button'));

    await waitFor(() => {
      expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: active/i);
    });

    // Click Pause
    fireEvent.click(screen.getByTestId('pause-button'));

    await waitFor(() => {
      expect(screen.getByTestId('error-alert')).toBeInTheDocument();
    });

    // Error is shown accessibly
    const alertEl = screen.getByTestId('error-alert');
    expect(within(alertEl).getByText(/DEPENDENCY_UNAVAILABLE/i)).toBeInTheDocument();

    // Backend state indicator MUST NOT claim paused
    expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: active/i);
  });

  it('supports keyboard shortcuts: Alt+P for pause, Alt+R for resume, and Esc for stop', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(week2StreamingSessionResponse),
      pauseSession: vi.fn().mockResolvedValue('paused'),
      resumeSession: vi.fn().mockResolvedValue('active'),
    };

    render(<App customClient={mockClient} />);

    // Start session
    fireEvent.click(screen.getByTestId('start-button'));

    await waitFor(() => {
      expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: active/i);
    });

    // Alt+P to pause
    act(() => {
      fireEvent.keyDown(window, { key: 'p', altKey: true });
    });

    await waitFor(() => {
      expect(mockClient.pauseSession).toHaveBeenCalled();
      expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: paused/i);
    });

    // Alt+R to resume
    act(() => {
      fireEvent.keyDown(window, { key: 'r', altKey: true });
    });

    await waitFor(() => {
      expect(mockClient.resumeSession).toHaveBeenCalled();
      expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: active/i);
    });

    // Esc to stop
    act(() => {
      fireEvent.keyDown(window, { key: 'Escape' });
    });

    expect(screen.getByTestId('backend-state-indicator')).toHaveTextContent(/Backend: completed/i);
    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/UI: idle/i);
  });

  it('renders Screen Context Panel OFF by default and shows synthetic sources when toggled ON', () => {
    render(<App />);

    const screenToggle = screen.getByTestId('screen-context-toggle');
    expect(screenToggle).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByTestId('screen-context-disabled-message')).toHaveTextContent(/OFF by default/i);
    expect(screen.getByText(/getDisplayMedia\(\)/i)).toBeInTheDocument();

    // Toggle ON
    fireEvent.click(screenToggle);
    expect(screenToggle).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByTestId('screen-context-active-content')).toBeInTheDocument();
    expect(screen.getByText('frame-demo-0')).toBeInTheDocument();
    expect(screen.getByText('demo-dashboard')).toBeInTheDocument();
    expect(screen.getByText('synthetic_screen')).toBeInTheDocument();

    // Toggle OFF
    fireEvent.click(screenToggle);
    expect(screenToggle).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByTestId('screen-context-active-content')).not.toBeInTheDocument();
  });

  it('renders interim, revisions, and handles duplicate segments without duplication', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(week2StreamingSessionResponse),
    };

    render(<App customClient={mockClient} />);

    fireEvent.click(screen.getByTestId('start-button'));

    await waitFor(() => {
      expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/active/i);
    });

    // Finalized segment with revision badge
    expect(screen.getByText('Checking the system status and metrics now.')).toBeInTheDocument();
    expect(screen.getByText(/Revised/i)).toBeInTheDocument();

    // Active interim segment
    expect(screen.getByText('Voicebot session is actively listening')).toBeInTheDocument();
    expect(screen.getByText('Interim')).toBeInTheDocument();

    // Ensure duplicates were not rendered twice
    const matchingFinal = screen.getAllByText('Checking the system status and metrics now.');
    expect(matchingFinal).toHaveLength(1);
  });

  it('blocks start and shows accessible error when simulated permission is denied', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(baselineSessionResponse),
    };

    render(<App customClient={mockClient} />);

    const deniedRadio = screen.getByLabelText('Denied');
    fireEvent.click(deniedRadio);

    const startBtn = screen.getByTestId('start-button');
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(screen.getByTestId('error-alert')).toBeInTheDocument();
    });

    expect(screen.getByText(/Microphone Permission Denied/i)).toBeInTheDocument();
    expect(screen.getByText(/Code: SIMULATED_MIC_DENIED/i)).toBeInTheDocument();
    expect(mockClient.startMockSession).not.toHaveBeenCalled();
  });

  it('blocks start and shows error when simulated permission is unavailable', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(baselineSessionResponse),
    };

    render(<App customClient={mockClient} />);

    const unavailRadio = screen.getByLabelText('Unavailable');
    fireEvent.click(unavailRadio);

    const startBtn = screen.getByTestId('start-button');
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(screen.getByTestId('error-alert')).toBeInTheDocument();
    });

    expect(screen.getByText(/Microphone Hardware Unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/Code: SIMULATED_MIC_UNAVAILABLE/i)).toBeInTheDocument();
    expect(mockClient.startMockSession).not.toHaveBeenCalled();
  });

  it('strictly ignores late responses after Stop button is clicked', async () => {
    let resolveSession: (val: MockSessionResponse) => void = () => {};
    const deferred = new Promise<MockSessionResponse>((resolve) => {
      resolveSession = resolve;
    });

    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockReturnValue(deferred),
    };

    render(<App customClient={mockClient} />);

    // Click Start
    fireEvent.click(screen.getByTestId('start-button'));
    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/connecting/i);

    // Click Stop while in-flight
    const stopBtn = screen.getByTestId('stop-button');
    expect(stopBtn).toBeEnabled();
    fireEvent.click(stopBtn);

    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/idle/i);
    expect(screen.getByText(/Late events ignored/i)).toBeInTheDocument();

    // Late response arrives
    await act(async () => {
      resolveSession(baselineSessionResponse);
    });

    // Transcript remains empty
    expect(screen.getByTestId('timeline-empty-message')).toBeInTheDocument();
    expect(screen.queryByText('Hello from the mock voicebot.')).not.toBeInTheDocument();
  });

  it('displays malformed-response errors accessibly', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockRejectedValue(new Error('Event envelope schema_version must be "1.0"')),
    };

    render(<App customClient={mockClient} />);

    fireEvent.click(screen.getByTestId('start-button'));

    await waitFor(() => {
      expect(screen.getByTestId('error-alert')).toBeInTheDocument();
    });

    const alertEl = screen.getByTestId('error-alert');
    expect(within(alertEl).getByText(/Event envelope schema_version must be "1.0"/i)).toBeInTheDocument();
    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/failed/i);
  });

  it('surfaces transcript.error event and transitions to failed state without reporting success', async () => {
    const errorResponse: MockSessionResponse = {
      session_id: 'session-error-demo',
      state: 'completed',
      mode: 'mock',
      events: [
        {
          event_id: 'event-audio-0',
          event_type: 'audio.chunk',
          schema_version: '1.0',
          session_id: 'session-error-demo',
          correlation_id: 'correlation-demo',
          timestamp: '2026-01-01T00:00:00Z',
          producer: 'audio',
          payload: {
            sequence_id: 0,
            start_ms: 0,
            duration_ms: 1000,
            sample_rate_hz: 16000,
            channels: 1,
            size_bytes: 32000,
          },
        },
        {
          event_id: 'event-transcript-err',
          event_type: 'transcript.error',
          schema_version: '1.0',
          session_id: 'session-error-demo',
          correlation_id: 'correlation-demo',
          timestamp: '2026-01-01T00:00:00Z',
          producer: 'transcription',
          payload: {
            code: 'TRANSCRIPTION_DECODER_FAILED',
            message_safe_for_user: 'Synthetic transcriber encountered an invalid audio frame.',
            retryable: false,
            correlation_id: 'correlation-demo',
            details_redacted: { reason: 'frame_corruption' },
          },
        },
      ],
    };

    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(errorResponse),
    };

    render(<App customClient={mockClient} />);

    fireEvent.click(screen.getByTestId('start-button'));

    await waitFor(() => {
      expect(screen.getByTestId('error-alert')).toBeInTheDocument();
    });

    const alertEl = screen.getByTestId('error-alert');
    expect(within(alertEl).getByText('Synthetic transcriber encountered an invalid audio frame.')).toBeInTheDocument();
    expect(within(alertEl).getByText(/TRANSCRIPTION_DECODER_FAILED/i)).toBeInTheDocument();

    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/failed/i);
    expect(screen.queryByText(/completed successfully/i)).not.toBeInTheDocument();
  });

  it('clears prior session timeline, audio events, and sessionId when a new session starts', async () => {
    let resolveSession2: (val: MockSessionResponse) => void = () => {};
    const session2Promise = new Promise<MockSessionResponse>((resolve) => {
      resolveSession2 = resolve;
    });

    const mockClient: SessionClient = {
      startMockSession: vi
        .fn()
        .mockResolvedValueOnce(baselineSessionResponse)
        .mockReturnValueOnce(session2Promise),
    };

    render(<App customClient={mockClient} />);

    // 1. Run Session 1
    fireEvent.click(screen.getByTestId('start-button'));
    await waitFor(() => {
      expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/completed/i);
    });

    expect(screen.getByText('Hello from the mock voicebot.')).toBeInTheDocument();
    expect(screen.getByText(/event-audio-0/i)).toBeInTheDocument();

    // 2. Start Session 2
    fireEvent.click(screen.getByTestId('start-button'));

    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/connecting/i);
    expect(screen.getByTestId('timeline-empty-message')).toBeInTheDocument();
    expect(screen.queryByText('Hello from the mock voicebot.')).not.toBeInTheDocument();
    expect(screen.queryByText(/event-audio-0/i)).not.toBeInTheDocument();

    await act(async () => {
      resolveSession2(baselineSessionResponse);
    });
  });
});
