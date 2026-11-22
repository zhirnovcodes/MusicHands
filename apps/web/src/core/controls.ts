// Observations → control values. Port of ControlTracker in reader/musichands_reader/features.py.
//
// Sliders are 0..255 integers, smoothed per frame. Triggers are 0 / 1 with hysteresis on the
// gesture score, so a wobbling score does not retrigger the note.

import { type ControlKey, HANDS, SLIDERS, type SliderId, TRIGGERS } from './catalog';
import type { HandObservation } from './observe';
import { normalizeX, normalizeY, type Rects } from './rectangles';

/** Wrist-to-middle-knuckle length, as a fraction of the frame, for Z = 0 (far) and Z = 255 (near). */
export const PALM_Z_FAR = 0.08;
export const PALM_Z_NEAR = 0.28;

export const GESTURE_ON = 0.65;
export const GESTURE_OFF = 0.45;

const clamp255 = (v: number): number => Math.min(255, Math.max(0, v));

export function spanToZ(span: number): number {
  return clamp255(((span - PALM_Z_FAR) / (PALM_Z_NEAR - PALM_Z_FAR)) * 255);
}

export class ControlTracker {
  private smooth = new Map<ControlKey, number>();
  private triggerOn = new Map<ControlKey, boolean>();

  /**
   * One camera frame. `follow` is how far each slider moves toward its new position per frame
   * (1 = no smoothing). Returns every control measured this frame:
   * - sliders of a hand in view (a hand out of view leaves its sliders out: they hold);
   * - triggers of both hands (0 for a hand out of view).
   */
  step(observations: HandObservation[], rects: Rects, follow: number): Map<ControlKey, number> {
    const out = new Map<ControlKey, number>();
    for (const hand of HANDS) {
      const o = observations.find((x) => x.hand === hand);
      if (!o) {
        for (const id of TRIGGERS) {
          this.triggerOn.set(`${hand}:${id}`, false);
          out.set(`${hand}:${id}`, 0);
        }
        // Coming back into view jumps straight to the new position.
        for (const id of SLIDERS) this.smooth.delete(`${hand}:${id}`);
        continue;
      }
      const rect = rects[hand];
      const x = rect ? normalizeX(rect, o.palmX) : Math.min(1, Math.max(0, o.palmX));
      const y = rect ? normalizeY(rect, o.palmY) : Math.min(1, Math.max(0, 1 - o.palmY));
      const target: Record<SliderId, number> = {
        palm_x: x * 255,
        palm_y: y * 255,
        palm_z: spanToZ(o.span),
      };
      for (const id of SLIDERS) {
        const key: ControlKey = `${hand}:${id}`;
        const prev = this.smooth.get(key) ?? target[id];
        const next = prev + follow * (target[id] - prev);
        this.smooth.set(key, next);
        out.set(key, Math.round(clamp255(next)));
      }
      for (const id of TRIGGERS) {
        const key: ControlKey = `${hand}:${id}`;
        const score = o.gestureId === id ? o.gestureScore : 0;
        const was = this.triggerOn.get(key) ?? false;
        const on = was ? score >= GESTURE_OFF : score >= GESTURE_ON;
        this.triggerOn.set(key, on);
        out.set(key, on ? 1 : 0);
      }
    }
    return out;
  }

  reset(): void {
    this.smooth.clear();
    this.triggerOn.clear();
  }
}
