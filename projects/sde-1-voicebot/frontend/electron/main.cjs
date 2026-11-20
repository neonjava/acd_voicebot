/**
 * Electron Main Process for the Notch Desktop Copilot.
 *
 * Rules:
 * - Frameless, transparent, always-on-top window centred at top of primary display.
 * - Collapsed: ~200×36 px pill.
 * - Expanded: at most 480×360 px.
 * - Never fullscreen, no taskbar entry, non-resizable by user.
 * - On Linux, launch under XWayland (--ozone-platform=x11).
 * - Spawns backend sidecar with random VOICEBOT_LAUNCH_TOKEN.
 * - Context isolation true, node integration false.
 */

const { app, BrowserWindow, ipcMain, screen } = require('electron');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { getNotchBounds } = require('./bounds.cjs');

// On Linux, launch under XWayland so always-on-top and positioning work on GNOME Wayland
if (process.platform === 'linux') {
  app.commandLine.appendSwitch('ozone-platform', 'x11');
}

// Generate launch token
const launchToken = `vbt-${crypto.randomBytes(24).toString('hex')}`;
process.env.VOICEBOT_LAUNCH_TOKEN = launchToken;

let mainWindow = null;
let backendProcess = null;
let isExpanded = false;

function startBackend() {
  const backendDir = path.resolve(__dirname, '../../backend');
  const isWindows = process.platform === 'win32';

  try {
    backendProcess = spawn('uv', ['run', 'python', '-m', 'app'], {
      cwd: backendDir,
      env: {
        ...process.env,
        VOICEBOT_LAUNCH_TOKEN: launchToken,
        PYTHONUNBUFFERED: '1',
      },
      shell: isWindows,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    backendProcess.stdout?.on('data', (chunk) => {
      const line = chunk.toString();
      // Ensure token is never logged
      const safe = line.split(launchToken).join('[REDACTED]');
      process.stdout.write(`[backend] ${safe}`);
    });

    backendProcess.stderr?.on('data', (chunk) => {
      const line = chunk.toString();
      const safe = line.split(launchToken).join('[REDACTED]');
      process.stderr.write(`[backend] ${safe}`);
    });

    backendProcess.on('error', (err) => {
      console.error('[sidecar error]', err.message);
    });
  } catch (err) {
    console.error('Failed to spawn backend sidecar:', err);
  }
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

  // Provide token over sync and async IPC
  ipcMain.on('voicebot:get-token-sync', (event) => {
    event.returnValue = launchToken;
  });

  ipcMain.handle('voicebot:get-token', () => {
    return launchToken;
  });

  // Handle window expansion/collapse
  ipcMain.handle('voicebot:set-expanded', (_event, expanded) => {
    isExpanded = Boolean(expanded);
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const currentDisplay = screen.getPrimaryDisplay();
    const newBounds = getNotchBounds(currentDisplay.bounds, isExpanded);
    mainWindow.setBounds(newBounds, true);
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5173';
  if (process.env.NODE_ENV === 'production') {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  } else {
    mainWindow.loadURL(devUrl).catch(() => {
      mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
    });
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function cleanupBackend() {
  if (backendProcess && !backendProcess.killed) {
    try {
      if (process.platform === 'win32' && backendProcess.pid) {
        spawn('taskkill', ['/pid', backendProcess.pid.toString(), '/f', '/t']);
      } else {
        backendProcess.kill('SIGTERM');
      }
    } catch {
      // Best-effort cleanup
    }
    backendProcess = null;
  }
}

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
