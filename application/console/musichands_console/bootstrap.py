"""Environment and dependency bootstrapper for MusicHands Console.

Uses only the Python standard library so it can run on a fresh machine
before any third-party packages (opencv-python, mediapipe, mido, python-rtmidi)
are installed.
"""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

REQUIRED_MODULES = ("cv2", "mediapipe", "mido", "rtmidi")
PREFERRED_PYTHON_MINORS = ("3.12", "3.11", "3.10")
BOOTSTRAPPED_ENV_VAR = "MUSICHANDS_BOOTSTRAPPED"

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)


def get_console_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def get_repo_root() -> Path:
    return get_console_dir().parent.parent


def get_venv_dir(repo_root: Path | None = None) -> Path:
    root = repo_root or get_repo_root()
    return root / ".venv"


def get_venv_python(venv_dir: Path | None = None) -> Path:
    vdir = venv_dir or get_venv_dir()
    if os.name == "nt":
        return vdir / "Scripts" / "python.exe"
    return vdir / "bin" / "python"


def current_interpreter_has_modules(modules=REQUIRED_MODULES) -> bool:
    return all(importlib.util.find_spec(mod) is not None for mod in modules)


def interpreter_has_modules(python_exe: Path, modules=REQUIRED_MODULES) -> bool:
    if not python_exe.exists():
        return False
    check_code = (
        "import importlib.util, sys; "
        f"mods = {list(modules)!r}; "
        "sys.exit(0 if all(importlib.util.find_spec(m) is not None for m in mods) else 1)"
    )
    res = subprocess.run(
        [str(python_exe), "-c", check_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


def get_interpreter_version(python_exe: Path) -> tuple[int, int] | None:
    if not python_exe.exists():
        return None
    res = subprocess.run(
        [
            str(python_exe),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return None
    try:
        major_s, minor_s = res.stdout.strip().split(".", 1)
        return int(major_s), int(minor_s)
    except ValueError:
        return None


def find_compatible_base_python() -> list[str]:
    """Find a Python 3.10-3.12 interpreter if current Python is >= 3.13."""
    if (3, 10) <= sys.version_info[:2] <= (3, 12):
        return [sys.executable]

    if os.name == "nt":
        # Check Windows py launcher for 3.12, 3.11, 3.10
        py_launcher = shutil.which("py")
        if py_launcher:
            for ver in PREFERRED_PYTHON_MINORS:
                res = subprocess.run(
                    [py_launcher, f"-{ver}", "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    exe = res.stdout.strip()
                    if exe and Path(exe).exists():
                        return [exe]

        # Check standard Windows install locations
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        for ver_nodot in ("312", "311", "310"):
            ver_dot = f"3.{ver_nodot[1:]}"
            candidates = [
                Path(local_app_data) / "Programs" / "Python" / f"Python{ver_nodot}" / "python.exe",
                Path(local_app_data) / "Python" / f"pythoncore-{ver_dot}-64" / "python.exe",
                Path(prog_files) / f"Python{ver_nodot}" / "python.exe",
            ]
            for candidate in candidates:
                if candidate.exists():
                    return [str(candidate)]

    else:
        for ver in PREFERRED_PYTHON_MINORS:
            exe = shutil.which(f"python{ver}")
            if exe:
                return [exe]

    return [sys.executable]


def try_install_python312_windows() -> list[str] | None:
    """Attempt to install Python 3.12 via winget if on Windows and no wheel-compatible Python exists."""
    if os.name != "nt":
        return None
    winget = shutil.which("winget")
    if not winget:
        return None

    print(
        f"\n[Setup] Python {sys.version_info.major}.{sys.version_info.minor} does not have prebuilt "
        "wheels for MediaPipe yet. Installing Python 3.12 via winget...",
        flush=True,
    )
    res = subprocess.run(
        [
            winget,
            "install",
            "-e",
            "--id",
            "Python.Python.3.12",
            "--scope",
            "user",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    )
    if res.returncode != 0:
        return None

    found = find_compatible_base_python()
    if found and Path(found[0]).resolve() != Path(sys.executable).resolve():
        return found
    return None


def ensure_venv_and_requirements(force_install: bool = False) -> Path:
    """Ensure `.venv` exists and all console requirements are installed. Returns the venv python path."""
    repo_root = get_repo_root()
    console_dir = get_console_dir()
    requirements_path = console_dir / "requirements.txt"
    venv_dir = get_venv_dir(repo_root)
    venv_python = get_venv_python(venv_dir)

    base_cmd = find_compatible_base_python()

    # If .venv exists but was created with Python >= 3.13 while a 3.10-3.12 base is available
    # (or its base interpreter was removed), recreate it cleanly.
    if venv_python.exists():
        venv_ver = get_interpreter_version(venv_python)
        if venv_ver is None:
            print("[Setup] Existing .venv is broken; recreating...", flush=True)
            shutil.rmtree(venv_dir, ignore_errors=True)
        elif venv_ver >= (3, 13) and not interpreter_has_modules(venv_python):
            base_ver = get_interpreter_version(Path(base_cmd[0]))
            if base_ver and (3, 10) <= base_ver <= (3, 12):
                print(
                    f"[Setup] Recreating .venv with Python {base_ver[0]}.{base_ver[1]} "
                    f"(replacing Python {venv_ver[0]}.{venv_ver[1]})...",
                    flush=True,
                )
                shutil.rmtree(venv_dir, ignore_errors=True)

    if not venv_python.exists():
        print(f"[Setup] Creating virtual environment at {venv_dir}...", flush=True)
        subprocess.check_call([*base_cmd, "-m", "venv", str(venv_dir)])

    if force_install or not interpreter_has_modules(venv_python):
        print(f"[Setup] Installing dependencies from {requirements_path}...", flush=True)
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            check=False,
        )
        pip_res = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", str(requirements_path)]
        )
        if pip_res.returncode != 0:
            venv_ver = get_interpreter_version(venv_python)
            if venv_ver and venv_ver >= (3, 13):
                new_base = try_install_python312_windows()
                if new_base:
                    shutil.rmtree(venv_dir, ignore_errors=True)
                    print(f"[Setup] Creating virtual environment with {new_base[0]}...", flush=True)
                    subprocess.check_call([*new_base, "-m", "venv", str(venv_dir)])
                    subprocess.run(
                        [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
                        check=False,
                    )
                    subprocess.check_call(
                        [str(venv_python), "-m", "pip", "install", "-r", str(requirements_path)]
                    )
                    return venv_python

                print(
                    "\n[Setup Error] Failed to install dependencies on Python "
                    f"{venv_ver[0]}.{venv_ver[1]}.\n"
                    "MediaPipe currently requires Python 3.10 - 3.12 on Windows.\n"
                    "Please install Python 3.12 (for example: `winget install Python.Python.3.12` "
                    "or from https://www.python.org/downloads/) and run this command again.",
                    file=sys.stderr,
                    flush=True,
                )
            sys.exit(pip_res.returncode)

    return venv_python


def ensure_gesture_model(repo_root: Path | None = None) -> Path:
    root = repo_root or get_repo_root()
    model_path = root / "reader" / "models" / "gesture_recognizer.task"
    if model_path.exists() and model_path.stat().st_size > 0:
        return model_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[Setup] Downloading MediaPipe gesture model to {model_path}...", flush=True)
    urllib.request.urlretrieve(MODEL_URL, model_path)
    return model_path


def ensure_midi_driver(repo_root: Path | None = None) -> None:
    if os.name != "nt":
        return
    root = repo_root or get_repo_root()
    bridge_dir = str(root / "bridge")
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)
    from musichands_bridge.driver import install_loopmidi_driver, is_driver_installed

    if not is_driver_installed():
        install_loopmidi_driver()


def run_setup_only() -> int:
    """Explicit `--setup` command: create `.venv`, install packages, download model, verify driver."""
    print("=== MusicHands Console Setup ===", flush=True)
    venv_python = ensure_venv_and_requirements(force_install=True)
    model_path = ensure_gesture_model()
    ensure_midi_driver()
    print("\nSetup complete!", flush=True)
    print(f"  Python environment : {venv_python}", flush=True)
    print(f"  Gesture model      : {model_path}", flush=True)
    print("\nRun the console application with:", flush=True)
    print("  python -m musichands_console", flush=True)
    return 0


def bootstrap_if_needed(argv: list[str] | None = None) -> int | None:
    """Ensure dependencies are available, bootstrapping `.venv` and re-executing if needed.

    Returns:
        - `None` if the current interpreter is ready and execution should continue in-process.
        - `int` exit code if setup/re-execution handled the command in a child process.
    """
    if getattr(sys, "frozen", False):
        return None

    args = list(sys.argv[1:] if argv is None else argv)

    if "--setup" in args:
        return run_setup_only()

    if "--no-bootstrap" in args or current_interpreter_has_modules():
        return None

    if os.environ.get(BOOTSTRAPPED_ENV_VAR) == "1":
        # Already re-executed once; avoid infinite recursion.
        return None

    print(
        "[Setup] Missing Python dependencies in current environment; bootstrapping .venv...",
        flush=True,
    )
    venv_python = ensure_venv_and_requirements(force_install=False)

    if Path(sys.executable).resolve() == venv_python.resolve() and current_interpreter_has_modules():
        return None

    env = os.environ.copy()
    env[BOOTSTRAPPED_ENV_VAR] = "1"
    cmd = [str(venv_python), "-m", "musichands_console", *args]
    try:
        res = subprocess.run(cmd, cwd=str(get_console_dir()), env=env)
        return res.returncode
    except KeyboardInterrupt:
        return 0
