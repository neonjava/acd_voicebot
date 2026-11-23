/**
 * Per-launch token management for local backend auth boundary.
 * Re-exports the single shared CommonJS implementation used by main.cjs.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const tokenCjs = require('./token.cjs');

export function generateLaunchToken(): string {
  return tokenCjs.generateLaunchToken();
}

export function sanitizeLogOutput(message: string, token: string): string {
  return tokenCjs.sanitizeLogOutput(message, token);
}
