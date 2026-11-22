import type { PluginEvent } from 'ivandaw-core';
import { describe, expect, it } from 'vitest';
import { ALL_KEYS, type ControlKey, type TriggerKey } from './catalog';
import { ControlTracker, spanToZ } from './controls';
import { type HandObservation, observe, type Point, type RecognizerResult } from './observe';
import { Output, type OutputSettings } from './output';
import { normalizeX, normalizeY, Rectangles } from './rectangles';

const hand = (o: Partial<HandObservation> & Pick<HandObservation, 'hand'>): HandObservation => ({
  palmX: 0.5,
  palmY: 0.5,
  span: 0.18,
  gestureId: null,
  gestureScore: 0,
  margins: [0.1, 0.1, 0.1, 0.1],
  ...o,
});

/** 21 landmarks with the palm (0, 5, 17) centred on (cx, cy). */
function landmarks(cx: number, cy: number): Point[] {
  const pts: Point[] = Array.from({ length: 21 }, () => ({ x: cx, y: cy }));
  pts[0] = { x: cx, y: cy + 0.1 };
  pts[5] = { x: cx - 0.05, y: cy - 0.05 };
  pts[17] = { x: cx + 0.05, y: cy - 0.05 };
  pts[9] = { x: cx, y: cy - 0.1 };
  return pts;
}

describe('observe', () => {
  it('swaps handedness (the frame is mirrored) and keeps one observation per hand', () => {
    const result: RecognizerResult = {
      landmarks: [landmarks(0.3, 0.5), landmarks(0.7, 0.5), landmarks(0.6, 0.4)],
      handedness: [
        [{ categoryName: 'Right', score: 0.9 }],
        [{ categoryName: 'Left', score: 0.9 }],
        [{ categoryName: 'Left', score: 0.8 }],
      ],
      gestures: [[{ categoryName: 'Closed_Fist', score: 0.8 }], [{ categoryName: 'Victory', score: 0.9 }], []],
    };
    const { observations } = observe(result);
    expect(observations.map((o) => o.hand)).toEqual(['L', 'R']);
    expect(observations[0]?.gestureId).toBe('closed_fist');
    expect(observations[0]?.palmX).toBeCloseTo(0.3);
    expect(observations[0]?.span).toBeCloseTo(0.2);
    // Gestures outside the catalog are dropped.
    expect(observations[1]?.gestureId).toBeNull();
    expect(observations[1]?.gestureScore).toBe(0);
  });
});

describe('rectangles', () => {
  it('normalizes inside the rectangle, Y inverted, clamped', () => {
    const r = { minX: 0.2, minY: 0.2, maxX: 0.6, maxY: 0.6 };
    expect(normalizeX(r, 0.4)).toBeCloseTo(0.5);
    expect(normalizeY(r, 0.2)).toBe(1);
    expect(normalizeY(r, 0.6)).toBe(0);
    expect(normalizeX(r, 0.9)).toBe(1);
  });

  it('automatic: each hand gets its half when both are on, shrunk by its margins', () => {
    const rects = new Rectangles();
    const enabled = new Set<ControlKey>(ALL_KEYS);
    const r = rects.compute([hand({ hand: 'L', margins: [0.05, 0.1, 0.15, 0.2] })], enabled);
    expect(r.L).toEqual({ minX: 0.05, minY: 0.15, maxX: 0.4, maxY: 0.8 });
    expect(r.R?.minX).toBeCloseTo(0.6);
    // Only the left hand's X/Y on: it gets the whole width.
    const onlyL = new Set<ControlKey>(['L:palm_x']);
    expect(rects.compute([], onlyL).L?.maxX).toBeCloseTo(0.9);
    expect(rects.compute([], onlyL).R).toBeUndefined();
  });

  it('manual: the placed rectangle', () => {
    const rects = new Rectangles();
    rects.automatic = false;
    rects.configs.R = { cx: 0.7, cy: 0.5, w: 0.2, h: 0.4 };
    const r = rects.compute([], new Set<ControlKey>(['R:palm_y']));
    expect(r.R?.minX).toBeCloseTo(0.6);
    expect(r.R?.maxY).toBeCloseTo(0.7);
  });
});

