// The plugin window: camera preview with hand skeletons and tracking rectangles, camera picker,
// auto / manual rectangles, and one toggle per control showing its live value.
// The view only draws and reports clicks; plugin.ts owns every value.

import {
  CONTROLS,
  type ControlKey,
  HANDS,
  type Hand,
  isTrigger,
  LABELS,
} from '../core/catalog';
import type { HandLandmarks } from '../core/observe';
import type { RectBounds, RectConfig, Rects } from '../core/rectangles';
import { type CameraStatus, listCameras } from '../vision';
import { CSS } from './styles';

export interface ViewHandlers {
  toggle(key: ControlKey): void;
  setAutoRect(on: boolean): void;
  setRect(hand: Hand, rect: RectConfig): void;
  selectCamera(deviceId: string): void;
  restart(): void;
}

export interface ViewState {
  enabled: ReadonlySet<ControlKey>;
  autoRect: boolean;
  deviceId: string | undefined;
  status: CameraStatus;
  fps: number;
}

export interface View {
  frame(
    src: HTMLCanvasElement,
    hands: HandLandmarks[],
    rects: Rects,
    values: ReadonlyMap<ControlKey, number>,
  ): void;
  /** Re-reads the state (status, toggles, camera) and redraws the chrome. */
  sync(): void;
  destroy(): void;
}

const W = 400;
const H = 300;
const HAND_COLOR: Record<Hand, string> = { L: '#f0565c', R: '#4c95ff' };
const HAND_NAME: Record<Hand, string> = { L: 'Left', R: 'Right' };
const CONNECTIONS: readonly [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];
const GRAB = 10;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls: string,
  parent?: HTMLElement,
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  e.className = cls;
  parent?.append(e);
  return e;
}

type Drag =
  | { hand: Hand; mode: 'move'; start: { x: number; y: number }; rect: RectBounds }
  | { hand: Hand; mode: 'resize'; anchor: { x: number; y: number } };

