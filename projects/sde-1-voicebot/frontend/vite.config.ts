/// <reference types="vitest" />
import { createRequire } from 'node:module';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// One source of truth with the Electron main process (electron/config.cjs): the dev
// server address Electron loads and the backend port the sidecar listens on.
const require = createRequire(import.meta.url);
const launchConfig = require('./electron/config.cjs') as {
  DEV_SERVER_HOST: string;
  DEV_SERVER_PORT: number;
  resolveBackendPort: (env?: Record<string, string | undefined>) => number;
  backendOrigin: (port: number) => string;
};

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind IPv4 loopback explicitly: "localhost" resolves to ::1 on Fedora, which
    // the Electron window and wait-on (http://127.0.0.1:5173) cannot reach.
    host: launchConfig.DEV_SERVER_HOST,
    port: launchConfig.DEV_SERVER_PORT,
    strictPort: true,
    proxy: {
      '/api': {
        target: launchConfig.backendOrigin(launchConfig.resolveBackendPort(process.env)),
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
});
