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
});
