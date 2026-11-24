import React, { useState } from 'react';
import { ApprovalRequest } from '../types/contracts';

export interface ApprovalDialogProps {
  approval: ApprovalRequest | null;
  onApprove: (approvalId: string) => Promise<void> | void;
  onReject: (approvalId: string) => Promise<void> | void;
}

export const ApprovalDialog: React.FC<ApprovalDialogProps> = ({
  approval,
  onApprove,
  onReject,
}) => {
  const [submitting, setSubmitting] = useState(false);

  if (!approval || approval.status !== 'pending') {
    return null;
  }

  const handleDecision = async (decision: 'approve' | 'reject') => {
    setSubmitting(true);
    try {
      if (decision === 'approve') {
        await onApprove(approval.approval_id);
      } else {
        await onReject(approval.approval_id);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      data-testid="approval-dialog"
      aria-modal="true"
      aria-labelledby="approval-title"
      aria-describedby="approval-desc"
      style={{
        backgroundColor: '#1e293b',
        border: '1px solid #f59e0b',
        borderRadius: '8px',
        padding: '10px 12px',
        margin: '8px 0',
        color: '#f8fafc',
        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.4)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
        <span style={{ color: '#f59e0b', fontSize: '14px', fontWeight: 'bold' }}>⚠️</span>
        <h4
          id="approval-title"
          style={{
            margin: 0,
            fontSize: '13px',
            fontWeight: 600,
            color: '#fbbf24',
          }}
        >
          Action Approval Required
        </h4>
      </div>

      {/* Exactly one-line risk explanation: what will happen and why it needs approval */}
      <p
        id="approval-desc"
        style={{
          margin: '4px 0 8px 0',
          fontSize: '11px',
          lineHeight: '1.4',
          color: '#e2e8f0',
        }}
      >
        Step <strong>{approval.step_id}</strong> in plan <strong>{approval.plan_id}</strong> will perform consequential system actions that require explicit human consent.
      </p>

      <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
        <button
          type="button"
          data-testid="approval-reject-button"
          onClick={() => handleDecision('reject')}
          disabled={submitting}
          aria-label="Reject action"
          style={{
            padding: '4px 10px',
            fontSize: '11px',
            fontWeight: 600,
            backgroundColor: '#ef4444',
            color: '#ffffff',
            border: 'none',
            borderRadius: '4px',
            cursor: submitting ? 'not-allowed' : 'pointer',
            opacity: submitting ? 0.7 : 1,
          }}
        >
          Reject
        </button>
        <button
          type="button"
          data-testid="approval-approve-button"
          onClick={() => handleDecision('approve')}
          disabled={submitting}
          aria-label="Approve action"
          style={{
            padding: '4px 10px',
            fontSize: '11px',
            fontWeight: 600,
            backgroundColor: '#10b981',
            color: '#ffffff',
            border: 'none',
            borderRadius: '4px',
            cursor: submitting ? 'not-allowed' : 'pointer',
            opacity: submitting ? 0.7 : 1,
          }}
        >
          Approve
        </button>
      </div>
    </div>
  );
};
