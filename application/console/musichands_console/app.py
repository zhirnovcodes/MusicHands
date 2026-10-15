"""Console launcher running Reader and Bridge on parallel threads in a single console instance."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\MusicHandsConsoleSingleInstance"


def _ensure_repo_packages_on_path():
    if getattr(sys, "frozen", False):
        return
    app_root = Path(__file__).resolve().parent.parent
    repo_root = app_root.parent.parent
    for sub in ("reader", "bridge"):
        pkg_dir = str(repo_root / sub)
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)


_ensure_repo_packages_on_path()


def acquire_single_instance_lock():
    """Ensure only one console instance can run at a time."""
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle or kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)
            return None
        return handle

    # Fallback lock socket for non-Windows platforms
    lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_sock.bind(("127.0.0.1", 9119))
        return lock_sock
    except OSError:
        lock_sock.close()
        return None


def release_single_instance_lock(lock_handle):
    if lock_handle is None:
        return
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.CloseHandle(lock_handle)
        except Exception:
            pass
    elif hasattr(lock_handle, "close"):
        try:
            lock_handle.close()
        except Exception:
            pass


def resolve_bridge_config_path(custom_config=None) -> Path:
    if custom_config:
        return Path(custom_config).resolve()
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / "bridge" / "config.json"


def run_bridge_thread(stop_event, config, midi_out, solo_key=None, quiet=False, verbose=False):
    """Run the UDP-to-MIDI bridge loop on a background thread."""
    from musichands_bridge.app import emit_actions
    from musichands_bridge.translator import MidiTranslator

    translator = MidiTranslator(config.mappings, solo_key=solo_key)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((config.udp_host, config.udp_port))
    timeout_s = min(0.1, max(0.05, config.release_timeout_ms / 1000.0))
    sock.settimeout(timeout_s)

    if verbose and not quiet:
        print(f"MIDI output: {midi_out.resolved_name}", flush=True)
        print(f"Listening on UDP {config.udp_host}:{config.udp_port}", flush=True)
        if solo_key:
            print(f"Solo filter: {solo_key} only", flush=True)

    last_packet_time = time.monotonic()
    release_timeout_s = max(0.05, config.release_timeout_ms / 1000.0)

    try:
        while not stop_event.is_set():
            try:
                payload, _ = sock.recvfrom(8192)
                last_packet_time = time.monotonic()
            except socket.timeout:
                if time.monotonic() - last_packet_time >= release_timeout_s:
                    released = translator.release_all_triggers()
                    emit_actions(released, midi_out, quiet)
                continue
            except OSError:
                break

            try:
                frame = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            actions = translator.process_frame(frame)
            emit_actions(actions, midi_out, quiet)
    finally:
        released = translator.release_all_triggers()
        emit_actions(released, midi_out, quiet)
        sock.close()
        midi_out.close()


def run_reader_thread(
    stop_event,
    host="127.0.0.1",
    port=9110,
    udp_host="127.0.0.1",
    udp_port=9100,
    camera=None,
    no_browser=False,
    verbose=False,
):
    """Run the Reader HTTP server and camera capture loop on background threads."""
    from musichands_reader import app as reader_app
    from musichands_reader.camera import CAMERA_PATH, load_camera_index
    from musichands_reader.hand_tracker import MODEL_PATH, ensure_model
    from musichands_reader.publish import UdpPublisher

    ensure_model(MODEL_PATH)
    camera_index = camera if camera is not None else load_camera_index(CAMERA_PATH)
    state = reader_app.ReaderState(reader_app.load_enabled(), camera_index)
    reader_app.ReaderHandler.state = state
    server = reader_app.ReaderHTTPServer((host, port), reader_app.ReaderHandler)
    publisher = UdpPublisher(udp_host, udp_port)
    started = time.monotonic()

    capture_worker = threading.Thread(
        target=reader_app.reader_loop,
        args=(state, publisher, started, MODEL_PATH),
        name="MusicHands-ReaderCapture",
        daemon=True,
    )
    capture_worker.start()

    url = f"http://{host}:{port}"
    if verbose:
        print(f"Reader UI: {url}", flush=True)
        print(f"Control frames: UDP {udp_host}:{udp_port}", flush=True)

    if not no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    watcher = threading.Thread(
        target=lambda: (stop_event.wait(), server.shutdown()),
        name="MusicHands-ReaderShutdown",
        daemon=True,
    )
    watcher.start()

    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        state.stop = True
        with state.condition:
            state.condition.notify_all()
        capture_worker.join(timeout=5.0)
        server.server_close()


def build_parser():
    parser = argparse.ArgumentParser(
        description="MusicHands single-console launcher (Reader + Bridge on parallel threads)"
    )
    parser.add_argument("--config", default=None, help="Path to bridge config.json")
    parser.add_argument("--camera", type=int, default=None, help="Override camera index")
    parser.add_argument("--reader-host", default="127.0.0.1", help="Reader HTTP host (default: 127.0.0.1)")
    parser.add_argument("--reader-port", type=int, default=9110, help="Reader HTTP port (default: 9110)")
    parser.add_argument("--solo", default=None, help="Solo a single control key in the MIDI bridge (e.g. R:palm_y)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the Reader UI in a browser")
    parser.add_argument("--quiet", action="store_true", help="Suppress MIDI message logging")
    parser.add_argument("--verbose", action="store_true", help="Also log startup/status messages")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        if args.verbose:
            print("MusicHands console is already running.", file=sys.stderr)
        return 1

    try:
        from musichands_bridge.config import load_config, parse_control_key
        from musichands_bridge.midi_out import MidiOutput, MissingMidiPortError

        if args.solo is not None and parse_control_key(args.solo) is None:
            print(f"Invalid --solo key {args.solo!r}. Expected <L|R>:<control_id>.", file=sys.stderr)
            return 2

        config_path = resolve_bridge_config_path(args.config)
        try:
            bridge_cfg = load_config(config_path)
        except Exception as exc:
            print(f"Configuration error ({config_path}): {exc}", file=sys.stderr)
            return 2

        try:
            midi_out = MidiOutput(bridge_cfg.midi_port, auto_install_driver=True)
        except (MissingMidiPortError, RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

        stop_event = threading.Event()

        bridge_thread = threading.Thread(
            target=run_bridge_thread,
            args=(stop_event, bridge_cfg, midi_out, args.solo, args.quiet, args.verbose),
            name="MusicHands-Bridge",
            daemon=True,
        )
        reader_thread = threading.Thread(
            target=run_reader_thread,
            args=(
                stop_event,
                args.reader_host,
                args.reader_port,
                bridge_cfg.udp_host,
                bridge_cfg.udp_port,
                args.camera,
                args.no_browser,
                args.verbose,
            ),
            name="MusicHands-Reader",
            daemon=True,
        )

        bridge_thread.start()
        reader_thread.start()

        try:
            while bridge_thread.is_alive() and reader_thread.is_alive():
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            bridge_thread.join(timeout=3.0)
            reader_thread.join(timeout=5.0)
    finally:
        release_single_instance_lock(instance_lock)

    return 0


if __name__ == "__main__":
    sys.exit(main())
