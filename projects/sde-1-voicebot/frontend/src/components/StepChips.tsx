import React from 'react';
import { BrowserActionEvent, BrowserActionStatus } from '../types/contracts';

export interface StepItem {
  id: string;
  label: string;
  status: BrowserActionStatus;
  target?: string;
}

export interface StepChipsProps {
  steps: StepItem[];
}

export function actionsToStepItems(actions: BrowserActionEvent[]): StepItem[] {
  return actions.map((a) => ({
    id: a.action_id,
    label: a.label,
    status: a.status,
    target: a.target,
  }));
}

export const StepChips: React.FC<StepChipsProps> = ({ steps }) => {
  if (steps.length === 0) {
    return null;
  }

  return (
    <div
      className="step-chips-container"
      role="region"
      aria-label="Workflow Browser Steps Progress"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '6px',
        alignItems: 'center',
        padding: '6px 8px',
        background: 'rgba(15, 23, 42, 0.65)',
        borderRadius: '8px',
        border: '1px solid rgba(56, 189, 248, 0.2)',
        fontSize: '11px',
      }}
    >
      <span style={{ color: '#94a3b8', fontWeight: 600, marginRight: '4px' }}>Steps:</span>
      {steps.map((step, idx) => {
        const isDone = step.status === 'completed';
        const isRunning = step.status === 'running';
        const isFailed = step.status === 'failed';

        const badgeColor = isDone
          ? '#34d399' // green
          : isRunning
          ? '#38bdf8' // cyan
          : isFailed
          ? '#f87171' // red
          : '#64748b'; // gray

        const icon = isDone ? '✓' : isRunning ? '◌' : isFailed ? '✗' : '…';

        return (
          <React.Fragment key={step.id}>
            <span
              className={`step-chip step-chip-${step.status}`}
              data-testid={`step-chip-${step.id}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '2px 8px',
                borderRadius: '9999px',
                background: isRunning ? 'rgba(56, 189, 248, 0.15)' : 'rgba(30, 41, 59, 0.8)',
                border: `1px solid ${badgeColor}`,
                color: isDone ? '#e2e8f0' : badgeColor,
                fontWeight: isRunning ? 700 : 500,
              }}
              title={`Step: ${step.label} (${step.status})`}
            >
              <span
                style={{
                  color: badgeColor,
                  fontWeight: 'bold',
                  display: 'inline-block',
                  animation: isRunning ? 'spin 1.5s linear infinite' : 'none',
                }}
                aria-hidden="true"
              >
                {icon}
              </span>
              <span>{step.label}</span>
            </span>
            {idx < steps.length - 1 && (
              <span style={{ color: '#475569', fontSize: '10px' }} aria-hidden="true">
                →
              </span>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};
