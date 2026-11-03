import {
  AudioChunkMetadata,
  ErrorEnvelope,
  EventEnvelope,
  MockSessionResponse,
  TranscriptSegment,
} from '../types/contracts';

export class MalformedResponseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MalformedResponseError';
  }
}

function isObject(val: unknown): val is Record<string, unknown> {
  return typeof val === 'object' && val !== null && !Array.isArray(val);
}

function isNonEmptyString(val: unknown): val is string {
  return typeof val === 'string' && val.trim().length > 0;
}

function isInteger(val: unknown): val is number {
  return typeof val === 'number' && Number.isInteger(val);
}

export function validateErrorEnvelope(val: unknown): ErrorEnvelope {
  if (!isObject(val)) {
    throw new MalformedResponseError('Error response is not a JSON object');
  }

  if (!isNonEmptyString(val.code)) {
    throw new MalformedResponseError('Error response missing valid "code"');
  }

  if (typeof val.message_safe_for_user !== 'string' || val.message_safe_for_user.length === 0) {
    throw new MalformedResponseError('Error response missing "message_safe_for_user"');
  }

  if (typeof val.retryable !== 'boolean') {
    throw new MalformedResponseError('Error response missing boolean "retryable"');
  }

  if (!isNonEmptyString(val.correlation_id)) {
    throw new MalformedResponseError('Error response missing valid "correlation_id"');
  }

  const details: Record<string, string> = {};
  if (isObject(val.details_redacted)) {
    for (const [k, v] of Object.entries(val.details_redacted)) {
      if (typeof v === 'string') {
        details[k] = v;
      }
    }
  }

  return {
    code: val.code,
    message_safe_for_user: val.message_safe_for_user,
    retryable: val.retryable,
    correlation_id: val.correlation_id,
    details_redacted: details,
  };
}

export function validateTranscriptSegment(val: unknown, expectedSessionId?: string): TranscriptSegment {
  if (!isObject(val)) {
    throw new MalformedResponseError('TranscriptSegment payload must be an object');
  }

  if (!isNonEmptyString(val.segment_id)) {
    throw new MalformedResponseError('TranscriptSegment missing non-empty "segment_id"');
  }

  if (!isNonEmptyString(val.session_id)) {
    throw new MalformedResponseError('TranscriptSegment missing non-empty "session_id"');
  }

  if (expectedSessionId && val.session_id !== expectedSessionId) {
    throw new MalformedResponseError(
      `TranscriptSegment session_id "${val.session_id}" does not match envelope session_id "${expectedSessionId}"`
    );
  }

  if (!isInteger(val.sequence_id) || val.sequence_id < 0) {
    throw new MalformedResponseError('TranscriptSegment "sequence_id" must be an integer >= 0');
  }

  if (!isInteger(val.start_ms) || val.start_ms < 0) {
    throw new MalformedResponseError('TranscriptSegment "start_ms" must be an integer >= 0');
  }

  if (!isInteger(val.end_ms) || val.end_ms < 0) {
    throw new MalformedResponseError('TranscriptSegment "end_ms" must be an integer >= 0');
  }

  if (val.end_ms < val.start_ms) {
    throw new MalformedResponseError(
      `TranscriptSegment "end_ms" (${val.end_ms}) cannot be less than "start_ms" (${val.start_ms})`
    );
  }

  if (!isNonEmptyString(val.text)) {
    throw new MalformedResponseError('TranscriptSegment "text" must be a non-blank string');
  }

  let confidence: number | null = null;
  if (val.confidence !== null && val.confidence !== undefined) {
    if (typeof val.confidence !== 'number' || Number.isNaN(val.confidence) || val.confidence < 0 || val.confidence > 1) {
      throw new MalformedResponseError('TranscriptSegment "confidence" must be between 0.0 and 1.0 or null');
    }
    confidence = val.confidence;
  }

  const language = typeof val.language === 'string' && val.language.trim().length > 0 ? val.language : 'en';

  if (typeof val.is_final !== 'boolean') {
    throw new MalformedResponseError('TranscriptSegment "is_final" must be a boolean');
  }

  return {
    segment_id: val.segment_id,
    session_id: val.session_id,
    sequence_id: val.sequence_id,
    start_ms: val.start_ms,
    end_ms: val.end_ms,
    text: val.text,
    confidence,
    language,
    is_final: val.is_final,
  };
}

