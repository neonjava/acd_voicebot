import React from 'react';
import { TranscriptSegment } from '../types/contracts';

interface TranscriptTimelineProps {
  segments: TranscriptSegment[];
}

export const TranscriptTimeline: React.FC<TranscriptTimelineProps> = ({ segments }) => {
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h2 style={{ margin: 0, fontSize: '1.15rem' }}>Ordered Transcript Timeline</h2>
        <span style={{ fontSize: '0.85rem', color: '#6c757d' }}>
          {segments.length} {segments.length === 1 ? 'segment' : 'segments'}
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
          style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}
        >
          {segments.map((seg) => (
            <li
              key={seg.segment_id}
              data-testid={`transcript-segment-${seg.segment_id}`}
              style={{
                border: '1px solid #e9ecef',
                borderLeft: seg.is_final ? '4px solid #28a745' : '4px solid #ffc107',
                borderRadius: '4px',
                padding: '12px',
                backgroundColor: '#f8f9fa',
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
                  {seg.confidence !== null && (
                    <span
                      style={{
                        fontSize: '0.75rem',
                        color: '#6c757d',
                      }}
                    >
                      Confidence: {Math.round(seg.confidence * 100)}%
                    </span>
                  )}
                  <span
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      padding: '2px 6px',
                      borderRadius: '3px',
                      backgroundColor: seg.is_final ? '#d4edda' : '#fff3cd',
                      color: seg.is_final ? '#155724' : '#856404',
                    }}
                  >
                    {seg.is_final ? 'Final' : 'Interim'}
                  </span>
                </div>
              </div>
              <p
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
          ))}
        </ol>
      )}
    </section>
  );
};
