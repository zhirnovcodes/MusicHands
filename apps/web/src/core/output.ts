// Control values → IvanDAW events. The web counterpart of bridge/musichands_bridge/translator.py:
// - a slider sends `automation` (0..1) on its own modulation port, only when its value changes;
// - a trigger sends a note on when it turns on and the matching note off when it turns off,
//   is disabled, or everything is released. Every note on gets its note off.

import type { PluginEvent } from 'ivandaw-core';
import {
  ALL_KEYS,
  type ControlKey,
  isTrigger,
  NOTES_PORT,
  SLIDER_PORT,
  type SliderKey,
  splitKey,
  type TriggerKey,
} from './catalog';

export interface OutputSettings {
  enabled: ReadonlySet<ControlKey>;
  note(key: TriggerKey): number;
  velocity: number;
}

const NOTE_ON = 0x90;
const NOTE_OFF = 0x80;

export class Output {
  /** Last value sent per slider, 0..255. */
  private sent = new Map<SliderKey, number>();
  /** Sounding note per trigger. */
  private held = new Map<TriggerKey, number>();

  constructor(private readonly emit: (e: PluginEvent) => void) {}

  apply(values: ReadonlyMap<ControlKey, number>, s: OutputSettings, time: number): void {
    for (const key of ALL_KEYS) {
      const v = values.get(key);
      if (v === undefined) continue;
      const [, id] = splitKey(key);
      if (isTrigger(id)) this.trigger(key as TriggerKey, v === 1 && s.enabled.has(key), s, time);
      else if (s.enabled.has(key)) this.slider(key as SliderKey, v, time);
      else this.sent.delete(key as SliderKey);
    }
  }

  /** Note off for one trigger, if it is sounding (its note changed, or it was disabled). */
  release(key: TriggerKey, time: number): void {
    const note = this.held.get(key);
    if (note === undefined) return;
    this.held.delete(key);
    this.emit({ type: 'midi', time, bytes: [NOTE_OFF, note, 0], port: NOTES_PORT });
  }

  releaseAll(time: number): void {
    for (const key of [...this.held.keys()]) this.release(key, time);
  }

  /** Forget what was sent, so every enabled slider sends its value again on the next frame. */
  resend(): void {
    this.sent.clear();
  }

  isHeld(key: TriggerKey): boolean {
    return this.held.has(key);
  }

  private trigger(key: TriggerKey, on: boolean, s: OutputSettings, time: number): void {
    const held = this.held.get(key);
    if (!on) {
      this.release(key, time);
      return;
    }
    if (held !== undefined) return;
    const note = s.note(key);
    this.held.set(key, note);
    this.emit({ type: 'midi', time, bytes: [NOTE_ON, note, s.velocity], port: NOTES_PORT });
  }

  private slider(key: SliderKey, v: number, time: number): void {
    if (this.sent.get(key) === v) return;
    this.sent.set(key, v);
    const port = SLIDER_PORT[key];
    this.emit({ type: 'automation', time, id: port, value: v / 255, port });
  }
}
