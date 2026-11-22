// Files the plugin loads at runtime, next to index.js: MediaPipe's wasm and the gesture model.
// Shared by vite.daw.config.ts (copied into dist-daw/) and vite.config.ts (served by the dev page).

import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const root = import.meta.dirname;

const WASM_DIR = resolve(root, 'node_modules/@mediapipe/tasks-vision/wasm');
/** The model the Python reader uses; committed in the repo. */
const REPO_MODEL = resolve(root, '../../reader/models/gesture_recognizer.task');
const CACHED_MODEL = resolve(root, '.cache/gesture_recognizer.task');
const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task';

/** Published path (relative to index.js) → file on disk. */
export async function runtimeAssets(): Promise<Record<string, string>> {
  return {
    'mediapipe/vision_wasm_internal.js': resolve(WASM_DIR, 'vision_wasm_internal.js'),
    'mediapipe/vision_wasm_internal.wasm': resolve(WASM_DIR, 'vision_wasm_internal.wasm'),
    'models/gesture_recognizer.task': await modelPath(),
  };
}

async function modelPath(): Promise<string> {
  if (existsSync(REPO_MODEL)) return REPO_MODEL;
  if (existsSync(CACHED_MODEL)) return CACHED_MODEL;
  console.log(`[musichands] downloading the gesture model to ${CACHED_MODEL}`);
  const res = await fetch(MODEL_URL);
  if (!res.ok) throw new Error(`gesture model download failed: HTTP ${res.status}`);
  mkdirSync(dirname(CACHED_MODEL), { recursive: true });
  writeFileSync(CACHED_MODEL, new Uint8Array(await res.arrayBuffer()));
  return CACHED_MODEL;
}
