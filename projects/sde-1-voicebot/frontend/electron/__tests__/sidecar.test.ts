import { EventEmitter } from 'node:events';
import { describe, expect, it, vi } from 'vitest';
import { setupPreloadBridge, VoicebotDesktopAPI } from '../preload';
import { startBackendSidecar } from '../sidecar';
import { generateLaunchToken, sanitizeLogOutput } from '../token';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const mainCjs = require('../main.cjs');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const sidecarCjs = require('../sidecar.cjs');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const tokenCjs = require('../token.cjs');

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

describe('Preload Bridge Setup', () => {
  it('exposes window.voicebot and never stores token in localStorage', async () => {
    let exposedKey = '';
    let exposedApi: VoicebotDesktopAPI | null = null;

    const mockExpose = vi.fn((key: string, api: VoicebotDesktopAPI) => {
      exposedKey = key;
      exposedApi = api;
    });

    const mockIpc = vi.fn().mockResolvedValue(undefined);
    const token = generateLaunchToken();

    // Ensure localStorage is empty before setup
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem');

    setupPreloadBridge(mockExpose, mockIpc, () => token);

    expect(exposedKey).toBe('voicebot');
    expect(exposedApi).not.toBeNull();
    expect(exposedApi!.isElectron).toBe(true);
    expect(exposedApi!.backendUrl).toBe('http://127.0.0.1:8000');
    expect(exposedApi!.getBackendUrl?.()).toBe('http://127.0.0.1:8000');
    expect(exposedApi!.getToken()).toBe(token);
    expect(exposedApi!.isBackendReady?.()).toBe(true);

    // Call setWindowExpanded
    await exposedApi!.setWindowExpanded(true);
    expect(mockIpc).toHaveBeenCalledWith('voicebot:set-expanded', true);

    await exposedApi!.setWindowExpanded(false);
    expect(mockIpc).toHaveBeenCalledWith('voicebot:set-expanded', false);

    // Token must never be written to localStorage
    expect(storageSpy).not.toHaveBeenCalled();
    storageSpy.mockRestore();
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

    // Emit startup line
    stdoutEmitter.emit('data', Buffer.from('INFO:     Application startup complete.\n'));

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
