import React from 'react';
import { TurnResponse, WorkflowStep } from '../types/contracts';

const ERROR_MESSAGES: Record<string, string> = {
  BROWSER_NOT_CONNECTED: 'The Jarvis browser extension is not connected.',
  DEPENDENCY_UNAVAILABLE: 'Part of Jarvis is not running yet. Try again in a moment.',
  TTS_UNAVAILABLE: 'Voice replies are off.',
  LLM_UNAVAILABLE: 'The local model is not running.',
};

/** A safe, user-facing line for a TurnResponse error_code. */
export function turnErrorMessage(code: string): string {
  return ERROR_MESSAGES[code] ?? `Something went wrong (${code}).`;
}

function siteOf(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
}

/** One plan step in plain words: "Browser task on youtube.com", "Close Chrome", … */
export function describeStep(step: WorkflowStep): string {
  const args = step.arguments ?? {};
  switch (step.tool_name) {
    case 'browser_task': {
      const site = siteOf(args.start_url);
      return site ? `Browser task on ${site}` : 'Browser task';
    }
    case 'open_url':
      return `Open ${siteOf(args.url) ?? 'a page'}`;
    case 'close_app':
      return `Close ${args.app ?? 'an app'}`;
    case 'system_stats':
      return 'Read system stats';
    default:
      return step.tool_name.replace(/_/g, ' ');
  }
}

export type PlanDecision = 'pending' | 'approved' | 'rejected';

const DECISION_LABEL: Record<PlanDecision, string> = {
  pending: 'needs your OK',
  approved: 'approved',
  rejected: 'rejected',
};

export interface SpeechBubbleProps {
  userQuery?: string;
  turnResponse?: TurnResponse | null;
  /** Where the plan's approval stands; shown next to steps that need one. */
  planDecision?: PlanDecision;
}

/** The current exchange: what the user asked and Jarvis's reply (answer, question or plan). */
export const SpeechBubble: React.FC<SpeechBubbleProps> = ({ userQuery, turnResponse, planDecision = 'pending' }) => {
  if (!userQuery && !turnResponse) return null;
  return (
    <div className="turn" data-testid="turn-view">
      {userQuery && (
        <p className="turn-user" data-testid="turn-user">
          {userQuery}
        </p>
      )}
      {turnResponse?.kind === 'answer' && (
        <div className="turn-reply" data-testid="turn-answer">
          <p>{turnResponse.answer}</p>
          {turnResponse.source_ids.length > 0 ? (
            <ul className="sources" aria-label="Sources">
              {turnResponse.source_ids.map((id) => (
                <li key={id}>{id}</li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
      {turnResponse?.kind === 'clarify' && (
        <div className="turn-reply turn-clarify" data-testid="turn-clarify">
          <p>{turnResponse.clarify}</p>
        </div>
      )}
      {turnResponse?.kind === 'proposal' && turnResponse.proposal && (
        <div className="turn-reply turn-plan" data-testid="turn-proposal">
          <p>{turnResponse.proposal.summary}</p>
          <ul className="plan-steps" aria-label="Plan">
            {turnResponse.proposal.steps.map((st) => (
              <li key={st.step_id}>
                {describeStep(st)}
                {st.requires_approval && (
                  <span className={`plan-flag is-${planDecision}`}> · {DECISION_LABEL[planDecision]}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
