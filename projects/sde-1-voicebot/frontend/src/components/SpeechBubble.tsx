import React, { useEffect, useRef } from 'react';
import {
  ApprovalRequest,
  BrowserActionEvent,
  TurnProposalResponse,
  TurnResponse,
} from '../types/contracts';
import { StepChips, StepItem } from './StepChips';

export interface SpeechBubbleProps {
  userQuery?: string;
  turnResponse?: TurnResponse | null;
  stepActions?: BrowserActionEvent[];
  pendingApproval?: ApprovalRequest | null;
  onApprove?: (approvalId: string) => void;
  onReject?: (approvalId: string) => void;
  isApproving?: boolean;
  approvalError?: string | null;
  onRetry?: () => void;
  reducedMotion?: boolean;
}

export const SpeechBubble: React.FC<SpeechBubbleProps> = ({
  userQuery,
  turnResponse,
  stepActions = [],
  pendingApproval,
  onApprove,
  onReject,
  isApproving = false,
  approvalError,
  onRetry,
  reducedMotion = false,
}) => {
  const approveBtnRef = useRef<HTMLButtonElement>(null);
  const rejectBtnRef = useRef<HTMLButtonElement>(null);

  // Focus trapping when approval is active
  useEffect(() => {
    if (pendingApproval) {
      approveBtnRef.current?.focus();
    }
  }, [pendingApproval]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!pendingApproval) return;
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === approveBtnRef.current) {
          e.preventDefault();
          rejectBtnRef.current?.focus();
        }
      } else {
        if (document.activeElement === approveBtnRef.current) {
          e.preventDefault();
          rejectBtnRef.current?.focus();
        } else if (document.activeElement === rejectBtnRef.current) {
          e.preventDefault();
          approveBtnRef.current?.focus();
        }
      }
    } else if (e.key === 'Escape') {
      if (onReject && pendingApproval) {
        e.preventDefault();
        onReject(pendingApproval.approval_id);
      }
    }
  };

  // Convert browser actions or proposal steps to step items for chips
  const stepItems: StepItem[] = [];
  if (stepActions.length > 0) {
    for (const act of stepActions) {
      stepItems.push({
        id: act.action_id,
        label: act.label,
        status: act.status,
        target: act.target,
      });
    }
  } else if (turnResponse && turnResponse.kind === 'proposal') {
    const proposal = turnResponse as TurnProposalResponse;
    for (const step of proposal.steps) {
      stepItems.push({
        id: step.step_id,
        label: step.tool_name.replace('_', ' '),
        status: 'pending',
      });
    }
  }

  const hasContent = Boolean(userQuery || turnResponse || stepItems.length > 0);
  if (!hasContent) {
    return null;
  }

  return (
    <div
      className={`speech-bubble-wrapper ${reducedMotion ? 'reduced-motion' : ''}`}
      onKeyDown={handleKeyDown}
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        width: '100%',
        maxWidth: '360px',
        maxHeight: '260px',
        overflowY: 'auto',
      }}
    >
      {/* Tether SVG thread connecting mascot and bubble */}
      <svg
        className="speech-bubble-tether"
        aria-hidden="true"
        style={{
          position: 'absolute',
          bottom: -12,
          right: 28,
          width: 24,
          height: 16,
          pointerEvents: 'none',
          overflow: 'visible',
        }}
      >
        <path
          d="M0 0 C 8 8, 16 12, 20 16"
          stroke="rgba(56, 189, 248, 0.5)"
          strokeWidth="2"
          fill="none"
          strokeDasharray={reducedMotion ? 'none' : '3 3'}
        />
      </svg>

      {/* Bubble card */}
      <div
        className="speech-bubble-card"
        style={{
          background: 'rgba(15, 23, 42, 0.95)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          borderRadius: '12px',
          padding: '10px 12px',
          boxShadow: '0 8px 24px rgba(0, 0, 0, 0.45)',
          backdropFilter: 'blur(8px)',
          color: '#f8fafc',
          fontSize: '12px',
          lineHeight: '1.4',
        }}
      >
        {/* User turn */}
        {userQuery && (
          <div
            className="speech-user-query"
            style={{
              padding: '4px 8px',
              borderRadius: '6px',
              background: 'rgba(30, 41, 59, 0.7)',
              color: '#38bdf8',
              fontWeight: 600,
              marginBottom: '6px',
            }}
          >
            <span>You: </span>
            <span style={{ color: '#e2e8f0', fontWeight: 400 }}>{userQuery}</span>
          </div>
        )}

        {/* Turn Response */}
        {turnResponse && (
          <div className={`turn-response turn-${turnResponse.kind}`}>
            {turnResponse.kind === 'answer' && (
              <div className="turn-answer">
                <div style={{ color: '#f1f5f9', fontWeight: 500 }}>{turnResponse.text}</div>

                {/* Sources / Citations */}
                {turnResponse.sources && turnResponse.sources.length > 0 && (
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: '4px',
                      marginTop: '6px',
                      fontSize: '10px',
                    }}
                  >
                    <span style={{ color: '#64748b' }}>Sources:</span>
                    {turnResponse.sources.map((src, idx) => (
                      <span
                        key={src.id || `src-${idx}`}
                        className="source-chip"
                        style={{
                          background: 'rgba(56, 189, 248, 0.12)',
                          color: '#38bdf8',
                          padding: '1px 6px',
                          borderRadius: '4px',
                          border: '1px solid rgba(56, 189, 248, 0.25)',
                        }}
                        title={src.locator ? `Locator: ${src.locator}` : src.label}
                      >
                        {src.label}
                      </span>
                    ))}
                  </div>
                )}

                {/* Spoken text indicator */}
                {turnResponse.spoken_text && (
                  <div
                    style={{
                      marginTop: '6px',
                      fontSize: '10px',
                      color: '#94a3b8',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                    title={`Spoken: "${turnResponse.spoken_text}"`}
                  >
                    <span aria-hidden="true">🔊</span>
                    <em>Spoken: "{turnResponse.spoken_text}"</em>
                  </div>
                )}
              </div>
            )}

            {turnResponse.kind === 'clarify' && (
              <div className="turn-clarify" style={{ color: '#f59e0b' }}>
                <div style={{ fontWeight: 600 }}>Clarification Needed:</div>
                <div style={{ color: '#f1f5f9', marginTop: '2px' }}>{turnResponse.question}</div>
              </div>
            )}

            {turnResponse.kind === 'proposal' && (
              <div className="turn-proposal">
                <div style={{ fontWeight: 600, color: '#38bdf8' }}>Proposed Plan:</div>
                <div style={{ color: '#e2e8f0', margin: '2px 0 6px 0' }}>{turnResponse.summary}</div>

                {/* Single task approval dialog inside the speech bubble */}
                {pendingApproval && (
                  <div
                    className="task-approval-box"
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="approval-heading"
                    style={{
                      marginTop: '8px',
                      padding: '8px',
                      borderRadius: '8px',
                      background: 'rgba(239, 68, 68, 0.1)',
                      border: '1px solid rgba(239, 68, 68, 0.3)',
                    }}
                  >
                    <div
                      id="approval-heading"
                      style={{
                        fontWeight: 600,
                        color: '#f87171',
                        marginBottom: '4px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                      }}
                    >
                      <span aria-hidden="true">⚠️</span> Action Approval Required
                    </div>
                    <div style={{ fontSize: '11px', color: '#cbd5e1', marginBottom: '8px' }}>
                      Executing this browser task requires confirmation. Rejecting never triggers execution.
                    </div>

                    {approvalError && (
                      <div
                        style={{ color: '#f87171', fontSize: '10px', marginBottom: '6px' }}
                        role="alert"
                      >
                        {approvalError}
                      </div>
                    )}

                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        ref={approveBtnRef}
                        type="button"
                        onClick={() => onApprove && onApprove(pendingApproval.approval_id)}
                        disabled={isApproving}
                        style={{
                          flex: 1,
                          padding: '4px 10px',
                          borderRadius: '6px',
                          background: '#0284c7',
                          color: '#ffffff',
                          border: 'none',
                          fontWeight: 600,
                          cursor: isApproving ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {isApproving ? 'Approving...' : 'Approve'}
                      </button>
                      <button
                        ref={rejectBtnRef}
                        type="button"
                        onClick={() => onReject && onReject(pendingApproval.approval_id)}
                        disabled={isApproving}
                        style={{
                          flex: 1,
                          padding: '4px 10px',
                          borderRadius: '6px',
                          background: 'rgba(239, 68, 68, 0.2)',
                          color: '#f87171',
                          border: '1px solid #ef4444',
                          fontWeight: 600,
                          cursor: isApproving ? 'not-allowed' : 'pointer',
                        }}
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {turnResponse.kind === 'error' && (
              <div
                className="turn-error"
                role="alert"
                style={{
                  color: '#f87171',
                  background: 'rgba(239, 68, 68, 0.1)',
                  padding: '6px 8px',
                  borderRadius: '6px',
                  border: '1px solid rgba(239, 68, 68, 0.25)',
                }}
              >
                <div style={{ fontWeight: 600 }}>Error:</div>
                <div>{turnResponse.message}</div>
                {turnResponse.retryable && onRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    style={{
                      marginTop: '6px',
                      background: 'rgba(239, 68, 68, 0.2)',
                      border: '1px solid #ef4444',
                      color: '#fca5a5',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '11px',
                    }}
                  >
                    Retry
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* Live step chips */}
        {stepItems.length > 0 && (
          <div style={{ marginTop: '8px' }}>
            <StepChips steps={stepItems} />
          </div>
        )}
      </div>
    </div>
  );
};
