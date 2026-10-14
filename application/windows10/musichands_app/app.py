"""Standalone Windows 10 desktop launcher running Reader and Bridge in parallel processes."""

import _thread
import argparse
from collections import deque
import io
import multiprocessing
import os
from pathlib import Path
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request


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


def get_app_dir() -> Path:
    """Return the application directory (installed directory when frozen, or windows10/ in dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _ensure_std_streams():
    """Ensure sys.stdout and sys.stderr are valid streams when running with --noconsole."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    fallback = io.StringIO()
    if getattr(sys, "frozen", False):
        try:
            log_path = get_app_dir() / "musichands.log"
            fallback = open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    if sys.stdout is None:
        sys.stdout = fallback
    if sys.stderr is None:
        sys.stderr = fallback


def get_shell_html_path() -> Path:
    app_dir = get_app_dir()
    if getattr(sys, "frozen", False):
        return app_dir / "app_web" / "index.html"
    return app_dir / "web" / "index.html"


def resolve_bridge_config_path(custom_config=None) -> Path:
    if custom_config:
        return Path(custom_config).resolve()
    if getattr(sys, "frozen", False):
        return get_app_dir() / "config.json"
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / "bridge" / "config.json"


class QueueStdout:
    """Captures line-buffered stdout/stderr from the bridge process into a multiprocessing.Queue."""

    def __init__(self, log_queue, started):
        self.log_queue = log_queue
        self.started = started
        self._buf = ""

    def _format_time(self):
        elapsed = max(0.0, time.monotonic() - started_or_zero(self.started))
        minutes = int(elapsed // 60)
        seconds = elapsed - minutes * 60
        return f"{minutes}:{seconds:05.2f}"

    def write(self, text):
        if not text:
            return 0
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            cleaned = line.strip()
            if cleaned:
                try:
                    self.log_queue.put_nowait({"time": self._format_time(), "text": cleaned})
                except Exception:
                    pass
        return len(text)

    def flush(self):
        pass


def started_or_zero(started):
    return started if started is not None else 0.0


def _watch_stop_event(stop_event, parent_pid):
    while not stop_event.wait(timeout=0.5):
        # Also stop if the parent GUI process exited unexpectedly
        if parent_pid and os.getppid() != parent_pid:
            break
    _thread.interrupt_main()
    time.sleep(1.5)
    os._exit(0)


def run_bridge_worker(log_queue, stop_event, config_path, solo_key=None, parent_pid=None):
    """Target function for the parallel Bridge OS process."""
    _ensure_repo_packages_on_path()
    log_queue.cancel_join_thread()
    started = time.monotonic()
    tap = QueueStdout(log_queue, started)
    sys.stdout = tap
    sys.stderr = tap

    watcher = threading.Thread(
        target=_watch_stop_event, args=(stop_event, parent_pid), daemon=True
    )
    watcher.start()

    from musichands_bridge.app import main as bridge_main

    argv = ["--config", str(config_path)]
    if solo_key:
        argv.extend(["--solo", solo_key])
    try:
        bridge_main(argv)
    except KeyboardInterrupt:
        pass


def run_reader_worker(
    stop_event,
    host="127.0.0.1",
    port=9110,
    udp_host="127.0.0.1",
    udp_port=9100,
    camera=None,
    parent_pid=None,
):
    """Target function for the parallel Reader OS process."""
    _ensure_repo_packages_on_path()
    _ensure_std_streams()

    watcher = threading.Thread(
        target=_watch_stop_event, args=(stop_event, parent_pid), daemon=True
    )
    watcher.start()

    from musichands_reader import app as reader_app

    if getattr(sys, "frozen", False):
        app_dir = get_app_dir()
        reader_app.WEB_PATH = app_dir / "web" / "index.html"
        reader_app.MODEL_PATH = app_dir / "models" / "gesture_recognizer.task"
        reader_app.ENABLED_PATH = app_dir / "enabled.json"
        reader_app.CAMERA_PATH = app_dir / "camera.json"

    argv = [
        "musichands_reader",
        "--host",
        str(host),
        "--port",
        str(port),
        "--udp-host",
        str(udp_host),
        "--udp-port",
        str(udp_port),
        "--no-browser",
    ]
    if camera is not None:
        argv.extend(["--camera", str(camera)])

    sys.argv = argv
    try:
        reader_app.main()
    except KeyboardInterrupt:
        pass


class BridgeLogApi:
    """Exposed to the pywebview shell page as window.pywebview.api."""

    def __init__(self, log_queue):
        self._queue = log_queue
        self._logs = deque(maxlen=200)
        self._seq = 0
        self._lock = threading.Lock()

    def get_midi_logs(self, after=0):
        with self._lock:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break
                self._seq += 1
                item["n"] = self._seq
                self._logs.append(item)
            try:
                after_num = int(after)
            except (TypeError, ValueError):
                after_num = 0
            return [entry for entry in self._logs if entry["n"] > after_num]


def wait_for_reader(url, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def build_parser():
    parser = argparse.ArgumentParser(description="MusicHands Windows 10 standalone application")
    parser.add_argument("--config", default=None, help="Path to bridge config.json")
    parser.add_argument("--camera", type=int, default=None, help="Override camera index")
    parser.add_argument("--reader-host", default="127.0.0.1", help="Reader HTTP host (default: 127.0.0.1)")
    parser.add_argument("--reader-port", type=int, default=9110, help="Reader HTTP port (default: 9110)")
    parser.add_argument("--solo", default=None, help="Solo a single control key in the MIDI bridge (e.g. R:palm_y)")
    return parser


def main(argv=None):
    multiprocessing.freeze_support()
    _ensure_std_streams()

    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = resolve_bridge_config_path(args.config)
    from musichands_bridge.config import load_config

    bridge_cfg = load_config(config_path)

    log_queue = multiprocessing.Queue()
    log_queue.cancel_join_thread()
    stop_event = multiprocessing.Event()
    parent_pid = os.getpid()

    bridge_proc = multiprocessing.Process(
        target=run_bridge_worker,
        args=(log_queue, stop_event, str(config_path), args.solo, parent_pid),
        name="MusicHands-Bridge",
        daemon=True,
    )
    reader_proc = multiprocessing.Process(
        target=run_reader_worker,
        args=(
            stop_event,
            args.reader_host,
            args.reader_port,
            bridge_cfg.udp_host,
            bridge_cfg.udp_port,
            args.camera,
            parent_pid,
        ),
        name="MusicHands-Reader",
        daemon=True,
    )

    bridge_proc.start()
    reader_proc.start()

    reader_base_url = f"http://{args.reader_host}:{args.reader_port}"
    wait_for_reader(f"{reader_base_url}/api/enabled", timeout=30.0)

    shell_html = get_shell_html_path().read_text(encoding="utf-8")
    shell_html = shell_html.replace("http://127.0.0.1:9110", reader_base_url)

    import webview

    api = BridgeLogApi(log_queue)
    webview.create_window(
        "MusicHands",
        html=shell_html,
        js_api=api,
        width=1280,
        height=760,
        min_size=(900, 520),
    )

    try:
        webview.start()
    finally:
        stop_event.set()
        for proc in (reader_proc, bridge_proc):
            proc.join(timeout=2.5)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1.0)
        try:
            log_queue.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
