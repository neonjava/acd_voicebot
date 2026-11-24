/**
 * Typed re-export of the preload bridge implemented once in preload.cjs.
 * Enforces contextIsolation: true and nodeIntegration: false (see appProtocol.cjs).
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const preloadCjs = require('./preload.cjs');

export interface VoicebotDesktopAPI {
  isElectron: true;
  getToken: () => string;
  setWindowExpanded: (expanded: boolean) => Promise<void>;
  isBackendReady?: () => boolean;
  onBackendReady?: (callback: () => void) => () => void;
}

export interface PreloadIpcRenderer {
  sendSync: (channel: string, ...args: unknown[]) => unknown;
  invoke: (channel: string, ...args: unknown[]) => Promise<unknown>;
  on: (channel: string, listener: (...args: unknown[]) => void) => unknown;
  removeListener: (channel: string, listener: (...args: unknown[]) => void) => unknown;
}

declare global {
  interface Window {
    voicebot?: VoicebotDesktopAPI;
  }
}

export const createVoicebotApi: (ipcRenderer: PreloadIpcRenderer) => VoicebotDesktopAPI =
  preloadCjs.createVoicebotApi;
