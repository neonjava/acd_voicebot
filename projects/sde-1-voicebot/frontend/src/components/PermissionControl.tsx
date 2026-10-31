import React from 'react';
import { SimulatedPermissionState } from '../types/contracts';

interface PermissionControlProps {
  permission: SimulatedPermissionState;
  onChange: (newPermission: SimulatedPermissionState) => void;
  disabled?: boolean;
}

export const PermissionControl: React.FC<PermissionControlProps> = ({
  permission,
  onChange,
  disabled = false,
}) => {
  const options: { value: SimulatedPermissionState; label: string; desc: string }[] = [
    { value: 'granted', label: 'Granted', desc: 'Mock microphone access allowed' },
    { value: 'prompt', label: 'Prompt', desc: 'Requires simulated user confirmation' },
    { value: 'denied', label: 'Denied', desc: 'User blocked simulated permission' },
    { value: 'unavailable', label: 'Unavailable', desc: 'Simulated microphone not detected' },
  ];

  return (
    <fieldset
      className="permission-control"
      style={{
        border: '1px solid #ced4da',
        borderRadius: '6px',
        padding: '12px 16px',
        marginBottom: '20px',
      }}
    >
      <legend style={{ fontWeight: 600, padding: '0 6px', fontSize: '0.95rem' }}>
        Simulated Microphone Permission (Mock only)
      </legend>
      <p style={{ margin: '0 0 10px 0', fontSize: '0.85rem', color: '#6c757d' }}>
        Controls simulated device state. Browser <code>getUserMedia()</code> is never invoked.
      </p>
      <div
        role="radiogroup"
        aria-label="Simulated microphone permission state"
        style={{ display: 'flex', flexWrap: 'wrap', gap: '16px' }}
      >
        {options.map((opt) => (
          <div key={opt.value} style={{ display: 'inline-flex', alignItems: 'center' }}>
            <input
              id={`perm-input-${opt.value}`}
              type="radio"
              name="simulated-mic-permission"
              value={opt.value}
              checked={permission === opt.value}
              onChange={() => onChange(opt.value)}
              disabled={disabled}
              aria-describedby={`perm-desc-${opt.value}`}
            />
            <label
              htmlFor={`perm-input-${opt.value}`}
              style={{
                marginLeft: '6px',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.6 : 1,
                fontSize: '0.9rem',
                fontWeight: permission === opt.value ? 600 : 400,
              }}
            >
              {opt.label}
            </label>
            <span id={`perm-desc-${opt.value}`} style={{ display: 'none' }}>
              {opt.desc}
            </span>
          </div>
        ))}
      </div>
    </fieldset>
  );
};
