"""Camera loop, skeleton preview, and the plain reader page."""

import os

os.environ.setdefault("GLOG_minloglevel", "2")

import argparse
import json
import threading
import time
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import GestureRecognizer, GestureRecognizerOptions, RunningMode

from musichands_reader.catalog import GOOGLE_TO_ID, LABELS, parse_key
from musichands_reader.features import WRIST, ControlTracker, HandObservation, hand_span
from musichands_reader.publish import UdpPublisher

ROOT = Path(__file__).resolve().parent.parent
WEB_PATH = ROOT / "web" / "index.html"
ENABLED_PATH = ROOT / "enabled.json"
CAMERA_PATH = ROOT / "camera.json"
MAX_CAMERA_INDEX = 5
BLACK_LEVEL = 16
BLACK_SECONDS = 2.0
READ_FAILURES_BEFORE_REOPEN = 15
MODEL_PATH = ROOT / "models" / "gesture_recognizer.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


class ReaderState:
    def __init__(self, enabled, camera_index):
        self.condition = threading.Condition()
        self.stop = False
        self.enabled = set(enabled)
        self.camera_index = camera_index
        self.camera_status = "opening"
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
    ENABLED_PATH.write_text(json.dumps(keys, indent=2), encoding="utf-8")


def load_camera_index():
    try:
        return int(json.loads(CAMERA_PATH.read_text(encoding="utf-8"))["index"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0


def save_camera_index(index):
    CAMERA_PATH.write_text(json.dumps({"index": index}), encoding="utf-8")


def ensure_model():
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 0:
        return
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading gesture model to {MODEL_PATH}")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)


def format_time(started):
    elapsed = max(0.0, time.monotonic() - started)
    minutes = int(elapsed // 60)
    seconds = elapsed - minutes * 60
    return f"{minutes}:{seconds:05.2f}"


def draw_hands(frame, hands):
    height, width = frame.shape[:2]
    for landmarks in hands:
        points = []
        for landmark in landmarks:
            points.append((int(landmark.x * width), int(landmark.y * height)))
        for start, end in HAND_CONNECTIONS:
            cv2.line(frame, points[start], points[end], (0, 0, 0), 4, cv2.LINE_AA)
            cv2.line(frame, points[start], points[end], (255, 255, 255), 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(frame, point, 4, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, point, 4, (0, 0, 0), 1, cv2.LINE_AA)


def draw_black_warning(frame):
    lines = (
        "Camera returns black frames.",
        "Check Windows camera privacy settings,",
        "close apps using the camera, or pick another camera.",
    )
    for row, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (24, 40 + row * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )


def text_jpeg(message):
    image = np.full((480, 640, 3), 255, np.uint8)
    cv2.putText(
        image,
        message,
        (24, 240),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return encode_jpeg(image)


def encode_jpeg(image):
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        return b""
    return encoded.tobytes()


def observations_from_result(result):
    observations = []
    landmark_groups = result.hand_landmarks or []
    handedness = result.handedness or []
    gestures = result.gestures or []
    seen = set()
    for index, landmarks in enumerate(landmark_groups):
        if index >= len(handedness) or not handedness[index] or len(landmarks) <= 9:
            continue
        name = handedness[index][0].category_name
        if name == "Left":
            hand = "L"
        elif name == "Right":
            hand = "R"
        else:
            continue
        if hand in seen:
            continue
        seen.add(hand)
        gesture_id = None
        gesture_score = 0.0
        if index < len(gestures) and gestures[index]:
            category = gestures[index][0]
            gesture_id = GOOGLE_TO_ID.get(category.category_name)
            gesture_score = float(category.score)
        wrist = landmarks[WRIST]
        observations.append(
            HandObservation(
                hand=hand,
                wrist_x=float(wrist.x),
                wrist_y=float(wrist.y),
                span=hand_span(landmarks),
                gesture_id=gesture_id,
                gesture_score=gesture_score,
            )
        )
    return observations, landmark_groups


def open_camera(index):
    capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(index)
    if not capture.isOpened():
        capture.release()
        return None
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def is_black(frame):
    return frame is None or frame.size == 0 or int(frame.max()) < BLACK_LEVEL


def probe_camera(index):
    capture = open_camera(index)
    if capture is None:
        return None
    try:
        frame = None
        for _ in range(5):
            ok, frame = capture.read()
            if ok and not is_black(frame):
                break
        if frame is None:
            return {"index": index, "name": f"Camera {index}", "status": "no frames"}
        height, width = frame.shape[:2]
        status = "black image" if is_black(frame) else "ok"
        return {"index": index, "name": f"Camera {index} ({width}x{height})", "status": status}
    finally:
        capture.release()


def scan_cameras(state):
    with state.scan_lock:
        with state.condition:
            current = state.camera_index
            current_status = state.camera_status
        cameras = []
        for index in range(MAX_CAMERA_INDEX + 1):
            if index == current and current_status in ("ok", "black image"):
                cameras.append(
                    {"index": index, "name": f"Camera {index}", "status": current_status}
                )
                continue
            info = probe_camera(index)
            if info is not None:
                cameras.append(info)
        return cameras


def publish_frame(state, jpeg, status=None):
    with state.condition:
        if status is not None:
            state.camera_status = status
        state.frame = jpeg
        state.frame_id += 1
        state.condition.notify_all()


def camera_loop(state, publisher, started):
    ensure_model()
    options = GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=RunningMode.VIDEO,
        num_hands=2,
    )
    recognizer = GestureRecognizer.create_from_options(options)
    capture = None
    capture_index = None
    tracker = ControlTracker()
    timestamp_ms = 0
    failures = 0
    black_since = None
    try:
        while not state.stop:
            with state.condition:
                wanted = state.camera_index
            if capture is None or capture_index != wanted:
                if capture is not None:
                    capture.release()
                publish_frame(state, text_jpeg(f"Opening camera {wanted}..."), "opening")
                with state.scan_lock:
                    capture = open_camera(wanted)
                capture_index = wanted
                failures = 0
                black_since = None
                if capture is None:
                    publish_frame(state, text_jpeg(f"No camera at index {wanted}"), "missing")
                    time.sleep(1.0)
                    continue

            ok, frame = capture.read()
            if not ok:
                failures += 1
                publish_frame(state, text_jpeg(f"Camera {wanted} read failed"), "read failed")
                if failures >= READ_FAILURES_BEFORE_REOPEN:
                    capture.release()
                    capture = None
                time.sleep(0.2)
                continue
            failures = 0

            if is_black(frame):
                black_since = black_since or time.monotonic()
            else:
                black_since = None
            black = black_since is not None and time.monotonic() - black_since > BLACK_SECONDS

            frame = cv2.flip(frame, 1)
            try:
                rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                timestamp_ms = max(timestamp_ms + 1, int(time.monotonic() * 1000))
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = recognizer.recognize_for_video(mp_image, timestamp_ms)
                observations, landmark_groups = observations_from_result(result)
            except Exception as exc:
                print(f"Tracker error: {exc}")
                publish_frame(state, text_jpeg("Tracker error"))
                time.sleep(0.2)
                continue
            with state.condition:
                enabled = set(state.enabled)
            controls, events = tracker.step(observations, enabled)
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
        if capture is not None:
            capture.release()
        recognizer.close()
        publisher.close()


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
        save_camera_index(index)
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


def main():
    parser = argparse.ArgumentParser(description="MusicHands camera reader")
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9110)
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=9100)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    ensure_model()
    camera_index = args.camera if args.camera is not None else load_camera_index()
    state = ReaderState(load_enabled(), camera_index)
    ReaderHandler.state = state
    publisher = UdpPublisher(args.udp_host, args.udp_port)
    started = time.monotonic()
    worker = threading.Thread(
        target=camera_loop,
        args=(state, publisher, started),
        daemon=True,
    )
    worker.start()

    server = ThreadingHTTPServer((args.host, args.port), ReaderHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Reader UI: {url}", flush=True)
    print(f"Control frames: UDP {args.udp_host}:{args.udp_port}", flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping reader")
    finally:
        state.stop = True
        with state.condition:
            state.condition.notify_all()
        server.shutdown()
        worker.join(timeout=2)


if __name__ == "__main__":
    main()
