import { MockSessionResponse, EventEnvelope, TranscriptSegment } from '../types/contracts';

/**
 * Baseline session response matching Rakshita's exact backend/tests/fixtures/session_response.json
 * and Megha's canonical transcript event specification in docs/contracts.md.
 */
export const baselineSessionResponse: MockSessionResponse = {
  session_id: 'session-demo',
  state: 'completed',
  mode: 'mock',
  events: [
    {
      event_id: 'event-audio-0',
      event_type: 'audio.chunk',
      schema_version: '1.0',
      session_id: 'session-demo',
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
      event_id: 'event-transcript-0',
      event_type: 'transcript.segment',
      schema_version: '1.0',
      session_id: 'session-demo',
      correlation_id: 'correlation-demo',
      timestamp: '2026-01-01T00:00:00Z',
      producer: 'transcription',
      payload: {
        segment_id: 'session-demo-segment-0',
        session_id: 'session-demo',
        sequence_id: 0,
        start_ms: 0,
        end_ms: 1000,
        text: 'Hello from the mock voicebot.',
        confidence: 1.0,
        language: 'en',
        is_final: true,
      },
    },
  ],
};

export const baselineTranscriptEvent: EventEnvelope<TranscriptSegment> = baselineSessionResponse.events[1] as EventEnvelope<TranscriptSegment>;
