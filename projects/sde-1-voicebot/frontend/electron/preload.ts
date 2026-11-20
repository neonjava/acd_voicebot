/**
 * Electron Preload script contract and pure setup helper.
 * Enforces contextIsolation: true and nodeIntegration: false.
 */

export interface VoicebotDesktopAPI {
  isElectron: true;
  getToken: () => string;
  setWindowExpanded: (expanded: boolean) => Promise<void>;
}

declare global {
  interface Window {
    voicebot?: VoicebotDesktopAPI;
  }
}

export function setupPreloadBridge(
  exposeFn: (key: string, api: VoicebotDesktopAPI) => void,
  invokeIpc: (channel: string, ...args: unknown[]) => Promise<unknown>,
  tokenGetter: () => string
): void {
  const api: VoicebotDesktopAPI = {
    isElectron: true,
    getToken: () => {
      const token = tokenGetter();
      // Ensure token is never stored in localStorage
      return token;
    },
    setWindowExpanded: async (expanded: boolean) => {
      await invokeIpc('voicebot:set-expanded', Boolean(expanded));
    },
  };
  exposeFn('voicebot', api);
}
