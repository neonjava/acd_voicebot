/**
 * Pure functions for calculating Electron companion window geometry (CommonJS).
 * Single shared implementation used by main.cjs and tested by bounds.test.ts.
 *
 * Week 4 Companion:
 * - Positioned at bottom-right corner of the primary display work area (respects taskbar/dock).
 * - Collapsed: ~72×72 px.
 * - Expanded: at most 380×320 px.
 * - Supports multi-monitor origins (x, y) and workArea bounds.
 */

const COLLAPSED_WIDTH = 72;
const COLLAPSED_HEIGHT = 72;
const MAX_EXPANDED_WIDTH = 380;
const MAX_EXPANDED_HEIGHT = 320;

function getCompanionBounds(display, expanded, margin = 0) {
  if (!display) {
    throw new Error('Display dimensions must be positive integers');
  }

  // Support either raw bounds or an Electron Display object containing workArea
  const area = display.workArea || display;
  if (!area || typeof area.width !== 'number' || typeof area.height !== 'number' || area.width <= 0 || area.height <= 0) {
    throw new Error('Display dimensions must be positive integers');
  }

  const targetWidth = expanded ? MAX_EXPANDED_WIDTH : COLLAPSED_WIDTH;
  const targetHeight = expanded ? MAX_EXPANDED_HEIGHT : COLLAPSED_HEIGHT;

  const width = Math.min(targetWidth, area.width, MAX_EXPANDED_WIDTH);
  const height = Math.min(targetHeight, area.height, MAX_EXPANDED_HEIGHT);

  const displayX = typeof area.x === 'number' ? area.x : 0;
  const displayY = typeof area.y === 'number' ? area.y : 0;

  // Position at bottom-right corner of the display work area
  const x = displayX + area.width - width - margin;
  const y = displayY + area.height - height - margin;

  return { x, y, width, height };
}

// Keep getNotchBounds as an alias for backwards compatibility
const getNotchBounds = getCompanionBounds;

module.exports = {
  COLLAPSED_WIDTH,
  COLLAPSED_HEIGHT,
  MAX_EXPANDED_WIDTH,
  MAX_EXPANDED_HEIGHT,
  getCompanionBounds,
  getNotchBounds,
};
