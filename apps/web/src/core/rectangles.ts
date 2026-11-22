// Per-hand tracking rectangles: the palm position inside its rectangle becomes the X / Y slider.
// Port of reader/musichands_reader/hand_rectangles.py.
//
// Automatic: each hand gets its half of the frame (the whole frame when only one hand's X/Y is on),
// shrunk by how far the fingertips reach from the palm, so the slider hits 0 and 1 while the
// whole hand is still in view. Manual: the rectangles the user placed.

import { type ControlKey, HANDS, type Hand } from './catalog';
import { DEFAULT_MARGINS, type HandObservation, type Margins } from './observe';

export interface RectConfig {
  cx: number;
  cy: number;
  w: number;
  h: number;
}

export interface RectBounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export type Rects = Partial<Record<Hand, RectBounds>>;

const MIN_SPAN = 0.02;

export const DEFAULT_RECTS: Readonly<Record<Hand, RectConfig>> = {
  L: { cx: 0.25, cy: 0.5, w: 0.4, h: 0.7 },
  R: { cx: 0.75, cy: 0.5, w: 0.4, h: 0.7 },
};

const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));

export function normalizeX(r: RectBounds, x: number): number {
  const span = r.maxX - r.minX;
  return span <= 1e-6 ? 0.5 : clamp01((x - r.minX) / span);
}

/** Inverted: the top of the rectangle is 1, the bottom 0. */
export function normalizeY(r: RectBounds, y: number): number {
  const span = r.maxY - r.minY;
  return span <= 1e-6 ? 0.5 : clamp01((r.maxY - y) / span);
}

export function ensureMinSpan(low: number, high: number, lo: number, hi: number): [number, number] {
  let a = Math.max(lo, Math.min(hi, low));
  let b = Math.max(lo, Math.min(hi, high));
  if (b - a < MIN_SPAN) {
    const mid = (a + b) / 2;
    a = Math.max(lo, mid - MIN_SPAN / 2);
    b = Math.min(hi, mid + MIN_SPAN / 2);
  }
  return [a, b];
}

export function readRect(v: unknown, fallback: RectConfig): RectConfig {
  if (typeof v !== 'object' || v === null) return { ...fallback };
  const o = v as Record<string, unknown>;
  const num = (x: unknown, d: number): number =>
    typeof x === 'number' && Number.isFinite(x) ? clamp01(x) : d;
  return {
    cx: num(o.cx, fallback.cx),
    cy: num(o.cy, fallback.cy),
    w: num(o.w, fallback.w),
    h: num(o.h, fallback.h),
  };
}

export class Rectangles {
  automatic = true;
  configs: Record<Hand, RectConfig> = { L: { ...DEFAULT_RECTS.L }, R: { ...DEFAULT_RECTS.R } };
  private lastMargins: Record<Hand, Margins> = { L: DEFAULT_MARGINS, R: DEFAULT_MARGINS };

  /** Rectangles for hands whose X or Y slider is enabled. */
  compute(observations: HandObservation[], enabled: ReadonlySet<ControlKey>): Rects {
    for (const o of observations) this.lastMargins[o.hand] = o.margins;
    const active = HANDS.filter((h) => enabled.has(`${h}:palm_x`) || enabled.has(`${h}:palm_y`));
    const rects: Rects = {};
    for (const hand of active) {
      rects[hand] = this.automatic
        ? this.auto(hand, active.length === 2)
        : manual(this.configs[hand]);
    }
    return rects;
  }

  private auto(hand: Hand, split: boolean): RectBounds {
    const [zx0, zx1] = split ? (hand === 'L' ? [0, 0.5] : [0.5, 1]) : [0, 1];
    const [l, r, t, b] = this.lastMargins[hand];
    const [minX, maxX] = ensureMinSpan(zx0 + l, zx1 - r, zx0, zx1);
    const [minY, maxY] = ensureMinSpan(t, 1 - b, 0, 1);
    return { minX, minY, maxX, maxY };
  }
}

function manual(c: RectConfig): RectBounds {
  const [minX, maxX] = ensureMinSpan(clamp01(c.cx - c.w / 2), clamp01(c.cx + c.w / 2), 0, 1);
  const [minY, maxY] = ensureMinSpan(clamp01(c.cy - c.h / 2), clamp01(c.cy + c.h / 2), 0, 1);
  return { minX, minY, maxX, maxY };
}
