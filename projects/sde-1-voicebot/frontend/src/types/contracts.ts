/**
 * TypeScript contract representations matching docs/contracts.md and shared backend models.
 */

export type SessionLifecycleState =
  | 'created'
  | 'active'
  | 'paused'
  | 'stopping'
  | 'completed'
  | 'failed'
  | 'expired';

export type SimulatedPermissionState =
  | 'prompt'
  | 'granted'
  | 'denied'
  | 'unavailable';

export interface AudioChunkMetadata {
  sequence_id: number;
  start_ms: number;
  duration_ms: number;
  sample_rate_hz: 16000;
  channels: 1;
  size_bytes: number;
}

export interface TranscriptSegment {
  segment_id: string;
  session_id: string;
  sequence_id: number;
  start_ms: number;
  end_ms: number;
  text: string;
  confidence: number | null;
  language: string;
  is_final: boolean;
}

export interface ErrorEnvelope {
  code: string;
  message_safe_for_user: string;
  retryable: boolean;
  correlation_id: string;
  details_redacted: Record<string, string>;
}

export interface EventEnvelope<T = unknown> {
  event_id: string;
  event_type: string;
  schema_version: '1.0';
  session_id: string;
  correlation_id: string;
  timestamp: string;
  producer: string;
  payload: T;
}

export interface MockSessionResponse {
  session_id: string;
  state: SessionLifecycleState;
  mode: 'mock';
  events: EventEnvelope<AudioChunkMetadata | TranscriptSegment | ErrorEnvelope | unknown>[];
}

/**
 * Screen Context & Reasoning models owned by W3 (backend/app/contracts/reasoning.py).
 */
export interface SourceReference {
  source_id: string;
  locator: string;
  kind: 'synthetic_screen' | 'transcript';
}

export interface ContextItem {
  item_id: string;
  text: string;
  source: SourceReference;
}

export interface ScreenContext {
  frame_id: string;
  captured_at: string;
  capture_enabled: boolean;
  items: ContextItem[];
}

export interface ReasoningResult {
  request_id: string;
  session_id: string;
  answer: string;
  source_ids: string[];
  insufficient_evidence: boolean;
  prompt_version: 'v1';
}

/**
 * Audio Speech Events owned by W1/W2/W5 (backend/app/contracts/audio.py).
 */
export type SpeechEventKind = 'wake' | 'speech_start' | 'speech_end';

export interface SpeechEvent {
  kind: SpeechEventKind;
  session_id: string;
  correlation_id: string;
  sequence_id: number;
  at_ms: number;
  wake_word?: string | null;
  score?: number | null;
}

/**
 * Workflow and Approvals contracts owned by W4 (backend/app/contracts/workflow.py).
 */
export type WorkflowState =
  | 'draft'
  | 'awaiting_approval'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface WorkflowStep {
  step_id: string;
  tool_name: string;
  arguments: Record<string, string>;
  requires_approval: boolean;
  depends_on?: string[];
}

export interface WorkflowPlan {
  plan_id: string;
  session_id: string;
  steps: WorkflowStep[];
  state?: WorkflowState;
}

export interface WorkflowProposal {
  proposal_id: string;
  session_id: string;
  correlation_id: string;
  summary: string;
  steps: WorkflowStep[];
  source_ids?: string[];
}

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface ApprovalRequest {
  approval_id: string;
  plan_id: string;
  step_id: string;
  session_id: string;
  status: ApprovalStatus;
  expires_at?: string | null;
}

export interface ApprovalDecisionRequest {
  decision: 'approve' | 'reject';
}

export type AuditKind =
  | 'approval_granted'
  | 'approval_rejected'
  | 'approval_expired'
  | 'approval_missing'
  | 'step_succeeded'
  | 'step_failed'
  | 'step_timed_out'
  | 'step_retried'
  | 'workflow_cancelled';

export interface AuditEvent {
  sequence: number;
  kind: AuditKind;
  plan_id: string;
  session_id: string;
  step_id?: string | null;
  approval_id?: string | null;
  details_redacted?: Record<string, string>;
}

export interface WorkflowResult {
  plan_id: string;
  session_id: string;
  state: WorkflowState;
  outputs?: Record<string, string>;
  error?: ErrorEnvelope | null;
  audit_events?: AuditEvent[];
}

/**
 * Event Stream / Replay response owned by W5 (backend/app/contracts/sessions.py).
 */
export interface SessionEventStreamResponse {
  session_id: string;
  events: EventEnvelope<unknown>[];
  from_sequence: number;
  total_events: number;
  has_more: boolean;
}

/**
 * Week 4 wire contracts. They mirror backend/app/contracts (audio.py CaptureStatus,
 * sessions.py TurnRequest/TurnResponse, browser.py BrowserAction) and
 * docs/contracts.md "Week 4 contracts". Change them only together with the backend.
 */
export type CaptureState = 'idle' | 'listening' | 'capturing' | 'paused' | 'stopped';

/** `audio.capture` event payload and GET/POST /api/sessions/{id}/capture|listen body. */
export interface CaptureStatus {
  session_id: string;
  state: CaptureState;
  source: 'mock' | 'mic';
  wake_required: boolean;
  wake_word?: string | null;
}

/** POST /api/sessions/{id}/turns request body. */
export interface TurnRequest {
  text: string;
  active_app?: string | null;
  active_window_title?: string | null;
}

export type TurnKind = 'answer' | 'clarify' | 'proposal' | 'error';

/** POST /api/sessions/{id}/turns response and `assistant.turn` event payload. */
export interface TurnResponse {
  session_id: string;
  turn_id: string;
  kind: TurnKind;
  answer?: string | null;
  source_ids: string[];
  clarify?: string | null;
  proposal?: WorkflowProposal | null;
  approvals: ApprovalRequest[];
  workflow?: WorkflowResult | null;
  error_code?: string | null;
  spoken_text?: string | null;
}

export type BrowserActionKind =
  | 'read_page'
  | 'navigate'
  | 'click'
  | 'type'
  | 'press_key'
  | 'scroll'
  | 'wait';

export interface BrowserAction {
  action_id: string;
  session_id: string;
  kind: BrowserActionKind;
  ref?: string | null;
  url?: string | null;
  text?: string | null;
  key?: string | null;
  scroll_y?: number | null;
}

/** `browser.action` event payload: the action and its outcome (no page text). */
export interface BrowserActionEventPayload {
  action: BrowserAction;
  ok: boolean;
  error_code?: string | null;
}

/** UI-only: what the companion glyph shows. Not a wire contract. */
export type CompanionState = 'idle' | 'listening' | 'thinking' | 'working' | 'done' | 'error';

export interface VoicebotDesktopBridge {
  isElectron: true;
  getToken: () => string;
  setWindowExpanded: (expanded: boolean) => Promise<void>;
  isBackendReady?: () => boolean;
  onBackendReady?: (callback: () => void) => () => void;
}

declare global {
  interface Window {
    voicebot?: VoicebotDesktopBridge;
  }
}



