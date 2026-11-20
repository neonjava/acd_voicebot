import { describe, expect, it } from 'vitest';
import {
  COLLAPSED_HEIGHT,
  COLLAPSED_WIDTH,
  MAX_EXPANDED_HEIGHT,
  MAX_EXPANDED_WIDTH,
  getNotchBounds,
} from '../bounds';

describe('getNotchBounds', () => {
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

  it('always anchors to top-center (y = 0)', () => {
    const displays = [
      { width: 1280, height: 800 },
      { width: 1440, height: 900 },
      { width: 3840, height: 2160 },
    ];

    for (const d of displays) {
      const c = getNotchBounds(d, false);
      const e = getNotchBounds(d, true);

      expect(c.y).toBe(0);
      expect(e.y).toBe(0);
      expect(c.x).toBe(Math.round((d.width - c.width) / 2));
      expect(e.x).toBe(Math.round((d.width - e.width) / 2));
      expect(e.width).toBeLessThanOrEqual(480);
      expect(e.height).toBeLessThanOrEqual(360);
    }
  });

  it('clamps width when display is narrower than expanded notch', () => {
    const smallDisplay = { width: 400, height: 600 };
    const expanded = getNotchBounds(smallDisplay, true);

    expect(expanded.width).toBe(400);
    expect(expanded.height).toBe(360);
    expect(expanded.x).toBe(0);
    expect(expanded.y).toBe(0);
  });

  it('throws on non-positive display dimensions', () => {
    expect(() => getNotchBounds({ width: 0, height: 800 }, false)).toThrow();
    expect(() => getNotchBounds({ width: 1920, height: -10 }, true)).toThrow();
  });
});
