import { TranscriptSegment } from '../types/contracts';

/**
 * Accumulates, updates, and orders transcript segments per docs/contracts.md:
 * - Chronological ordering by (start_ms, sequence_id, segment_id)
 * - Interim/final updates: Same segment ID replaces interim with final
 * - Revisions: Text revisions on the same segment ID update the segment and track revisions
 * - Regression prevention: Final segments cannot regress back to interim
 * - Duplicate handling: Repeated identical events do not duplicate
 * - Session isolation: Rejects events from mixed sessions
 */
export class TranscriptAccumulator {
  private segmentsMap = new Map<string, TranscriptSegment>();
  private revisionCounts = new Map<string, number>();
  private activeSessionId: string | null = null;

  constructor(initialSessionId?: string) {
    if (initialSessionId) {
      this.activeSessionId = initialSessionId;
    }
  }

  /**
   * Add or update a transcript segment. Returns true if segment was added or modified.
   */
  add(segment: TranscriptSegment): boolean {
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
      // 1. Final cannot regress to interim
      if (existing.is_final && !segment.is_final) {
        return false;
      }

      // 2. Exact duplicate check
      const isDuplicate =
        existing.sequence_id === segment.sequence_id &&
        existing.start_ms === segment.start_ms &&
        existing.end_ms === segment.end_ms &&
        existing.text === segment.text &&
        existing.confidence === segment.confidence &&
        existing.language === segment.language &&
        existing.is_final === segment.is_final;

      if (isDuplicate) {
        return false;
      }

      // 3. Revision tracking: if text changed, record revision
      if (existing.text !== segment.text) {
        const count = this.revisionCounts.get(segment.segment_id) ?? 0;
        this.revisionCounts.set(segment.segment_id, count + 1);
      }

      // 4. Update segment
      this.segmentsMap.set(segment.segment_id, segment);
      return true;
    }

    // New segment
    this.segmentsMap.set(segment.segment_id, segment);
    this.revisionCounts.set(segment.segment_id, 0);
    return true;
  }

  /**
   * Return segments sorted strictly by start_ms, sequence_id, and segment_id.
   */
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

  /**
   * Return full accumulated transcript text ordered chronologically.
   * By default, includes only finalized segments.
   */
  text(onlyFinal = true): string {
    return this.getSegments()
      .filter((s) => !onlyFinal || s.is_final)
      .map((s) => s.text.trim())
      .filter((t) => t.length > 0)
      .join(' ');
  }

  /**
   * Return whether a segment underwent text revisions.
   */
  isRevised(segmentId: string): boolean {
    return (this.revisionCounts.get(segmentId) ?? 0) > 0;
  }

  /**
   * Return the number of text revisions a segment has undergone.
   */
  getRevisionCount(segmentId: string): number {
    return this.revisionCounts.get(segmentId) ?? 0;
  }

  clear(): void {
    this.segmentsMap.clear();
    this.revisionCounts.clear();
    this.activeSessionId = null;
  }
}
