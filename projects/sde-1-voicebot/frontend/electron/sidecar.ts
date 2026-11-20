/**
 * Python backend sidecar process manager for Electron desktop app.
 *
 * Requirements:
 * - Spawns backend (uv run python -m app from backend/) with random VOICEBOT_LAUNCH_TOKEN.
 * - Waits for the ready line before signaling readiness.
 * - Supports dependency-injected spawn for pure unit testing without external side-effects.
 * - Token is never logged in full.
 */

import { ChildProcess, SpawnOptions, spawn } from 'node:child_process';
import { sanitizeLogOutput } from './token.js';

export interface SidecarOptions {
  backendDir?: string;
  token: string;
  spawnFn?: (command: string, args: string[], options: SpawnOptions) => ChildProcess;
  onReady?: () => void;
  onError?: (error: Error) => void;
  onLog?: (line: string) => void;
}

export interface SidecarHandle {
  process: ChildProcess;
  isReady: () => boolean;
  stop: () => void;
}

export function startBackendSidecar(options: SidecarOptions): SidecarHandle {
  const {
    backendDir = '../../backend',
    token,
    spawnFn = spawn,
    onReady,
    onError,
    onLog,
  } = options;

  if (!token || token.trim().length === 0) {
    throw new Error('A non-empty launch token is required to start the backend sidecar');
  }

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    VOICEBOT_LAUNCH_TOKEN: token,
    PYTHONUNBUFFERED: '1',
  };

  const isWindows = process.platform === 'win32';
  const child = spawnFn('uv', ['run', 'python', '-m', 'app'], {
    cwd: backendDir,
    env,
    shell: isWindows,
  });

  let readyState = false;

  const handleOutput = (chunk: Buffer | string) => {
    const text = chunk.toString();
    const sanitized = sanitizeLogOutput(text, token);
    onLog?.(sanitized);

    if (
      !readyState &&
      (text.includes('Application startup complete') ||
        text.includes('Uvicorn running on') ||
        text.includes('"status":"ready"') ||
        text.includes('ready'))
    ) {
      readyState = true;
      onReady?.();
    }
  };

  child.stdout?.on('data', handleOutput);
  child.stderr?.on('data', handleOutput);

  child.on('error', (err) => {
    onError?.(err);
  });

  return {
    process: child,
    isReady: () => readyState,
    stop: () => {
      try {
        if (isWindows && child.pid) {
          spawn('taskkill', ['/pid', child.pid.toString(), '/f', '/t']);
        } else {
          child.kill('SIGTERM');
        }
      } catch {
        // Process may already have exited
      }
    },
  };
}
