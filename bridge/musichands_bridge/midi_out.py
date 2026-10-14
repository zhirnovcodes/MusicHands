"""MIDI output port creation (teVirtualMIDI) and fallback discovery (mido + python-rtmidi)."""

import sys

from musichands_bridge.driver import (
    DriverNotInstalledError,
    PortAlreadyExistsError,
    TeVirtualMidiPort,
    install_loopmidi_driver,
    is_driver_installed,
)


class MissingMidiPortError(RuntimeError):
    """Raised when the configured MIDI output port cannot be created or opened."""


def _import_mido():
    try:
        import mido
        return mido
    except ImportError as exc:
        raise RuntimeError(
            "mido and python-rtmidi are required for MIDI output. "
            "Install them with: pip install -r bridge/requirements.txt"
        ) from exc


def list_output_ports():
    mido = _import_mido()
    return list(mido.get_output_names())


def resolve_output_port_name(target_name, available_names=None):
    names = list_output_ports() if available_names is None else list(available_names)
    target = target_name.strip()
    target_lower = target.lower()

    for name in names:
        if name == target or name.lower() == target_lower:
            return name

    # Windows rtmidi appends a numeric port index (e.g., "MusicHands 1").
    for name in names:
        name_lower = name.lower()
        if name_lower.startswith(target_lower + " "):
            suffix = name[len(target):].strip()
            if suffix.isdigit():
                return name

    for name in names:
        if target_lower in name.lower():
            return name

    return None


def format_missing_port_help(target_name, available_names, reason=None):
    lines = [f"MIDI output port {target_name!r} could not be created or opened."]
    if reason:
        lines.append(f"Reason: {reason}")
    lines.extend(["", "Available MIDI output ports:"])
    if available_names:
        for name in available_names:
            lines.append(f"  - {name}")
    else:
        lines.append("  (none detected)")
    lines.extend(
        [
            "",
            "Setup instructions:",
            "  1. Run: python -m musichands_bridge --install-driver",
            "  2. In Ableton Live (Preferences -> Link, Tempo & MIDI), enable 'Track' and 'Remote' for Input: "
            f"{target_name}.",
        ]
    )
    return "\n".join(lines)


class MidiOutput:
    """Creates a virtual MIDI port via teVirtualMIDI, or opens an existing port via mido."""

    def __init__(self, target_name, auto_install_driver=True):
        self.target_name = target_name
        self.resolved_name = None
        self.backend = None
        self._virtual_port = None
        self._mido = None
        self._port = None

        if sys.platform == "win32":
            if not is_driver_installed() and auto_install_driver:
                install_loopmidi_driver()

            if is_driver_installed():
                try:
                    self._virtual_port = TeVirtualMidiPort(target_name)
                    self.resolved_name = f"{target_name} (virtual port created)"
                    self.backend = "teVirtualMIDI"
                    return
                except PortAlreadyExistsError:
                    # Port already exists (e.g. created in loopMIDI GUI); fall back to mido.
                    pass
                except DriverNotInstalledError:
                    if auto_install_driver:
                        install_loopmidi_driver()
                        self._virtual_port = TeVirtualMidiPort(target_name)
                        self.resolved_name = f"{target_name} (virtual port created)"
                        self.backend = "teVirtualMIDI"
                        return

        self._mido = _import_mido()
        available = list(self._mido.get_output_names())
        resolved = resolve_output_port_name(target_name, available)
        if resolved is None:
            raise MissingMidiPortError(format_missing_port_help(target_name, available))
        self.resolved_name = resolved
        self.backend = "mido"
        self._port = self._mido.open_output(resolved)

    def send(self, action):
        if self._virtual_port is not None:
            self._virtual_port.send_action(action)
            return
        if self._port is None:
            return
        if action.msg_type == "control_change":
            msg = self._mido.Message(
                "control_change",
                channel=action.mido_channel,
                control=action.number,
                value=action.value,
            )
        elif action.msg_type == "note_on":
            msg = self._mido.Message(
                "note_on",
                channel=action.mido_channel,
                note=action.number,
                velocity=action.value,
            )
        elif action.msg_type == "note_off":
            msg = self._mido.Message(
                "note_off",
                channel=action.mido_channel,
                note=action.number,
                velocity=0,
            )
        else:
            return
        self._port.send(msg)

    def close(self):
        if self._virtual_port is not None:
            try:
                self._virtual_port.close()
            finally:
                self._virtual_port = None
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None
