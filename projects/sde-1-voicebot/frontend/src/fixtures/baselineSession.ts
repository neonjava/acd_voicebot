import canonicalSessionResponse from '../../../backend/tests/fixtures/session_response.json';
import {
  ApprovalRequest,
  AuditEvent,
  EventEnvelope,
  MockSessionResponse,
  SpeechEvent,
  TranscriptSegment,
} from '../types/contracts';

/**
 * Baseline session response loaded directly from the canonical backend fixture:
 * projects/sde-1-voicebot/backend/tests/fixtures/session_response.json
 *
 * Avoids maintaining a separate TypeScript duplicate and guarantees 100% wire parity.
 */
export const baselineSessionResponse: MockSessionResponse = canonicalSessionResponse as unknown as MockSessionResponse;

export const baselineTranscriptEvent: EventEnvelope<TranscriptSegment> = baselineSessionResponse.events.find(
  (evt) => evt.event_type === 'transcript.segment'
) as EventEnvelope<TranscriptSegment>;

/**
 * Week 2 active streaming fixture:
 * - Session state: 'active' (enables pause/resume controls verification)
 * - Interim transcript segment with revision
 * - Finalized transcript segment
 * - Duplicate segment event (tests duplicate handling)
 * - Active interim segment with confidence
 * - Audio chunks strictly matching 32 bytes/ms duration
 */
export const week2StreamingSessionResponse: MockSessionResponse = {
  session_id: 'session-week2-stream',
  state: 'active',
  mode: 'mock',
  events: [
    {
      event_id: 'event-audio-0',
      event_type: 'audio.chunk',
      schema_version: '1.0',
      session_id: 'session-week2-stream',
      correlation_id: 'corr-week2-0',
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
      event_id: 'event-transcript-0a',
      event_type: 'transcript.segment',
      schema_version: '1.0',
      session_id: 'session-week2-stream',
      correlation_id: 'corr-week2-0',
      timestamp: '2026-01-01T00:00:00.500Z',
      producer: 'transcription',
      payload: {
        segment_id: 'seg-0',
        session_id: 'session-week2-stream',
        sequence_id: 0,
        start_ms: 0,
        end_ms: 500,
        text: 'Checking the status',
        confidence: 0.85,
        language: 'en',
        is_final: false,
      },
    },
    {
      event_id: 'event-transcript-0b',
      event_type: 'transcript.segment',
      schema_version: '1.0',
      session_id: 'session-week2-stream',
      correlation_id: 'corr-week2-0',
      timestamp: '2026-01-01T00:00:00.800Z',
      producer: 'transcription',
      payload: {
        segment_id: 'seg-0',
        session_id: 'session-week2-stream',
        sequence_id: 1,
        start_ms: 0,
        end_ms: 800,
        text: 'Checking the system status and metrics',
        confidence: 0.92,
        language: 'en',
        is_final: false,
      },
    },
    {
      event_id: 'event-transcript-0c',
      event_type: 'transcript.segment',
      schema_version: '1.0',
      session_id: 'session-week2-stream',
      correlation_id: 'corr-week2-0',
      timestamp: '2026-01-01T00:00:01.000Z',
      producer: 'transcription',
      payload: {
        segment_id: 'seg-0',
        session_id: 'session-week2-stream',
        sequence_id: 2,
        start_ms: 0,
        end_ms: 1000,
        text: 'Checking the system status and metrics now.',
        confidence: 0.98,
        language: 'en',
        is_final: true,
      },
    },
    {
      event_id: 'event-transcript-0c-dup',
      event_type: 'transcript.segment',
      schema_version: '1.0',
      session_id: 'session-week2-stream',
      correlation_id: 'corr-week2-0',
      timestamp: '2026-01-01T00:00:01.000Z',
      producer: 'transcription',
      payload: {
        segment_id: 'seg-0',
        session_id: 'session-week2-stream',
        sequence_id: 2,
        start_ms: 0,
        end_ms: 1000,
        text: 'Checking the system status and metrics now.',
        confidence: 0.98,
        language: 'en',
        is_final: true,
      },
    },
    {
      event_id: 'event-audio-1',
      event_type: 'audio.chunk',
      schema_version: '1.0',
      session_id: 'session-week2-stream',
      correlation_id: 'corr-week2-1',
      timestamp: '2026-01-01T00:00:01.000Z',
      producer: 'audio',
      payload: {
        sequence_id: 1,
        start_ms: 1000,
        duration_ms: 500,
        sample_rate_hz: 16000,
        channels: 1,
        size_bytes: 16000,
      },
    },
    {
      event_id: 'event-transcript-1',
      event_type: 'transcript.segment',
      schema_version: '1.0',
      session_id: 'session-week2-stream',
      correlation_id: 'corr-week2-1',
      timestamp: '2026-01-01T00:00:01.500Z',
      producer: 'transcription',
      payload: {
        segment_id: 'seg-1',
        session_id: 'session-week2-stream',
        sequence_id: 3,
        start_ms: 1000,
        end_ms: 1500,
        text: 'Voicebot session is actively listening',
        confidence: 0.88,
        language: 'en',
        is_final: false,
      },
    },
  ],
};

