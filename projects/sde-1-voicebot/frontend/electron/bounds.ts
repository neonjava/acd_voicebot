/**
 * Pure functions for calculating Electron notch window geometry.
 * Re-exports the single shared CommonJS implementation used by main.cjs.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const boundsCjs = require('./bounds.cjs');

export interface DisplaySize {
  x?: number;
  y?: number;
  width: number;
  height: number;
}

export interface WindowBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const COLLAPSED_WIDTH: number = boundsCjs.COLLAPSED_WIDTH;
export const COLLAPSED_HEIGHT: number = boundsCjs.COLLAPSED_HEIGHT;
export const MAX_EXPANDED_WIDTH: number = boundsCjs.MAX_EXPANDED_WIDTH;
export const MAX_EXPANDED_HEIGHT: number = boundsCjs.MAX_EXPANDED_HEIGHT;

export const getNotchBounds: (display: DisplaySize, expanded: boolean) => WindowBounds =
  boundsCjs.getNotchBounds;
