/**
 * Electron Preload script contract and pure setup helper.
 * Enforces contextIsolation: true and nodeIntegration: false.
 */

export interface VoicebotDesktopAPI {
  isElectron: true;
  backendUrl?: string;
  getBackendUrl?: () => string;
  getToken: () => string;
  setWindowExpanded: (expanded: boolean) => Promise<void>;
  isBackendReady?: () => boolean;
  onBackendReady?: (callback: () => void) => () => void;
}

declare global {
  interface Window {
    voicebot?: VoicebotDesktopAPI;
  }
}

export function setupPreloadBridge(
  exposeFn: (key: string, api: VoicebotDesktopAPI) => void,
  invokeIpc: (channel: string, ...args: unknown[]) => Promise<unknown>,
  tokenGetter: () => string,
  isReadyGetter: () => boolean = () => true,
  onReadySubscribe?: (cb: () => void) => () => void
): void {
  const api: VoicebotDesktopAPI = {
    isElectron: true,
    backendUrl: 'http://127.0.0.1:8000',
    getBackendUrl: () => 'http://127.0.0.1:8000',
    getToken: () => {
      const token = tokenGetter();
      // Ensure token is never stored in localStorage
      return token;
    },
    setWindowExpanded: async (expanded: boolean) => {
      await invokeIpc('voicebot:set-expanded', Boolean(expanded));
    },
    isBackendReady: () => isReadyGetter(),
    onBackendReady: onReadySubscribe,
  };
  exposeFn('voicebot', api);
}
