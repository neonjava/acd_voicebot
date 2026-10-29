import canonicalSessionResponse from '../../../backend/tests/fixtures/session_response.json';
import { MockSessionResponse, EventEnvelope, TranscriptSegment } from '../types/contracts';

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
