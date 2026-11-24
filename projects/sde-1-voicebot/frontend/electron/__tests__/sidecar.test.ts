import { EventEmitter } from 'node:events';
import { describe, expect, it, vi } from 'vitest';
import { createVoicebotApi } from '../preload';
import { parseReadyLine, startBackendSidecar } from '../sidecar';
import { generateLaunchToken, sanitizeLogOutput } from '../token';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const mainCjs = require('../main.cjs');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const sidecarCjs = require('../sidecar.cjs');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const tokenCjs = require('../token.cjs');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const preloadCjs = require('../preload.cjs');

function fakeChild(pid: number) {
  const stdout = new EventEmitter();
  const stderr = new EventEmitter();
  const child = new EventEmitter() as any;
  child.stdout = stdout;
  child.stderr = stderr;
  child.kill = vi.fn();
  child.pid = pid;
  return { child, stdout, stderr };
}

describe('Token Generation and Sanitization (Finding 11)', () => {
  it('guarantees token.ts re-exports the exact implementation from token.cjs', () => {
    const t = generateLaunchToken();
    expect(t).toMatch(/^vbt-[0-9a-f]{48}$/);
    const sanitized = sanitizeLogOutput(`secret ${t}`, t);
    expect(sanitized).toBe('secret [REDACTED_LAUNCH_TOKEN]');
    expect(tokenCjs.sanitizeLogOutput(`secret ${t}`, t)).toBe('secret [REDACTED_LAUNCH_TOKEN]');
  });

  it('generates random launch tokens with vbt- prefix and high entropy', () => {
    const t1 = generateLaunchToken();
    const t2 = generateLaunchToken();

    expect(t1).toMatch(/^vbt-[0-9a-f]{48}$/);
    expect(t2).toMatch(/^vbt-[0-9a-f]{48}$/);
    expect(t1).not.toBe(t2);
  });

  it('sanitizes launch token from logs and output streams', () => {
    const token = 'vbt-1234567890abcdef12345678';
    const logLine = `Starting server with token: ${token} at 127.0.0.1:8000`;
    const sanitized = sanitizeLogOutput(logLine, token);

    expect(sanitized).not.toContain(token);
    expect(sanitized).toBe('Starting server with token: [REDACTED_LAUNCH_TOKEN] at 127.0.0.1:8000');
  });

  it('handles empty or short tokens gracefully without corrupting messages', () => {
    const msg = 'regular message without secrets';
    expect(sanitizeLogOutput(msg, '')).toBe(msg);
  });
});

// Behaviour change (review of #79): the test now drives createVoicebotApi from
// preload.cjs, the code the window actually loads, instead of a separate TS copy.
// The bridge no longer exposes a backend URL (requests stay same-origin).
describe('Preload Bridge Setup', () => {
  function fakeIpc(token: string) {
    const listeners = new Map<string, Set<(...args: unknown[]) => void>>();
    return {
      sendSync: vi.fn((channel: string) => {
        if (channel === 'voicebot:get-token-sync') return token;
        if (channel === 'voicebot:is-ready-sync') return true;
        return undefined;
      }),
      invoke: vi.fn().mockResolvedValue(undefined),
      on: vi.fn((channel: string, l: (...args: unknown[]) => void) => {
        if (!listeners.has(channel)) listeners.set(channel, new Set());
        listeners.get(channel)!.add(l);
      }),
      removeListener: vi.fn((channel: string, l: (...args: unknown[]) => void) => {
        listeners.get(channel)?.delete(l);
      }),
      emit: (channel: string) => listeners.get(channel)?.forEach((l) => l()),
    };
  }

  it('exposes window.voicebot from preload.cjs and never stores token in localStorage', async () => {
    expect(createVoicebotApi).toBe(preloadCjs.createVoicebotApi);
    const token = generateLaunchToken();
    const ipc = fakeIpc(token);
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem');

    const api = createVoicebotApi(ipc);

    expect(api.isElectron).toBe(true);
    expect(api).not.toHaveProperty('backendUrl');
    expect(api).not.toHaveProperty('getBackendUrl');
    expect(api.getToken()).toBe(token);
    expect(api.getToken()).toBe(token);
    // token fetched once from the main process and cached in the closure
    expect(ipc.sendSync.mock.calls.filter((c) => c[0] === 'voicebot:get-token-sync')).toHaveLength(1);
    expect(api.isBackendReady?.()).toBe(true);

    await api.setWindowExpanded(true);
    expect(ipc.invoke).toHaveBeenCalledWith('voicebot:set-expanded', true);

    const onReady = vi.fn();
    const unsubscribe = api.onBackendReady!(onReady);
    ipc.emit('voicebot:ready');
    expect(onReady).toHaveBeenCalledTimes(1);
    unsubscribe();
    ipc.emit('voicebot:ready');
    expect(onReady).toHaveBeenCalledTimes(1);

    expect(storageSpy).not.toHaveBeenCalled();
    expect(Object.values({ ...localStorage })).not.toContain(token);
    storageSpy.mockRestore();
  });

  it('retries the token lookup when the main process had none yet', () => {
    const ipc = fakeIpc('');
    const api = createVoicebotApi(ipc);
    expect(api.getToken()).toBe('');
    ipc.sendSync.mockImplementation((channel: string) =>
      channel === 'voicebot:get-token-sync' ? 'vbt-later-token-123' : undefined
    );
    expect(api.getToken()).toBe('vbt-later-token-123');
  });
});

