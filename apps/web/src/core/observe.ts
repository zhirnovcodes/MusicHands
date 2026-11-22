// MediaPipe result → one observation per hand. Port of observations_from_result,
// palm_center, palm_margins and hand_span in reader/musichands_reader/.

import { GOOGLE_TO_ID, type Hand, type TriggerId } from './catalog';

export interface Point {
  x: number;
  y: number;
}

export interface Category {
  categoryName: string;
  score: number;
}

/** The parts of a MediaPipe GestureRecognizerResult this module reads. */
export interface RecognizerResult {
  landmarks: Point[][];
  handedness: Category[][];
  gestures: Category[][];
}

/** Distances from the palm centre to the outermost wrist / fingertip: left, right, top, bottom. */
export type Margins = readonly [number, number, number, number];

export interface HandObservation {
  hand: Hand;
  palmX: number;
  palmY: number;
  /** Wrist to middle knuckle, as a fraction of the frame. Larger = closer to the camera. */
  span: number;
  gestureId: TriggerId | null;
  gestureScore: number;
  margins: Margins;
}

export interface HandLandmarks {
  hand: Hand;
  points: Point[];
}

const WRIST = 0;
const INDEX_MCP = 5;
const MIDDLE_MCP = 9;
const PINKY_MCP = 17;
const PALM_POINTS = [WRIST, INDEX_MCP, PINKY_MCP] as const;
const EXTREMITY_POINTS = [WRIST, 4, 8, 12, 16, 20] as const;
export const DEFAULT_MARGINS: Margins = [0.1, 0.1, 0.12, 0.12];

/** Average of wrist, index knuckle and pinky knuckle. */
export function palmCenter(points: Point[]): Point {
  let x = 0;
  let y = 0;
  for (const i of PALM_POINTS) {
    x += points[i]?.x ?? 0;
    y += points[i]?.y ?? 0;
  }
  return { x: x / PALM_POINTS.length, y: y / PALM_POINTS.length };
}

export function palmMargins(points: Point[], c: Point): Margins {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const i of EXTREMITY_POINTS) {
    const p = points[i];
    if (!p) continue;
    xs.push(p.x);
    ys.push(p.y);
  }
  if (xs.length === 0) return DEFAULT_MARGINS;
  return [
    Math.max(0, c.x - Math.min(...xs)),
    Math.max(0, Math.max(...xs) - c.x),
    Math.max(0, c.y - Math.min(...ys)),
    Math.max(0, Math.max(...ys) - c.y),
  ];
}

export function handSpan(points: Point[]): number {
  const w = points[WRIST];
  const m = points[MIDDLE_MCP];
  if (!w || !m) return 0;
  return Math.hypot(m.x - w.x, m.y - w.y);
}

/**
 * The frame given to MediaPipe is mirrored (selfie view), which inverts its handedness label,
 * so "Left" is the player's right hand. Same swap as the Python reader.
 * At most one observation per hand; extra detections of the same hand are dropped.
 */
export function observe(result: RecognizerResult): {
  observations: HandObservation[];
  hands: HandLandmarks[];
} {
  const observations: HandObservation[] = [];
  const hands: HandLandmarks[] = [];
  const seen = new Set<Hand>();
  result.landmarks.forEach((points, i) => {
    const label = result.handedness[i]?.[0]?.categoryName;
    if (points.length <= PINKY_MCP) return;
    const hand: Hand | undefined = label === 'Left' ? 'R' : label === 'Right' ? 'L' : undefined;
    if (!hand || seen.has(hand)) return;
    seen.add(hand);
    hands.push({ hand, points });
    const g = result.gestures[i]?.[0];
    const gestureId = g ? (GOOGLE_TO_ID[g.categoryName] ?? null) : null;
    const c = palmCenter(points);
    observations.push({
      hand,
      palmX: c.x,
      palmY: c.y,
      span: handSpan(points),
      gestureId,
      gestureScore: gestureId && g ? g.score : 0,
      margins: palmMargins(points, c),
    });
  });
  return { observations, hands };
}
