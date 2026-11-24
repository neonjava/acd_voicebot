import React from 'react';
import { MascotState } from '../types/contracts';

export interface MascotProps {
  state: MascotState;
  reducedMotion?: boolean;
  size?: number;
  onClick?: () => void;
}

const STATE_CONFIG: Record<
  MascotState,
  { label: string; primaryColor: string; glowColor: string; description: string }
> = {
  idle: {
    label: 'Idle',
    primaryColor: '#38bdf8', // soft cyan
    glowColor: 'rgba(56, 189, 248, 0.35)',
    description: 'Jarvis is resting and ready',
  },
  listening: {
    label: 'Listening',
    primaryColor: '#60a5fa', // bright blue wave
    glowColor: 'rgba(96, 165, 250, 0.65)',
    description: 'Listening for your voice or request',
  },
  thinking: {
    label: 'Thinking',
    primaryColor: '#c084fc', // purple / violet shimmer
    glowColor: 'rgba(192, 132, 252, 0.6)',
    description: 'Reasoning and planning next steps',
  },
  working: {
    label: 'Working',
    primaryColor: '#2dd4bf', // energetic teal
    glowColor: 'rgba(45, 212, 191, 0.7)',
    description: 'Performing browser actions and steps',
  },
  done: {
    label: 'Done',
    primaryColor: '#34d399', // emerald green
    glowColor: 'rgba(52, 211, 153, 0.55)',
    description: 'Finished request successfully',
  },
};

export const Mascot: React.FC<MascotProps> = ({
  state,
  reducedMotion = false,
  size = 56,
  onClick,
}) => {
  const config = STATE_CONFIG[state] || STATE_CONFIG.idle;

  return (
    <div
      className={`mascot-container mascot-${state} ${reducedMotion ? 'reduced-motion' : ''}`}
      onClick={onClick}
      role="status"
      aria-label={`Jarvis Companion Mascot: ${config.label}`}
      title={`Jarvis: ${config.label} - ${config.description}`}
      style={{
        width: size,
        height: size,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      {/* Outer glow ring */}
      <div
        className="mascot-glow-ring"
        style={{
          position: 'absolute',
          inset: -4,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${config.glowColor} 0%, transparent 70%)`,
          filter: 'blur(4px)',
          transition: reducedMotion ? 'none' : 'all 0.4s ease',
          animation:
            reducedMotion
              ? 'none'
              : state === 'listening' || state === 'working'
              ? 'pulseRing 1.8s infinite ease-in-out'
              : 'none',
        }}
      />

      {/* SVG Glowing Thread Knot Shape */}
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="mascot-thread-svg"
        aria-hidden="true"
        style={{
          filter: `drop-shadow(0 0 8px ${config.glowColor})`,
          transition: reducedMotion ? 'none' : 'transform 0.3s ease',
        }}
      >
        <defs>
          <linearGradient id={`mascot-grad-${state}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={config.primaryColor} stopOpacity="1" />
            <stop offset="100%" stopColor="#ffffff" stopOpacity="0.85" />
          </linearGradient>
        </defs>

        {/* Orbiting / glowing thread path */}
        <path
          d="M32 10C20 10 12 18 12 28C12 40 28 44 32 54C36 44 52 40 52 28C52 18 44 10 32 10Z"
          stroke={`url(#mascot-grad-${state})`}
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={reducedMotion ? 'none' : state === 'thinking' ? '8 4' : 'none'}
        />

        {/* Inner loop core */}
        <circle
          cx="32"
          cy="28"
          r="6"
          fill={config.primaryColor}
          opacity="0.9"
        />

        {/* Dynamic status indicators */}
        {state === 'listening' && (
          <circle
            cx="32"
            cy="28"
            r="12"
            stroke={config.primaryColor}
            strokeWidth="1.5"
            strokeDasharray="4 4"
            opacity="0.6"
          />
        )}
      </svg>

      {/* Screen-reader live announcement */}
      <span className="sr-only" aria-live="polite">
        Mascot status is {config.label}: {config.description}
      </span>
    </div>
  );
};
