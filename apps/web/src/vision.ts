// Webcam + MediaPipe gesture recognizer, on the main thread.
// Each camera frame is drawn mirrored (selfie view) into `frame`, recognized, and handed to `onResult`.
// Frames are polled with requestAnimationFrame and processed only when the video has a new one.

import { GestureRecognizer, type GestureRecognizerResult } from '@mediapipe/tasks-vision';

export interface VisionAssets {
  wasmLoader: string;
  wasmBinary: string;
  model: string;
}

export type CameraState = 'off' | 'starting' | 'on' | 'error';
export interface CameraStatus {
  state: CameraState;
  message?: string;
}

type Delegate = 'GPU' | 'CPU';

function createRecognizer(a: VisionAssets, delegate: Delegate): Promise<GestureRecognizer> {
  return GestureRecognizer.createFromOptions(
    { wasmLoaderPath: a.wasmLoader, wasmBinaryPath: a.wasmBinary },
    {
      baseOptions: { modelAssetPath: a.model, delegate },
      runningMode: 'VIDEO',
      numHands: 2,
    },
  );
}

/**
 * True when WebGL runs in software (no usable GPU, or a blocklisted one). MediaPipe's GPU delegate is
 * then ~15× slower than its CPU one (measured: 1100 ms vs 80 ms per frame on SwiftShader).
 */
function softwareWebGl(): boolean {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    if (!gl) return true;
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return /swiftshader|llvmpipe|softpipe|software|basic render/i.test(renderer);
  } catch {
    return true;
  }
}

/** Loads the model. Prefers the GPU; uses the CPU when the GPU is software or fails to load. */
export async function loadRecognizer(a: VisionAssets): Promise<Recognizer> {
  if (softwareWebGl()) return { assets: a, delegate: 'CPU', task: await createRecognizer(a, 'CPU') };
  try {
    return { assets: a, delegate: 'GPU', task: await createRecognizer(a, 'GPU') };
  } catch {
    return { assets: a, delegate: 'CPU', task: await createRecognizer(a, 'CPU') };
  }
}

export interface Recognizer {
  assets: VisionAssets;
  delegate: Delegate;
  task: GestureRecognizer;
}

export async function listCameras(): Promise<MediaDeviceInfo[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const all = await navigator.mediaDevices.enumerateDevices();
  return all.filter((d) => d.kind === 'videoinput');
}

function describe(e: unknown): string {
  const name = e instanceof DOMException ? e.name : '';
  if (name === 'NotAllowedError') return 'Camera access was blocked. Allow it in the browser.';
  if (name === 'NotFoundError') return 'No camera found.';
  if (name === 'NotReadableError') return 'The camera is busy in another app.';
  return e instanceof Error ? e.message : String(e);
}

export class HandCamera {
  /** The latest frame, mirrored. */
  readonly frame: HTMLCanvasElement = document.createElement('canvas');
  status: CameraStatus = { state: 'off' };
  /** The camera actually open (may differ from the one asked for). */
  deviceId: string | undefined;
  fps = 0;

  private readonly video: HTMLVideoElement = document.createElement('video');
  private readonly draw: CanvasRenderingContext2D;
  private stream: MediaStream | null = null;
  private generation = 0;
  private raf = 0;
  private lastVideoTime = -1;
  private lastStamp = 0;
  private frames = 0;
  private fpsSince = 0;
  private closed = false;

  constructor(
    private recognizer: Recognizer,
    private readonly onResult: (r: GestureRecognizerResult) => void,
    private readonly onStatus: (s: CameraStatus) => void,
  ) {
    this.video.muted = true;
    this.video.playsInline = true;
    const draw = this.frame.getContext('2d', { willReadFrequently: false });
    if (!draw) throw new Error('2D canvas is not available');
    this.draw = draw;
  }

