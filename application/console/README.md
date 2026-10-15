# MusicHands Console

Single-console launcher that runs both **MusicHands Reader** (camera hand-tracking + web UI) and **MusicHands Bridge** (UDP-to-MIDI translation) on parallel threads in a single process.

## Prerequisites

- **Python 3.10 – 3.12 (64-bit)** (or any Python 3.10+ on Windows; if your default Python is 3.13+, the bootstrapper automatically looks for Python 3.12/3.11/3.10 or installs Python 3.12 via `winget`).
- **Webcam** (for hand tracking)
- **Windows:** Virtual MIDI port via **loopMIDI** (automatically installed and configured on first run if missing).

---

## Quick Start (Zero Manual Setup)

From `application/console`, simply run:

```bash
cd application/console
python -m musichands_console
```

If `.venv` or required packages (`opencv-python`, `mediapipe`, `mido`, `python-rtmidi`) are missing on a new computer, `musichands_console` **automatically bootstraps itself**:
1. Finds a compatible Python interpreter (preferring Python 3.12 / 3.11 / 3.10) and creates `<repo_root>/.venv`.
2. Installs all dependencies from `requirements.txt` into `.venv`.
3. Re-launches `musichands_console` inside `.venv` automatically (no manual venv activation required).
4. Downloads the MediaPipe gesture model (`reader/models/gesture_recognizer.task`) if missing.
5. Opens the configured MIDI output port (auto-installing loopMIDI on Windows if needed) and starts the Reader + Bridge threads.

Press `Ctrl+C` in the terminal to stop both threads cleanly and release any active MIDI notes.

---

## Setup Only (Without Starting the App)

If you want to provision the environment, install dependencies, download the MediaPipe model, and verify the MIDI driver ahead of time without launching the app, run either:

```bash
python setup.py
```
or:
```bash
python -m musichands_console --setup
```

---

## Command-Line Options

```text
python -m musichands_console [options]
```

| Option | Default | Description |
| :--- | :--- | :--- |
| `--setup` | `False` | Create `.venv`, install dependencies, download the MediaPipe model, verify MIDI driver, and exit |
| `--no-bootstrap` | `False` | Skip automatic `.venv` creation and dependency installation on startup |
| `--config <path>` | `../../bridge/config.json` | Path to a custom bridge `config.json` file |
| `--camera <index>` | From `reader/camera.json` | Override the camera index (e.g. `--camera 0`) |
| `--reader-host <host>` | `127.0.0.1` | Reader HTTP server bind address |
| `--reader-port <port>` | `9110` | Reader HTTP server port |
| `--solo <key>` | `None` | Solo a single control key in the MIDI bridge (e.g. `--solo R:palm_y`) |
| `--no-browser` | `False` | Do not automatically open the Reader web UI in a browser |
| `--quiet` | `False` | Suppress MIDI message logging in the console |
| `--verbose` | `False` | Log startup and status messages (MIDI port, UDP address, UI URL) |

### Examples

Run with status output enabled:
```bash
python -m musichands_console --verbose
```

Run headless without opening a browser window and solo right-hand palm height:
```bash
python -m musichands_console --no-browser --solo R:palm_y
```

Override camera index and use a custom bridge config:
```bash
python -m musichands_console --camera 1 --config /path/to/config.json
```
