"""MediaPipe hand landmark detection, gesture recognition, and skeleton overlay."""

import os

os.environ.setdefault("GLOG_minloglevel", "2")

import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import (
    GestureRecognizer,
    GestureRecognizerOptions,
    RunningMode,
)

from musichands_reader.catalog import GOOGLE_TO_ID
from musichands_reader.features import (
    ControlTracker,
    HandObservation,
    hand_span,
    palm_center,
    palm_margins,
)
from musichands_reader.hand_rectangles import HAND_COLORS_BGR

ROOT = Path(__file__).resolve().parent.parent
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


def ensure_model(model_path=None):
    target = Path(model_path) if model_path is not None else MODEL_PATH
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading gesture model to {target}")
    urllib.request.urlretrieve(MODEL_URL, target)
    return target


def draw_hands(frame, hands):
    height, width = frame.shape[:2]
    for item in hands:
        if isinstance(item, tuple) and len(item) == 2:
            hand, landmarks = item
        else:
            hand, landmarks = None, item
        points = []
        for landmark in landmarks:
            points.append((int(landmark.x * width), int(landmark.y * height)))
        for start, end in HAND_CONNECTIONS:
            cv2.line(frame, points[start], points[end], (0, 0, 0), 4, cv2.LINE_AA)
            cv2.line(frame, points[start], points[end], (255, 255, 255), 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(frame, point, 4, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, point, 4, (0, 0, 0), 1, cv2.LINE_AA)
        if len(landmarks) > 17:
            px, py = palm_center(landmarks)
            center_pt = (int(px * width), int(py * height))
            dot_color = HAND_COLORS_BGR.get(hand, (0, 0, 255))
            cv2.circle(frame, center_pt, 6, dot_color, -1, cv2.LINE_AA)
            cv2.circle(frame, center_pt, 6, (0, 0, 0), 1, cv2.LINE_AA)


def observations_from_result(result):
    observations = []
    hand_landmarks = []
    landmark_groups = result.hand_landmarks or []
    handedness = result.handedness or []
    gestures = result.gestures or []
    seen = set()
    for index, landmarks in enumerate(landmark_groups):
        if index >= len(handedness) or not handedness[index] or len(landmarks) <= 17:
            continue
        # Frames are horizontally mirrored (cv2.flip) before tracking, which
        # inverts MediaPipe's non-mirrored handedness classification.
        name = handedness[index][0].category_name
        if name == "Left":
            hand = "R"
        elif name == "Right":
            hand = "L"
        else:
            continue
        if hand in seen:
            continue
        seen.add(hand)
        hand_landmarks.append((hand, landmarks))
        gesture_id = None
        gesture_score = 0.0
        if index < len(gestures) and gestures[index]:
            category = gestures[index][0]
            gesture_id = GOOGLE_TO_ID.get(category.category_name)
            gesture_score = float(category.score)
        px, py = palm_center(landmarks)
        margins = palm_margins(landmarks, px, py)
        observations.append(
            HandObservation(
                hand=hand,
                palm_x=px,
                palm_y=py,
                span=hand_span(landmarks),
                gesture_id=gesture_id,
                gesture_score=gesture_score,
                margins=margins,
            )
        )
    return observations, hand_landmarks


class HandTracker:
    """Runs MediaPipe video gesture recognition and tracks control state."""

    def __init__(self, model_path=None):
        resolved_model = ensure_model(model_path)
        options = GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(resolved_model)),
            running_mode=RunningMode.VIDEO,
            num_hands=2,
        )
        self._recognizer = GestureRecognizer.create_from_options(options)
        self._controls = ControlTracker()
        self._timestamp_ms = 0

    def process_frame(self, bgr_frame, enabled, rect_manager=None):
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB))
        self._timestamp_ms = max(self._timestamp_ms + 1, int(time.monotonic() * 1000))
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._recognizer.recognize_for_video(mp_image, self._timestamp_ms)
        observations, landmark_groups = observations_from_result(result)
        active_rects = (
            rect_manager.compute_rectangles(observations, enabled)
            if rect_manager is not None
            else {}
        )
        controls, events = self._controls.step(observations, enabled, active_rects)
        return controls, events, landmark_groups, active_rects

    def close(self):
        self._recognizer.close()
