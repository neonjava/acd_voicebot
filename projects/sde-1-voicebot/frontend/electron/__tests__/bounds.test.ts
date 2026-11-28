import { describe, expect, it } from 'vitest';
import {
  COLLAPSED_HEIGHT,
  COLLAPSED_WIDTH,
  MAX_EXPANDED_HEIGHT,
  MAX_EXPANDED_WIDTH,
  getCompanionBounds,
  getNotchBounds,
} from '../bounds';
// Test the exact CommonJS module loaded by main.cjs
// eslint-disable-next-line @typescript-eslint/no-require-imports
const boundsCjs = require('../bounds.cjs');

describe('getCompanionBounds / getNotchBounds (Week 4 Companion Geometry)', () => {
  it('guarantees bounds.ts re-exports the exact same implementation as bounds.cjs', () => {
    expect(getCompanionBounds).toBe(boundsCjs.getCompanionBounds);
    expect(getNotchBounds).toBe(boundsCjs.getNotchBounds);
    expect(COLLAPSED_WIDTH).toBe(72);
    expect(COLLAPSED_HEIGHT).toBe(72);
    expect(MAX_EXPANDED_WIDTH).toBe(380);
    expect(MAX_EXPANDED_HEIGHT).toBe(320);
    expect(COLLAPSED_WIDTH).toBe(boundsCjs.COLLAPSED_WIDTH);
    expect(COLLAPSED_HEIGHT).toBe(boundsCjs.COLLAPSED_HEIGHT);
    expect(MAX_EXPANDED_WIDTH).toBe(boundsCjs.MAX_EXPANDED_WIDTH);
    expect(MAX_EXPANDED_HEIGHT).toBe(boundsCjs.MAX_EXPANDED_HEIGHT);
  });

  it('calculates collapsed and expanded bounds for 1366x768 display', () => {
    const display = { width: 1366, height: 768 };

    const collapsed = getCompanionBounds(display, false);
    expect(collapsed).toEqual({
      x: 1366 - 72, // 1294
      y: 768 - 72,  // 696
      width: 72,
      height: 72,
    });
    expect(collapsed.width).toBeLessThanOrEqual(MAX_EXPANDED_WIDTH);
    expect(collapsed.height).toBeLessThanOrEqual(MAX_EXPANDED_HEIGHT);

    const expanded = getCompanionBounds(display, true);
    expect(expanded).toEqual({
      x: 1366 - 380, // 986
      y: 768 - 320,  // 448
      width: 380,
      height: 320,
    });
    expect(expanded.width).toBeLessThanOrEqual(MAX_EXPANDED_WIDTH);
    expect(expanded.height).toBeLessThanOrEqual(MAX_EXPANDED_HEIGHT);
  });

  it('calculates collapsed and expanded bounds for 1920x1080 display', () => {
    const display = { width: 1920, height: 1080 };

    const collapsed = getCompanionBounds(display, false);
    expect(collapsed).toEqual({
      x: 1848,
      y: 1008,
      width: 72,
      height: 72,
    });

    const expanded = getCompanionBounds(display, true);
    expect(expanded).toEqual({
      x: 1540,
      y: 760,
      width: 380,
      height: 320,
    });
    expect(expanded.width).toBeLessThanOrEqual(380);
    expect(expanded.height).toBeLessThanOrEqual(320);
  });

  it('calculates collapsed and expanded bounds for 2560x1440 display', () => {
    const display = { width: 2560, height: 1440 };

    const collapsed = getCompanionBounds(display, false);
    expect(collapsed).toEqual({
      x: 2488,
      y: 1368,
      width: 72,
      height: 72,
    });

    const expanded = getCompanionBounds(display, true);
    expect(expanded).toEqual({
      x: 2180,
      y: 1120,
      width: 380,
      height: 320,
    });
    expect(expanded.width).toBeLessThanOrEqual(380);
    expect(expanded.height).toBeLessThanOrEqual(320);
  });

  it('positions companion correctly on secondary display at x = 1920', () => {
    const displayAt1920 = { x: 1920, y: 0, width: 1920, height: 1080 };

    const collapsed = getCompanionBounds(displayAt1920, false);
    expect(collapsed).toEqual({
      x: 1920 + (1920 - 72), // 3768
      y: 0 + (1080 - 72),    // 1008
      width: 72,
      height: 72,
    });

    const expanded = getCompanionBounds(displayAt1920, true);
    expect(expanded).toEqual({
      x: 1920 + (1920 - 380), // 3460
      y: 0 + (1080 - 320),    // 760
      width: 380,
      height: 320,
    });
  });

  it('respects workArea accounting for taskbar / dock', () => {
    const displayWithTaskbar = {
      bounds: { x: 0, y: 0, width: 1920, height: 1080 },
      workArea: { x: 0, y: 0, width: 1920, height: 1040 }, // 40px taskbar at bottom
    };

    const collapsed = getCompanionBounds(displayWithTaskbar, false);
    expect(collapsed).toEqual({
      x: 1848,
      y: 968, // 1040 - 72
      width: 72,
      height: 72,
    });

    const expanded = getCompanionBounds(displayWithTaskbar, true);
    expect(expanded).toEqual({
      x: 1540,
      y: 720, // 1040 - 320
      width: 380,
      height: 320,
    });
  });

  it('clamps width and height when display is smaller than expanded bounds', () => {
    const tinyDisplay = { x: 10, y: 20, width: 300, height: 250 };
    const expanded = getCompanionBounds(tinyDisplay, true);

    expect(expanded.width).toBe(300);
    expect(expanded.height).toBe(250);
    expect(expanded.x).toBe(10);
    expect(expanded.y).toBe(20);
  });

  it('throws on invalid or non-positive display dimensions', () => {
    expect(() => getCompanionBounds(null as any, false)).toThrow('Display dimensions must be positive integers');
    expect(() => getCompanionBounds({ width: -10, height: 100 } as any, false)).toThrow('Display dimensions must be positive integers');
    expect(() => getCompanionBounds({ width: 100, height: 0 } as any, false)).toThrow('Display dimensions must be positive integers');
  });

  it('guarantees bounds are never larger than 380x320 and never full screen', () => {
    const displays = [
      { x: 0, y: 0, width: 1366, height: 768 },
      { x: 0, y: 0, width: 1920, height: 1080 },
      { x: 1920, y: 0, width: 2560, height: 1440 },
      { x: -1920, y: 100, width: 1920, height: 1200 },
    ];

    for (const d of displays) {
      const c = getCompanionBounds(d, false);
      const e = getCompanionBounds(d, true);

      expect(c.width).toBe(72);
      expect(c.height).toBe(72);
      expect(e.width).toBeLessThanOrEqual(380);
      expect(e.height).toBeLessThanOrEqual(320);

      // Verify bottom-right positioning within display
      expect(c.x + c.width).toBe(d.x + d.width);
      expect(c.y + c.height).toBe(d.y + d.height);
      expect(e.x + e.width).toBe(d.x + d.width);
      expect(e.y + e.height).toBe(d.y + d.height);

      // Verify never full screen
      expect(e.width).toBeLessThan(d.width);
      expect(e.height).toBeLessThan(d.height);
    }
  });
});
