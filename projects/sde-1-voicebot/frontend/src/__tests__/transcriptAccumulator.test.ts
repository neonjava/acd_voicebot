import { describe, it, expect } from 'vitest';
import { TranscriptAccumulator } from '../utils/transcriptAccumulator';
import { TranscriptSegment } from '../types/contracts';

describe('TranscriptAccumulator', () => {
  it('orders segments by start_ms, sequence_id, and segment_id', () => {
    const acc = new TranscriptAccumulator('session-1');

    const seg2: TranscriptSegment = {
      segment_id: 'seg-2',
      session_id: 'session-1',
      sequence_id: 1,
      start_ms: 1000,
      end_ms: 2000,
      text: 'Second chunk',
      confidence: 0.9,
      language: 'en',
      is_final: true,
    };

    const seg1: TranscriptSegment = {
      segment_id: 'seg-1',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 1000,
      text: 'First chunk',
      confidence: 1.0,
      language: 'en',
      is_final: true,
    };

    acc.add(seg2);
    acc.add(seg1);

    const ordered = acc.getSegments();
    expect(ordered).toHaveLength(2);
    expect(ordered[0].segment_id).toBe('seg-1');
    expect(ordered[1].segment_id).toBe('seg-2');
  });

  it('replaces interim segment with final segment having the same segment_id', () => {
    const acc = new TranscriptAccumulator('session-1');

    const interim: TranscriptSegment = {
      segment_id: 'seg-1',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 500,
      text: 'Hel...',
      confidence: null,
      language: 'en',
      is_final: false,
    };

    const finalSeg: TranscriptSegment = {
      segment_id: 'seg-1',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 1000,
      text: 'Hello world',
      confidence: 0.98,
      language: 'en',
      is_final: true,
    };

    acc.add(interim);
    expect(acc.getSegments()[0].is_final).toBe(false);
    expect(acc.getSegments()[0].text).toBe('Hel...');

    acc.add(finalSeg);
    const result = acc.getSegments();
    expect(result).toHaveLength(1);
    expect(result[0].is_final).toBe(true);
    expect(result[0].text).toBe('Hello world');
  });

  it('prevents final segment from regressing to interim', () => {
    const acc = new TranscriptAccumulator('session-1');

    const finalSeg: TranscriptSegment = {
      segment_id: 'seg-1',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 1000,
      text: 'Hello world',
      confidence: 1.0,
      language: 'en',
      is_final: true,
    };

    const regressingInterim: TranscriptSegment = {
      segment_id: 'seg-1',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 800,
      text: 'Hello...',
      confidence: null,
      language: 'en',
      is_final: false,
    };

    acc.add(finalSeg);
    acc.add(regressingInterim);

    const result = acc.getSegments();
    expect(result).toHaveLength(1);
    expect(result[0].is_final).toBe(true);
    expect(result[0].text).toBe('Hello world');
  });

  it('rejects segments from mixed sessions', () => {
    const acc = new TranscriptAccumulator('session-A');

    const foreignSeg: TranscriptSegment = {
      segment_id: 'seg-foreign',
      session_id: 'session-B',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 1000,
      text: 'Foreign text',
      confidence: 1.0,
      language: 'en',
      is_final: true,
    };

    expect(() => acc.add(foreignSeg)).toThrow(/session "session-B"/);
  });

  it('detects and ignores exact duplicates', () => {
    const acc = new TranscriptAccumulator('session-1');

    const seg: TranscriptSegment = {
      segment_id: 'seg-dup',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 1000,
      text: 'Original chunk',
      confidence: 0.95,
      language: 'en',
      is_final: true,
    };

    const firstAdded = acc.add(seg);
    expect(firstAdded).toBe(true);

    // Exact duplicate should return false and not be duplicated
    const secondAdded = acc.add({ ...seg });
    expect(secondAdded).toBe(false);

    expect(acc.getSegments()).toHaveLength(1);
    expect(acc.isRevised('seg-dup')).toBe(false);
  });

  it('tracks revisions when interim text is updated with higher sequence_id', () => {
    const acc = new TranscriptAccumulator('session-1');

    const interimV1: TranscriptSegment = {
      segment_id: 'seg-rev',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 500,
      text: 'Checking the st',
      confidence: 0.8,
      language: 'en',
      is_final: false,
    };

    const interimV2: TranscriptSegment = {
      segment_id: 'seg-rev',
      session_id: 'session-1',
      sequence_id: 1,
      start_ms: 0,
      end_ms: 800,
      text: 'Checking the status',
      confidence: 0.9,
      language: 'en',
      is_final: false,
    };

    acc.add(interimV1);
    expect(acc.getRevisionCount('seg-rev')).toBe(0);
    expect(acc.isRevised('seg-rev')).toBe(false);

    acc.add(interimV2);
    expect(acc.getRevisionCount('seg-rev')).toBe(1);
    expect(acc.isRevised('seg-rev')).toBe(true);
    expect(acc.getSegments()[0].text).toBe('Checking the status');
  });

  it('concatenates finalized segments with text() helper', () => {
    const acc = new TranscriptAccumulator('session-1');

    acc.add({
      segment_id: 'seg-1',
      session_id: 'session-1',
      sequence_id: 0,
      start_ms: 0,
      end_ms: 1000,
      text: 'Hello',
      confidence: 1.0,
      language: 'en',
      is_final: true,
    });

    acc.add({
      segment_id: 'seg-2',
      session_id: 'session-1',
      sequence_id: 1,
      start_ms: 1000,
      end_ms: 2000,
      text: 'world.',
      confidence: 0.95,
      language: 'en',
      is_final: true,
    });

    acc.add({
      segment_id: 'seg-3',
      session_id: 'session-1',
      sequence_id: 2,
      start_ms: 2000,
      end_ms: 2500,
      text: 'Still typing',
      confidence: 0.5,
      language: 'en',
      is_final: false, // interim should be excluded from text()
    });

    expect(acc.text()).toBe('Hello world.');
  });
});
