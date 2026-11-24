/**
 * Preload bridge for the notch window (runs sandboxed, contextIsolation on).
 * createVoicebotApi is the single implementation: the window exposes it and the
 * tests call it with a fake ipcRenderer. The token is fetched from the main
 * process on demand and kept only in this closure (never in localStorage).
 */

function createVoicebotApi(ipcRenderer) {
  let cachedToken = null;
  return {
    isElectron: true,
    getToken: () => {
      if (cachedToken === null) {
        try {
          const token = ipcRenderer.sendSync('voicebot:get-token-sync');
          if (typeof token === 'string' && token.length > 0) {
            cachedToken = token;
          }
        } catch {
          // fall through: no token available yet
        }
      }
      return cachedToken || '';
    },
    setWindowExpanded: (expanded) => ipcRenderer.invoke('voicebot:set-expanded', Boolean(expanded)),
    isBackendReady: () => {
      try {
        return Boolean(ipcRenderer.sendSync('voicebot:is-ready-sync'));
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
  };
}

let electron = null;
try {
  electron = require('electron');
} catch {
  electron = null;
}
if (electron && electron.contextBridge && electron.ipcRenderer) {
  electron.contextBridge.exposeInMainWorld('voicebot', createVoicebotApi(electron.ipcRenderer));
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createVoicebotApi };
}
