// The frozen control list, the same as reader/musichands_reader/catalog.py.
// Each hand has two triggers (gestures → notes) and three sliders (palm position → modulation).

export const HANDS = ['L', 'R'] as const;
export type Hand = (typeof HANDS)[number];

export const TRIGGERS = ['closed_fist', 'open_palm'] as const;
export type TriggerId = (typeof TRIGGERS)[number];

export const SLIDERS = ['palm_x', 'palm_y', 'palm_z'] as const;
export type SliderId = (typeof SLIDERS)[number];

export type ControlId = TriggerId | SliderId;
export const CONTROLS: readonly ControlId[] = [...TRIGGERS, ...SLIDERS];

export type ControlKey = `${Hand}:${ControlId}`;
export type SliderKey = `${Hand}:${SliderId}`;
export type TriggerKey = `${Hand}:${TriggerId}`;

/** Every control, in output order: L before R, triggers before sliders. */
export const ALL_KEYS: readonly ControlKey[] = HANDS.flatMap((h) =>
  CONTROLS.map((c): ControlKey => `${h}:${c}`),
);

export const isTrigger = (id: ControlId): id is TriggerId =>
  (TRIGGERS as readonly string[]).includes(id);

export function splitKey(key: ControlKey): [Hand, ControlId] {
  const [hand, id] = key.split(':') as [Hand, ControlId];
  return [hand, id];
}

export function isControlKey(v: unknown): v is ControlKey {
  return typeof v === 'string' && (ALL_KEYS as readonly string[]).includes(v);
}

/** Only these classifier labels become controls; anything else the model reports is dropped. */
export const GOOGLE_TO_ID: Readonly<Record<string, TriggerId>> = {
  Closed_Fist: 'closed_fist',
  Open_Palm: 'open_palm',
};

export const LABELS: Readonly<Record<ControlId, string>> = {
  closed_fist: 'Fist',
  open_palm: 'Palm',
  palm_x: 'X',
  palm_y: 'Y',
  palm_z: 'Z',
};

/** The IvanDAW events port that carries the gesture notes. */
export const NOTES_PORT = 'notes';

/** The modulation port each slider drives. */
export const SLIDER_PORT: Readonly<Record<SliderKey, string>> = {
  'L:palm_x': 'l-x',
  'L:palm_y': 'l-y',
  'L:palm_z': 'l-z',
  'R:palm_x': 'r-x',
  'R:palm_y': 'r-y',
  'R:palm_z': 'r-z',
};
