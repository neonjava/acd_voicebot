/**
 * Python backend sidecar process manager for Electron desktop app (CommonJS).
 * Single shared implementation used by main.cjs and tested by sidecar.test.ts.
 */

const { spawn } = require('node:child_process');
const path = require('node:path');
const { sanitizeLogOutput } = require('./token.cjs');

function startBackendSidecar(options) {
  const {
    backendDir = path.resolve(__dirname, '../../backend'),
    token,
    spawnFn = spawn,
    onReady,
    onError,
    onLog,
  } = options || {};

  if (!token || typeof token !== 'string' || token.trim().length === 0) {
    throw new Error('A non-empty launch token is required to start the backend sidecar');
  }

  const env = {
    ...process.env,
    VOICEBOT_LAUNCH_TOKEN: token,
    PYTHONUNBUFFERED: '1',
  };

  const isWindows = process.platform === 'win32';
  const child = spawnFn('uv', ['run', 'python', '-m', 'app'], {
    cwd: backendDir,
    env,
    shell: isWindows,
  });

  let readyState = false;

  const handleOutput = (chunk) => {
    const text = chunk.toString();
    const sanitized = sanitizeLogOutput(text, token);
    onLog?.(sanitized);

    // Strictly match exact ready lines:
    // "VOICEBOT_READY" or full uvicorn "Application startup complete." line.
    // Drop bare "ready" which falsely matches "address already in use" or other errors!
    if (
      !readyState &&
      !text.includes('address already in use') &&
      !text.includes('error while attempting to bind') &&
      (text.includes('VOICEBOT_READY') ||
        text.includes('Application startup complete.') ||
        text.includes('Uvicorn running on http://127.0.0.1:8000'))
    ) {
      readyState = true;
      onReady?.();
    }
  };

  child.stdout?.on('data', handleOutput);
  child.stderr?.on('data', handleOutput);

  child.on('error', (err) => {
    onError?.(err);
  });

  return {
    process: child,
    isReady: () => readyState,
    stop: () => {
      try {
        if (isWindows && child.pid) {
          spawn('taskkill', ['/pid', child.pid.toString(), '/f', '/t']);
        } else {
          child.kill('SIGTERM');
        }
      } catch {
        // Process may already have exited
      }
    },
  };
}

module.exports = {
  startBackendSidecar,
};
