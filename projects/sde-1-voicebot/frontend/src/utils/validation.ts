import {
  ApprovalRequest,
  AuditEvent,
  AuditKind,
  AudioChunkMetadata,
  ContextItem,
  ErrorEnvelope,
  EventEnvelope,
  MockSessionResponse,
  ReasoningResult,
  ScreenContext,
  SessionEventStreamResponse,
  SessionLifecycleState,
  SourceReference,
  SpeechEvent,
  SpeechEventKind,
  TranscriptSegment,
  WorkflowProposal,
  WorkflowStep,
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

export const VALID_SESSION_STATES: ReadonlySet<SessionLifecycleState> = new Set([
  'created',
  'active',
  'paused',
  'stopping',
  'completed',
  'failed',
  'expired',
]);

export function validateSessionLifecycleState(val: unknown): SessionLifecycleState {
  if (typeof val !== 'string' || !VALID_SESSION_STATES.has(val as SessionLifecycleState)) {
    throw new MalformedResponseError(
      `Invalid session lifecycle state "${String(val)}". Expected one of: ${Array.from(VALID_SESSION_STATES).join(', ')}`
    );
  }
  return val as SessionLifecycleState;
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
  } else if (val.event_type === 'audio.speech') {
    payload = validateSpeechEvent(val.payload, expectedSessionId);
  } else if (val.event_type === 'workflow.audit') {
    payload = validateAuditEvent(val.payload, expectedSessionId);
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

  const validatedState = validateSessionLifecycleState(data.state);

  if (data.mode !== 'mock') {
    throw new MalformedResponseError(`Session response mode must be "mock", got "${data.mode}"`);
  }

  if (!Array.isArray(data.events)) {
    throw new MalformedResponseError('Session response "events" must be an array');
  }

  const events = data.events.map((evt) => validateEventEnvelope(evt, data.session_id as string));

  return {
    session_id: data.session_id,
    state: validatedState,
    mode: 'mock',
    events,
  };
}

/**
 * Validation for Screen Context & Reasoning models.
 */
export function validateSourceReference(val: unknown): SourceReference {
  if (!isObject(val)) {
    throw new MalformedResponseError('SourceReference must be an object');
  }

  if (!isNonEmptyString(val.source_id)) {
    throw new MalformedResponseError('SourceReference missing non-empty "source_id"');
  }

  if (!isNonEmptyString(val.locator)) {
    throw new MalformedResponseError('SourceReference missing non-empty "locator"');
  }

  if (val.kind !== 'synthetic_screen' && val.kind !== 'transcript' && val.kind !== 'note') {
    throw new MalformedResponseError(
      `SourceReference "kind" must be "synthetic_screen", "transcript" or "note", got "${val.kind}"`
    );
  }

  return {
    source_id: val.source_id,
    locator: val.locator,
    kind: val.kind,
  };
}

export function validateContextItem(val: unknown): ContextItem {
  if (!isObject(val)) {
    throw new MalformedResponseError('ContextItem must be an object');
  }

  if (!isNonEmptyString(val.item_id)) {
    throw new MalformedResponseError('ContextItem missing non-empty "item_id"');
  }

  if (!isNonEmptyString(val.text)) {
    throw new MalformedResponseError('ContextItem missing non-empty "text"');
  }

  const source = validateSourceReference(val.source);

  return {
    item_id: val.item_id,
    text: val.text,
    source,
  };
}

export function validateScreenContext(val: unknown): ScreenContext {
  if (!isObject(val)) {
    throw new MalformedResponseError('ScreenContext must be an object');
  }

  if (!isNonEmptyString(val.frame_id)) {
    throw new MalformedResponseError('ScreenContext missing non-empty "frame_id"');
  }

  if (!isNonEmptyString(val.captured_at)) {
    throw new MalformedResponseError('ScreenContext missing non-empty "captured_at"');
  }

  if (typeof val.capture_enabled !== 'boolean') {
    throw new MalformedResponseError('ScreenContext "capture_enabled" must be a boolean');
  }

  if (!Array.isArray(val.items)) {
    throw new MalformedResponseError('ScreenContext "items" must be an array');
  }

  const items = val.items.map((item) => validateContextItem(item));

  return {
    frame_id: val.frame_id,
    captured_at: val.captured_at,
    capture_enabled: val.capture_enabled,
    items,
  };
}

export function validateReasoningResult(val: unknown): ReasoningResult {
  if (!isObject(val)) {
    throw new MalformedResponseError('ReasoningResult must be an object');
  }

  if (!isNonEmptyString(val.request_id)) {
    throw new MalformedResponseError('ReasoningResult missing non-empty "request_id"');
  }

  if (!isNonEmptyString(val.session_id)) {
    throw new MalformedResponseError('ReasoningResult missing non-empty "session_id"');
  }

  if (!isNonEmptyString(val.answer)) {
    throw new MalformedResponseError('ReasoningResult missing non-empty "answer"');
  }

  if (val.prompt_version !== 'v1') {
    throw new MalformedResponseError(`ReasoningResult "prompt_version" must be "v1", got "${val.prompt_version}"`);
  }

  if (typeof val.insufficient_evidence !== 'boolean') {
    throw new MalformedResponseError('ReasoningResult "insufficient_evidence" must be a boolean');
  }

  if (!Array.isArray(val.source_ids)) {
    throw new MalformedResponseError('ReasoningResult "source_ids" must be an array');
  }

  const sourceIds: string[] = [];
  for (const s of val.source_ids) {
    if (!isNonEmptyString(s)) {
      throw new MalformedResponseError('ReasoningResult source_ids contains non-string or blank ID');
    }
    sourceIds.push(s);
  }

  const uniqueSourceIds = Array.from(new Set(sourceIds));
  if (uniqueSourceIds.length !== sourceIds.length) {
    throw new MalformedResponseError('ReasoningResult source_ids must be unique');
  }

  if (val.insufficient_evidence && sourceIds.length > 0) {
    throw new MalformedResponseError('ReasoningResult with insufficient_evidence cannot cite sources');
  }

  if (!val.insufficient_evidence && sourceIds.length === 0) {
    throw new MalformedResponseError('ReasoningResult with grounded answer must cite at least one source');
  }

  return {
    request_id: val.request_id,
    session_id: val.session_id,
    answer: val.answer,
    source_ids: sourceIds,
    insufficient_evidence: val.insufficient_evidence,
    prompt_version: 'v1',
  };
}

export const VALID_SPEECH_EVENT_KINDS: ReadonlySet<SpeechEventKind> = new Set([
  'wake',
  'speech_start',
  'speech_end',
]);

export function validateSpeechEvent(val: unknown, expectedSessionId?: string): SpeechEvent {
  if (!isObject(val)) {
    throw new MalformedResponseError('SpeechEvent must be an object');
  }

  if (typeof val.kind !== 'string' || !VALID_SPEECH_EVENT_KINDS.has(val.kind as SpeechEventKind)) {
    throw new MalformedResponseError(`Invalid SpeechEvent kind "${val.kind}"`);
  }

  if (!isNonEmptyString(val.session_id)) {
    throw new MalformedResponseError('SpeechEvent missing non-empty "session_id"');
  }

  if (expectedSessionId && val.session_id !== expectedSessionId) {
    throw new MalformedResponseError(
      `SpeechEvent session_id "${val.session_id}" does not match expected "${expectedSessionId}"`
    );
  }

  if (!isNonEmptyString(val.correlation_id)) {
    throw new MalformedResponseError('SpeechEvent missing non-empty "correlation_id"');
  }

  if (!isInteger(val.sequence_id) || val.sequence_id < 0) {
    throw new MalformedResponseError('SpeechEvent sequence_id must be an integer >= 0');
  }

  if (!isInteger(val.at_ms) || val.at_ms < 0) {
    throw new MalformedResponseError('SpeechEvent at_ms must be an integer >= 0');
  }

  const isWake = val.kind === 'wake';
  const hasWakeWord = isNonEmptyString(val.wake_word);
  const hasScore = typeof val.score === 'number' && val.score >= 0.0 && val.score <= 1.0;

  if (isWake) {
    if (!hasWakeWord || !hasScore) {
      throw new MalformedResponseError('SpeechEvent with kind "wake" requires non-empty wake_word and score in [0.0, 1.0]');
    }
  } else {
    if (val.wake_word !== undefined && val.wake_word !== null) {
      throw new MalformedResponseError('SpeechEvent wake_word is only permitted on "wake" events');
    }
    if (val.score !== undefined && val.score !== null) {
      throw new MalformedResponseError('SpeechEvent score is only permitted on "wake" events');
    }
  }

  return {
    kind: val.kind as SpeechEventKind,
    session_id: val.session_id,
    correlation_id: val.correlation_id,
    sequence_id: val.sequence_id,
    at_ms: val.at_ms,
    wake_word: isWake ? (val.wake_word as string) : null,
    score: isWake ? (val.score as number) : null,
  };
}

export const VALID_AUDIT_KINDS: ReadonlySet<AuditKind> = new Set([
  'approval_granted',
  'approval_rejected',
  'approval_expired',
  'approval_missing',
  'step_succeeded',
  'step_failed',
  'step_timed_out',
  'step_retried',
  'workflow_cancelled',
]);

export function validateAuditEvent(val: unknown, expectedSessionId?: string): AuditEvent {
  if (!isObject(val)) {
    throw new MalformedResponseError('AuditEvent must be an object');
  }

  if (!isInteger(val.sequence) || val.sequence < 0) {
    throw new MalformedResponseError('AuditEvent sequence must be an integer >= 0');
  }

  if (typeof val.kind !== 'string' || !VALID_AUDIT_KINDS.has(val.kind as AuditKind)) {
    throw new MalformedResponseError(`Invalid AuditEvent kind "${val.kind}"`);
  }

  if (!isNonEmptyString(val.plan_id)) {
    throw new MalformedResponseError('AuditEvent missing non-empty "plan_id"');
  }

  if (!isNonEmptyString(val.session_id)) {
    throw new MalformedResponseError('AuditEvent missing non-empty "session_id"');
  }

  if (expectedSessionId && val.session_id !== expectedSessionId) {
    throw new MalformedResponseError(
      `AuditEvent session_id "${val.session_id}" does not match expected "${expectedSessionId}"`
    );
  }

  const stepId = isNonEmptyString(val.step_id) ? val.step_id : null;
  const approvalId = isNonEmptyString(val.approval_id) ? val.approval_id : null;

  const details: Record<string, string> = {};
  if (isObject(val.details_redacted)) {
    for (const [k, v] of Object.entries(val.details_redacted)) {
      if (typeof v === 'string') {
        details[k] = v;
      }
    }
  }

  return {
    sequence: val.sequence,
    kind: val.kind as AuditKind,
    plan_id: val.plan_id,
    session_id: val.session_id,
    step_id: stepId,
    approval_id: approvalId,
    details_redacted: details,
  };
}

export function validateApprovalRequest(val: unknown, expectedSessionId?: string): ApprovalRequest {
  if (!isObject(val)) {
    throw new MalformedResponseError('ApprovalRequest must be an object');
  }

  if (!isNonEmptyString(val.approval_id)) {
    throw new MalformedResponseError('ApprovalRequest missing non-empty "approval_id"');
  }

  if (!isNonEmptyString(val.plan_id)) {
    throw new MalformedResponseError('ApprovalRequest missing non-empty "plan_id"');
  }

  if (!isNonEmptyString(val.step_id)) {
    throw new MalformedResponseError('ApprovalRequest missing non-empty "step_id"');
  }

  if (!isNonEmptyString(val.session_id)) {
    throw new MalformedResponseError('ApprovalRequest missing non-empty "session_id"');
  }

  if (expectedSessionId && val.session_id !== expectedSessionId) {
    throw new MalformedResponseError(
      `ApprovalRequest session_id "${val.session_id}" does not match expected "${expectedSessionId}"`
    );
  }

  if (val.status !== 'pending' && val.status !== 'approved' && val.status !== 'rejected') {
    throw new MalformedResponseError(`ApprovalRequest status must be pending/approved/rejected, got "${val.status}"`);
  }

  let expiresAt: string | null = null;
  if (val.expires_at !== undefined && val.expires_at !== null) {
    if (typeof val.expires_at !== 'string' || Number.isNaN(Date.parse(val.expires_at))) {
      throw new MalformedResponseError('ApprovalRequest expires_at must be a valid ISO date string');
    }
    expiresAt = val.expires_at;
  }

  return {
    approval_id: val.approval_id,
    plan_id: val.plan_id,
    step_id: val.step_id,
    session_id: val.session_id,
    status: val.status,
    expires_at: expiresAt,
  };
}

export function validateWorkflowStep(val: unknown): WorkflowStep {
  if (!isObject(val)) {
    throw new MalformedResponseError('WorkflowStep must be an object');
  }

  if (!isNonEmptyString(val.step_id)) {
    throw new MalformedResponseError('WorkflowStep missing non-empty "step_id"');
  }

  if (!isNonEmptyString(val.tool_name)) {
    throw new MalformedResponseError('WorkflowStep missing non-empty "tool_name"');
  }

  if (!isObject(val.arguments)) {
    throw new MalformedResponseError('WorkflowStep arguments must be a dictionary object');
  }

  const args: Record<string, string> = {};
  for (const [k, v] of Object.entries(val.arguments)) {
    if (typeof v !== 'string') {
      throw new MalformedResponseError(`WorkflowStep argument "${k}" must be a string`);
    }
    args[k] = v;
  }

  const requiresApproval = typeof val.requires_approval === 'boolean' ? val.requires_approval : true;

  const dependsOn: string[] = [];
  if (Array.isArray(val.depends_on)) {
    for (const d of val.depends_on) {
      if (!isNonEmptyString(d)) {
        throw new MalformedResponseError('WorkflowStep depends_on entries must be non-empty strings');
      }
      if (d === val.step_id) {
        throw new MalformedResponseError(`WorkflowStep "${val.step_id}" cannot depend on itself`);
      }
      dependsOn.push(d);
    }
  }

  return {
    step_id: val.step_id,
    tool_name: val.tool_name,
    arguments: args,
    requires_approval: requiresApproval,
    depends_on: dependsOn,
  };
}

export function validateWorkflowProposal(val: unknown): WorkflowProposal {
  if (!isObject(val)) {
    throw new MalformedResponseError('WorkflowProposal must be an object');
  }

  if (!isNonEmptyString(val.proposal_id)) {
    throw new MalformedResponseError('WorkflowProposal missing non-empty "proposal_id"');
  }

  if (!isNonEmptyString(val.session_id)) {
    throw new MalformedResponseError('WorkflowProposal missing non-empty "session_id"');
  }

  if (!isNonEmptyString(val.correlation_id)) {
    throw new MalformedResponseError('WorkflowProposal missing non-empty "correlation_id"');
  }

  if (!isNonEmptyString(val.summary) || val.summary.length > 500) {
    throw new MalformedResponseError('WorkflowProposal summary must be a non-empty string <= 500 characters');
  }

  if (!Array.isArray(val.steps) || val.steps.length === 0 || val.steps.length > 20) {
    throw new MalformedResponseError('WorkflowProposal steps must be an array of 1 to 20 steps');
  }

  const steps = val.steps.map((s) => validateWorkflowStep(s));
  const stepIds = new Set<string>();
  for (const s of steps) {
    if (stepIds.has(s.step_id)) {
      throw new MalformedResponseError(`Duplicate step_id "${s.step_id}" in WorkflowProposal`);
    }
    stepIds.add(s.step_id);
  }

  for (const s of steps) {
    for (const dep of s.depends_on || []) {
      if (!stepIds.has(dep)) {
        throw new MalformedResponseError(
          `WorkflowStep "${s.step_id}" depends on unknown step "${dep}" in proposal`
        );
      }
    }
  }

  const sourceIds: string[] = [];
  if (Array.isArray(val.source_ids)) {
    for (const sid of val.source_ids) {
      if (!isNonEmptyString(sid)) {
        throw new MalformedResponseError('WorkflowProposal source_ids entries must be non-empty strings');
      }
      sourceIds.push(sid);
    }
  }

  return {
    proposal_id: val.proposal_id,
    session_id: val.session_id,
    correlation_id: val.correlation_id,
    summary: val.summary,
    steps,
    source_ids: sourceIds,
  };
}

export function validateSessionEventStreamResponse(val: unknown): SessionEventStreamResponse {
  if (!isObject(val)) {
    throw new MalformedResponseError('SessionEventStreamResponse must be an object');
  }

  if (!isNonEmptyString(val.session_id)) {
    throw new MalformedResponseError('SessionEventStreamResponse missing non-empty "session_id"');
  }

  if (!isInteger(val.from_sequence) || val.from_sequence < 0) {
    throw new MalformedResponseError('SessionEventStreamResponse from_sequence must be an integer >= 0');
  }

  if (!isInteger(val.total_events) || val.total_events < 0) {
    throw new MalformedResponseError('SessionEventStreamResponse total_events must be an integer >= 0');
  }

  if (typeof val.has_more !== 'boolean') {
    throw new MalformedResponseError('SessionEventStreamResponse has_more must be a boolean');
  }

  if (!Array.isArray(val.events)) {
    throw new MalformedResponseError('SessionEventStreamResponse events must be an array');
  }

  const events = val.events.map((evt) => validateEventEnvelope(evt, val.session_id as string));

  return {
    session_id: val.session_id,
    events,
    from_sequence: val.from_sequence,
    total_events: val.total_events,
    has_more: val.has_more,
  };
}
