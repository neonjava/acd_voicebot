const { contextBridge, ipcRenderer } = require('electron');

let cachedToken = null;

contextBridge.exposeInMainWorld('voicebot', {
  isElectron: true,
  getToken: () => {
    if (cachedToken === null) {
      try {
        cachedToken = ipcRenderer.sendSync('voicebot:get-token-sync') || process.env.VOICEBOT_LAUNCH_TOKEN || '';
      } catch {
        cachedToken = process.env.VOICEBOT_LAUNCH_TOKEN || '';
      }
    }
    return cachedToken;
  },
  setWindowExpanded: (expanded) => {
    return ipcRenderer.invoke('voicebot:set-expanded', Boolean(expanded));
  },
});
