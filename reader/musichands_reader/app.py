"""Reader HTTP server, state management, and CLI entry point."""

import argparse
import json
import os
import socket
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from musichands_reader.camera import (
    CAMERA_PATH,
    MAX_CAMERA_INDEX,
    draw_black_warning,
    encode_jpeg,
    iter_camera_frames,
    load_camera_index,
    publish_frame,
    save_camera_index,
    scan_cameras,
    text_jpeg,
    wait_stop,
)
from musichands_reader.catalog import LABELS, parse_key
from musichands_reader.hand_tracker import (
    MODEL_PATH,
    HandTracker,
    draw_hands,
    ensure_model,
)
from musichands_reader.publish import UdpPublisher

ROOT = Path(__file__).resolve().parent.parent
WEB_PATH = ROOT / "web" / "index.html"
ENABLED_PATH = ROOT / "enabled.json"


class ReaderState:
    def __init__(self, enabled, camera_index):
        self.condition = threading.Condition()
        self.stop = False
        self.enabled = set(enabled)
        self.camera_index = camera_index
        self.camera_status = "opening"
        self.camera_resolution = None
        self.initial_open_done = False
        self.capture_paused = False
        self.capture_held = False
        self.scan_lock = threading.Lock()
        self.frame = b""
        self.frame_id = 0
        self.events = deque(maxlen=200)
        self.event_seq = 0


def load_enabled():
    if not ENABLED_PATH.exists():
        return set()
    try:
        raw = json.loads(ENABLED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    enabled = set()
    for key in raw:
        parsed = parse_key(key)
        if parsed is not None:
            enabled.add(parsed)
    return enabled


def save_enabled(enabled):
    keys = sorted(f"{hand}:{control_id}" for hand, control_id in enabled)
    try:
        ENABLED_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENABLED_PATH.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    except OSError:
        pass


def format_time(started):
    elapsed = max(0.0, time.monotonic() - started)
    minutes = int(elapsed // 60)
    seconds = elapsed - minutes * 60
    return f"{minutes}:{seconds:05.2f}"


def reader_loop(state, publisher, started, model_path=None):
    hand_tracker = HandTracker(model_path=model_path)
    try:
        for frame, black in iter_camera_frames(state):
            with state.condition:
                enabled = set(state.enabled)
            try:
                controls, events, landmark_groups = hand_tracker.process_frame(frame, enabled)
            except Exception as exc:
                print(f"Tracker error: {exc}")
                publish_frame(state, text_jpeg("Tracker error"))
                wait_stop(state, 0.2)
                continue

            publisher.send(
                {
                    "v": 1,
                    "t_ms": int((time.monotonic() - started) * 1000),
                    "source": "mediapipe",
                    "controls": controls,
                }
            )
            draw_hands(frame, landmark_groups)
            if black:
                draw_black_warning(frame)
            jpeg = encode_jpeg(frame)
            stamp = format_time(started)
            with state.condition:
                state.camera_status = "black image" if black else "ok"
                for event in events:
                    state.event_seq += 1
                    event["n"] = state.event_seq
                    event["time"] = stamp
                    event["control"] = LABELS[event["id"]]
                    state.events.append(event)
                state.frame = jpeg
                state.frame_id += 1
                state.condition.notify_all()
    finally:
        hand_tracker.close()
        publisher.close()


camera_loop = reader_loop


class ReaderHandler(BaseHTTPRequestHandler):
    state = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = WEB_PATH.read_bytes()
            self._send(200, "text/html; charset=utf-8", body)
            return
        if parsed.path == "/video":
            self._stream_video()
            return
        if parsed.path == "/api/enabled":
            with self.state.condition:
                keys = sorted(f"{hand}:{control_id}" for hand, control_id in self.state.enabled)
            self._send(200, "application/json", json.dumps({"enabled": keys}).encode("utf-8"))
            return
        if parsed.path == "/api/camera":
            with self.state.condition:
                body = {"index": self.state.camera_index, "status": self.state.camera_status}
            self._send(200, "application/json", json.dumps(body).encode("utf-8"))
            return
        if parsed.path == "/api/cameras":
            cameras = scan_cameras(self.state)
            self._send(200, "application/json", json.dumps({"cameras": cameras}).encode("utf-8"))
            return
        if parsed.path == "/api/events":
            query = parse_qs(parsed.query)
            try:
                after = int(query.get("after", ["0"])[0])
            except ValueError:
                after = 0
            with self.state.condition:
                events = [event for event in self.state.events if event["n"] > after]
            self._send(200, "application/json", json.dumps({"events": events}).encode("utf-8"))
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/camera":
            self._set_camera()
            return
        if parsed.path != "/api/enabled":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            keys = payload["enabled"]
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            self.send_error(400)
            return
        enabled = set()
        for key in keys:
            parsed_key = parse_key(key)
            if parsed_key is None:
                self.send_error(400)
                return
            enabled.add(parsed_key)
        with self.state.condition:
            self.state.enabled = enabled
        save_enabled(enabled)
        self._send(200, "application/json", b'{"ok":true}')

    def _set_camera(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            index = int(payload["index"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeDecodeError):
            self.send_error(400)
            return
        if not 0 <= index <= MAX_CAMERA_INDEX:
            self.send_error(400)
            return
        with self.state.condition:
            self.state.camera_index = index
            self.state.camera_status = "opening"
        save_camera_index(index, camera_path=CAMERA_PATH)
        self._send(200, "application/json", b'{"ok":true}')

    def _stream_video(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last_id = -1
        try:
            while not self.state.stop:
                with self.state.condition:
                    if self.state.frame_id == last_id:
                        self.state.condition.wait(timeout=0.5)
                    frame_id = self.state.frame_id
                    frame = self.state.frame
                if frame_id == last_id or not frame:
                    continue
                last_id = frame_id
                packet = (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
                self.wfile.write(packet)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class ReaderHTTPServer(ThreadingHTTPServer):
    if os.name == "nt":
        allow_reuse_address = False

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()


def main():
    parser = argparse.ArgumentParser(description="MusicHands camera reader")
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9110)
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=9100)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    ensure_model(MODEL_PATH)
    camera_index = (
        args.camera if args.camera is not None else load_camera_index(CAMERA_PATH)
    )
    state = ReaderState(load_enabled(), camera_index)
    ReaderHandler.state = state
    server = ReaderHTTPServer((args.host, args.port), ReaderHandler)
    publisher = UdpPublisher(args.udp_host, args.udp_port)
    started = time.monotonic()
    worker = threading.Thread(
        target=reader_loop,
        args=(state, publisher, started, MODEL_PATH),
        daemon=True,
    )
    worker.start()

    url = f"http://{args.host}:{args.port}"
    print(f"Reader UI: {url}", flush=True)
    print(f"Control frames: UDP {args.udp_host}:{args.udp_port}", flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("Stopping reader", flush=True)
    finally:
        state.stop = True
        with state.condition:
            state.condition.notify_all()
        worker.join(timeout=5.0)
        server.server_close()


if __name__ == "__main__":
    main()
