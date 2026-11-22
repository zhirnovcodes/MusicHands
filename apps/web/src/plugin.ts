// MusicHands for IvanDAW (Plugin API v2): a webcam MIDI controller.
//
// Ports:
//   notes        events out: a note while a gesture is held (fist / open palm, each hand)
//   l-x … r-z    modulation out: palm X, Y and Z of each hand, 0..1
//
// The camera and MediaPipe run on the main thread. Events go out as they are measured
// (time = now): this is a live controller, like a hardware knob, not a scheduled source.

import type {
  ParameterChange,
  PluginEvent,
  PluginFactory,
  PluginInstance,
  PluginState,
  PortHandle,
} from 'ivandaw-core';
import { ALL_KEYS, type ControlKey, HANDS, isControlKey, isTrigger, splitKey, type TriggerKey } from './core/catalog';
import { ControlTracker } from './core/controls';
import { observe } from './core/observe';
import { Output, type OutputSettings } from './core/output';
import { DEFAULT_RECTS, Rectangles, readRect } from './core/rectangles';
import { ID, manifest, VERSION } from './manifest';
import {
  clampPlain,
  NOTE_PARAM,
  PARAMS,
  type ParamId,
  paramInfo,
  toNormalized,
  toPlain,
} from './params';
import { createView, type View } from './ui/view';
import { HandCamera, loadRecognizer } from './vision';

const STATE_VERSION = 1;

interface SavedData {
  v: number;
  params: Record<string, number>;
  enabled: string[];
  rects: Record<string, unknown>;
  deviceId?: string;
}

