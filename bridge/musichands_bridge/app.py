"""CLI entry point and UDP receive loop for the MusicHands MIDI bridge."""

import argparse
import json
import socket
import sys
import time

from musichands_bridge.config import DEFAULT_CONFIG_PATH, load_config, parse_control_key
from musichands_bridge.midi_out import MissingMidiPortError, MidiOutput, list_output_ports
from musichands_bridge.translator import MidiTranslator


def build_parser():
    parser = argparse.ArgumentParser(description="MusicHands UDP-to-MIDI bridge")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to bridge config JSON (default: bridge/config.json)",
    )
    parser.add_argument("--udp-host", default=None, help="Override UDP bind host")
    parser.add_argument("--udp-port", type=int, default=None, help="Override UDP bind port")
    parser.add_argument("--midi-port", default=None, help="Override target MIDI output port name")
    parser.add_argument(
        "--solo",
        default=None,
        help="Only forward one control key (e.g. R:palm_y) for easy DAW MIDI Learn",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Translate and log MIDI events without opening a MIDI output port",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List available MIDI output ports and exit",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-message terminal logging",
    )
    return parser


def emit_actions(actions, midi_out, quiet):
    for action in actions:
        midi_out.send(action)
        if not quiet:
            print(action.format_log(), flush=True)


def run_bridge(config, midi_out, solo_key=None, quiet=False):
    translator = MidiTranslator(config.mappings, solo_key=solo_key)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((config.udp_host, config.udp_port))
    timeout_s = max(0.05, config.release_timeout_ms / 1000.0)
    sock.settimeout(timeout_s)

    port_label = "(dry-run)" if midi_out.dry_run else midi_out.resolved_name
    print(f"Listening on UDP {config.udp_host}:{config.udp_port}", flush=True)
    print(f"MIDI output: {port_label}", flush=True)
    if solo_key:
        print(f"Solo filter: {solo_key} only", flush=True)

    try:
        while True:
            try:
                payload, _ = sock.recvfrom(8192)
            except socket.timeout:
                released = translator.release_all_triggers()
                emit_actions(released, midi_out, quiet)
                continue

            try:
                frame = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            actions = translator.process_frame(frame)
            emit_actions(actions, midi_out, quiet)
    except KeyboardInterrupt:
        print("\nStopping bridge", flush=True)
    finally:
        released = translator.release_all_triggers()
        emit_actions(released, midi_out, quiet)
        sock.close()
        midi_out.close()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_ports:
        try:
            ports = list_output_ports()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if not ports:
            print("No MIDI output ports detected.")
        else:
            print("Available MIDI output ports:")
            for name in ports:
                print(f"  - {name}")
        return 0

    if args.solo is not None and parse_control_key(args.solo) is None:
        print(f"Invalid --solo key {args.solo!r}. Expected <L|R>:<control_id>.", file=sys.stderr)
        return 2

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Configuration error ({args.config}): {exc}", file=sys.stderr)
        return 2

    udp_host = args.udp_host if args.udp_host is not None else config.udp_host
    udp_port = args.udp_port if args.udp_port is not None else config.udp_port
    midi_port = args.midi_port if args.midi_port is not None else config.midi_port
    config = type(config)(
        udp_host=udp_host,
        udp_port=udp_port,
        midi_port=midi_port,
        release_timeout_ms=config.release_timeout_ms,
        mappings=config.mappings,
    )

    try:
        midi_out = MidiOutput(config.midi_port, dry_run=args.dry_run)
    except (MissingMidiPortError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    run_bridge(config, midi_out, solo_key=args.solo, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