describe('Backend Sidecar Process Manager & Readiness (Finding 10 & 11)', () => {
  it('guarantees sidecar.ts re-exports sidecar.cjs used by main.cjs', () => {
    expect(startBackendSidecar).toBe(sidecarCjs.startBackendSidecar);
  });

  it('throws when launch token is empty', () => {
    expect(() =>
      startBackendSidecar({
        token: '',
      })
    ).toThrow('A non-empty launch token is required');
  });

  it('does NOT trigger readiness on port conflict line ("address already in use") (Finding 10)', () => {
    const token = generateLaunchToken();
    const stdoutEmitter = new EventEmitter();
    const stderrEmitter = new EventEmitter();
    const processEmitter = new EventEmitter() as any;
    processEmitter.stdout = stdoutEmitter;
    processEmitter.stderr = stderrEmitter;
    processEmitter.kill = vi.fn();
    processEmitter.pid = 9991;

    const mockSpawn = vi.fn(() => processEmitter);
    const onReady = vi.fn();

    const handle = startBackendSidecar({
      backendDir: '../backend',
      token,
      spawnFn: mockSpawn as any,
      onReady,
    });

    expect(handle.isReady()).toBe(false);

    // Emit the exact error line that previously caused false readiness
    const bindError = "ERROR:    [Errno 98] error while attempting to bind on address ('127.0.0.1', 8000): address already in use\n";
    stderrEmitter.emit('data', Buffer.from(bindError));

    // Must stay strictly false!
    expect(handle.isReady()).toBe(false);
    expect(onReady).not.toHaveBeenCalled();

    // Now emit the real agreed VOICEBOT_READY line
    stdoutEmitter.emit('data', Buffer.from('VOICEBOT_READY\n'));
    expect(handle.isReady()).toBe(true);
    expect(onReady).toHaveBeenCalledTimes(1);

    handle.stop();
  });

  it('spawns backend with injected spawn, passes token in env, and detects readiness', () => {
    const token = generateLaunchToken();
    const stdoutEmitter = new EventEmitter();
    const stderrEmitter = new EventEmitter();
    const processEmitter = new EventEmitter() as any;
    processEmitter.stdout = stdoutEmitter;
    processEmitter.stderr = stderrEmitter;
    processEmitter.kill = vi.fn();
    processEmitter.pid = 9999;

    let capturedCommand = '';
    let capturedArgs: string[] = [];
    let capturedOptions: any = null;

    const mockSpawn = vi.fn((cmd: string, args: string[], opts: any) => {
      capturedCommand = cmd;
      capturedArgs = args;
      capturedOptions = opts;
      return processEmitter;
    });

    const onReady = vi.fn();
    const onLog = vi.fn();

    const handle = startBackendSidecar({
      backendDir: '../backend',
      token,
      spawnFn: mockSpawn as any,
      onReady,
      onLog,
    });

    expect(capturedCommand).toBe('uv');
    expect(capturedArgs).toEqual(['run', 'python', '-m', 'app']);
    expect(capturedOptions.env.VOICEBOT_LAUNCH_TOKEN).toBe(token);
    expect(capturedOptions.cwd).toBe('../backend');
    expect(handle.isReady()).toBe(false);

    // Behaviour change (review of #79): uvicorn prints these before the port is
    // bound (and with a hardcoded port check), so they are not a ready signal.
    stdoutEmitter.emit('data', Buffer.from('INFO:     Application startup complete.\n'));
    stderrEmitter.emit('data', Buffer.from('INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)\n'));
    expect(handle.isReady()).toBe(false);
    expect(onReady).not.toHaveBeenCalled();

    stdoutEmitter.emit('data', Buffer.from('VOICEBOT_READY: http://127.0.0.1:8000\n'));
    expect(handle.isReady()).toBe(true);
    expect(onReady).toHaveBeenCalledTimes(1);

    // Emit log with token and check redaction
    stdoutEmitter.emit('data', Buffer.from(`Configured token is ${token}\n`));
    expect(onLog).toHaveBeenCalledWith('Configured token is [REDACTED_LAUNCH_TOKEN]\n');

    // Stop process
    handle.stop();
  });

  it('verifies main.cjs uses startBackend with injected spawn and redacts tokens (Finding 11)', () => {
    const stdoutEmitter = new EventEmitter();
    const stderrEmitter = new EventEmitter();
    const processEmitter = new EventEmitter() as any;
    processEmitter.stdout = stdoutEmitter;
    processEmitter.stderr = stderrEmitter;
    processEmitter.kill = vi.fn();
    processEmitter.pid = 9992;

    const mockSpawn = vi.fn(() => processEmitter);
    const onReady = vi.fn();
    const onLog = vi.fn();

    const handle = mainCjs.startBackend({
      backendDir: '../backend',
      spawnFn: mockSpawn,
      onReady,
      onLog,
    });

    expect(mockSpawn).toHaveBeenCalled();
    expect(handle.isReady()).toBe(false);

    // Emit VOICEBOT_READY
    stdoutEmitter.emit('data', Buffer.from('VOICEBOT_READY\n'));
    expect(handle.isReady()).toBe(true);
    expect(onReady).toHaveBeenCalledTimes(1);
    expect(mainCjs.isBackendReady()).toBe(true);

    mainCjs.cleanupBackend();
  });
});

