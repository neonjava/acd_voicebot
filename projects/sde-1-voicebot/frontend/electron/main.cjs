/**
 * Electron Main Process for the Notch Desktop Copilot.
 *
 * Rules:
 * - Frameless, transparent, always-on-top window centred at top of primary display.
 * - Collapsed: ~200×36 px pill.
 * - Expanded: at most 480×360 px.
 * - Multi-monitor origin support (display.x, display.y).
 * - Never fullscreen, no taskbar entry, non-resizable by user.
 * - On Linux, launch under XWayland (--ozone-platform=x11).
 * - Spawns backend sidecar using shared sidecar.cjs with random VOICEBOT_LAUNCH_TOKEN.
 * - Waits for readiness (VOICEBOT_READY / startup complete) and informs renderer.
 * - Context isolation true, node integration false.
 */

let electron = {};
try {
  electron = require('electron');
} catch {
  // Allows testing main.cjs pure functions in Node/Vitest without GUI binary
}
const { app, BrowserWindow, ipcMain, screen } = electron;
const path = require('node:path');
const { getNotchBounds } = require('./bounds.cjs');
const { generateLaunchToken } = require('./token.cjs');
const { startBackendSidecar } = require('./sidecar.cjs');

// On Linux, launch under XWayland so always-on-top and positioning work on GNOME Wayland
if (app && process.platform === 'linux') {
  app.commandLine.appendSwitch('ozone-platform', 'x11');
}

// Generate launch token via shared module
const launchToken = generateLaunchToken();
process.env.VOICEBOT_LAUNCH_TOKEN = launchToken;

let mainWindow = null;
let sidecarHandle = null;
let isExpanded = false;
let isBackendReadyState = false;

function startBackend(options = {}) {
  const backendDir = options.backendDir || path.resolve(__dirname, '../../backend');
  const spawnFn = options.spawnFn;

  sidecarHandle = startBackendSidecar({
    backendDir,
    token: launchToken,
    spawnFn,
    onReady: () => {
      isBackendReadyState = true;
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('voicebot:ready');
      }
      options.onReady?.();
    },
    onLog: (line) => {
      process.stdout.write(`[backend] ${line}`);
      options.onLog?.(line);
    },
    onError: (err) => {
      console.error('[sidecar error]', err.message);
      options.onError?.(err);
    },
  });

  return sidecarHandle;
}

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const bounds = getNotchBounds(primaryDisplay.bounds, false);

  mainWindow = new BrowserWindow({
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5173';
  if (process.env.NODE_ENV === 'production') {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  } else {
    mainWindow.loadURL(devUrl).catch(() => {
      mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
    });
  }

  // If backend was already ready before window finished loading, notify renderer
  mainWindow.webContents.on('did-finish-load', () => {
    if (isBackendReadyState) {
      mainWindow.webContents.send('voicebot:ready');
    }
  });

  return mainWindow;
}

// Register IPC handlers
if (ipcMain) {
  ipcMain.on('voicebot:get-token-sync', (event) => {
    event.returnValue = launchToken;
  });

  ipcMain.handle('voicebot:get-token', () => {
    return launchToken;
  });

  ipcMain.on('voicebot:is-ready-sync', (event) => {
    event.returnValue = isBackendReadyState;
  });

  ipcMain.handle('voicebot:is-ready', () => {
    return isBackendReadyState;
  });

  ipcMain.handle('voicebot:set-expanded', (_event, expanded) => {
    isExpanded = Boolean(expanded);
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const currentDisplay = screen.getPrimaryDisplay();
    const newBounds = getNotchBounds(currentDisplay.bounds, isExpanded);
    mainWindow.setBounds(newBounds, true);
  });
}

function cleanupBackend() {
  if (sidecarHandle) {
    sidecarHandle.stop();
    sidecarHandle = null;
  }
}

if (app) {
  app.whenReady().then(() => {
    if (process.env.START_SIDECAR !== 'false') {
      startBackend();
    }
    createWindow();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });

  app.on('before-quit', cleanupBackend);
  app.on('will-quit', cleanupBackend);
  app.on('window-all-closed', () => {
    cleanupBackend();
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });
}

module.exports = {
  startBackend,
  createWindow,
  cleanupBackend,
  launchToken,
  isBackendReady: () => isBackendReadyState,
};