/**
 * Week 3 Live Notch & Progress Fixtures
 */
export const baselineApprovalRequest: ApprovalRequest = {
  approval_id: 'appr-w3-001',
  plan_id: 'plan-system-health',
  step_id: 'step-run-diagnostic',
  session_id: 'session-week3-notch',
  status: 'pending',
  expires_at: '2026-12-31T23:59:59Z',
};

export const week3NotchSessionResponse: MockSessionResponse = {
  session_id: 'session-week3-notch',
  state: 'active',
  mode: 'mock',
  events: [
    {
      event_id: 'event-speech-wake',
      event_type: 'audio.speech',
      schema_version: '1.0',
      session_id: 'session-week3-notch',
      correlation_id: 'corr-w3-1',
      timestamp: '2026-01-01T00:00:00.100Z',
      producer: 'audio',
      payload: {
        kind: 'wake',
        session_id: 'session-week3-notch',
        correlation_id: 'corr-w3-1',
        sequence_id: 0,
        at_ms: 100,
        wake_word: 'hey voicebot',
        score: 0.98,
      } as SpeechEvent,
    },
    {
      event_id: 'event-audio-chunk-0',
      event_type: 'audio.chunk',
      schema_version: '1.0',
      session_id: 'session-week3-notch',
      correlation_id: 'corr-w3-1',
      timestamp: '2026-01-01T00:00:00.200Z',
      producer: 'audio',
      payload: {
        sequence_id: 0,
        start_ms: 0,
        duration_ms: 500,
        sample_rate_hz: 16000,
        channels: 1,
        size_bytes: 16000,
      },
    },
    {
      event_id: 'event-caption-0',
      event_type: 'transcript.segment',
      schema_version: '1.0',
      session_id: 'session-week3-notch',
      correlation_id: 'corr-w3-1',
      timestamp: '2026-01-01T00:00:00.500Z',
      producer: 'transcription',
      payload: {
        segment_id: 'seg-caption-0',
        session_id: 'session-week3-notch',
        sequence_id: 1,
        start_ms: 0,
        end_ms: 500,
        text: 'Checking server health and logs',
        confidence: 0.95,
        language: 'en',
        is_final: true,
      },
    },
    {
      event_id: 'event-audit-0',
      event_type: 'workflow.audit',
      schema_version: '1.0',
      session_id: 'session-week3-notch',
      correlation_id: 'corr-w3-1',
      timestamp: '2026-01-01T00:00:00.700Z',
      producer: 'workflow',
      payload: {
        sequence: 0,
        kind: 'step_succeeded',
        plan_id: 'plan-system-health',
        session_id: 'session-week3-notch',
        step_id: 'step-read-metrics',
        details_redacted: { tool: 'read_metrics' },
      } as AuditEvent,
    },
  ],
};
