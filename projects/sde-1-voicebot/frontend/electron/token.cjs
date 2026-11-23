/**
 * Per-launch token management for local backend auth boundary (CommonJS).
 * Single shared implementation used by main.cjs and tested by sidecar.test.ts.
 */

const crypto = require('node:crypto');

function generateLaunchToken() {
  return `vbt-${crypto.randomBytes(24).toString('hex')}`;
}

function sanitizeLogOutput(message, token) {
  if (!token || typeof token !== 'string' || token.length < 8) {
    return message;
  }
  return message.split(token).join('[REDACTED_LAUNCH_TOKEN]');
}

module.exports = {
  generateLaunchToken,
  sanitizeLogOutput,
};
