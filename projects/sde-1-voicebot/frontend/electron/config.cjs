/**
 * Shared launch configuration for the notch desktop app (CommonJS).
 * One source of truth for the dev-server address and the backend port, used by
 * main.cjs (sidecar + window), vite.config.ts (dev proxy) and the tests.
 */

const DEV_SERVER_HOST = '127.0.0.1';
const DEV_SERVER_PORT = 5173;
const DEFAULT_BACKEND_PORT = 8000;
const BACKEND_HOST = '127.0.0.1';

/**
 * Port the backend sidecar listens on. Read from VOICEBOT_PORT so the Electron
 * main process, the Vite dev proxy and the backend all agree on one value.
 */
function resolveBackendPort(env = process.env) {
  const raw = env && env.VOICEBOT_PORT;
  if (raw === undefined || raw === null || String(raw).trim() === '') {
    return DEFAULT_BACKEND_PORT;
  }
  const text = String(raw).trim();
  const port = Number(text);
  if (!/^\d+$/.test(text) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('VOICEBOT_PORT must be an integer between 1 and 65535');
  }
  return port;
}

function backendOrigin(port) {
  return `http://${BACKEND_HOST}:${port}`;
}

function devServerUrl() {
  return `http://${DEV_SERVER_HOST}:${DEV_SERVER_PORT}`;
}

module.exports = {
  DEV_SERVER_HOST,
  DEV_SERVER_PORT,
  DEFAULT_BACKEND_PORT,
  BACKEND_HOST,
  resolveBackendPort,
  backendOrigin,
  devServerUrl,
};
