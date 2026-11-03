import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import { App } from '../App';
import { SessionClient } from '../services/sessionClient';
import { MockSessionResponse } from '../types/contracts';
import { baselineSessionResponse } from '../fixtures/baselineSession';

describe('Voicebot App Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders initial UI with Mock Mode banner, Start/Stop buttons, and permission controls', () => {
    render(<App />);

    expect(screen.getByRole('region', { name: /mock mode notice/i })).toBeInTheDocument();
    expect(screen.getByText(/MOCK MODE:/i)).toBeInTheDocument();
    expect(screen.getByText(/No getUserMedia/i)).toBeInTheDocument();

    const startBtn = screen.getByTestId('start-button');
    const stopBtn = screen.getByTestId('stop-button');
    expect(startBtn).toBeEnabled();
    expect(stopBtn).toBeDisabled();

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

    // Verify transcript timeline
    expect(screen.getByText('Hello from the mock voicebot.')).toBeInTheDocument();
    expect(screen.getByText('[0ms – 1000ms]')).toBeInTheDocument();
    expect(screen.getByText('Final')).toBeInTheDocument();
    expect(screen.getByText(/Confidence: 100%/i)).toBeInTheDocument();

    // Verify audio events summary
    expect(screen.getByText(/event-audio-0/i)).toBeInTheDocument();
    expect(screen.getByText(/16000Hz \| 32000 bytes/i)).toBeInTheDocument();
  });

  it('blocks start and shows accessible error when simulated permission is denied', async () => {
    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockResolvedValue(baselineSessionResponse),
    };

    render(<App customClient={mockClient} />);

    // Select Denied
    const deniedRadio = screen.getByLabelText('Denied');
    fireEvent.click(deniedRadio);

    // Click Start
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

    // Select Unavailable
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

  it('triggers start and stop via keyboard shortcuts (Alt+S and Escape)', async () => {
    let resolveSession: (val: MockSessionResponse) => void = () => {};
    const deferredPromise = new Promise<MockSessionResponse>((resolve) => {
      resolveSession = resolve;
    });

    const mockClient: SessionClient = {
      startMockSession: vi.fn().mockReturnValue(deferredPromise),
    };

    render(<App customClient={mockClient} />);

    // Trigger Alt+S to start
    act(() => {
      fireEvent.keyDown(window, { key: 's', altKey: true });
    });

    expect(mockClient.startMockSession).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/connecting/i);

    // Trigger Escape to stop
    act(() => {
      fireEvent.keyDown(window, { key: 'Escape' });
    });

    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/idle/i);
    expect(screen.getByText(/Session stopped by user/i)).toBeInTheDocument();

    // Now resolve the late session response
    act(() => {
      resolveSession(baselineSessionResponse);
    });

    // Make sure late response didn't populate the timeline
    expect(screen.queryByText('Hello from the mock voicebot.')).not.toBeInTheDocument();
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

    // Error alert is shown with safe message and code
    const alertEl = screen.getByTestId('error-alert');
    expect(within(alertEl).getByText('Synthetic transcriber encountered an invalid audio frame.')).toBeInTheDocument();
    expect(within(alertEl).getByText(/TRANSCRIPTION_DECODER_FAILED/i)).toBeInTheDocument();

    // UI state indicator transitions to failed, NOT completed
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
        .mockResolvedValueOnce(baselineSessionResponse) // Session 1 resolves immediately
        .mockReturnValueOnce(session2Promise), // Session 2 is pending
    };

    render(<App customClient={mockClient} />);

    // 1. Run Session 1
    fireEvent.click(screen.getByTestId('start-button'));
    await waitFor(() => {
      expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/completed/i);
    });

    // Verify session 1 segments and audio events are present
    expect(screen.getByText('Hello from the mock voicebot.')).toBeInTheDocument();
    expect(screen.getByText(/event-audio-0/i)).toBeInTheDocument();

    // 2. Start Session 2
    fireEvent.click(screen.getByTestId('start-button'));

    // As soon as session 2 begins connecting, prior results must be cleared
    expect(screen.getByTestId('ui-state-indicator')).toHaveTextContent(/connecting/i);
    expect(screen.getByTestId('timeline-empty-message')).toBeInTheDocument();
    expect(screen.queryByText('Hello from the mock voicebot.')).not.toBeInTheDocument();
    expect(screen.queryByText(/event-audio-0/i)).not.toBeInTheDocument();

    // Clean up pending session 2
    await act(async () => {
      resolveSession2(baselineSessionResponse);
    });
  });
});
