/**
 * Python backend sidecar process manager for Electron desktop app (CommonJS).
 * Single shared implementation used by main.cjs and tested by sidecar.test.ts.
 */

const { spawn } = require('node:child_process');
const path = require('node:path');
const { sanitizeLogOutput } = require('./token.cjs');
const { BACKEND_HOST, DEFAULT_BACKEND_PORT } = require('./config.cjs');

const READY_LINE = /^VOICEBOT_READY(?::\s*(\S+))?$/;

/**
 * Check one complete output line for the backend's ready signal.
 * Only the backend's own `VOICEBOT_READY[: http://host:port]` line counts. Uvicorn's
 * "Application startup complete." is printed before the port is bound, so it is
 * not a ready signal. When the line names a URL, its port must be the port the
 * sidecar was started with.
 */
function parseReadyLine(line, expectedPort) {
  const match = READY_LINE.exec(String(line).trim());
  if (!match) return { ready: false };
  if (!match[1]) return { ready: true };
  let url;
  try {
    url = new URL(match[1]);
  } catch {
    return { ready: false, error: 'Backend ready line has a malformed URL' };
  }
  const port = Number(url.port || (url.protocol === 'https:' ? 443 : 80));
  if (port !== expectedPort) {
    return {
      ready: false,
      error: `Backend reported ready on port ${port}, expected ${expectedPort}`,
    };
  }
  return { ready: true };
}

function startBackendSidecar(options) {
  const {
    backendDir = path.resolve(__dirname, '../../backend'),
    token,
    port = DEFAULT_BACKEND_PORT,
    spawnFn = spawn,
    onReady,
    onError,
    onLog,
  } = options || {};

  if (!token || typeof token !== 'string' || token.trim().length === 0) {
    throw new Error('A non-empty launch token is required to start the backend sidecar');
  }
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('Backend port must be an integer between 1 and 65535');
  }

  const env = {
    ...process.env,
    VOICEBOT_LAUNCH_TOKEN: token,
    VOICEBOT_PORT: String(port),
    PORT: String(port),
    HOST: BACKEND_HOST,
    PYTHONUNBUFFERED: '1',
  };

  const isWindows = process.platform === 'win32';
  const child = spawnFn('uv', ['run', 'python', '-m', 'app'], {
    cwd: backendDir,
    env,
    shell: isWindows,
  });

  let readyState = false;
  let failed = false;

  const lineHandler = () => {
    let buffered = '';
    return (chunk) => {
      const text = chunk.toString();
      onLog?.(sanitizeLogOutput(text, token));
      buffered += text;
      const lines = buffered.split(/\r?\n/);
      buffered = lines.pop() ?? '';
      for (const line of lines) {
        if (readyState || failed) continue;
        const result = parseReadyLine(line, port);
        if (result.ready) {
          readyState = true;
          onReady?.();
        } else if (result.error) {
          failed = true;
          onError?.(new Error(result.error));
        }
      }
    };
  };

  child.stdout?.on('data', lineHandler());
  child.stderr?.on('data', lineHandler());

  child.on('error', (err) => {
    onError?.(err);
  });

  child.on('exit', (code, signal) => {
    if (!readyState && !failed) {
      failed = true;
      onError?.(
        new Error(`Backend exited before it was ready (code ${code ?? 'none'}, signal ${signal ?? 'none'})`)
      );
    }
  });

  return {
    process: child,
    port,
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
  parseReadyLine,
  startBackendSidecar,
};