describe('Backend ready line and port (review of #79)', () => {
  it('accepts only the VOICEBOT_READY line, with the configured port', () => {
    expect(parseReadyLine('VOICEBOT_READY', 8000)).toEqual({ ready: true });
    expect(parseReadyLine('VOICEBOT_READY: http://127.0.0.1:8123', 8123)).toEqual({ ready: true });
    expect(parseReadyLine('INFO:     Application startup complete.', 8000).ready).toBe(false);
    expect(parseReadyLine('INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)', 8000).ready).toBe(false);
    expect(parseReadyLine('not VOICEBOT_READY yet', 8000).ready).toBe(false);
    const wrongPort = parseReadyLine('VOICEBOT_READY: http://127.0.0.1:8000', 8123);
    expect(wrongPort.ready).toBe(false);
    expect(wrongPort.error).toContain('expected 8123');
  });

  it('starts the backend on the configured port and reports a ready line for another port as an error', () => {
    const { child, stdout } = fakeChild(4242);
    let opts: any = null;
    const onReady = vi.fn();
    const onError = vi.fn();
    const handle = startBackendSidecar({
      token: generateLaunchToken(),
      port: 8123,
      spawnFn: ((_c: string, _a: string[], o: any) => {
        opts = o;
        return child;
      }) as any,
      onReady,
      onError,
    });
    expect(handle.port).toBe(8123);
    expect(opts.env.VOICEBOT_PORT).toBe('8123');
    expect(opts.env.PORT).toBe('8123');
    expect(opts.env.HOST).toBe('127.0.0.1');

    stdout.emit('data', Buffer.from('VOICEBOT_READY: http://127.0.0.1:8000\n'));
    expect(handle.isReady()).toBe(false);
    expect(onReady).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toContain('expected 8123');
  });

  it('detects a ready line split across output chunks', () => {
    const { child, stdout } = fakeChild(4243);
    const onReady = vi.fn();
    const handle = startBackendSidecar({
      token: generateLaunchToken(),
      port: 8000,
      spawnFn: (() => child) as any,
      onReady,
    });
    stdout.emit('data', Buffer.from('VOICEBOT_RE'));
    expect(handle.isReady()).toBe(false);
    stdout.emit('data', Buffer.from('ADY: http://127.0.0.1:8000\n'));
    expect(handle.isReady()).toBe(true);
    expect(onReady).toHaveBeenCalledTimes(1);
  });

  it('reports a backend that exits before it is ready', () => {
    const { child } = fakeChild(4244);
    const onError = vi.fn();
    startBackendSidecar({ token: generateLaunchToken(), spawnFn: (() => child) as any, onError });
    child.emit('exit', 1, null);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toContain('exited before it was ready');
  });

  it('main.cjs passes the VOICEBOT_PORT port to the sidecar and never puts the token in its own env', () => {
    const { child } = fakeChild(4245);
    let opts: any = null;
    mainCjs.startBackend({
      backendDir: '../backend',
      spawnFn: (_c: string, _a: string[], o: any) => {
        opts = o;
        return child;
      },
    });
    expect(opts.env.VOICEBOT_PORT).toBe(String(mainCjs.backendPort));
    expect(opts.env.VOICEBOT_LAUNCH_TOKEN).toBe(mainCjs.launchToken);
    expect(process.env.VOICEBOT_LAUNCH_TOKEN).toBeUndefined();
    mainCjs.cleanupBackend();
  });
});
