import React from 'react';
import { BrowserAction, BrowserActionEventPayload } from '../types/contracts';

function host(url: string | null | undefined): string {
  if (!url) return 'page';
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return 'page';
  }
}

/**
 * A short human label for one browser action. Typed text is never shown (it may be
 * a search, a message or a sensitive value); only its length is.
 */
export function describeAction(action: BrowserAction): string {
  switch (action.kind) {
    case 'navigate':
      return `Open ${host(action.url)}`;
    case 'read_page':
      return 'Read page';
    case 'click':
      return `Click ${action.ref ?? 'element'}`;
    case 'type': {
      const n = action.text?.length ?? 0;
      return `Type ${n} character${n === 1 ? '' : 's'}`;
    }
    case 'press_key':
      return `Press ${action.key ?? 'key'}`;
    case 'scroll':
      return (action.scroll_y ?? 0) < 0 ? 'Scroll up' : 'Scroll down';
    case 'wait':
      return 'Wait';
    default:
      return 'Action';
  }
}

export type ChipStatus = 'done' | 'active' | 'failed';

export function chipStatus(item: BrowserActionEventPayload, isLast: boolean, running: boolean): ChipStatus {
  if (!item.ok) return 'failed';
  return isLast && running ? 'active' : 'done';
}

export interface StepChipsProps {
  actions: BrowserActionEventPayload[];
  /** True while the task runs: the newest chip is the one in progress. */
  running: boolean;
}

export const StepChips: React.FC<StepChipsProps> = ({ actions, running }) => {
  if (actions.length === 0) return null;
  return (
    <ol className="chips" aria-label="Browser steps">
      {actions.map((item, i) => {
        const status = chipStatus(item, i === actions.length - 1, running);
        return (
          <li
            key={item.action.action_id}
            className={`chip chip-${status}`}
            data-testid={`step-chip-${item.action.action_id}`}
            data-status={status}
          >
            <span className="chip-mark" aria-hidden="true" />
            <span>{describeAction(item.action)}</span>
            {status === 'failed' && <span className="chip-code">{item.error_code}</span>}
            <span className="sr-only">
              {status === 'done' ? ' (done)' : status === 'active' ? ' (in progress)' : ' (failed)'}
            </span>
          </li>
        );
      })}
    </ol>
  );
};
