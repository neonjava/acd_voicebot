/**
 * Pure functions for calculating Electron notch window geometry.
 *
 * Rules:
 * - Collapsed: about 200×36 px pill.
 * - Expanded: at most 480×360 px.
 * - Always centered at the top of the display (y: 0).
 * - Never larger than 480×360 px.
 */

export interface DisplaySize {
  width: number;
  height: number;
}

export interface WindowBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const COLLAPSED_WIDTH = 200;
export const COLLAPSED_HEIGHT = 36;
export const MAX_EXPANDED_WIDTH = 480;
export const MAX_EXPANDED_HEIGHT = 360;

/**
 * Calculates window bounds for collapsed or expanded notch states.
 * Guarantees window is always top-centre and bounds never exceed 480×360.
 */
export function getNotchBounds(display: DisplaySize, expanded: boolean): WindowBounds {
  if (display.width <= 0 || display.height <= 0) {
    throw new Error('Display dimensions must be positive integers');
  }

  // Constrain width and height
  const targetWidth = expanded ? MAX_EXPANDED_WIDTH : COLLAPSED_WIDTH;
  const targetHeight = expanded ? MAX_EXPANDED_HEIGHT : COLLAPSED_HEIGHT;

  const width = Math.min(targetWidth, display.width, MAX_EXPANDED_WIDTH);
  const height = Math.min(targetHeight, display.height, MAX_EXPANDED_HEIGHT);

  // Position at top center
  const x = Math.round((display.width - width) / 2);
  const y = 0;

  return { x, y, width, height };
}
