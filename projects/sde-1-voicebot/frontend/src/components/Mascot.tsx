import React from 'react';
import { CompanionState } from '../types/contracts';

/**
 * The companion's glyph: one loose thread tied in a loop. Its glow and motion show
 * what Jarvis is doing (idle, listening, thinking, working, done, error). While
 * working, the free end of the thread reaches out, as the browser extension's
 * thread cursor does inside the page. Decorative: the owning button carries the label.
 */
export const KNOT_PATH =
  'M6 52 C 14 50, 18 40, 22 30 C 27 17, 42 12, 46 22 C 50 32, 36 40, 28 34 C 20 28, 30 16, 42 26 C 52 34, 50 50, 40 52 C 32 54, 30 46, 36 42 C 44 37, 54 40, 60 34';

/** The free end that "reaches out" while a task runs. */
export const THREAD_TAIL_PATH = 'M60 34 C 63 30, 63 20, 62 8';

export const STATE_LABELS: Record<CompanionState, string> = {
  idle: 'Ready',
  listening: 'Listening',
  thinking: 'Thinking',
  working: 'Working',
  done: 'Done',
  error: 'Needs attention',
};

export interface MascotProps {
  state: CompanionState;
  reducedMotion?: boolean;
  size?: number;
}

export const Mascot: React.FC<MascotProps> = ({ state, reducedMotion = false, size = 56 }) => (
  <span
    className={`knot knot-${state}${reducedMotion ? ' reduced-motion' : ''}`}
    data-testid="companion-knot"
    data-state={state}
    aria-hidden="true"
    style={{ width: size, height: size }}
  >
    <svg viewBox="0 0 64 64" width={size} height={size} focusable="false">
      <path className="knot-halo" d={KNOT_PATH} />
      <path className="knot-tail" d={THREAD_TAIL_PATH} pathLength={100} />
      <path className="knot-line" d={KNOT_PATH} pathLength={100} />
    </svg>
  </span>
);
