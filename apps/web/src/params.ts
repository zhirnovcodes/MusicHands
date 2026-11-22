// The parameter list. Ids are stable forever (saved projects, control cables): append only.

import type { ParameterInfo } from 'ivandaw-core';
import type { TriggerKey } from './core/catalog';

const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
/** Same octave numbering as ivandaw-core (C1 = 36, so C3 = 60). */
export const noteName = (n: number): string =>
  `${NAMES[Math.round(n) % 12]}${Math.floor(Math.round(n) / 12) - 2}`;

const note = (id: string, label: string, def: number): ParameterInfo => ({
  id,
  label,
  kind: 'int',
  min: 0,
  max: 127,
  default: def,
  group: 'Notes',
  automatable: false,
  format: noteName,
});

export const PARAMS: ParameterInfo[] = [
  {
    id: 'autoRect',
    label: 'Auto rectangles',
    kind: 'boolean',
    min: 0,
    max: 1,
    default: 1,
    group: 'Tracking',
    automatable: false,
  },
  {
    id: 'smoothing',
    label: 'Smoothing',
    kind: 'float',
    min: 0,
    max: 0.9,
    default: 0.55,
    group: 'Tracking',
    automatable: true,
    format: (v) => `${Math.round(v * 100)}%`,
  },
  {
    id: 'velocity',
    label: 'Velocity',
    kind: 'int',
    min: 1,
    max: 127,
    default: 127,
    group: 'Notes',
    automatable: true,
  },
  note('noteLFist', 'Left fist', 48),
  note('noteLPalm', 'Left palm', 50),
  note('noteRFist', 'Right fist', 60),
  note('noteRPalm', 'Right palm', 62),
];

export type ParamId =
  | 'autoRect'
  | 'smoothing'
  | 'velocity'
  | 'noteLFist'
  | 'noteLPalm'
  | 'noteRFist'
  | 'noteRPalm';

export const NOTE_PARAM: Readonly<Record<TriggerKey, ParamId>> = {
  'L:closed_fist': 'noteLFist',
  'L:open_palm': 'noteLPalm',
  'R:closed_fist': 'noteRFist',
  'R:open_palm': 'noteRPalm',
};

export const paramInfo = (id: string): ParameterInfo | undefined => PARAMS.find((p) => p.id === id);

/** normalized 0..1 → plain min..max. */
export function toPlain(p: ParameterInfo, n: number): number {
  const c = Math.min(1, Math.max(0, n));
  let v = p.scale === 'log' ? p.min * (p.max / p.min) ** c : p.min + c * (p.max - p.min);
  if (p.kind === 'int' || p.kind === 'choice' || p.kind === 'boolean') v = Math.round(v);
  return v;
}

/** plain min..max → normalized 0..1. */
export function toNormalized(p: ParameterInfo, v: number): number {
  if (p.max === p.min) return 0;
  const n =
    p.scale === 'log'
      ? Math.log(v / p.min) / Math.log(p.max / p.min)
      : (v - p.min) / (p.max - p.min);
  return Math.min(1, Math.max(0, n));
}

/** Clamps (and rounds, for whole-number kinds) a plain value read from saved state. */
export function clampPlain(p: ParameterInfo, v: number): number {
  const c = Math.min(p.max, Math.max(p.min, v));
  return p.kind === 'float' ? c : Math.round(c);
}
