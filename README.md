# MusicHands

**MusicHands** is an open-source virtual MIDI controller powered by Google's [MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer) hand-recognition library.

It connects to your webcam, tracks your hand positions and basic gestures in real time, translates them into MIDI signals, and sends them to a Windows virtual MIDI input. You can use it with **Ableton Live**, **FL Studio**, **TouchDesigner**, or any other MIDI-compatible software.

[![MusicHands Demo Video](https://img.youtube.com/vi/cGj63p7LfAU/maxresdefault.jpg)](https://youtu.be/cGj63p7LfAU)

> **Watch the demo & walkthrough on YouTube:** [https://youtu.be/cGj63p7LfAU](https://youtu.be/cGj63p7LfAU)

---

## Features

- **Low-Latency Hand Tracking:** Powered by [MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer), running smoothly at ~30 FPS even on older processors (such as an Intel i5) using default MediaPipe configurations.
- **Two Types of MIDI Signals:**
  - **Sliders (Continuous Control Changes / CC):** Track left and right palm `X`, `Y`, and `Z` positions.
  - **Triggers (Buttons / MIDI Notes):** Detect basic hand gestures—**Open Palm** and **Closed Fist**—for both hands.
- **Interactive Browser UI:**
  - Select and rescan connected webcams.
  - Enable or disable individual triggers and sliders on the fly.
  - Manually adjust left/right hand-tracking bounding boxes or toggle **Automatic rectangles** mode so the tracking area dynamically adapts to keep your hands in frame.
  - Inspect live trigger and slider change logs in real time.
- **Virtual MIDI Routing on Windows:** Uses [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) to expose a virtual `MusicHands` MIDI port to your DAW or creative coding environment.
- **Single-Command Console Launcher:** Launches both the browser UI (`reader`) and the MIDI bridge (`bridge`) together. On the first run, it automatically sets up a Python virtual environment, installs dependencies, downloads the MediaPipe model, and configures the virtual MIDI port.

---

## How It Works

MusicHands consists of two core components wrapped in a single console application:

1. **Reader (`reader/`):** Captures webcam frames, runs MediaPipe hand and gesture tracking within configurable bounding boxes, serves the browser-based control UI (default `http://127.0.0.1:9110`), and publishes tracking data over `localhost` via UDP (default port `9100`).
2. **Bridge (`bridge/`):** Listens to the localhost port at a set interval, translates hand positions and gestures into MIDI Control Change (CC) and Note messages, and routes them to the `MusicHands` virtual MIDI port created via **loopMIDI**.

---

## Getting Started

### Prerequisites

- **Windows** (with a webcam)
- **Python 3.10 – 3.12 (64-bit)**
- **[loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html)** (bundled and automatically installed/configured on first run if missing)

### Running MusicHands

From the repository root, run the console application:

```bash
cd application/console
python -m musichands_console
```

On the **first run**, the application automatically:
1. Creates a local `.venv` virtual environment and installs all required Python packages (`opencv-python`, `mediapipe`, `mido`, `python-rtmidi`).
2. Downloads the MediaPipe gesture recognition model.
3. Ensures the `MusicHands` virtual MIDI port is available via loopMIDI.
4. Launches both the **Browser UI** (`http://127.0.0.1:9110`) and the **MIDI Bridge**.

Press `Ctrl+C` in the terminal at any time to stop the application cleanly.

*(For advanced CLI flags and standalone setup options, see [`application/console/README.md`](application/console/README.md).)*

---

## Using MusicHands in Ableton Live

1. **Enable the MIDI Input:**
   - Open Ableton Live and go to **Preferences → Link, Tempo & MIDI**.
   - Find the **`MusicHands`** device in the list of connected MIDI inputs and turn on the toggles (**Track** and **Remote**) next to it.

2. **Map Hand Controls to Parameters:**
   - In the MusicHands browser UI, **keep only one slider or trigger enabled** while mapping (Ableton locks onto whichever MIDI signal fires first).
   - In Ableton Live, press **`Ctrl+M`** to enter **MIDI Map Mode**.
   - Click the instrument or effect parameter you want to control, then move your hand in front of the camera.
   - Once mapped, enable the next slider in the MusicHands UI and repeat the process one by one.
   - Press **`Ctrl+M`** again to exit MIDI Map Mode.

3. **Adjust Your Tracking Area:**
   - Drag or resize the red (left hand) and blue (right hand) bounding boxes directly in the camera preview, or check **Automatic rectangles** so the tracking bounds dynamically adapt to your hands.

---

## Default MIDI Mappings

MIDI mappings are configured in [`bridge/config.json`](bridge/config.json):

| Control Key | Hand | Gesture / Axis | MIDI Type | Channel | Note / CC # | Range / Velocity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `R:closed_fist` | Right | Closed fist | Note | 1 | Note `60` (C4) | Velocity `127` |
| `R:open_palm` | Right | Open palm | Note | 1 | Note `62` (D4) | Velocity `127` |
| `R:palm_x` | Right | Palm X | CC | 1 | CC `16` | `0 – 127` |
| `R:palm_y` | Right | Palm Y | CC | 1 | CC `17` | `0 – 127` |
| `R:palm_z` | Right | Palm Z | CC | 1 | CC `18` | `0 – 127` |
| `L:closed_fist` | Left | Closed fist | Note | 2 | Note `60` (C4) | Velocity `127` |
| `L:open_palm` | Left | Open palm | Note | 2 | Note `62` (D4) | Velocity `127` |
| `L:palm_x` | Left | Palm X | CC | 2 | CC `16` | `0 – 127` |
| `L:palm_y` | Left | Palm Y | CC | 2 | CC `17` | `0 – 127` |
| `L:palm_z` | Left | Palm Z | CC | 2 | CC `18` | `0 – 127` |

---

## Project Structure

- `reader/` — Webcam capture, MediaPipe hand/gesture tracking, bounding box logic, and web UI (`http://127.0.0.1:9110`).
- `bridge/` — UDP listener, MIDI translator, loopMIDI driver integration, and mapping configuration.
- `application/console/` — Single-command console launcher with automatic virtual environment bootstrapping.
- `application/windows10/` — Windows desktop packaging and installer scripts.
