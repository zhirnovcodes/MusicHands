"""Camera capture, device probing, black-frame detection, and JPEG helpers."""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CAMERA_PATH = ROOT / "camera.json"
MAX_CAMERA_INDEX = 5
BLACK_LEVEL = 16
BLACK_SECONDS = 2.0
READ_FAILURES_BEFORE_REOPEN = 15
# Uncompressed 1080p from a built-in webcam overruns USB and the picture tears.
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480


def load_camera_index(camera_path=None):
    target = Path(camera_path) if camera_path is not None else CAMERA_PATH
    try:
        return int(json.loads(target.read_text(encoding="utf-8"))["index"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0


def save_camera_index(index, camera_path=None):
    target = Path(camera_path) if camera_path is not None else CAMERA_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"index": index}), encoding="utf-8")
    except OSError:
        pass


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


def open_camera(index):
    # DirectShow otherwise keeps the webcam's default mode, often uncompressed
    # 1080p. That saturates USB and the built-in camera image tears.
    # Passing properties at open time avoids restarting the DirectShow stream
    # multiple times (which causes the camera LED to blink repeatedly).
    params = [
        cv2.CAP_PROP_FOURCC,
        cv2.VideoWriter_fourcc(*"MJPG"),
        cv2.CAP_PROP_FRAME_WIDTH,
        CAPTURE_WIDTH,
        cv2.CAP_PROP_FRAME_HEIGHT,
        CAPTURE_HEIGHT,
        cv2.CAP_PROP_BUFFERSIZE,
        1,
    ]
    if os.name == "nt":
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW, params)
    else:
        capture = cv2.VideoCapture(index, cv2.CAP_ANY, params)
    if not capture.isOpened():
        capture.release()
        return None
    for _ in range(5):
        capture.read()
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


def limit_frame(frame):
    """Shrink a frame the driver refused to deliver at the requested size."""
    height, width = frame.shape[:2]
    if width <= CAPTURE_WIDTH and height <= CAPTURE_HEIGHT:
        return frame
    scale = min(CAPTURE_WIDTH / width, CAPTURE_HEIGHT / height)
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


def _camera_entry(index, status, resolution):
    label = (
        f"Camera {index} ({resolution[0]}x{resolution[1]})"
        if resolution
        else f"Camera {index}"
    )
    selected_status = "ok" if status == "opening" else status
    return {"index": index, "name": label, "status": selected_status}


def _release_capture(capture):
    if capture is None:
        return
    try:
        capture.release()
    except Exception:
        pass


def _mark_held(state, held):
    with state.condition:
        state.capture_held = held
        state.condition.notify_all()


def scan_cameras(state):
    with state.condition:
        deadline = time.monotonic() + 8.0
        while not state.initial_open_done and not state.stop:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            state.condition.wait(timeout=remaining)

    with state.scan_lock:
        with state.condition:
            current = state.camera_index
            current_status = state.camera_status
            current_res = state.camera_resolution
        cameras = []
        for index in range(MAX_CAMERA_INDEX + 1):
            if state.stop:
                break
            if index == current and current_status != "missing":
                cameras.append(_camera_entry(index, current_status, current_res))
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


def wait_stop(state, seconds):
    with state.condition:
        if not state.stop:
            state.condition.wait(timeout=seconds)


def iter_camera_frames(state):
    """Yield `(flipped_bgr_frame, is_black_warning)` while managing camera open/reopen."""
    capture = None
    capture_index = None
    failures = 0
    black_since = None
    reported = False
    try:
        while not state.stop:
            with state.condition:
                paused = state.capture_paused
                wanted = state.camera_index
            if paused:
                if capture is not None:
                    _release_capture(capture)
                    capture = None
                    capture_index = None
                _mark_held(state, False)
                with state.condition:
                    while state.capture_paused and not state.stop:
                        state.condition.wait(timeout=0.2)
                continue

            if capture is None or capture_index != wanted:
                if capture is not None:
                    _release_capture(capture)
                    capture = None
                    _mark_held(state, False)
                publish_frame(state, text_jpeg(f"Opening camera {wanted}..."), "opening")
                with state.scan_lock:
                    with state.condition:
                        paused = state.capture_paused or state.stop
                    if paused:
                        with state.condition:
                            state.initial_open_done = True
                            state.condition.notify_all()
                        continue
                    capture = open_camera(wanted)
                    capture_index = wanted
                    failures = 0
                    black_since = None
                    reported = False
                    _mark_held(state, capture is not None)
                    if capture is None:
                        with state.condition:
                            state.camera_resolution = None
                            state.initial_open_done = True
                            state.condition.notify_all()
                        publish_frame(state, text_jpeg(f"No camera at index {wanted}"), "missing")
                        wait_stop(state, 1.0)
                        continue

            ok, frame = capture.read()
            if not ok or frame is None or frame.size == 0:
                failures += 1
                if not reported:
                    with state.condition:
                        state.initial_open_done = True
                        state.condition.notify_all()
                    reported = True
                publish_frame(state, text_jpeg(f"Camera {wanted} read failed"), "read failed")
                if failures >= READ_FAILURES_BEFORE_REOPEN:
                    _release_capture(capture)
                    capture = None
                    _mark_held(state, False)
                wait_stop(state, 0.2)
                continue
            failures = 0
            frame = limit_frame(frame)
            if not reported:
                height, width = frame.shape[:2]
                with state.condition:
                    state.camera_resolution = (width, height)
                    state.camera_status = "black image" if is_black(frame) else "ok"
                    state.initial_open_done = True
                    state.condition.notify_all()
                reported = True

            if is_black(frame):
                black_since = black_since or time.monotonic()
            else:
                black_since = None
            black = black_since is not None and time.monotonic() - black_since > BLACK_SECONDS

            yield cv2.flip(frame, 1), black
    finally:
        _release_capture(capture)
        _mark_held(state, False)
