import React from 'react';

export const MockModeBanner: React.FC = () => {
  return (
    <aside
      role="region"
      aria-label="Mock mode notice"
      className="mock-mode-banner"
      style={{
        backgroundColor: '#fff3cd',
        border: '1px solid #ffeeba',
        color: '#856404',
        padding: '12px 16px',
        borderRadius: '6px',
        marginBottom: '20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontWeight: 500,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span
          aria-hidden="true"
          style={{
            display: 'inline-block',
            width: '10px',
            height: '10px',
            borderRadius: '50%',
            backgroundColor: '#d39e00',
          }}
        />
        <span>
          <strong>MOCK MODE:</strong> Voicebot simulation active. Real microphone/screen capture,
          external messages, and paid APIs are strictly disabled for Week 1.
        </span>
      </div>
      <span
        style={{
          fontSize: '0.85em',
          backgroundColor: '#ffe8a1',
          padding: '2px 8px',
          borderRadius: '4px',
          border: '1px solid #e0a800',
        }}
      >
        No getUserMedia
      </span>
    </aside>
  );
};
