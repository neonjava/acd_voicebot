import React from 'react';
import { AudioChunkMetadata, EventEnvelope } from '../types/contracts';

interface AudioEventsSummaryProps {
  events: EventEnvelope<AudioChunkMetadata>[];
}

export const AudioEventsSummary: React.FC<AudioEventsSummaryProps> = ({ events }) => {
  if (events.length === 0) {
    return null;
  }

  return (
    <section
      aria-label="Audio Events Metadata"
      className="audio-events-section"
      style={{
        marginTop: '16px',
        border: '1px solid #dee2e6',
        borderRadius: '6px',
        padding: '12px 16px',
        backgroundColor: '#fdfdfe',
      }}
    >
      <h3 style={{ margin: '0 0 8px 0', fontSize: '0.95rem', color: '#495057' }}>
        Received Audio Events (Metadata only, no PCM)
      </h3>
      <ul
        style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '6px' }}
      >
        {events.map((evt) => (
          <li
            key={evt.event_id}
            data-testid={`audio-event-${evt.event_id}`}
            style={{
              fontSize: '0.82rem',
              color: '#495057',
              backgroundColor: '#f1f3f5',
              padding: '6px 10px',
              borderRadius: '4px',
              display: 'flex',
              justifyContent: 'space-between',
              fontFamily: 'monospace',
            }}
          >
            <span>
              <strong>{evt.event_id}</strong>: seq #{evt.payload.sequence_id} ({evt.payload.start_ms}ms, {evt.payload.duration_ms}ms duration)
            </span>
            <span>
              {evt.payload.sample_rate_hz}Hz | {evt.payload.size_bytes} bytes
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
};