  async start(deviceId?: string): Promise<void> {
    this.stop();
    const gen = this.generation;
    this.setStatus({ state: 'starting' });
    if (!navigator.mediaDevices?.getUserMedia) {
      this.setStatus({ state: 'error', message: 'This browser has no camera access (needs https or localhost).' });
      return;
    }
    let stream: MediaStream;
    try {
      stream = await open(deviceId);
    } catch (e) {
      if (gen === this.generation) this.setStatus({ state: 'error', message: describe(e) });
      return;
    }
    if (gen !== this.generation) {
      for (const t of stream.getTracks()) t.stop();
      return;
    }
    this.stream = stream;
    const track = stream.getVideoTracks()[0];
    this.deviceId = track?.getSettings().deviceId;
    if (track) {
      track.onended = () => {
        if (gen === this.generation) {
          this.halt();
          this.setStatus({ state: 'error', message: 'The camera was disconnected.' });
        }
      };
    }
    this.video.srcObject = stream;
    try {
      await this.video.play();
    } catch (e) {
      if (gen === this.generation) {
        this.halt();
        this.setStatus({ state: 'error', message: describe(e) });
      }
      return;
    }
    if (gen !== this.generation) return;
    this.lastVideoTime = -1;
    this.fpsSince = performance.now();
    this.frames = 0;
    this.setStatus({ state: 'on' });
    this.raf = requestAnimationFrame(() => this.tick(gen));
  }

  stop(): void {
    this.halt();
    if (this.status.state !== 'off') this.setStatus({ state: 'off' });
  }

  close(): void {
    this.stop();
    this.closed = true;
    this.recognizer.task.close();
  }

  /** Stops the loop and releases the camera, without a status change. */
  private halt(): void {
    this.generation++;
    cancelAnimationFrame(this.raf);
    if (this.stream) for (const t of this.stream.getTracks()) t.stop();
    this.stream = null;
    this.video.srcObject = null;
    this.fps = 0;
  }

  private setStatus(s: CameraStatus): void {
    this.status = s;
    this.onStatus(s);
  }

  private tick(gen: number): void {
    if (gen !== this.generation) return;
    const v = this.video;
    if (v.readyState >= 2 && v.videoWidth > 0 && v.currentTime !== this.lastVideoTime) {
      this.lastVideoTime = v.currentTime;
      this.process(v);
    }
    if (gen === this.generation) this.raf = requestAnimationFrame(() => this.tick(gen));
  }

  private process(v: HTMLVideoElement): void {
    const w = v.videoWidth;
    const h = v.videoHeight;
    if (this.frame.width !== w || this.frame.height !== h) {
      this.frame.width = w;
      this.frame.height = h;
    }
    this.draw.setTransform(-1, 0, 0, 1, w, 0);
    this.draw.drawImage(v, 0, 0, w, h);
    this.draw.setTransform(1, 0, 0, 1, 0, 0);
    const stamp = Math.max(this.lastStamp + 1, Math.round(performance.now()));
    this.lastStamp = stamp;
    let result: GestureRecognizerResult;
    try {
      result = this.recognizer.task.recognizeForVideo(this.frame, stamp);
    } catch (e) {
      this.fallBackToCpu(e);
      return;
    }
    this.frames++;
    const now = performance.now();
    if (now - this.fpsSince >= 1000) {
      this.fps = Math.round((this.frames * 1000) / (now - this.fpsSince));
      this.frames = 0;
      this.fpsSince = now;
    }
    this.onResult(result);
  }

  /** A GPU that loaded but fails on frames: reload on the CPU once, then keep going. */
  private fallBackToCpu(e: unknown): void {
    const gen = this.generation;
    if (this.recognizer.delegate === 'CPU') {
      this.halt();
      this.setStatus({ state: 'error', message: `Hand tracking failed: ${describe(e)}` });
      return;
    }
    const old = this.recognizer;
    this.recognizer = { ...old, delegate: 'CPU' };
    cancelAnimationFrame(this.raf);
    this.setStatus({ state: 'starting', message: 'Switching hand tracking to the CPU…' });
    createRecognizer(old.assets, 'CPU').then(
      (task) => {
        if (this.closed) {
          task.close();
          return;
        }
        old.task.close();
        this.recognizer = { assets: old.assets, delegate: 'CPU', task };
        if (gen !== this.generation) return;
        this.setStatus({ state: 'on' });
        this.raf = requestAnimationFrame(() => this.tick(gen));
      },
      (err: unknown) => {
        if (gen !== this.generation) return;
        this.halt();
        this.setStatus({ state: 'error', message: `Hand tracking failed: ${describe(err)}` });
      },
    );
  }
}

async function open(deviceId: string | undefined): Promise<MediaStream> {
  const size = { width: { ideal: 640 }, height: { ideal: 480 } };
  if (deviceId) {
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: { ...size, deviceId: { exact: deviceId } },
        audio: false,
      });
    } catch (e) {
      // The saved camera is gone (another PC, unplugged): use the default one.
      if (!(e instanceof DOMException) || e.name === 'NotAllowedError') throw e;
    }
  }
  return navigator.mediaDevices.getUserMedia({ video: size, audio: false });
}
