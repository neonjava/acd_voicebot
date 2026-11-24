/**
 * Window security and the packaged-renderer protocol (CommonJS, pure helpers).
 *
 * The production renderer is served from app://notch/ instead of file://. Requests
 * to app://notch/api/... are forwarded by main.cjs to the backend sidecar, so the
 * renderer always talks to the backend same-origin (the backend has no CORS
 * support, so a cross-origin fetch with a Bearer header fails its preflight).
 */

const path = require('node:path');

const APP_SCHEME = 'app';
const APP_HOST = 'notch';
const APP_ORIGIN = `${APP_SCHEME}://${APP_HOST}`;

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
  "form-action 'none'",
].join('; ');

function parseUrl(value) {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/** Same scheme and host (incl. port). Works for custom schemes whose URL.origin is "null". */
function isSameAppOrigin(target, allowed) {
  const a = parseUrl(target);
  const b = parseUrl(allowed);
  if (!a || !b) return false;
  return a.protocol === b.protocol && a.host === b.host;
}

/** True only when `url` belongs to one of the app's own origins. */
function isAllowedAppUrl(url, allowedOrigins) {
  return (allowedOrigins || []).some((origin) => isSameAppOrigin(url, origin));
}

/**
 * Decide how to answer a request on the app:// scheme.
 * - /api and /api/... -> proxy to the backend sidecar
 * - anything else      -> a file inside distDir (never outside it)
 */
function resolveAppRequest(requestUrl, distDir, backend) {
  const url = parseUrl(requestUrl);
  if (!url || url.protocol !== `${APP_SCHEME}:` || url.host !== APP_HOST) {
    return { kind: 'forbidden' };
  }
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
    return { kind: 'proxy', target: `${backend}${url.pathname}${url.search}` };
  }
  let relative;
  try {
    relative = decodeURIComponent(url.pathname);
  } catch {
    return { kind: 'forbidden' };
  }
  if (relative === '' || relative === '/') relative = '/index.html';
  const root = path.resolve(distDir);
  const filePath = path.resolve(root, `.${relative}`);
  if (!filePath.startsWith(root + path.sep)) {
    return { kind: 'forbidden' };
  }
  return { kind: 'file', filePath };
}

/** webPreferences for the notch window: isolated, sandboxed, no Node in the page. */
function buildWebPreferences(preloadPath) {
  return {
    preload: preloadPath,
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    webSecurity: true,
  };
}

module.exports = {
  APP_SCHEME,
  APP_HOST,
  APP_ORIGIN,
  CONTENT_SECURITY_POLICY,
  isSameAppOrigin,
  isAllowedAppUrl,
  resolveAppRequest,
  buildWebPreferences,
};
