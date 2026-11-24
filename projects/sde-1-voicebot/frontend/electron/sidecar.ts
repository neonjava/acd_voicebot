/**
 * Python backend sidecar process manager for Electron desktop app.
 * Re-exports the single shared CommonJS implementation used by main.cjs.
 */

import { ChildProcess, SpawnOptions } from 'node:child_process';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const sidecarCjs = require('./sidecar.cjs');

export interface SidecarOptions {
  backendDir?: string;
  token: string;
  port?: number;
  spawnFn?: (command: string, args: string[], options: SpawnOptions) => ChildProcess;
  onReady?: () => void;
  onError?: (error: Error) => void;
  onLog?: (line: string) => void;
}

export interface SidecarHandle {
  process: ChildProcess;
  port: number;
  isReady: () => boolean;
  stop: () => void;
}

export const startBackendSidecar: (options: SidecarOptions) => SidecarHandle = sidecarCjs.startBackendSidecar;

export const parseReadyLine: (
  line: string,
  expectedPort: number
) => { ready: boolean; error?: string } = sidecarCjs.parseReadyLine;
