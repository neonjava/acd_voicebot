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
  state: 'completed';
  mode: 'mock';
  events: EventEnvelope<AudioChunkMetadata | TranscriptSegment | ErrorEnvelope | unknown>[];
}
