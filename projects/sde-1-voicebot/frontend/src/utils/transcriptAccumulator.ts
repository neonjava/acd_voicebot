import { TranscriptSegment } from '../types/contracts';

/**
 * Accumulates and orders transcript segments per docs/contracts.md:
 * - Order by start_ms, sequence_id, segment_id
 * - Same segment ID replaces interim with final
 * - Final segments never regress to interim
 * - Repeats do not duplicate
 */
export class TranscriptAccumulator {
  private segmentsMap = new Map<string, TranscriptSegment>();
  private activeSessionId: string | null = null;

  constructor(initialSessionId?: string) {
    if (initialSessionId) {
      this.activeSessionId = initialSessionId;
    }
  }

  add(segment: TranscriptSegment): void {
    if (this.activeSessionId && segment.session_id !== this.activeSessionId) {
      throw new Error(
        `Cannot add segment from session "${segment.session_id}" to accumulator for session "${this.activeSessionId}"`
      );
    }
    if (!this.activeSessionId) {
      this.activeSessionId = segment.session_id;
    }

    const existing = this.segmentsMap.get(segment.segment_id);
    if (existing) {
      // Final cannot regress to interim
      if (existing.is_final && !segment.is_final) {
        return;
      }
      // Update with new data
      this.segmentsMap.set(segment.segment_id, segment);
    } else {
      this.segmentsMap.set(segment.segment_id, segment);
    }
  }

  getSegments(): TranscriptSegment[] {
    return Array.from(this.segmentsMap.values()).sort((a, b) => {
      if (a.start_ms !== b.start_ms) {
        return a.start_ms - b.start_ms;
      }
      if (a.sequence_id !== b.sequence_id) {
        return a.sequence_id - b.sequence_id;
      }
      return a.segment_id.localeCompare(b.segment_id);
    });
  }

  clear(): void {
    this.segmentsMap.clear();
    this.activeSessionId = null;
  }
}