export function createView(container: HTMLElement, on: ViewHandlers, read: () => ViewState): View {
  const style = document.createElement('style');
  style.textContent = CSS;
  const root = el('div', 'mh-root');
  container.append(style, root);

  // Header
  const head = el('div', 'mh-head', root);
  const status = el('div', 'mh-status', head);
  const dot = el('span', 'mh-dot', status);
  const statusText = el('span', '', status);
  const select = el('select', 'mh-select', head);
  select.title = 'Camera';
  const autoLabel = el('label', 'mh-check', head);
  const auto = el('input', '', autoLabel);
  auto.type = 'checkbox';
  auto.dataset.param = 'autoRect';
  autoLabel.append('Auto rectangles');
  autoLabel.title = 'On: rectangles follow your hands. Off: drag them where you want.';

  // Stage
  const body = el('div', 'mh-body', root);
  const stage = el('div', 'mh-stage', body);
  const canvas = el('canvas', 'mh-canvas', stage);
  const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  const g = canvas.getContext('2d') as CanvasRenderingContext2D;
  g.scale(dpr, dpr);
  const msg = el('div', 'mh-msg', stage);
  const msgText = el('div', '', msg);
  const msgBtn = el('button', 'mh-btn', msg);
  msgBtn.type = 'button';
  msgBtn.addEventListener('click', () => on.restart());

  // Controls
  const cols = el('div', 'mh-cols', body);
  const buttons = new Map<ControlKey, { btn: HTMLButtonElement; mark: HTMLElement }>();
  for (const hand of HANDS) {
    const col = el('div', '', cols);
    const title = el('div', 'mh-hand', col);
    title.dataset.hand = hand;
    title.textContent = HAND_NAME[hand];
    for (const id of CONTROLS) {
      const key: ControlKey = `${hand}:${id}`;
      const btn = el('button', 'mh-ctl', col);
      btn.type = 'button';
      btn.dataset.hand = hand;
      const name = el('span', 'mh-name', btn);
      name.textContent = LABELS[id];
      let mark: HTMLElement;
      if (isTrigger(id)) {
        mark = el('span', 'mh-lamp', btn);
        btn.title = `${HAND_NAME[hand]} ${LABELS[id].toLowerCase()}: plays a note. Click to mute.`;
      } else {
        const bar = el('span', 'mh-bar', btn);
        mark = el('span', 'mh-fill', bar);
        btn.title = `${HAND_NAME[hand]} palm ${LABELS[id]}: drives port ${hand} ${LABELS[id]}. Click to mute.`;
      }
      btn.addEventListener('click', () => on.toggle(key));
      buttons.set(key, { btn, mark });
    }
  }
  const hint = el('div', 'mh-hint', cols);

  // Camera list
  let cameras: MediaDeviceInfo[] = [];
  const fillCameras = async (): Promise<void> => {
    try {
      cameras = await listCameras();
    } catch {
      cameras = [];
    }
    const current = read().deviceId;
    select.replaceChildren();
    if (cameras.length === 0) {
      const o = el('option', '', select);
      o.textContent = 'No camera';
      o.value = '';
    }
    cameras.forEach((c, i) => {
      const o = el('option', '', select);
      o.value = c.deviceId;
      o.textContent = c.label || `Camera ${i + 1}`;
      o.selected = c.deviceId === current;
    });
  };
  select.addEventListener('change', () => {
    if (select.value) on.selectCamera(select.value);
  });
  const onDeviceChange = (): void => void fillCameras();
  navigator.mediaDevices?.addEventListener?.('devicechange', onDeviceChange);
  void fillCameras();

  auto.addEventListener('change', () => on.setAutoRect(auto.checked));

  // Drawing
  let last: { src: HTMLCanvasElement; hands: HandLandmarks[]; rects: Rects } | null = null;
  let fit = { x: 0, y: 0, w: W, h: H };
  const toCanvas = (nx: number, ny: number): { x: number; y: number } => ({
    x: fit.x + nx * fit.w,
    y: fit.y + ny * fit.h,
  });
  const toNorm = (x: number, y: number): { x: number; y: number } => ({
    x: Math.min(1, Math.max(0, (x - fit.x) / fit.w)),
    y: Math.min(1, Math.max(0, (y - fit.y) / fit.h)),
  });

  const draw = (): void => {
    g.fillStyle = '#000';
    g.fillRect(0, 0, W, H);
    if (!last) return;
    const { src, hands, rects } = last;
    if (src.width > 0 && src.height > 0) {
      const s = Math.min(W / src.width, H / src.height);
      fit = { w: src.width * s, h: src.height * s, x: 0, y: 0 };
      fit.x = (W - fit.w) / 2;
      fit.y = (H - fit.h) / 2;
      g.drawImage(src, fit.x, fit.y, fit.w, fit.h);
    }
    for (const hand of HANDS) {
      const r = rects[hand];
      if (!r) continue;
      const a = toCanvas(r.minX, r.minY);
      const b = toCanvas(r.maxX, r.maxY);
      g.lineWidth = 2;
      g.strokeStyle = HAND_COLOR[hand];
      g.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
      if (!read().autoRect) {
        g.fillStyle = HAND_COLOR[hand];
        for (const c of [a, b, { x: a.x, y: b.y }, { x: b.x, y: a.y }]) g.fillRect(c.x - 4, c.y - 4, 8, 8);
      }
    }
    for (const { hand, points } of hands) {
      const pts = points.map((p) => toCanvas(p.x, p.y));
      g.lineCap = 'round';
      for (const [w, color] of [[4, 'rgba(0,0,0,0.6)'], [2, '#fff']] as const) {
        g.lineWidth = w;
        g.strokeStyle = color;
        g.beginPath();
        for (const [i, j] of CONNECTIONS) {
          const p = pts[i];
          const q = pts[j];
          if (!p || !q) continue;
          g.moveTo(p.x, p.y);
          g.lineTo(q.x, q.y);
        }
        g.stroke();
      }
      const palm = [0, 5, 17].map((i) => pts[i]).filter((p) => p !== undefined);
      if (palm.length === 3) {
        const cx = palm.reduce((s, p) => s + p.x, 0) / 3;
        const cy = palm.reduce((s, p) => s + p.y, 0) / 3;
        g.beginPath();
        g.arc(cx, cy, 6, 0, Math.PI * 2);
        g.fillStyle = HAND_COLOR[hand];
        g.fill();
        g.lineWidth = 1;
        g.strokeStyle = '#000';
        g.stroke();
      }
    }
  };

  // Manual rectangles: drag inside to move, drag a corner to resize.
  let drag: Drag | null = null;
  const point = (e: PointerEvent): { x: number; y: number } => {
    const b = canvas.getBoundingClientRect();
    return { x: ((e.clientX - b.left) * W) / b.width, y: ((e.clientY - b.top) * H) / b.height };
  };
  const toConfig = (minX: number, minY: number, maxX: number, maxY: number): RectConfig => ({
    cx: (minX + maxX) / 2,
    cy: (minY + maxY) / 2,
    w: maxX - minX,
    h: maxY - minY,
  });
  canvas.addEventListener('pointerdown', (e) => {
    if (read().autoRect || !last) return;
    const p = point(e);
    for (const hand of HANDS) {
      const r = last.rects[hand];
      if (!r) continue;
      const corners = [
        [r.minX, r.minY, r.maxX, r.maxY],
        [r.maxX, r.minY, r.minX, r.maxY],
        [r.minX, r.maxY, r.maxX, r.minY],
        [r.maxX, r.maxY, r.minX, r.minY],
      ] as const;
      for (const [cx, cy, ax, ay] of corners) {
        const c = toCanvas(cx, cy);
        if (Math.hypot(c.x - p.x, c.y - p.y) <= GRAB) {
          drag = { hand, mode: 'resize', anchor: { x: ax, y: ay } };
        }
      }
      if (drag) break;
      const a = toCanvas(r.minX, r.minY);
      const b = toCanvas(r.maxX, r.maxY);
      if (p.x >= a.x && p.x <= b.x && p.y >= a.y && p.y <= b.y) {
        drag = { hand, mode: 'move', start: toNorm(p.x, p.y), rect: { ...r } };
        break;
      }
    }
    if (drag) {
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
    }
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag || !last) return;
    const p = point(e);
    const n = toNorm(p.x, p.y);
    let b: RectBounds;
    if (drag.mode === 'move') {
      const r = drag.rect;
      const w = r.maxX - r.minX;
      const h = r.maxY - r.minY;
      const minX = Math.min(1 - w, Math.max(0, r.minX + n.x - drag.start.x));
      const minY = Math.min(1 - h, Math.max(0, r.minY + n.y - drag.start.y));
      b = { minX, minY, maxX: minX + w, maxY: minY + h };
    } else {
      const { x, y } = drag.anchor;
      b = { minX: Math.min(x, n.x), minY: Math.min(y, n.y), maxX: Math.max(x, n.x), maxY: Math.max(y, n.y) };
    }
    last.rects = { ...last.rects, [drag.hand]: b };
    on.setRect(drag.hand, toConfig(b.minX, b.minY, b.maxX, b.maxY));
    draw();
  });
  const endDrag = (): void => {
    drag = null;
  };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // Chrome
  let lastStatusAt = 0;
  let wasOn = false;
  const sync = (): void => {
    const s = read();
    dot.dataset.state = s.status.state;
    statusText.textContent =
      s.status.state === 'on'
        ? `Tracking · ${s.fps} fps`
        : s.status.state === 'starting'
          ? (s.status.message ?? 'Starting camera…')
          : s.status.state === 'error'
            ? (s.status.message ?? 'Camera error')
            : 'Camera off';
    msg.hidden = s.status.state === 'on';
    msgText.textContent =
      s.status.state === 'starting'
        ? (s.status.message ?? 'Starting camera… Allow camera access if the browser asks.')
        : s.status.state === 'error'
          ? (s.status.message ?? 'Camera error')
          : 'Camera off';
    msgBtn.hidden = s.status.state === 'starting';
    msgBtn.textContent = s.status.state === 'error' ? 'Retry' : 'Start camera';
    auto.checked = s.autoRect;
    canvas.dataset.edit = s.autoRect ? '0' : '1';
    hint.textContent = s.autoRect
      ? 'Click a control to mute it.'
      : 'Click a control to mute it. Drag a rectangle to move it, a corner to resize.';
    for (const [key, { btn }] of buttons) btn.setAttribute('aria-pressed', String(s.enabled.has(key)));
    // Camera labels appear once access is granted.
    const isOn = s.status.state === 'on';
    if (isOn && !wasOn) void fillCameras();
    wasOn = isOn;
    for (const o of select.options) o.selected = o.value === s.deviceId;
    draw();
  };

  sync();

  return {
    frame(src, hands, rects, values) {
      last = { src, hands, rects: drag ? { ...rects, ...last?.rects } : rects };
      draw();
      for (const [key, { mark }] of buttons) {
        const v = values.get(key);
        if (v === undefined) continue;
        if (mark.className === 'mh-lamp') mark.dataset.on = v === 1 ? '1' : '0';
        else mark.style.width = `${(v / 255) * 100}%`;
      }
      const now = performance.now();
      if (now - lastStatusAt > 500) {
        lastStatusAt = now;
        const s = read();
        if (s.status.state === 'on') statusText.textContent = `Tracking · ${s.fps} fps`;
      }
    },
    sync,
    destroy() {
      navigator.mediaDevices?.removeEventListener?.('devicechange', onDeviceChange);
      style.remove();
      root.remove();
    },
  };
}
