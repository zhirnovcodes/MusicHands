# MusicHands for IvanDAW

The MusicHands webcam MIDI controller as an [IvanDAW](https://github.com/zhirnovcodes/ivan-daw) web plugin (Plugin API v2). It runs entirely in the browser: no Python, no loopMIDI, no bridge. MediaPipe's gesture recognizer runs as WebAssembly on the page. The tracking logic is a direct port of `reader/` and `bridge/`: the same smoothing, gesture hysteresis, rectangles and handedness rules.

## What it sends

| Port | Kind | Carries |
| --- | --- | --- |
| `notes` | events out (MIDI) | a note while a gesture is held: note on at the gesture, note off when it ends |
| `l-x`, `l-y`, `l-z` | modulation out | left palm X, Y and Z, 0..1 |
| `r-x`, `r-y`, `r-z` | modulation out | right palm X, Y and Z, 0..1 |

X and Y are measured inside each hand's rectangle (Y = 1 at the top). Z grows as the hand comes closer to the camera.

Default notes (C3 = 60): left fist C2 (48), left palm D2 (50), right fist C3 (60), right palm D3 (62).

## Wiring in IvanDAW

- **Sliders:** draw a control cable from `l-x` … `r-z` to any parameter, volume or pan.
- **Gestures:** cable `notes` → an instrument's `in`.

## Parameters

| id | kind | default | |
| --- | --- | --- | --- |
| `autoRect` | boolean | on | rectangles follow your hands; off: drag them in the window |
| `smoothing` | float 0..0.9 | 0.55 | higher = smoother, slower sliders |
| `velocity` | int 1..127 | 127 | note velocity |
| `noteLFist`, `noteLPalm`, `noteRFist`, `noteRPalm` | int 0..127 | 48, 50, 60, 62 | note per gesture |

Ids never change and new ones are only appended.

## Window

- Camera picker, tracking status and frame rate.
- Live preview with hand skeletons and the tracking rectangles (red = left, blue = right).
- One button per control with its live value. Click a button to mute that control: a muted slider holds its last value, and a muted gesture releases its note.
- With *Auto rectangles* off, drag a rectangle to move it, or drag a corner to resize it.

Saved with the project: parameters, muted controls, manual rectangles, chosen camera.

## Build

```
pnpm install
pnpm --filter @musichands/web dev         # dev page: camera, port meters, event log, test synth
pnpm --filter @musichands/web build:daw   # typecheck + tests + build → apps/web/dist-daw/
```

`dist-daw/` is the plugin folder: `index.js`, `manifest.json`, `mediapipe/` (wasm loader and binary) and `models/gesture_recognizer.task`. The model is taken from `reader/models/` (or downloaded once into `.cache/`). Everything loads from the plugin's own folder, so it works offline.

CI (`.github/workflows/daw-plugin.yml`): PRs get a `musichands-daw` artifact. Every push to `master` that touches the plugin publishes the release `daw-build-<n>` with `musichands-daw.zip`.

## Known limits

- **Events are sent on arrival** (`time` = now), like a hardware controller. Latency is one camera frame plus inference: about 30–60 ms.
- **Background tabs:** the camera loop stops while the tab is hidden; held notes are released when it hides.
- **One camera per plugin instance.** Two MusicHands nodes open the camera twice.
- **Needs WebGL2**, even on the CPU path: MediaPipe uploads frames through it. The plugin uses the GPU delegate, unless WebGL is software-rendered (then the CPU delegate, which is about 15× faster there).
- Camera access requires `localhost` or https, which IvanDAW's dev server provides.
