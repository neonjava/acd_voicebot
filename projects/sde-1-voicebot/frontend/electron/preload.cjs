const { contextBridge, ipcRenderer } = require('electron');

let cachedToken = null;

contextBridge.exposeInMainWorld('voicebot', {
  isElectron: true,
  backendUrl: 'http://127.0.0.1:8000',
  getBackendUrl: () => 'http://127.0.0.1:8000',
  getToken: () => {
    if (cachedToken === null) {
      try {
        cachedToken =
          ipcRenderer.sendSync('voicebot:get-token-sync') ||
          process.env.VOICEBOT_LAUNCH_TOKEN ||
          '';
      } catch {
        cachedToken = process.env.VOICEBOT_LAUNCH_TOKEN || '';
      }
    }
    return cachedToken;
  },
  setWindowExpanded: (expanded) => {
    return ipcRenderer.invoke('voicebot:set-expanded', Boolean(expanded));
  },
  isBackendReady: () => {
    try {
      return ipcRenderer.sendSync('voicebot:is-ready-sync');
    } catch {
      return false;
    }
  },
  onBackendReady: (callback) => {
    const handler = () => callback();
    ipcRenderer.on('voicebot:ready', handler);
    return () => {
      ipcRenderer.removeListener('voicebot:ready', handler);
    };
  },
});