const factory: PluginFactory = {
  manifest,
  async create(host, container) {
    const ctx = host.audioContext;
    const now = (): number => ctx.currentTime;
    const listeners = new Set<(e: PluginEvent) => void>();
    const watchers = new Set<(c: ParameterChange) => void>();
    const emit = (e: PluginEvent): void => {
      for (const l of [...listeners]) l(e);
    };
    const tell = (c: ParameterChange): void => {
      for (const w of [...watchers]) w(c);
    };

    const values = new Map<string, number>(PARAMS.map((p) => [p.id, p.default]));
    const value = (id: ParamId): number => values.get(id) ?? 0;
    const enabled = new Set<ControlKey>(ALL_KEYS);
    const rects = new Rectangles();
    const tracker = new ControlTracker();
    const output = new Output(emit);
    const settings: OutputSettings = {
      enabled,
      note: (key) => value(NOTE_PARAM[key]),
      get velocity() {
        return value('velocity');
      },
    };
    /** Latest value of each control, for the meters. */
    const shown = new Map<ControlKey, number>();
    let deviceId: string | undefined;
    let suspended = false;
    let view: View | null = null;
    let warned = '';

    const recognizer = await loadRecognizer({
      wasmLoader: host.assetUrl('mediapipe/vision_wasm_internal.js'),
      wasmBinary: host.assetUrl('mediapipe/vision_wasm_internal.wasm'),
      model: host.assetUrl('models/gesture_recognizer.task'),
    });

    const camera = new HandCamera(
      recognizer,
      (result) => {
        const { observations, hands } = observe(result);
        const r = rects.compute(observations, enabled);
        const measured = tracker.step(observations, r, 1 - value('smoothing'));
        output.apply(measured, settings, now());
        for (const [k, v] of measured) shown.set(k, v);
        view?.frame(camera.frame, hands, r, shown);
      },
      (s) => {
        // A lost camera releases held notes; a sliders hold its last value.
        if (s.state !== 'on') output.releaseAll(now());
        if (s.state === 'error' && s.message && s.message !== warned) {
          warned = s.message;
          host.notify('warning', `MusicHands: ${s.message}`);
        }
        if (s.state === 'on') {
          warned = '';
          if (camera.deviceId) deviceId = camera.deviceId;
        }
        view?.sync();
      },
    );

    const startCamera = (): void => {
      if (suspended) return;
      tracker.reset();
      output.resend();
      void camera.start(deviceId);
    };

    /** A hidden tab stops the camera loop: release notes so none hang. */
    const onVisibility = (): void => {
      if (document.hidden) {
        output.releaseAll(now());
        tracker.reset();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    const setParam = (id: string, plain: number, source: ParameterChange['source']): void => {
      const p = paramInfo(id);
      if (!p) return;
      const v = clampPlain(p, plain);
      const before = values.get(id);
      values.set(id, v);
      if (id === 'autoRect') rects.automatic = v === 1;
      if (before !== v) {
        // A new note for a held gesture: release the old note; it sounds again with the new one.
        for (const key of Object.keys(NOTE_PARAM) as TriggerKey[]) {
          if (NOTE_PARAM[key] === id) output.release(key, now());
        }
      }
      tell({ id, value: toNormalized(p, v), source });
      view?.sync();
    };

    const toggle = (key: ControlKey): void => {
      if (enabled.has(key)) {
        enabled.delete(key);
        const [, id] = splitKey(key);
        if (isTrigger(id)) output.release(key as TriggerKey, now());
      } else {
        enabled.add(key);
      }
      host.markDirty();
      view?.sync();
    };

    const mount = (el: HTMLElement): void => {
      view?.destroy();
      view = createView(
        el,
        {
          toggle,
          setAutoRect: (on) => {
            setParam('autoRect', on ? 1 : 0, 'ui');
            host.markDirty();
          },
          setRect: (hand, rect) => {
            rects.configs[hand] = rect;
            host.markDirty();
          },
          selectCamera: (id) => {
            deviceId = id;
            host.markDirty();
            startCamera();
          },
          restart: startCamera,
        },
        () => ({
          enabled,
          autoRect: value('autoRect') === 1,
          deviceId: camera.deviceId ?? deviceId,
          status: camera.status,
          fps: camera.fps,
        }),
      );
    };

    const ports = new Map<string, PortHandle>(
      manifest.ports.map((info): [string, PortHandle] => [
        info.id,
        { info: info as PortHandle['info'] & { kind: 'events' | 'modulation' } },
      ]),
    );

    const instance: PluginInstance = {
      ports,
      latency: 0,
      tail: 0,
      parameters: () => PARAMS,
      parameter(id) {
        const p = paramInfo(id);
        return p ? toNormalized(p, values.get(id) ?? p.default) : 0;
      },
      schedule(events) {
        for (const e of events) {
          if (e.type !== 'automation') continue;
          const p = paramInfo(e.id);
          if (!p) continue;
          setParam(e.id, toPlain(p, e.value), e.source === 'binding' ? 'binding' : 'host');
        }
      },
      listen(l) {
        listeners.add(l);
        return () => listeners.delete(l);
      },
      subscribe(w) {
        watchers.add(w);
        return () => watchers.delete(w);
      },
      async getState(): Promise<PluginState> {
        const data: SavedData = {
          v: STATE_VERSION,
          params: Object.fromEntries(values),
          enabled: ALL_KEYS.filter((k) => enabled.has(k)),
          rects: { L: { ...rects.configs.L }, R: { ...rects.configs.R } },
          deviceId,
        };
        return { pluginId: ID, pluginVersion: VERSION, data };
      },
      async setState(s) {
        output.releaseAll(now());
        const d = (typeof s.data === 'object' && s.data !== null ? s.data : {}) as Partial<SavedData>;
        const saved = (typeof d.params === 'object' && d.params !== null ? d.params : {}) as Record<
          string,
          unknown
        >;
        for (const p of PARAMS) {
          const v = saved[p.id];
          setParam(p.id, typeof v === 'number' && Number.isFinite(v) ? v : p.default, 'host');
        }
        if (Array.isArray(d.enabled)) {
          enabled.clear();
          for (const k of d.enabled) if (isControlKey(k)) enabled.add(k);
        }
        const savedRects = (typeof d.rects === 'object' && d.rects !== null ? d.rects : {}) as Record<
          string,
          unknown
        >;
        for (const hand of HANDS) rects.configs[hand] = readRect(savedRects[hand], DEFAULT_RECTS[hand]);
        const nextDevice = typeof d.deviceId === 'string' && d.deviceId ? d.deviceId : undefined;
        if (nextDevice && nextDevice !== (camera.deviceId ?? deviceId)) {
          deviceId = nextDevice;
          startCamera();
        }
        view?.sync();
      },
      mount,
      unmount() {
        view?.destroy();
        view = null;
      },
      suspend() {
        suspended = true;
        camera.stop();
      },
      resume() {
        suspended = false;
        startCamera();
      },
      dispose() {
        document.removeEventListener('visibilitychange', onVisibility);
        camera.close();
        output.releaseAll(now());
        view?.destroy();
        view = null;
        listeners.clear();
        watchers.clear();
      },
    };

    if (container) mount(container);
    startCamera();
    return instance;
  },
};

export default factory;
