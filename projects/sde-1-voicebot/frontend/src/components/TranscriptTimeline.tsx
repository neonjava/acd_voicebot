import React from 'react';
import { TranscriptSegment } from '../types/contracts';

interface TranscriptTimelineProps {
  segments: TranscriptSegment[];
  isRevised?: (segmentId: string) => boolean;
  revisionCount?: (segmentId: string) => number;
}

export const TranscriptTimeline: React.FC<TranscriptTimelineProps> = ({
  segments,
  isRevised,
  revisionCount,
}) => {
  const finalCount = segments.filter((s) => s.is_final).length;
  const interimCount = segments.length - finalCount;

  return (
    <section
      aria-label="Transcript Timeline"
      className="transcript-timeline-section"
      style={{
        marginTop: '24px',
        border: '1px solid #dee2e6',
        borderRadius: '6px',
        padding: '16px',
        backgroundColor: '#ffffff',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '12px',
        }}
      >
        <h2 style={{ margin: 0, fontSize: '1.15rem' }}>Ordered Transcript Timeline</h2>
        <span
          data-testid="timeline-counts"
          style={{ fontSize: '0.85rem', color: '#6c757d' }}
        >
          {segments.length} {segments.length === 1 ? 'segment' : 'segments'}
          {segments.length > 0 && ` (${finalCount} final, ${interimCount} interim)`}
        </span>
      </div>

      {segments.length === 0 ? (
        <p
          data-testid="timeline-empty-message"
          style={{ color: '#6c757d', fontStyle: 'italic', margin: '16px 0' }}
        >
          No transcript segments yet. Start a session to stream events.
        </p>
      ) : (
        <ol
          data-testid="transcript-timeline-list"
          role="list"
          style={{
            listStyle: 'none',
            padding: 0,
            margin: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
          }}
        >
          {segments.map((seg) => {
            const revised = isRevised ? isRevised(seg.segment_id) : false;
            const revCount = revisionCount ? revisionCount(seg.segment_id) : 0;

            return (
              <li
                key={seg.segment_id}
                data-testid={`transcript-segment-${seg.segment_id}`}
                style={{
                  border: '1px solid #e9ecef',
                  borderLeft: seg.is_final ? '4px solid #28a745' : '4px solid #ffc107',
                  borderRadius: '4px',
                  padding: '12px',
                  backgroundColor: seg.is_final ? '#f8f9fa' : '#fffdf5',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '6px',
                    fontSize: '0.85rem',
                    color: '#495057',
                  }}
                >
                  <span>
                    <strong>[{seg.start_ms}ms – {seg.end_ms}ms]</strong> (seq #{seg.sequence_id})
                  </span>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    {/* Confidence score */}
                    <span
                      data-testid={`confidence-${seg.segment_id}`}
                      style={{
                        fontSize: '0.75rem',
                        color: '#6c757d',
                      }}
                    >
                      Confidence:{' '}
                      {seg.confidence !== null
                        ? `${Math.round(seg.confidence * 100)}%`
                        : 'unknown'}
                    </span>

                    {/* Revision badge if text was revised */}
                    {revised && (
                      <span
                        data-testid={`revised-badge-${seg.segment_id}`}
                        style={{
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          padding: '2px 6px',
                          borderRadius: '3px',
                          backgroundColor: '#e7f5ff',
                          color: '#1864ab',
                          border: '1px solid #a5d8ff',
                        }}
                      >
                        Revised{revCount > 1 ? ` (${revCount}x)` : ''}
                      </span>
                    )}

                    {/* Final vs Interim badge */}
                    <span
                      data-testid={`status-badge-${seg.segment_id}`}
                      style={{
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        padding: '2px 6px',
                        borderRadius: '3px',
                        backgroundColor: seg.is_final ? '#d4edda' : '#fff3cd',
                        color: seg.is_final ? '#155724' : '#856404',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                      }}
                    >
                      {!seg.is_final && (
                        <span
                          aria-hidden="true"
                          style={{
                            display: 'inline-block',
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            backgroundColor: '#856404',
                          }}
                        />
                      )}
                      {seg.is_final ? 'Final' : 'Interim'}
                    </span>
                  </div>
                </div>
                <p
                  data-testid={`segment-text-${seg.segment_id}`}
                  style={{
                    margin: '4px 0 0 0',
                    fontSize: '1rem',
                    color: '#212529',
                    lineHeight: '1.4',
                  }}
                >
                  {seg.text}
                </p>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
};
