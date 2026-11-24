// @vitest-environment node
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import viteConfig from '../../vite.config';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const appProtocol = require('../appProtocol.cjs');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const launchConfig = require('../config.cjs');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const mainCjs = require('../main.cjs');

const distDir = path.resolve('/opt/notch/dist');
const backend = 'http://127.0.0.1:8123';

describe('app:// protocol for the packaged renderer', () => {
  it('forwards same-origin /api requests to the backend sidecar', () => {
    expect(appProtocol.resolveAppRequest('app://notch/api/sessions/mock', distDir, backend)).toEqual({
      kind: 'proxy',
      target: 'http://127.0.0.1:8123/api/sessions/mock',
    });
    expect(
      appProtocol.resolveAppRequest('app://notch/api/sessions/s-1/events?from_sequence=4', distDir, backend)
    ).toEqual({ kind: 'proxy', target: 'http://127.0.0.1:8123/api/sessions/s-1/events?from_sequence=4' });
  });

  it('serves files only from inside dist', () => {
    expect(appProtocol.resolveAppRequest('app://notch/', distDir, backend)).toEqual({
      kind: 'file',
      filePath: path.join(distDir, 'index.html'),
    });
    expect(appProtocol.resolveAppRequest('app://notch/assets/index-1.js', distDir, backend)).toEqual({
      kind: 'file',
      filePath: path.join(distDir, 'assets', 'index-1.js'),
    });
    // URL parsing folds "%2e%2e" segments, so this stays inside dist
    expect(appProtocol.resolveAppRequest('app://notch/%2e%2e/%2e%2e/etc/passwd', distDir, backend)).toEqual({
      kind: 'file',
      filePath: path.join(distDir, 'etc', 'passwd'),
    });
    expect(appProtocol.resolveAppRequest('app://notch/..%2fsecret', distDir, backend).kind).toBe('forbidden');
    expect(appProtocol.resolveAppRequest('app://other/index.html', distDir, backend).kind).toBe('forbidden');
    expect(appProtocol.resolveAppRequest('https://example.com/api/x', distDir, backend).kind).toBe('forbidden');
  });

  it('only allows the app origins for navigation and the token IPC', () => {
    const allowed = ['http://127.0.0.1:5173', appProtocol.APP_ORIGIN];
    expect(appProtocol.isAllowedAppUrl('http://127.0.0.1:5173/index.html', allowed)).toBe(true);
    expect(appProtocol.isAllowedAppUrl('app://notch/index.html', allowed)).toBe(true);
    expect(appProtocol.isAllowedAppUrl('http://127.0.0.1:8000/', allowed)).toBe(false);
    expect(appProtocol.isAllowedAppUrl('https://evil.example/', allowed)).toBe(false);
    expect(appProtocol.isAllowedAppUrl('app://notch.evil/index.html', allowed)).toBe(false);
    expect(appProtocol.isAllowedAppUrl('file:///etc/passwd', allowed)).toBe(false);
    expect(appProtocol.isAllowedAppUrl('not a url', allowed)).toBe(false);
    expect(mainCjs.allowedOrigins).toEqual(['http://127.0.0.1:5173', 'app://notch']);
  });

  it('runs the window sandboxed with context isolation and a same-origin-only CSP', () => {
    expect(appProtocol.buildWebPreferences('/p/preload.cjs')).toEqual({
      preload: '/p/preload.cjs',
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    });
    const csp: string = appProtocol.CONTENT_SECURITY_POLICY;
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).not.toMatch(/script-src[^;]*unsafe/);
  });
});

describe('shared launch configuration', () => {
  it('reads the backend port from VOICEBOT_PORT and rejects invalid values', () => {
    expect(launchConfig.resolveBackendPort({})).toBe(8000);
    expect(launchConfig.resolveBackendPort({ VOICEBOT_PORT: '8123' })).toBe(8123);
    expect(() => launchConfig.resolveBackendPort({ VOICEBOT_PORT: 'abc' })).toThrow('VOICEBOT_PORT');
    expect(() => launchConfig.resolveBackendPort({ VOICEBOT_PORT: '70000' })).toThrow('VOICEBOT_PORT');
    expect(() => launchConfig.resolveBackendPort({ VOICEBOT_PORT: '80.5' })).toThrow('VOICEBOT_PORT');
  });

  it('binds the Vite dev server to the IPv4 address Electron and wait-on use, and proxies to the sidecar port', () => {
    const server = (viteConfig as { server: { host: string; port: number; strictPort: boolean; proxy: Record<string, { target: string }> } }).server;
    expect(server.host).toBe('127.0.0.1');
    expect(server.port).toBe(5173);
    expect(server.strictPort).toBe(true);
    expect(`http://${server.host}:${server.port}`).toBe(launchConfig.devServerUrl());
    expect(server.proxy['/api'].target).toBe(launchConfig.backendOrigin(mainCjs.backendPort));
  });
});
