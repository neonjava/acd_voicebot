import React from 'react';
import { AuditEvent, AuditKind } from '../types/contracts';

export interface WorkflowProgressPanelProps {
  auditEvents: AuditEvent[];
}

function getStatusBadge(kind: AuditKind): { label: string; bg: string; color: string } {
  switch (kind) {
    case 'step_succeeded':
      return { label: 'Succeeded', bg: '#065f46', color: '#6ee7b7' };
    case 'step_failed':
      return { label: 'Failed', bg: '#991b1b', color: '#fca5a5' };
    case 'step_timed_out':
      return { label: 'Timed Out', bg: '#7c2d12', color: '#fdba74' };
    case 'step_retried':
      return { label: 'Retried', bg: '#854d0e', color: '#fde047' };
    case 'approval_granted':
      return { label: 'Approved', bg: '#1e40af', color: '#93c5fd' };
    case 'approval_rejected':
      return { label: 'Rejected', bg: '#991b1b', color: '#fca5a5' };
    case 'approval_expired':
      return { label: 'Expired', bg: '#475569', color: '#cbd5e1' };
    case 'approval_missing':
      return { label: 'Missing Approval', bg: '#9a3412', color: '#fdba74' };
    case 'workflow_cancelled':
      return { label: 'Cancelled', bg: '#475569', color: '#cbd5e1' };
    default:
      return { label: kind, bg: '#334155', color: '#f8fafc' };
  }
}

export const WorkflowProgressPanel: React.FC<WorkflowProgressPanelProps> = ({ auditEvents }) => {
  if (auditEvents.length === 0) {
    return null;
  }

  return (
    <section
      aria-label="Workflow progress"
      style={{
        margin: '8px 0',
        padding: '8px 10px',
        backgroundColor: '#0f172a',
        borderRadius: '6px',
        border: '1px solid #334155',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
        <h4 style={{ margin: 0, fontSize: '11px', textTransform: 'uppercase', color: '#94a3b8', letterSpacing: '0.05em' }}>
          Workflow Progress
        </h4>
        <span style={{ fontSize: '10px', color: '#64748b' }}>
          {auditEvents.length} {auditEvents.length === 1 ? 'step event' : 'step events'}
        </span>
      </div>

      <ol
        style={{
          listStyle: 'none',
          padding: 0,
          margin: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          maxHeight: '90px',
          overflowY: 'auto',
        }}
      >
        {auditEvents.map((evt, idx) => {
          const badge = getStatusBadge(evt.kind);
          return (
            <li
              key={`${evt.sequence}-${idx}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '3px 6px',
                backgroundColor: '#1e293b',
                borderRadius: '4px',
                fontSize: '11px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden' }}>
                <span style={{ color: '#64748b', fontSize: '10px', minWidth: '16px' }}>#{evt.sequence}</span>
                <span
                  style={{
                    color: '#e2e8f0',
                    fontFamily: 'monospace',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                  }}
                  title={evt.step_id || evt.plan_id}
                >
                  {evt.step_id ? `step: ${evt.step_id}` : `plan: ${evt.plan_id}`}
                </span>
              </div>
              <span
                style={{
                  padding: '1px 6px',
                  borderRadius: '10px',
                  fontSize: '9px',
                  fontWeight: 600,
                  backgroundColor: badge.bg,
                  color: badge.color,
                  whiteSpace: 'nowrap',
                }}
              >
                {badge.label}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
};
