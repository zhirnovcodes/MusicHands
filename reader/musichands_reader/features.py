"""Landmark and gesture values for the frozen catalog."""

import math
from dataclasses import dataclass

from musichands_reader.catalog import (
    CONTROL_IDS,
    HANDS,
    KIND,
    SLIDER_IDS,
    TRIGGER_IDS,
    sort_key,
)

# Wrist-to-middle-knuckle length in the image, as a fraction of the frame.
# Larger means the hand is closer. This is not the model's wrist-relative z.
PALM_Z_FAR = 0.08
PALM_Z_NEAR = 0.28

GESTURE_ON = 0.65
GESTURE_OFF = 0.45
SMOOTHING = 0.45

WRIST = 0
MIDDLE_MCP = 9


@dataclass
class HandObservation:
    hand: str
    wrist_x: float
    wrist_y: float
    span: float
    gesture_id: str | None
    gesture_score: float


def span_to_z(span):
    if PALM_Z_NEAR == PALM_Z_FAR:
        return 0.0
    amount = (span - PALM_Z_FAR) / (PALM_Z_NEAR - PALM_Z_FAR)
    return max(0.0, min(255.0, amount * 255.0))


class ControlTracker:
    """Smooths sliders, holds triggers, and builds one output frame."""

    def __init__(self):
        self._smooth = {}
        self._trigger_on = {}
        self._logged_slider = {}
        self._logged_trigger = {}
        self._on_wire = {}

    def step(self, observations, enabled):
        by_hand = {}
        for observation in observations:
            if observation.hand in HANDS and observation.hand not in by_hand:
                by_hand[observation.hand] = observation

        measured = {}
        trigger_edges = {}
        slider_changes = {}

        for hand in HANDS:
            observation = by_hand.get(hand)
            if observation is None:
                for control_id in TRIGGER_IDS:
                    key = (hand, control_id)
                    was_on = self._trigger_on.get(key, False)
                    self._trigger_on[key] = False
                    if was_on:
                        trigger_edges[key] = 0
                for control_id in SLIDER_IDS:
                    self._smooth.pop((hand, control_id), None)
                    self._logged_slider.pop((hand, control_id), None)
                continue

            slider_targets = {
                "palm_x": observation.wrist_x * 255.0,
                "palm_y": (1.0 - observation.wrist_y) * 255.0,
                "palm_z": span_to_z(observation.span),
            }
            for control_id in SLIDER_IDS:
                key = (hand, control_id)
                value, changed = self._update_slider(key, slider_targets[control_id])
                measured[key] = value
                if changed:
                    slider_changes[key] = value

            for control_id in TRIGGER_IDS:
                key = (hand, control_id)
                score = (
                    observation.gesture_score
                    if observation.gesture_id == control_id
                    else 0.0
                )
                value, changed = self._update_trigger(key, score)
                measured[key] = value
                if changed:
                    trigger_edges[key] = value

        active = {}
        for key, value in measured.items():
            if key not in enabled:
                continue
            kind = KIND[key[1]]
            if kind == "trigger" and value == 0:
                continue
            active[key] = value

        releases = []
        for key, previous in self._on_wire.items():
            if key not in active and previous != 0:
                releases.append(key)
        self._on_wire = dict(active)

        ordered = sorted(list(active) + releases, key=lambda item: sort_key(*item))
        controls = []
        for key in ordered:
            hand, control_id = key
            controls.append(
                {
                    "id": control_id,
                    "hand": hand,
                    "kind": KIND[control_id],
                    "value": active.get(key, 0),
                }
            )

        events = []
        for hand in HANDS:
            for control_id in CONTROL_IDS:
                key = (hand, control_id)
                if key not in enabled:
                    self._logged_trigger.pop(key, None)
                    self._logged_slider.pop(key, None)
                    continue
                if control_id in TRIGGER_IDS:
                    events.extend(self._trigger_event(key, measured, trigger_edges))
                elif key in slider_changes and key in measured:
                    previous = self._logged_slider.get(key)
                    value = slider_changes[key]
                    if previous != value:
                        self._logged_slider[key] = value
                        events.append(
                            {"hand": hand, "id": control_id, "kind": "slider", "value": value}
                        )
        return controls, events

    def _trigger_event(self, key, measured, trigger_edges):
        hand, control_id = key
        if key in measured:
            current = measured[key]
        elif key in trigger_edges:
            current = trigger_edges[key]
        else:
            current = 0 if self._logged_trigger.get(key) else None
        if current is None:
            return []
        previous = self._logged_trigger.get(key)
        if previous is None:
            self._logged_trigger[key] = current
            if current == 0:
                return []
            edge = "0 → 1"
        elif previous == current:
            return []
        else:
            self._logged_trigger[key] = current
            edge = "0 → 1" if current == 1 else "1 → 0"
        return [{"hand": hand, "id": control_id, "kind": "trigger", "edge": edge}]

    def _update_slider(self, key, target):
        previous = self._smooth.get(key, target)
        smoothed = previous + SMOOTHING * (target - previous)
        self._smooth[key] = smoothed
        value = int(round(max(0.0, min(255.0, smoothed))))
        changed = self._logged_slider.get(key) != value
        return value, changed

    def _update_trigger(self, key, score):
        was_on = self._trigger_on.get(key, False)
        is_on = was_on
        if not was_on and score >= GESTURE_ON:
            is_on = True
        elif was_on and score < GESTURE_OFF:
            is_on = False
        self._trigger_on[key] = is_on
        value = 1 if is_on else 0
        return value, is_on != was_on


def hand_span(landmarks):
    wrist = landmarks[WRIST]
    middle = landmarks[MIDDLE_MCP]
    return math.hypot(middle.x - wrist.x, middle.y - wrist.y)