describe('control tracker', () => {
  it('maps palm position to 0..255 and smooths toward it', () => {
    const t = new ControlTracker();
    const rects = { L: { minX: 0, minY: 0, maxX: 1, maxY: 1 } };
    expect(t.step([hand({ hand: 'L', palmX: 0.2 })], rects, 0.5).get('L:palm_x')).toBe(51);
    // Halfway from 51 toward 204.
    expect(t.step([hand({ hand: 'L', palmX: 0.8 })], rects, 0.5).get('L:palm_x')).toBe(128);
  });

  it('Z grows as the hand comes closer', () => {
    expect(spanToZ(0.08)).toBe(0);
    expect(spanToZ(0.28)).toBe(255);
    expect(spanToZ(0.5)).toBe(255);
  });

  it('gesture hysteresis: on at 0.65, off below 0.45', () => {
    const t = new ControlTracker();
    const fist = (score: number) =>
      t.step([hand({ hand: 'R', gestureId: 'closed_fist', gestureScore: score })], {}, 1).get('R:closed_fist');
    expect(fist(0.6)).toBe(0);
    expect(fist(0.7)).toBe(1);
    expect(fist(0.5)).toBe(1);
    expect(fist(0.4)).toBe(0);
  });

  it('a hand out of view: triggers 0, sliders hold (absent), and it jumps back on return', () => {
    const t = new ControlTracker();
    t.step([hand({ hand: 'L', palmX: 0, gestureId: 'open_palm', gestureScore: 0.9 })], {}, 0.1);
    const gone = t.step([], {}, 0.1);
    expect(gone.get('L:open_palm')).toBe(0);
    expect(gone.has('L:palm_x')).toBe(false);
    expect(t.step([hand({ hand: 'L', palmX: 1 })], {}, 0.1).get('L:palm_x')).toBe(255);
  });
});

describe('output', () => {
  const setup = () => {
    const events: PluginEvent[] = [];
    const out = new Output((e) => events.push(e));
    const notes: Record<TriggerKey, number> = {
      'L:closed_fist': 48,
      'L:open_palm': 50,
      'R:closed_fist': 60,
      'R:open_palm': 62,
    };
    const s: OutputSettings = { enabled: new Set<ControlKey>(ALL_KEYS), note: (k) => notes[k], velocity: 100 };
    return { events, out, s, notes };
  };

  it('a slider sends automation on its port only when it changes', () => {
    const { events, out, s } = setup();
    out.apply(new Map([['R:palm_y', 255]]), s, 1);
    out.apply(new Map([['R:palm_y', 255]]), s, 2);
    out.apply(new Map([['R:palm_y', 0]]), s, 3);
    expect(events).toEqual([
      { type: 'automation', time: 1, id: 'r-y', value: 1, port: 'r-y' },
      { type: 'automation', time: 3, id: 'r-y', value: 0, port: 'r-y' },
    ]);
  });

  it('a trigger plays its note while held, on the notes port', () => {
    const { events, out, s } = setup();
    out.apply(new Map([['L:closed_fist', 1]]), s, 1);
    out.apply(new Map([['L:closed_fist', 1]]), s, 2);
    out.apply(new Map([['L:closed_fist', 0]]), s, 3);
    expect(events).toEqual([
      { type: 'midi', time: 1, bytes: [0x90, 48, 100], port: 'notes' },
      { type: 'midi', time: 3, bytes: [0x80, 48, 0], port: 'notes' },
    ]);
  });

  it('muting a held trigger, or a new note number, sends the note off for the note that sounds', () => {
    const { events, out, s, notes } = setup();
    out.apply(new Map([['R:open_palm', 1]]), s, 1);
    notes['R:open_palm'] = 64;
    out.release('R:open_palm', 2);
    out.apply(new Map([['R:open_palm', 1]]), s, 3);
    (s.enabled as Set<ControlKey>).delete('R:open_palm');
    out.apply(new Map([['R:open_palm', 1]]), s, 4);
    expect(events.map((e) => (e.type === 'midi' ? [e.time, ...e.bytes] : []))).toEqual([
      [1, 0x90, 62, 100],
      [2, 0x80, 62, 0],
      [3, 0x90, 64, 100],
      [4, 0x80, 64, 0],
    ]);
  });

  it('releaseAll ends every held note; a muted slider sends again when unmuted', () => {
    const { events, out, s } = setup();
    out.apply(new Map<ControlKey, number>([['L:closed_fist', 1], ['R:closed_fist', 1], ['L:palm_x', 10]]), s, 1);
    out.releaseAll(2);
    expect(events.filter((e) => e.type === 'midi' && e.bytes[0] === 0x80)).toHaveLength(2);
    (s.enabled as Set<ControlKey>).delete('L:palm_x');
    out.apply(new Map([['L:palm_x', 10]]), s, 3);
    (s.enabled as Set<ControlKey>).add('L:palm_x');
    out.apply(new Map([['L:palm_x', 10]]), s, 4);
    expect(events.filter((e) => e.type === 'automation').map((e) => e.time)).toEqual([1, 4]);
  });
});
