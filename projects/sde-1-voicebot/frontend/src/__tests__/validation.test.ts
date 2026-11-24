import { describe, it, expect } from 'vitest';
import {
  validateMockSessionResponse,
  validateTranscriptSegment,
  validateAudioChunkMetadata,
  validateErrorEnvelope,
  validateSessionLifecycleState,
  validateSourceReference,
  validateContextItem,
  validateScreenContext,
  validateReasoningResult,
  validateSpeechEvent,
  validateAuditEvent,
  validateApprovalRequest,
  validateWorkflowProposal,
  validateSessionEventStreamResponse,
  validateEventEnvelope,
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

  it('accepts valid session lifecycle states and rejects illegal state or mode', () => {
    expect(validateMockSessionResponse({ ...baselineSessionResponse, state: 'active' }).state).toBe('active');
    expect(validateMockSessionResponse({ ...baselineSessionResponse, state: 'paused' }).state).toBe('paused');
    expect(validateMockSessionResponse({ ...baselineSessionResponse, state: 'completed' }).state).toBe('completed');

    expect(() =>
      validateMockSessionResponse({ ...baselineSessionResponse, state: 'unknown_state' as any })
    ).toThrow(MalformedResponseError);

    expect(() =>
      validateMockSessionResponse({ ...baselineSessionResponse, mode: 'real' as any })
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

  describe('SessionLifecycleState validation', () => {
    it('validates all legal states', () => {
      expect(validateSessionLifecycleState('created')).toBe('created');
      expect(validateSessionLifecycleState('active')).toBe('active');
      expect(validateSessionLifecycleState('paused')).toBe('paused');
      expect(validateSessionLifecycleState('stopping')).toBe('stopping');
      expect(validateSessionLifecycleState('completed')).toBe('completed');
      expect(validateSessionLifecycleState('failed')).toBe('failed');
      expect(validateSessionLifecycleState('expired')).toBe('expired');
    });

    it('rejects illegal lifecycle states', () => {
      expect(() => validateSessionLifecycleState('stopped')).toThrow(MalformedResponseError);
      expect(() => validateSessionLifecycleState('pending')).toThrow(MalformedResponseError);
      expect(() => validateSessionLifecycleState('')).toThrow(MalformedResponseError);
      expect(() => validateSessionLifecycleState(null)).toThrow(MalformedResponseError);
    });
  });

  describe('ScreenContext and SourceReference validation', () => {
    const validSource = {
      source_id: 'src-1',
      locator: 'screen-region-header',
      kind: 'synthetic_screen' as const,
    };

    const validItem = {
      item_id: 'item-1',
      text: 'Synthetic Title',
      source: validSource,
    };

    const validScreen = {
      frame_id: 'frame-0',
      captured_at: '2026-01-01T00:00:00Z',
      capture_enabled: false,
      items: [validItem],
    };

    it('validates valid SourceReference', () => {
      const res = validateSourceReference(validSource);
      expect(res.source_id).toBe('src-1');
      expect(res.kind).toBe('synthetic_screen');
    });

    it('accepts note sources from the Week 4 RAG contract', () => {
      const res = validateSourceReference({ ...validSource, kind: 'note' });
      expect(res.kind).toBe('note');
    });

    it('rejects invalid SourceReference', () => {
      expect(() => validateSourceReference({ source_id: '', locator: 'loc' })).toThrow(MalformedResponseError);
      expect(() => validateSourceReference(null)).toThrow(MalformedResponseError);
      expect(() => validateSourceReference({ ...validSource, kind: 'invalid_kind' as any })).toThrow(MalformedResponseError);
    });

    it('validates valid ContextItem', () => {
      const res = validateContextItem(validItem);
      expect(res.item_id).toBe('item-1');
      expect(res.source.source_id).toBe('src-1');
    });

    it('rejects ContextItem with invalid fields', () => {
      expect(() => validateContextItem({ ...validItem, item_id: '' })).toThrow(/item_id/);
      expect(() => validateContextItem({ ...validItem, text: '' })).toThrow(/text/);
      expect(() => validateContextItem({ ...validItem, source: null })).toThrow(/SourceReference/);
    });

    it('validates valid ScreenContext', () => {
      const res = validateScreenContext(validScreen);
      expect(res.frame_id).toBe('frame-0');
      expect(res.capture_enabled).toBe(false);
      expect(res.items).toHaveLength(1);
    });

    it('rejects invalid ScreenContext', () => {
      expect(() => validateScreenContext({ ...validScreen, frame_id: '' })).toThrow(MalformedResponseError);
      expect(() => validateScreenContext({ ...validScreen, captured_at: '' })).toThrow(MalformedResponseError);
      expect(() => validateScreenContext({ ...validScreen, capture_enabled: 'yes' })).toThrow(MalformedResponseError);
      expect(() => validateScreenContext({ ...validScreen, items: 'not-an-array' })).toThrow(MalformedResponseError);
    });

    it('validates valid ReasoningResult', () => {
      const validReasoning = {
        request_id: 'req-1',
        session_id: 'sess-1',
        answer: 'Screen status is active.',
        source_ids: ['src-1'],
        insufficient_evidence: false,
        prompt_version: 'v1' as const,
      };
      const res = validateReasoningResult(validReasoning);
      expect(res.request_id).toBe('req-1');
      expect(res.session_id).toBe('sess-1');
      expect(res.answer).toBe('Screen status is active.');
      expect(res.source_ids).toHaveLength(1);
      expect(res.prompt_version).toBe('v1');
    });

    it('rejects invalid ReasoningResult', () => {
      expect(() =>
        validateReasoningResult({
          request_id: '',
          session_id: 'sess-1',
          answer: 'ans',
          source_ids: [],
          insufficient_evidence: false,
          prompt_version: 'v1',
        })
      ).toThrow(MalformedResponseError);

      expect(() =>
        validateReasoningResult({
          request_id: 'req-1',
          session_id: '',
          answer: 'ans',
          source_ids: [],
          insufficient_evidence: false,
          prompt_version: 'v1',
        })
      ).toThrow(MalformedResponseError);

      expect(() =>
        validateReasoningResult({
          request_id: 'req-1',
          session_id: 'sess-1',
          answer: 'ans',
          source_ids: [],
          insufficient_evidence: false,
          prompt_version: 'v2' as any,
        })
      ).toThrow(MalformedResponseError);
    });
  });

  describe('Week 3 Contracts Validation', () => {
    it('validates SpeechEvent and enforces wake field exclusivity', () => {
      const wake = validateSpeechEvent({
        kind: 'wake',
        session_id: 'sess-1',
        correlation_id: 'corr-1',
        sequence_id: 0,
        at_ms: 120,
        wake_word: 'hey voicebot',
        score: 0.95,
      });
      expect(wake.kind).toBe('wake');
      expect(wake.wake_word).toBe('hey voicebot');
      expect(wake.score).toBe(0.95);

      // Wake requires wake_word and score
      expect(() =>
        validateSpeechEvent({
          kind: 'wake',
          session_id: 'sess-1',
          correlation_id: 'corr-1',
          sequence_id: 0,
          at_ms: 120,
        })
      ).toThrow(MalformedResponseError);

      // Non-wake cannot have wake_word
      expect(() =>
        validateSpeechEvent({
          kind: 'speech_start',
          session_id: 'sess-1',
          correlation_id: 'corr-1',
          sequence_id: 1,
          at_ms: 200,
          wake_word: 'hey',
        })
      ).toThrow(MalformedResponseError);

      const speechStart = validateSpeechEvent({
        kind: 'speech_start',
        session_id: 'sess-1',
        correlation_id: 'corr-1',
        sequence_id: 1,
        at_ms: 200,
      });
      expect(speechStart.kind).toBe('speech_start');
      expect(speechStart.wake_word).toBeNull();
    });

    it('validates AuditEvent for workflow progress', () => {
      const audit = validateAuditEvent({
        sequence: 3,
        kind: 'step_succeeded',
        plan_id: 'plan-101',
        session_id: 'sess-1',
        step_id: 'step-1',
        details_redacted: { tool: 'echo' },
      });
      expect(audit.kind).toBe('step_succeeded');
      expect(audit.step_id).toBe('step-1');
      expect(audit.details_redacted?.tool).toBe('echo');

      expect(() =>
        validateAuditEvent({
          sequence: -1,
          kind: 'step_succeeded',
          plan_id: 'plan-1',
          session_id: 'sess-1',
        })
      ).toThrow(MalformedResponseError);

      expect(() =>
        validateAuditEvent({
          sequence: 0,
          kind: 'invalid_kind' as any,
          plan_id: 'plan-1',
          session_id: 'sess-1',
        })
      ).toThrow(MalformedResponseError);
    });

    it('validates ApprovalRequest status and expiry', () => {
      const pending = validateApprovalRequest({
        approval_id: 'appr-1',
        plan_id: 'plan-1',
        step_id: 'step-2',
        session_id: 'sess-1',
        status: 'pending',
        expires_at: '2026-11-20T17:00:00Z',
      });
      expect(pending.status).toBe('pending');
      expect(pending.expires_at).toBe('2026-11-20T17:00:00Z');

      expect(() =>
        validateApprovalRequest({
          approval_id: 'appr-1',
          plan_id: 'plan-1',
          step_id: 'step-2',
          session_id: 'sess-1',
          status: 'invalid' as any,
        })
      ).toThrow(MalformedResponseError);

      expect(() =>
        validateApprovalRequest({
          approval_id: 'appr-1',
          plan_id: 'plan-1',
          step_id: 'step-2',
          session_id: 'sess-1',
          status: 'pending',
          expires_at: 'invalid-date',
        })
      ).toThrow(MalformedResponseError);
    });

    it('validates WorkflowProposal and checks dependencies and max steps', () => {
      const valid = validateWorkflowProposal({
        proposal_id: 'prop-1',
        session_id: 'sess-1',
        correlation_id: 'corr-1',
        summary: 'Run automated check',
        steps: [
          {
            step_id: 's1',
            tool_name: 'read_status',
            arguments: {},
            requires_approval: false,
          },
          {
            step_id: 's2',
            tool_name: 'delete_file',
            arguments: { path: '/tmp/test' },
            requires_approval: true,
            depends_on: ['s1'],
          },
        ],
      });
      expect(valid.steps).toHaveLength(2);
      expect(valid.steps[1].depends_on).toEqual(['s1']);

      // Duplicate step IDs rejected
      expect(() =>
        validateWorkflowProposal({
          proposal_id: 'prop-1',
          session_id: 'sess-1',
          correlation_id: 'corr-1',
          summary: 'Dupe steps',
          steps: [
            { step_id: 's1', tool_name: 'a', arguments: {} },
            { step_id: 's1', tool_name: 'b', arguments: {} },
          ],
        })
      ).toThrow(MalformedResponseError);

      // Unknown dependency rejected
      expect(() =>
        validateWorkflowProposal({
          proposal_id: 'prop-1',
          session_id: 'sess-1',
          correlation_id: 'corr-1',
          summary: 'Missing dep',
          steps: [
            { step_id: 's1', tool_name: 'a', arguments: {}, depends_on: ['missing'] },
          ],
        })
      ).toThrow(MalformedResponseError);
    });

    it('validates SessionEventStreamResponse and validates nested events with audio.speech and workflow.audit', () => {
      const streamRes = validateSessionEventStreamResponse({
        session_id: 'sess-1',
        from_sequence: 0,
        total_events: 2,
        has_more: false,
        events: [
          {
            event_id: 'evt-1',
            event_type: 'audio.speech',
            schema_version: '1.0',
            session_id: 'sess-1',
            correlation_id: 'corr-1',
            timestamp: '2026-11-20T17:00:00Z',
            producer: 'audio',
            payload: {
              kind: 'speech_start',
              session_id: 'sess-1',
              correlation_id: 'corr-1',
              sequence_id: 0,
              at_ms: 50,
            },
          },
          {
            event_id: 'evt-2',
            event_type: 'workflow.audit',
            schema_version: '1.0',
            session_id: 'sess-1',
            correlation_id: 'corr-1',
            timestamp: '2026-11-20T17:00:01Z',
            producer: 'workflow',
            payload: {
              sequence: 1,
              kind: 'step_succeeded',
              plan_id: 'plan-1',
              session_id: 'sess-1',
              step_id: 'step-1',
            },
          },
        ],
      });
      expect(streamRes.events).toHaveLength(2);
      expect(streamRes.from_sequence).toBe(0);
    });

    it('validates individual event envelope and rejects unsupported event types', () => {
      const valid = validateEventEnvelope(
        {
          event_id: 'evt-direct-1',
          event_type: 'audio.speech',
          schema_version: '1.0',
          session_id: 'sess-direct',
          correlation_id: 'corr-direct',
          timestamp: '2026-11-20T17:00:00Z',
          producer: 'audio',
          payload: {
            kind: 'speech_start',
            session_id: 'sess-direct',
            correlation_id: 'corr-direct',
            sequence_id: 1,
            at_ms: 100,
          },
        },
        'sess-direct'
      );
      expect(valid.event_id).toBe('evt-direct-1');

      expect(() =>
        validateEventEnvelope(
          {
            event_id: 'evt-bad',
            event_type: 'unknown.event',
            schema_version: '1.0',
            session_id: 'sess-direct',
            correlation_id: 'corr-direct',
            timestamp: '2026-11-20T17:00:00Z',
            producer: 'test',
            payload: {},
          },
          'sess-direct'
        )
      ).toThrow(/Unsupported event_type/);
    });
  });
});
