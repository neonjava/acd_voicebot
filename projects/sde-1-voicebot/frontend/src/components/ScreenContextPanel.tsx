import React from 'react';
import { ScreenContext, TranscriptSegment } from '../types/contracts';

interface ScreenContextPanelProps {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  disabled?: boolean;
  transcriptSegments?: TranscriptSegment[];
}

export const ScreenContextPanel: React.FC<ScreenContextPanelProps> = ({
  enabled,
  onToggle,
  disabled = false,
  transcriptSegments = [],
}) => {
  // Construct synthetic screen context item (matching W3 contracts/reasoning.py make_synthetic_screen_context)
  const syntheticScreenContext: ScreenContext = {
    frame_id: 'frame-demo-0',
    captured_at: '2026-01-01T00:00:00Z',
    capture_enabled: enabled,
    items: [
      {
        item_id: 'screen-status',
        text: 'Mock dashboard status: ready.',
        source: {
          source_id: 'screen-status',
          kind: 'synthetic_screen',
          locator: 'demo-dashboard',
        },
      },
    ],
  };

  // Final transcript segments mapped to ContextItem per W3 context_item_from_transcript
  const transcriptContextItems = transcriptSegments
    .filter((seg) => seg.is_final)
    .map((seg) => ({
      item_id: seg.segment_id,
      text: seg.text,
      source: {
        source_id: seg.segment_id,
        kind: 'transcript' as const,
        locator: seg.segment_id,
      },
    }));

  return (
    <section
      aria-label="Screen Context Panel"
      className="screen-context-panel"
      data-testid="screen-context-panel"
      style={{
        marginTop: '20px',
        border: '1px solid #ced4da',
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
          flexWrap: 'wrap',
          gap: '12px',
          marginBottom: '12px',
        }}
      >
        <div>
          <h2 style={{ margin: '0 0 4px 0', fontSize: '1.15rem' }}>
            Screen Context & Source References
          </h2>
          <p style={{ margin: 0, fontSize: '0.85rem', color: '#6c757d' }}>
            Mock screen context for reasoning (W3 contract). Real screen capture (
            <code>getDisplayMedia()</code>) is strictly disabled.
          </p>
        </div>

        {/* Accessible Switch Control */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <label
            htmlFor="screen-context-toggle"
            style={{
              fontSize: '0.9rem',
              fontWeight: 600,
              cursor: disabled ? 'not-allowed' : 'pointer',
            }}
          >
            Screen Context:
          </label>
          <button
            id="screen-context-toggle"
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="Toggle synthetic screen context"
            data-testid="screen-context-toggle"
            disabled={disabled}
            onClick={() => onToggle(!enabled)}
            style={{
              padding: '6px 14px',
              fontSize: '0.85rem',
              fontWeight: 600,
              borderRadius: '20px',
              border: '1px solid',
              borderColor: enabled ? '#198754' : '#6c757d',
              backgroundColor: enabled ? '#d1e7dd' : '#e9ecef',
              color: enabled ? '#0f5132' : '#495057',
              cursor: disabled ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'background-color 0.2s, border-color 0.2s',
            }}
          >
            <span
              aria-hidden="true"
              style={{
                display: 'inline-block',
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                backgroundColor: enabled ? '#198754' : '#6c757d',
              }}
            />
            {enabled ? 'ON (capture_enabled: true)' : 'OFF (capture_enabled: false)'}
          </button>
        </div>
      </div>

      {/* Screen Context Notice / Details */}
      {!enabled ? (
        <div
          data-testid="screen-context-disabled-message"
          style={{
            padding: '12px 14px',
            backgroundColor: '#f8f9fa',
            borderRadius: '4px',
            border: '1px dashed #ced4da',
            color: '#6c757d',
            fontSize: '0.9rem',
          }}
        >
          <span>
            Screen context is currently <strong>OFF</strong> by default.
            Synthetic frame capture is inactive (<code>capture_enabled: false</code>).
            Toggle ON to inspect synthetic screen context items and source references.
          </span>
        </div>
      ) : (
        <div
          data-testid="screen-context-active-content"
          style={{
            padding: '14px',
            backgroundColor: '#f0fdf4',
            borderRadius: '4px',
            border: '1px solid #bbf7d0',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: '10px',
              fontSize: '0.85rem',
              color: '#166534',
              fontFamily: 'monospace',
            }}
          >
            <span>
              <strong>Frame:</strong> {syntheticScreenContext.frame_id}
            </span>
            <span>
              <strong>Captured At:</strong> {syntheticScreenContext.captured_at} (UTC)
            </span>
            <span
              style={{
                backgroundColor: '#dcfce7',
                padding: '2px 8px',
                borderRadius: '4px',
                fontWeight: 600,
              }}
            >
              Mock Mode (Zero Device Access)
            </span>
          </div>

          <h3
            style={{
              margin: '10px 0 8px 0',
              fontSize: '0.95rem',
              color: '#15803d',
            }}
          >
            Context Items & Grounded Source References:
          </h3>

          <ul
            data-testid="screen-context-items-list"
            style={{
              listStyle: 'none',
              padding: 0,
              margin: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
            }}
          >
            {/* Synthetic Screen Context Item */}
            {syntheticScreenContext.items.map((item) => (
              <li
                key={item.item_id}
                data-testid={`context-item-${item.item_id}`}
                style={{
                  backgroundColor: '#ffffff',
                  border: '1px solid #bbf7d0',
                  borderRadius: '4px',
                  padding: '10px',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '0.82rem',
                    color: '#166534',
                    marginBottom: '4px',
                  }}
                >
                  <span>
                    <strong>Item ID:</strong> <code>{item.item_id}</code>
                  </span>
                  <span>
                    <strong>Source Kind:</strong>{' '}
                    <span
                      style={{
                        backgroundColor: '#e0f2fe',
                        color: '#0369a1',
                        padding: '2px 6px',
                        borderRadius: '3px',
                        fontWeight: 600,
                        fontSize: '0.75rem',
                      }}
                    >
                      {item.source.kind}
                    </span>
                  </span>
                  <span>
                    <strong>Locator:</strong> <code>{item.source.locator}</code>
                  </span>
                </div>
                <p style={{ margin: '4px 0 0 0', fontSize: '0.9rem', color: '#1f2937' }}>
                  {item.text}
                </p>
              </li>
            ))}

            {/* Transcript-Derived Context Items */}
            {transcriptContextItems.map((item) => (
              <li
                key={`transcript-ctx-${item.item_id}`}
                data-testid={`context-item-${item.item_id}`}
                style={{
                  backgroundColor: '#ffffff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '4px',
                  padding: '10px',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '0.82rem',
                    color: '#475569',
                    marginBottom: '4px',
                  }}
                >
                  <span>
                    <strong>Item ID:</strong> <code>{item.item_id}</code>
                  </span>
                  <span>
                    <strong>Source Kind:</strong>{' '}
                    <span
                      style={{
                        backgroundColor: '#f1f5f9',
                        color: '#334155',
                        padding: '2px 6px',
                        borderRadius: '3px',
                        fontWeight: 600,
                        fontSize: '0.75rem',
                      }}
                    >
                      {item.source.kind}
                    </span>
                  </span>
                  <span>
                    <strong>Locator:</strong> <code>{item.source.locator}</code>
                  </span>
                </div>
                <p style={{ margin: '4px 0 0 0', fontSize: '0.9rem', color: '#1f2937' }}>
                  {item.text}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};
