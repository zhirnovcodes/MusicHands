"""Restrictive rectangles for left and right hands, automatic/manual bounds, and overlay drawing."""

from dataclasses import dataclass
import json
from pathlib import Path

import cv2

from musichands_reader.catalog import HANDS

ROOT = Path(__file__).resolve().parent.parent
RECTANGLES_PATH = ROOT / "rectangles.json"

# Default margin around palm center when no hand observation has been seen yet.
DEFAULT_MARGIN = (0.10, 0.10, 0.12, 0.12)
MIN_RECT_SPAN = 0.02

# BGR colors: Red for Left hand, Blue for Right hand.
HAND_COLORS_BGR = {
    "L": (0, 0, 255),
    "R": (255, 0, 0),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class RectBounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def normalize_x(self, x: float) -> float:
        span = self.max_x - self.min_x
        if span <= 1e-6:
            return 0.5
        return _clamp01((x - self.min_x) / span)

    def normalize_y(self, y: float) -> float:
        span = self.max_y - self.min_y
        if span <= 1e-6:
            return 0.5
        # Inverted Y: top of rectangle (min_y) is 1.0, bottom (max_y) is 0.0.
        return _clamp01((self.max_y - y) / span)


@dataclass
class HandRectConfig:
    center_x: float
    center_y: float
    width: float
    height: float

    def to_dict(self) -> dict:
        return {
            "center_x": round(_clamp01(self.center_x), 4),
            "center_y": round(_clamp01(self.center_y), 4),
            "width": round(_clamp01(self.width), 4),
            "height": round(_clamp01(self.height), 4),
        }

    @classmethod
    def from_dict(cls, data: dict, default: "HandRectConfig") -> "HandRectConfig":
        if not isinstance(data, dict):
            return cls(default.center_x, default.center_y, default.width, default.height)
        try:
            cx = _clamp01(data.get("center_x", default.center_x))
            cy = _clamp01(data.get("center_y", default.center_y))
            w = _clamp01(data.get("width", default.width))
            h = _clamp01(data.get("height", default.height))
            return cls(cx, cy, w, h)
        except (TypeError, ValueError):
            return cls(default.center_x, default.center_y, default.width, default.height)


DEFAULT_CONFIGS = {
    "L": HandRectConfig(center_x=0.25, center_y=0.50, width=0.40, height=0.70),
    "R": HandRectConfig(center_x=0.75, center_y=0.50, width=0.40, height=0.70),
}


class HandRectangleManager:
    """Computes per-hand restrictive rectangles in automatic or manual mode."""

    def __init__(self, automatic: bool = True, configs: dict | None = None):
        self.automatic = bool(automatic)
        self.configs = {
            hand: HandRectConfig(
                DEFAULT_CONFIGS[hand].center_x,
                DEFAULT_CONFIGS[hand].center_y,
                DEFAULT_CONFIGS[hand].width,
                DEFAULT_CONFIGS[hand].height,
            )
            for hand in HANDS
        }
        if configs:
            for hand in HANDS:
                if hand in configs and isinstance(configs[hand], HandRectConfig):
                    self.configs[hand] = configs[hand]
        self._last_margins = {
            "L": DEFAULT_MARGIN,
            "R": DEFAULT_MARGIN,
        }

    def to_dict(self) -> dict:
        return {
            "automatic": self.automatic,
            "L": self.configs["L"].to_dict(),
            "R": self.configs["R"].to_dict(),
        }

    def update_from_dict(self, payload: dict) -> bool:
        if not isinstance(payload, dict):
            return False
        if "automatic" in payload:
            self.automatic = bool(payload["automatic"])
        for hand in HANDS:
            if hand in payload:
                if not isinstance(payload[hand], dict):
                    return False
                self.configs[hand] = HandRectConfig.from_dict(payload[hand], self.configs[hand])
        return True

    @staticmethod
    def is_hand_xy_enabled(hand: str, enabled: set) -> bool:
        return (hand, "palm_x") in enabled or (hand, "palm_y") in enabled

    def compute_rectangles(self, observations, enabled: set) -> dict[str, RectBounds]:
        """Return active RectBounds keyed by hand ('L', 'R').

        If a hand's palm_x and palm_y sliders are both locked (disabled),
        that hand has no active rectangle.
        """
        for obs in observations:
            if obs.hand in HANDS and getattr(obs, "margins", None) is not None:
                self._last_margins[obs.hand] = obs.margins

        active_hands = [hand for hand in HANDS if self.is_hand_xy_enabled(hand, enabled)]
        if not active_hands:
            return {}

        rects = {}
        both_enabled = len(active_hands) == 2

        for hand in active_hands:
            if self.automatic:
                if both_enabled:
                    zone_min_x, zone_max_x = (0.0, 0.5) if hand == "L" else (0.5, 1.0)
                else:
                    zone_min_x, zone_max_x = 0.0, 1.0
                zone_min_y, zone_max_y = 0.0, 1.0

                left_m, right_m, top_m, bottom_m = self._last_margins.get(hand, DEFAULT_MARGIN)
                min_x = zone_min_x + max(0.0, left_m)
                max_x = zone_max_x - max(0.0, right_m)
                min_y = zone_min_y + max(0.0, top_m)
                max_y = zone_max_y - max(0.0, bottom_m)

                min_x, max_x = _ensure_min_span(min_x, max_x, zone_min_x, zone_max_x)
                min_y, max_y = _ensure_min_span(min_y, max_y, zone_min_y, zone_max_y)
                rects[hand] = RectBounds(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
            else:
                cfg = self.configs[hand]
                half_w = cfg.width * 0.5
                half_h = cfg.height * 0.5
                min_x = _clamp01(cfg.center_x - half_w)
                max_x = _clamp01(cfg.center_x + half_w)
                min_y = _clamp01(cfg.center_y - half_h)
                max_y = _clamp01(cfg.center_y + half_h)
                min_x, max_x = _ensure_min_span(min_x, max_x, 0.0, 1.0)
                min_y, max_y = _ensure_min_span(min_y, max_y, 0.0, 1.0)
                rects[hand] = RectBounds(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)

        return rects


def _ensure_min_span(low: float, high: float, bound_low: float, bound_high: float) -> tuple[float, float]:
    low = max(bound_low, min(bound_high, low))
    high = max(bound_low, min(bound_high, high))
    if high - low < MIN_RECT_SPAN:
        mid = 0.5 * (low + high)
        half = 0.5 * MIN_RECT_SPAN
        low = max(bound_low, mid - half)
        high = min(bound_high, mid + half)
    return low, high


def draw_rectangles(frame, rects: dict[str, RectBounds]):
    """Draw active hand restrictive rectangles on the camera frame (Red for L, Blue for R)."""
    if not rects:
        return
    height, width = frame.shape[:2]
    for hand, bounds in rects.items():
        color = HAND_COLORS_BGR.get(hand, (0, 255, 0))
        x1 = int(round(bounds.min_x * (width - 1)))
        y1 = int(round(bounds.min_y * (height - 1)))
        x2 = int(round(bounds.max_x * (width - 1)))
        y2 = int(round(bounds.max_y * (height - 1)))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)


def load_rectangles(rectangles_path=None) -> HandRectangleManager:
    target = Path(rectangles_path) if rectangles_path is not None else RECTANGLES_PATH
    mgr = HandRectangleManager()
    if not target.exists():
        return mgr
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        mgr.update_from_dict(raw)
    except (OSError, json.JSONDecodeError):
        pass
    return mgr


def save_rectangles(mgr: HandRectangleManager, rectangles_path=None):
    target = Path(rectangles_path) if rectangles_path is not None else RECTANGLES_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(mgr.to_dict(), indent=2), encoding="utf-8")
    except OSError:
        pass
