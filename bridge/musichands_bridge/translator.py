"""Translate UDP JSON control frames into deduplicated 7-bit MIDI events."""

from dataclasses import dataclass

from musichands_bridge.config import CcMapping, NoteMapping, SLIDER_IDS, TRIGGER_IDS


@dataclass(frozen=True)
class MidiAction:
    key: str
    msg_type: str  # "note_on", "note_off", or "control_change"
    channel: int   # 1-16 (human-readable)
    number: int    # note or control number (0-127)
    value: int     # velocity or CC value (0-127)

    @property
    def mido_channel(self):
        return self.channel - 1

    def format_log(self):
        if self.msg_type == "control_change":
            return f"{self.key:<14} -> Ch {self.channel:<2} CC   {self.number:<3} val {self.value}"
        if self.msg_type == "note_on":
            return f"{self.key:<14} -> Ch {self.channel:<2} Note {self.number:<3} ON  vel {self.value}"
        return f"{self.key:<14} -> Ch {self.channel:<2} Note {self.number:<3} OFF"


def scale_255_to_range(raw_value, min_val=0, max_val=127):
    clamped_in = max(0.0, min(255.0, float(raw_value)))
    scaled = min_val + (clamped_in / 255.0) * (max_val - min_val)
    return max(0, min(127, int(round(scaled))))


class MidiTranslator:
    """Stateful translator that deduplicates 7-bit MIDI values and tracks active triggers."""

    def __init__(self, mappings, solo_key=None):
        self._mappings = dict(mappings)
        self._solo_key = solo_key
        self._last_cc_value = {}
        self._active_triggers = {}

    def process_frame(self, frame):
        if not isinstance(frame, dict) or frame.get("v") != 1:
            return []
        controls = frame.get("controls")
        if not isinstance(controls, list):
            return []

        actions = []
        seen_triggers = set()

        for item in controls:
            if not isinstance(item, dict):
                continue
            hand = item.get("hand")
            control_id = item.get("id")
            kind = item.get("kind")
            raw_value = item.get("value")
            if not isinstance(hand, str) or not isinstance(control_id, str):
                continue
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                continue

            key = f"{hand}:{control_id}"
            if self._solo_key is not None and key != self._solo_key:
                continue

            mapping = self._mappings.get(key)
            if mapping is None:
                continue

            if kind == "trigger" or control_id in TRIGGER_IDS:
                seen_triggers.add(key)
                actions.extend(self._handle_trigger(key, mapping, int(raw_value) != 0))
            elif kind == "slider" or control_id in SLIDER_IDS:
                actions.extend(self._handle_slider(key, mapping, raw_value))

        # Safety: if an active trigger was omitted without a 0 release frame, release it.
        for key in list(self._active_triggers):
            if self._active_triggers.get(key) and key not in seen_triggers:
                mapping = self._mappings.get(key)
                if mapping is not None:
                    actions.extend(self._handle_trigger(key, mapping, False))

        return actions

    def release_all_triggers(self):
        actions = []
        for key, is_on in list(self._active_triggers.items()):
            if not is_on:
                continue
            mapping = self._mappings.get(key)
            if mapping is not None:
                actions.extend(self._handle_trigger(key, mapping, False))
        return actions

    def _handle_trigger(self, key, mapping, is_on):
        was_on = self._active_triggers.get(key, False)
        if is_on == was_on:
            return []
        self._active_triggers[key] = is_on

        if isinstance(mapping, NoteMapping):
            if is_on:
                return [
                    MidiAction(
                        key=key,
                        msg_type="note_on",
                        channel=mapping.channel,
                        number=mapping.note,
                        value=mapping.velocity,
                    )
                ]
            return [
                MidiAction(
                    key=key,
                    msg_type="note_off",
                    channel=mapping.channel,
                    number=mapping.note,
                    value=0,
                )
            ]

        if isinstance(mapping, CcMapping):
            cc_val = mapping.max_val if is_on else mapping.min_val
            self._last_cc_value[key] = cc_val
            return [
                MidiAction(
                    key=key,
                    msg_type="control_change",
                    channel=mapping.channel,
                    number=mapping.control,
                    value=cc_val,
                )
            ]

        return []

    def _handle_slider(self, key, mapping, raw_value):
        if isinstance(mapping, CcMapping):
            cc_val = scale_255_to_range(raw_value, mapping.min_val, mapping.max_val)
            if self._last_cc_value.get(key) == cc_val:
                return []
            self._last_cc_value[key] = cc_val
            return [
                MidiAction(
                    key=key,
                    msg_type="control_change",
                    channel=mapping.channel,
                    number=mapping.control,
                    value=cc_val,
                )
            ]

        if isinstance(mapping, NoteMapping):
            is_on = int(round(raw_value)) >= 128
            return self._handle_trigger(key, mapping, is_on)

        return []
