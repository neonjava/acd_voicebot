import { describe, it, expect } from 'vitest';
import {
  validateMockSessionResponse,
  validateTranscriptSegment,
  validateAudioChunkMetadata,
  validateErrorEnvelope,
  MalformedResponseError,
} from '../utils/validation';
import { baselineSessionResponse } from '../fixtures/baselineSession';

describe('Runtime Validation', () => {
  it('validates a valid MockSessionResponse', () => {
    const validated = validateMockSessionResponse(baselineSessionResponse);
    expect(validated.session_id).toBe('session-demo');
    expect(validated.state).toBe('completed');
    expect(validated.mode).toBe('mock');
    expect(validated.events).toHaveLength(2);
  });

  it('rejects non-object responses', () => {
    expect(() => validateMockSessionResponse('invalid string')).toThrow(MalformedResponseError);
    expect(() => validateMockSessionResponse(null)).toThrow(MalformedResponseError);
    expect(() => validateMockSessionResponse([1, 2, 3])).toThrow(MalformedResponseError);
  });

  it('rejects missing or empty session_id', () => {
    const invalid = { ...baselineSessionResponse, session_id: '   ' };
    expect(() => validateMockSessionResponse(invalid)).toThrow(MalformedResponseError);
  });

  it('rejects illegal state or mode', () => {
    expect(() =>
      validateMockSessionResponse({ ...baselineSessionResponse, state: 'active' })
    ).toThrow(MalformedResponseError);

    expect(() =>
      validateMockSessionResponse({ ...baselineSessionResponse, mode: 'real' })
    ).toThrow(MalformedResponseError);
  });

  it('rejects incompatible schema_version in envelope', () => {
    const invalid = {
      ...baselineSessionResponse,
      events: [
        {
          ...baselineSessionResponse.events[0],
          schema_version: '2.0',
        },
      ],
    };
    expect(() => validateMockSessionResponse(invalid)).toThrow(/schema_version/);
  });

  it('rejects event with mismatched session_id', () => {
    const invalid = {
      ...baselineSessionResponse,
      events: [
        {
          ...baselineSessionResponse.events[0],
          session_id: 'different-session',
        },
      ],
    };
    expect(() => validateMockSessionResponse(invalid)).toThrow(/session_id/);
  });

  it('rejects unsupported event types instead of silently accepting their payload', () => {
    const invalid = {
      ...baselineSessionResponse,
      events: [
        {
          ...baselineSessionResponse.events[0],
          event_type: 'transcript.failed',
          payload: null,
        },
      ],
    };
    expect(() => validateMockSessionResponse(invalid)).toThrow(MalformedResponseError);
    expect(() => validateMockSessionResponse(invalid)).toThrow(/Unsupported event_type/);
  });

  describe('TranscriptSegment validation', () => {
    const validSegment = {
      segment_id: 'seg-1',
      session_id: 'session-demo',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 1000,
      text: 'Hello world',
      confidence: 0.95,
      language: 'en',
      is_final: true,
    };

    it('validates a correct segment', () => {
      const res = validateTranscriptSegment(validSegment, 'session-demo');
      expect(res.segment_id).toBe('seg-1');
      expect(res.confidence).toBe(0.95);
    });

    it('rejects end_ms < start_ms', () => {
      expect(() =>
        validateTranscriptSegment({ ...validSegment, start_ms: 500, end_ms: 400 })
      ).toThrow(/cannot be less than/);
    });

    it('rejects non-integer sequence_id or timing', () => {
      expect(() =>
        validateTranscriptSegment({ ...validSegment, sequence_id: 1.5 })
      ).toThrow(/integer/);
      expect(() =>
        validateTranscriptSegment({ ...validSegment, start_ms: '0' })
      ).toThrow(/integer/);
    });

    it('rejects blank text', () => {
      expect(() =>
        validateTranscriptSegment({ ...validSegment, text: '   ' })
      ).toThrow(/non-blank/);
    });

    it('rejects confidence out of range', () => {
      expect(() =>
        validateTranscriptSegment({ ...validSegment, confidence: 1.5 })
      ).toThrow(/between 0.0 and 1.0/);
      expect(() =>
        validateTranscriptSegment({ ...validSegment, confidence: -0.1 })
      ).toThrow(/between 0.0 and 1.0/);
    });
  });

  describe('AudioChunkMetadata validation', () => {
    const validAudio = {
      sequence_id: 0,
      start_ms: 0,
      duration_ms: 1000,
      sample_rate_hz: 16000,
      channels: 1,
      size_bytes: 32000,
    };

    it('validates valid audio chunk metadata', () => {
      const res = validateAudioChunkMetadata(validAudio);
      expect(res.sample_rate_hz).toBe(16000);
      expect(res.channels).toBe(1);
    });

    it('rejects unsupported sample rate or channels', () => {
      expect(() =>
        validateAudioChunkMetadata({ ...validAudio, sample_rate_hz: 44100 })
      ).toThrow(/strictly 16000/);
      expect(() =>
        validateAudioChunkMetadata({ ...validAudio, channels: 2 })
      ).toThrow(/strictly 1/);
    });

    it('rejects non-positive duration or size', () => {
      expect(() =>
        validateAudioChunkMetadata({ ...validAudio, duration_ms: 0 })
      ).toThrow(/integer > 0/);
      expect(() =>
        validateAudioChunkMetadata({ ...validAudio, size_bytes: -10 })
      ).toThrow(/integer > 0/);
    });

    it('rejects byte size that does not match agreed fixed PCM duration (duration_ms * 32)', () => {
      // 1000ms should be 32000 bytes. Mismatched 16000 or 100 should be rejected.
      expect(() =>
        validateAudioChunkMetadata({ ...validAudio, duration_ms: 1000, size_bytes: 16000 })
      ).toThrow(/does not match agreed fixed PCM duration bytes/);

      expect(() =>
        validateAudioChunkMetadata({ ...validAudio, duration_ms: 20, size_bytes: 500 })
      ).toThrow(/does not match agreed fixed PCM duration bytes/);
    });

    it('accepts byte size that strictly matches agreed fixed PCM duration (e.g. 20ms -> 640 bytes)', () => {
      const chunk20ms = validateAudioChunkMetadata({
        ...validAudio,
        duration_ms: 20,
        size_bytes: 640,
      });
      expect(chunk20ms.size_bytes).toBe(640);
      expect(chunk20ms.duration_ms).toBe(20);
    });
  });

  describe('ErrorEnvelope validation', () => {
    it('validates safe error envelope', () => {
      const err = {
        code: 'AUDIO_INPUT_EMPTY',
        message_safe_for_user: 'Audio input cannot be empty',
        retryable: false,
        correlation_id: 'corr-123',
        details_redacted: { reason: 'buffer_empty' },
      };
      const res = validateErrorEnvelope(err);
      expect(res.code).toBe('AUDIO_INPUT_EMPTY');
      expect(res.retryable).toBe(false);
      expect(res.details_redacted.reason).toBe('buffer_empty');
    });

    it('rejects invalid retryable boolean', () => {
      const err = {
        code: 'ERROR',
        message_safe_for_user: 'Failed',
        retryable: 'yes',
        correlation_id: 'corr-123',
      };
      expect(() => validateErrorEnvelope(err)).toThrow(/boolean/);
    });
  });
});
