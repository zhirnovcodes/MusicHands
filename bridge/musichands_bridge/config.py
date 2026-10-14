"""Load and validate bridge/config.json."""

from dataclasses import dataclass
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.json"

HANDS = ("L", "R")
TRIGGER_IDS = ("closed_fist", "open_palm")
SLIDER_IDS = ("palm_x", "palm_y", "palm_z")
CONTROL_IDS = TRIGGER_IDS + SLIDER_IDS


@dataclass(frozen=True)
class NoteMapping:
    key: str
    channel: int  # 1-16
    note: int     # 0-127
    velocity: int = 127

    @property
    def type(self):
        return "note"

    @property
    def mido_channel(self):
        return self.channel - 1


@dataclass(frozen=True)
class CcMapping:
    key: str
    channel: int  # 1-16
    control: int  # 0-119
    min_val: int = 0
    max_val: int = 127

    @property
    def type(self):
        return "cc"

    @property
    def mido_channel(self):
        return self.channel - 1


@dataclass(frozen=True)
class BridgeConfig:
    udp_host: str
    udp_port: int
    midi_port: str
    release_timeout_ms: int
    mappings: dict


def parse_control_key(key):
    if not isinstance(key, str):
        return None
    hand, sep, control_id = key.partition(":")
    if sep and hand in HANDS and control_id in CONTROL_IDS:
        return hand, control_id
    return None


def _require_int_range(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
        raise ValueError(f"{name} must be an integer between {low} and {high}, got {value!r}")
    return value


def parse_mapping(key, raw):
    if parse_control_key(key) is None:
        raise ValueError(f"Unknown control key {key!r}")
    if not isinstance(raw, dict):
        raise ValueError(f"Mapping for {key} must be an object")

    msg_type = raw.get("type")
    channel = _require_int_range(raw.get("channel"), f"{key}.channel", 1, 16)

    if msg_type == "note":
        note = _require_int_range(raw.get("note"), f"{key}.note", 0, 127)
        velocity = _require_int_range(raw.get("velocity", 127), f"{key}.velocity", 1, 127)
        return NoteMapping(key=key, channel=channel, note=note, velocity=velocity)

    if msg_type == "cc":
        control = _require_int_range(raw.get("control"), f"{key}.control", 0, 119)
        min_val = _require_int_range(raw.get("min", 0), f"{key}.min", 0, 127)
        max_val = _require_int_range(raw.get("max", 127), f"{key}.max", 0, 127)
        return CcMapping(key=key, channel=channel, control=control, min_val=min_val, max_val=max_val)

    raise ValueError(f"{key}.type must be 'note' or 'cc', got {msg_type!r}")


def load_config(path=DEFAULT_CONFIG_PATH):
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")

    udp_host = str(data.get("udp_host", "127.0.0.1"))
    udp_port = _require_int_range(data.get("udp_port", 9100), "udp_port", 1, 65535)
    midi_port = str(data.get("midi_port", "MusicHands")).strip()
    if not midi_port:
        raise ValueError("midi_port must not be empty")
    release_timeout_ms = _require_int_range(
        data.get("release_timeout_ms", 500), "release_timeout_ms", 50, 60000
    )

    raw_mappings = data.get("mappings", {})
    if not isinstance(raw_mappings, dict):
        raise ValueError("mappings must be a JSON object")

    mappings = {}
    for key, raw in raw_mappings.items():
        mappings[key] = parse_mapping(key, raw)

    return BridgeConfig(
        udp_host=udp_host,
        udp_port=udp_port,
        midi_port=midi_port,
        release_timeout_ms=release_timeout_ms,
        mappings=mappings,
    )
