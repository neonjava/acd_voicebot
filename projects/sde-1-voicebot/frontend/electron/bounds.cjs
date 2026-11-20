/**
 * Pure functions for calculating Electron notch window geometry (CommonJS).
 */

const COLLAPSED_WIDTH = 200;
const COLLAPSED_HEIGHT = 36;
const MAX_EXPANDED_WIDTH = 480;
const MAX_EXPANDED_HEIGHT = 360;

function getNotchBounds(display, expanded) {
  if (!display || display.width <= 0 || display.height <= 0) {
    throw new Error('Display dimensions must be positive integers');
  }

  const targetWidth = expanded ? MAX_EXPANDED_WIDTH : COLLAPSED_WIDTH;
  const targetHeight = expanded ? MAX_EXPANDED_HEIGHT : COLLAPSED_HEIGHT;

  const width = Math.min(targetWidth, display.width, MAX_EXPANDED_WIDTH);
  const height = Math.min(targetHeight, display.height, MAX_EXPANDED_HEIGHT);

  const x = Math.round((display.width - width) / 2);
  const y = 0;

  return { x, y, width, height };
}

module.exports = {
  COLLAPSED_WIDTH,
  COLLAPSED_HEIGHT,
  MAX_EXPANDED_WIDTH,
  MAX_EXPANDED_HEIGHT,
  getNotchBounds,
};