export function validateAudioChunkMetadata(val: unknown): AudioChunkMetadata {
  if (!isObject(val)) {
    throw new MalformedResponseError('AudioChunkMetadata payload must be an object');
  }

  if (!isInteger(val.sequence_id) || val.sequence_id < 0) {
    throw new MalformedResponseError('AudioChunkMetadata "sequence_id" must be an integer >= 0');
  }

  if (!isInteger(val.start_ms) || val.start_ms < 0) {
    throw new MalformedResponseError('AudioChunkMetadata "start_ms" must be an integer >= 0');
  }

  if (!isInteger(val.duration_ms) || val.duration_ms <= 0) {
    throw new MalformedResponseError('AudioChunkMetadata "duration_ms" must be an integer > 0');
  }

  if (val.sample_rate_hz !== 16000) {
    throw new MalformedResponseError('AudioChunkMetadata "sample_rate_hz" must be strictly 16000');
  }

  if (val.channels !== 1) {
    throw new MalformedResponseError('AudioChunkMetadata "channels" must be strictly 1');
  }

  if (!isInteger(val.size_bytes) || val.size_bytes <= 0) {
    throw new MalformedResponseError('AudioChunkMetadata "size_bytes" must be an integer > 0');
  }

  const expectedBytes = val.duration_ms * 32; // 16000 Hz * 1 channel * 2 bytes per sample / 1000 ms
  if (val.size_bytes !== expectedBytes) {
    throw new MalformedResponseError(
      `AudioChunkMetadata "size_bytes" (${val.size_bytes}) does not match agreed fixed PCM duration bytes (${expectedBytes} for ${val.duration_ms}ms at 16000Hz 16-bit mono)`
    );
  }

  return {
    sequence_id: val.sequence_id,
    start_ms: val.start_ms,
    duration_ms: val.duration_ms,
    sample_rate_hz: 16000,
    channels: 1,
    size_bytes: val.size_bytes,
  };
}

export function validateEventEnvelope(val: unknown, expectedSessionId: string): EventEnvelope {
  if (!isObject(val)) {
    throw new MalformedResponseError('Event envelope must be an object');
  }

  if (!isNonEmptyString(val.event_id)) {
    throw new MalformedResponseError('Event envelope missing valid "event_id"');
  }

  if (!isNonEmptyString(val.event_type)) {
    throw new MalformedResponseError('Event envelope missing valid "event_type"');
  }

  if (val.schema_version !== '1.0') {
    throw new MalformedResponseError(`Event envelope schema_version must be "1.0", got "${val.schema_version}"`);
  }

  if (!isNonEmptyString(val.session_id) || val.session_id !== expectedSessionId) {
    throw new MalformedResponseError(
      `Event envelope session_id "${val.session_id}" does not match session response session_id "${expectedSessionId}"`
    );
  }

  if (!isNonEmptyString(val.correlation_id)) {
    throw new MalformedResponseError('Event envelope missing valid "correlation_id"');
  }

  if (!isNonEmptyString(val.timestamp)) {
    throw new MalformedResponseError('Event envelope timestamp must be a non-empty string');
  }

  if (!isNonEmptyString(val.producer)) {
    throw new MalformedResponseError('Event envelope missing valid "producer"');
  }

  let payload: unknown = val.payload;
  if (val.event_type === 'transcript.segment') {
    payload = validateTranscriptSegment(val.payload, expectedSessionId);
  } else if (val.event_type === 'audio.chunk') {
    payload = validateAudioChunkMetadata(val.payload);
  } else if (val.event_type === 'transcript.error') {
    payload = validateErrorEnvelope(val.payload);
  } else {
    throw new MalformedResponseError(`Unsupported event_type "${val.event_type}"`);
  }

  return {
    event_id: val.event_id,
    event_type: val.event_type,
    schema_version: '1.0',
    session_id: val.session_id,
    correlation_id: val.correlation_id,
    timestamp: val.timestamp,
    producer: val.producer,
    payload,
  };
}

export function validateMockSessionResponse(data: unknown): MockSessionResponse {
  if (!isObject(data)) {
    throw new MalformedResponseError('Session response must be a JSON object');
  }

  if (!isNonEmptyString(data.session_id)) {
    throw new MalformedResponseError('Session response missing non-empty "session_id"');
  }

  if (data.state !== 'completed') {
    throw new MalformedResponseError(`Session response state must be "completed", got "${data.state}"`);
  }

  if (data.mode !== 'mock') {
    throw new MalformedResponseError(`Session response mode must be "mock", got "${data.mode}"`);
  }

  if (!Array.isArray(data.events)) {
    throw new MalformedResponseError('Session response "events" must be an array');
  }

  const events = data.events.map((evt) => validateEventEnvelope(evt, data.session_id as string));

  return {
    session_id: data.session_id,
    state: 'completed',
    mode: 'mock',
    events,
  };
}
