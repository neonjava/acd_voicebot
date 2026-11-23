import { describe, expect, it } from 'vitest';
import {
  COLLAPSED_HEIGHT,
  COLLAPSED_WIDTH,
  MAX_EXPANDED_HEIGHT,
  MAX_EXPANDED_WIDTH,
  getNotchBounds,
} from '../bounds';
// Test the exact CommonJS module loaded by main.cjs as required by Finding 11
// eslint-disable-next-line @typescript-eslint/no-require-imports
const boundsCjs = require('../bounds.cjs');

describe('getNotchBounds (Finding 11 & 12)', () => {
  it('guarantees bounds.ts re-exports the exact same implementation as bounds.cjs', () => {
    expect(getNotchBounds).toBe(boundsCjs.getNotchBounds);
    expect(COLLAPSED_WIDTH).toBe(boundsCjs.COLLAPSED_WIDTH);
    expect(COLLAPSED_HEIGHT).toBe(boundsCjs.COLLAPSED_HEIGHT);
    expect(MAX_EXPANDED_WIDTH).toBe(boundsCjs.MAX_EXPANDED_WIDTH);
    expect(MAX_EXPANDED_HEIGHT).toBe(boundsCjs.MAX_EXPANDED_HEIGHT);
  });

  it('calculates collapsed and expanded bounds for 1366x768 display', () => {
    const display = { width: 1366, height: 768 };

    const collapsed = getNotchBounds(display, false);
    expect(collapsed).toEqual({
      x: Math.round((1366 - COLLAPSED_WIDTH) / 2),
      y: 0,
      width: 200,
      height: 36,
    });
    expect(collapsed.width).toBeLessThanOrEqual(MAX_EXPANDED_WIDTH);
    expect(collapsed.height).toBeLessThanOrEqual(MAX_EXPANDED_HEIGHT);

    const expanded = getNotchBounds(display, true);
    expect(expanded).toEqual({
      x: Math.round((1366 - MAX_EXPANDED_WIDTH) / 2),
      y: 0,
      width: 480,
      height: 360,
    });
    expect(expanded.width).toBeLessThanOrEqual(MAX_EXPANDED_WIDTH);
    expect(expanded.height).toBeLessThanOrEqual(MAX_EXPANDED_HEIGHT);
  });

  it('calculates collapsed and expanded bounds for 1920x1080 display', () => {
    const display = { width: 1920, height: 1080 };

    const collapsed = getNotchBounds(display, false);
    expect(collapsed).toEqual({
      x: 860,
      y: 0,
      width: 200,
      height: 36,
    });

    const expanded = getNotchBounds(display, true);
    expect(expanded).toEqual({
      x: 720,
      y: 0,
      width: 480,
      height: 360,
    });
    expect(expanded.width).toBeLessThanOrEqual(480);
    expect(expanded.height).toBeLessThanOrEqual(360);
  });

  it('calculates collapsed and expanded bounds for 2560x1440 display', () => {
    const display = { width: 2560, height: 1440 };

    const collapsed = getNotchBounds(display, false);
    expect(collapsed).toEqual({
      x: 1180,
      y: 0,
      width: 200,
      height: 36,
    });

    const expanded = getNotchBounds(display, true);
    expect(expanded).toEqual({
      x: 1040,
      y: 0,
      width: 480,
      height: 360,
    });
    expect(expanded.width).toBeLessThanOrEqual(480);
    expect(expanded.height).toBeLessThanOrEqual(360);
  });

  it('positions notch correctly with multi-monitor non-zero display origins (Finding 12)', () => {
    // Primary display is positioned to the right of another monitor (x = 1920)
    const rightDisplay = { x: 1920, y: 0, width: 1366, height: 768 };
    const collapsedRight = boundsCjs.getNotchBounds(rightDisplay, false);
    expect(collapsedRight).toEqual({
      x: 1920 + Math.round((1366 - 200) / 2), // 2503
      y: 0,
      width: 200,
      height: 36,
    });

    // Primary display is stacked vertically below another monitor (y = 1080)
    const bottomDisplay = { x: 0, y: 1080, width: 1920, height: 1080 };
    const collapsedBottom = boundsCjs.getNotchBounds(bottomDisplay, false);
    expect(collapsedBottom).toEqual({
      x: 860,
      y: 1080,
      width: 200,
      height: 36,
    });

    // Secondary monitor with negative x offset and custom y offset
    const leftDisplay = { x: -1920, y: 150, width: 1920, height: 1080 };
    const expandedLeft = boundsCjs.getNotchBounds(leftDisplay, true);
    expect(expandedLeft).toEqual({
      x: -1920 + Math.round((1920 - 480) / 2), // -1200
      y: 150,
      width: 480,
      height: 360,
    });
  });

  it('always anchors to top-center (y = display.y)', () => {
    const displays = [
      { x: 0, y: 0, width: 1280, height: 800 },
      { x: 100, y: 200, width: 1440, height: 900 },
      { x: 0, y: 0, width: 3840, height: 2160 },
    ];

    for (const d of displays) {
      const c = getNotchBounds(d, false);
      const e = getNotchBounds(d, true);

      expect(c.y).toBe(d.y);
      expect(e.y).toBe(d.y);
      expect(c.x).toBe(d.x + Math.round((d.width - c.width) / 2));
      expect(e.x).toBe(d.x + Math.round((d.width - e.width) / 2));
      expect(e.width).toBeLessThanOrEqual(480);
      expect(e.height).toBeLessThanOrEqual(360);
    }
  });

  it('clamps width when display is narrower than expanded notch', () => {
    const smallDisplay = { x: 50, y: 10, width: 400, height: 600 };
    const expanded = getNotchBounds(smallDisplay, true);

    expect(expanded.width).toBe(400);
    expect(expanded.height).toBe(360);
    expect(expanded.x).toBe(50);
    expect(expanded.y).toBe(10);
  });

  it('throws on non-positive display dimensions', () => {
    expect(() => getNotchBounds({ width: 0, height: 800 }, false)).toThrow();
    expect(() => getNotchBounds({ width: 1920, height: -10 }, true)).toThrow();
  });
});
