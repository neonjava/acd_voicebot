import React, { useState, useEffect, useRef } from 'react';
import { ApprovalRequest } from '../types/contracts';

/** What a browser_task approval covers, shown in plain words (one approval per task). */
export interface ApprovalTask {
  goal: string;
  site: string | null;
}

export interface ApprovalDialogProps {
  approval: ApprovalRequest | null;
  onApprove: (approvalId: string) => Promise<void> | void;
  onReject: (approvalId: string) => Promise<void> | void;
  task?: ApprovalTask | null;
}

export const ApprovalDialog: React.FC<ApprovalDialogProps> = ({ approval, onApprove, onReject, task }) => {
  const [submitting, setSubmitting] = useState(false);
  const rejectBtnRef = useRef<HTMLButtonElement>(null);
  const approveBtnRef = useRef<HTMLButtonElement>(null);

  // Focus the primary action when a new approval arrives.
  useEffect(() => {
    if (approval && approval.status === 'pending') {
      approveBtnRef.current?.focus();
    }
  }, [approval]);

  // Focus trap between the two buttons; Escape rejects.
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === rejectBtnRef.current) {
          e.preventDefault();
          approveBtnRef.current?.focus();
        }
      } else if (document.activeElement === approveBtnRef.current) {
        e.preventDefault();
        rejectBtnRef.current?.focus();
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      if (!submitting && approval) {
        onReject(approval.approval_id);
      }
    }
  };

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
      className="approval"
      data-testid="approval-dialog"
      aria-modal="true"
      aria-labelledby="approval-title"
      aria-describedby="approval-desc"
      onKeyDown={handleKeyDown}
    >
      <h4 id="approval-title" className="approval-title">
        Action Approval Required
      </h4>
      {task ? (
        <p id="approval-desc" className="approval-desc">
          One approval covers this task{task.site ? ` on ${task.site}` : ''}. Jarvis asks again before
          passwords, payments, sending, deleting or leaving the site.
        </p>
      ) : (
        <p id="approval-desc" className="approval-desc">
          Step <strong>{approval.step_id}</strong> in plan <strong>{approval.plan_id}</strong> will perform
          consequential system actions that require explicit human consent.
        </p>
      )}
      <div className="approval-actions">
        <button
          ref={rejectBtnRef}
          type="button"
          className="btn btn-ghost"
          data-testid="approval-reject-button"
          onClick={() => handleDecision('reject')}
          disabled={submitting}
          aria-label="Reject action"
        >
          Reject
        </button>
        <button
          ref={approveBtnRef}
          type="button"
          className="btn btn-primary"
          data-testid="approval-approve-button"
          onClick={() => handleDecision('approve')}
          disabled={submitting}
          aria-label="Approve action"
        >
          Approve
        </button>
      </div>
    </div>
  );
};
