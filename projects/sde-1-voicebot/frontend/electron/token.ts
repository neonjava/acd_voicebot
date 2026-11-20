/**
 * Per-launch token management for local backend auth boundary.
 *
 * Requirements:
 * - High-entropy random token per launch (VOICEBOT_LAUNCH_TOKEN).
 * - Never logged in plain text.
 * - Never stored in browser localStorage.
 */

import crypto from 'node:crypto';

export function generateLaunchToken(): string {
  // Generate a 48-character cryptographically secure hex token
  return `vbt-${crypto.randomBytes(24).toString('hex')}`;
}

/**
 * Redacts any occurrence of the secret launch token from log messages.
 */
export function sanitizeLogOutput(message: string, token: string): string {
  if (!token || token.length < 8) {
    return message;
  }
  return message.split(token).join('[REDACTED_LAUNCH_TOKEN]');
}
