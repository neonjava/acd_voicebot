/**
 * Electron Main Process for the Notch Desktop Copilot.
 *
 * Rules:
 * - Frameless, transparent, always-on-top window centred at top of primary display.
 * - Collapsed: ~200×36 px pill. Expanded: at most 480×360 px.
 * - Multi-monitor origin support (display.x, display.y).
 * - Never fullscreen, no taskbar entry, non-resizable by user.
 * - On Linux, launch under XWayland (--ozone-platform=x11).
 * - Spawns the backend sidecar (sidecar.cjs) with a random VOICEBOT_LAUNCH_TOKEN on
 *   the port from VOICEBOT_PORT (config.cjs) and waits for its VOICEBOT_READY line.
 * - The renderer always calls the backend same-origin: the Vite proxy in dev, the
 *   app:// protocol (appProtocol.cjs) in production.
 * - Sandboxed renderer, context isolation on, node integration off, navigation and
 *   new windows blocked, token only handed to the app's own pages.
 */

let electron = {};
try {
  electron = require('electron');
} catch {
  // Allows testing main.cjs pure functions in Node/Vitest without GUI binary
}
const { app, BrowserWindow, ipcMain, screen, protocol, net } = electron;
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { getNotchBounds } = require('./bounds.cjs');
const { generateLaunchToken } = require('./token.cjs');
const { startBackendSidecar } = require('./sidecar.cjs');
const { resolveBackendPort, backendOrigin, devServerUrl } = require('./config.cjs');
const {
  APP_SCHEME,
  APP_ORIGIN,
  CONTENT_SECURITY_POLICY,
  isAllowedAppUrl,
  resolveAppRequest,
  buildWebPreferences,
} = require('./appProtocol.cjs');

// On Linux, launch under XWayland so always-on-top and positioning work on GNOME Wayland
if (app && process.platform === 'linux') {
  app.commandLine.appendSwitch('ozone-platform', 'x11');
}

if (protocol && typeof protocol.registerSchemesAsPrivileged === 'function') {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: APP_SCHEME,
      privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true },
    },
  ]);
}

// Per-launch token: kept in this process and passed to the sidecar explicitly.
const launchToken = generateLaunchToken();
const backendPort = resolveBackendPort(process.env);
const backendUrl = backendOrigin(backendPort);
const distDir = path.join(__dirname, '../dist');
const devUrl = process.env.VITE_DEV_SERVER_URL || devServerUrl();
const allowedOrigins = [devUrl, APP_ORIGIN];

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
    port: backendPort,
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

/** Serve the built renderer on app://notch and forward app://notch/api/* to the sidecar. */
async function handleAppProtocol(request) {
  const decision = resolveAppRequest(request.url, distDir, backendUrl);
  if (decision.kind === 'proxy') {
    const method = request.method || 'GET';
    const body = method === 'GET' || method === 'HEAD' ? undefined : await request.arrayBuffer();
    try {
      return await net.fetch(decision.target, { method, headers: request.headers, body });
    } catch {
      return new Response(
        JSON.stringify({
          code: 'BACKEND_UNREACHABLE',
          message_safe_for_user: 'The local backend is not reachable.',
          retryable: true,
          correlation_id: 'corr-electron-proxy',
          details_redacted: {},
        }),
        { status: 502, headers: { 'Content-Type': 'application/json' } }
      );
    }
  }
  if (decision.kind === 'file') {
    try {
      const fileResponse = await net.fetch(pathToFileURL(decision.filePath).toString());
      const headers = new Headers(fileResponse.headers);
      headers.set('Content-Security-Policy', CONTENT_SECURITY_POLICY);
      return new Response(fileResponse.body, { status: fileResponse.status, headers });
    } catch {
      return new Response('Not found', { status: 404 });
    }
  }
  return new Response('Forbidden', { status: 403 });
}

function lockDownWindow(win) {
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedAppUrl(url, allowedOrigins)) {
      event.preventDefault();
    }
  });
  win.webContents.on('will-redirect', (event, url) => {
    if (!isAllowedAppUrl(url, allowedOrigins)) {
      event.preventDefault();
    }
  });
}

function isTrustedSender(event) {
  const url = event && event.senderFrame ? event.senderFrame.url : '';
  return isAllowedAppUrl(url, allowedOrigins);
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
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: buildWebPreferences(path.join(__dirname, 'preload.cjs')),
  });
  lockDownWindow(mainWindow);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  const appUrl = `${APP_ORIGIN}/index.html`;
  if (process.env.NODE_ENV === 'production') {
    mainWindow.loadURL(appUrl);
  } else {
    mainWindow.loadURL(devUrl).catch(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadURL(appUrl);
      }
    });
  }

  // If backend was already ready before window finished loading, notify renderer
  mainWindow.webContents.on('did-finish-load', () => {
    if (isBackendReadyState && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('voicebot:ready');
    }
  });

  return mainWindow;
}

// Register IPC handlers
if (ipcMain) {
  ipcMain.on('voicebot:get-token-sync', (event) => {
    event.returnValue = isTrustedSender(event) ? launchToken : '';
  });

  ipcMain.on('voicebot:is-ready-sync', (event) => {
    event.returnValue = isBackendReadyState;
  });

  ipcMain.handle('voicebot:set-expanded', (event, expanded) => {
    if (!isTrustedSender(event)) return;
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
    protocol.handle(APP_SCHEME, handleAppProtocol);
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
  backendPort,
  allowedOrigins,
  isBackendReady: () => isBackendReadyState,
};
