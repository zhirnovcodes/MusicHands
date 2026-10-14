"""loopMIDI / teVirtualMIDI driver installation and dynamic virtual MIDI port creation."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import struct
import tempfile
import zipfile

INSTALL_DIR = Path(__file__).resolve().parent / "loopMidi_install"

TE_VM_FLAGS_PARSE_RX = 1

ERROR_PATH_NOT_FOUND = 3
ERROR_ALREADY_EXISTS = 183
ERROR_ALIAS_EXISTS = 1379

SEE_MASK_NOCLOSEPROCESS = 0x00000040
INFINITE = 0xFFFFFFFF
SW_SHOWNORMAL = 1


class PortAlreadyExistsError(RuntimeError):
    """Raised when the virtual MIDI port name is already in use by another process."""


class DriverNotInstalledError(RuntimeError):
    """Raised when teVirtualMIDI DLL or kernel driver is not available."""


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _candidate_dll_names():
    if struct.calcsize("P") * 8 == 64:
        return ("teVirtualMIDI64.dll", "teVirtualMIDI.dll")
    return ("teVirtualMIDI32.dll", "teVirtualMIDI.dll")


def load_tevirtualmidi_dll():
    last_err = None
    for name in _candidate_dll_names():
        try:
            return ctypes.WinDLL(name, use_last_error=True)
        except OSError as exc:
            last_err = exc
    raise DriverNotInstalledError(
        "teVirtualMIDI driver DLL (teVirtualMIDI64.dll) is not installed."
    ) from last_err


def is_driver_installed():
    try:
        load_tevirtualmidi_dll()
        return True
    except DriverNotInstalledError:
        return False


def find_installer_source(install_dir=INSTALL_DIR):
    folder = Path(install_dir)
    if not folder.exists():
        return None
    for exe in sorted(folder.glob("loopMIDISetup*.exe")):
        return exe
    for archive in sorted(folder.glob("loopMIDISetup*.zip")):
        return archive
    for archive in sorted(folder.glob("*.zip")):
        return archive
    return None


def _run_elevated_and_wait(exe_path, parameters):
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = str(exe_path)
    info.lpParameters = parameters
    info.lpDirectory = str(exe_path.parent)
    info.nShow = SW_SHOWNORMAL

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        raise RuntimeError(f"Failed to launch driver installer (WinError {err}).")

    if info.hProcess:
        try:
            kernel32.WaitForSingleObject(info.hProcess, INFINITE)
            exit_code = wintypes.DWORD(0)
            if kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
                return int(exit_code.value)
        finally:
            kernel32.CloseHandle(info.hProcess)
    return 0


def install_loopmidi_driver(install_dir=INSTALL_DIR, quiet=False):
    source = find_installer_source(install_dir)
    if source is None:
        raise FileNotFoundError(
            f"No loopMIDI installer found in {install_dir}. "
            "Expected loopMIDISetup_*.zip or loopMIDISetup.exe."
        )

    mode_flag = "/quiet" if quiet else "/passive"
    params = f"/install {mode_flag} /norestart"

    with tempfile.TemporaryDirectory(prefix="musichands_loopmidi_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source, "r") as zf:
                zf.extractall(tmp_path)
            exes = list(tmp_path.rglob("*.exe"))
            if not exes:
                raise RuntimeError(f"No .exe found inside {source}")
            exe_path = exes[0]
        else:
            exe_path = source

        print(f"Installing virtual MIDI driver from {source.name}...", flush=True)
        exit_code = _run_elevated_and_wait(exe_path, params)
        if exit_code not in (0, 3010):  # 3010 = ERROR_SUCCESS_REBOOT_REQUIRED
            raise RuntimeError(f"loopMIDI installer exited with code {exit_code}")

    if not is_driver_installed():
        raise DriverNotInstalledError(
            "Installer finished, but teVirtualMIDI64.dll was Still not found in System32."
        )
    print("Virtual MIDI driver installed.", flush=True)


_CALLBACK_TYPE = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_ubyte),
    wintypes.DWORD,
    ctypes.c_size_t,
)


class TeVirtualMidiPort:
    """Dynamically creates and owns a named virtual MIDI port via teVirtualMIDI64.dll."""

    def __init__(self, port_name):
        self.port_name = port_name
        self._dll = load_tevirtualmidi_dll()
        self._handle = None

        self._dll.virtualMIDICreatePortEx2.argtypes = [
            wintypes.LPCWSTR,
            _CALLBACK_TYPE,
            ctypes.c_size_t,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._dll.virtualMIDICreatePortEx2.restype = ctypes.c_void_p

        self._dll.virtualMIDISendData.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            wintypes.DWORD,
        ]
        self._dll.virtualMIDISendData.restype = wintypes.BOOL

        self._dll.virtualMIDIShutdown.argtypes = [ctypes.c_void_p]
        self._dll.virtualMIDIShutdown.restype = wintypes.BOOL

        self._dll.virtualMIDIClosePort.argtypes = [ctypes.c_void_p]
        self._dll.virtualMIDIClosePort.restype = None

        # Keep callback reference alive for the lifetime of the port.
        self._callback = _CALLBACK_TYPE(self._on_midi_data_received)

        ctypes.set_last_error(0)
        handle = self._dll.virtualMIDICreatePortEx2(
            port_name,
            self._callback,
            0,
            65535,
            TE_VM_FLAGS_PARSE_RX,
        )
        if not handle:
            err = ctypes.get_last_error()
            if err in (ERROR_ALREADY_EXISTS, ERROR_ALIAS_EXISTS):
                raise PortAlreadyExistsError(
                    f"Virtual MIDI port {port_name!r} already exists (WinError {err})."
                )
            if err == ERROR_PATH_NOT_FOUND:
                raise DriverNotInstalledError(
                    "teVirtualMIDI kernel driver (teVirtualMIDI.sys) is not active or installed."
                )
            raise RuntimeError(
                f"virtualMIDICreatePortEx2({port_name!r}) failed with WinError {err}."
            )
        self._handle = handle

    @staticmethod
    def _on_midi_data_received(port, data_ptr, length, instance):
        # Discard any MIDI sent from the DAW into our controller port.
        return

    def send_action(self, action):
        if not self._handle:
            return
        ch = action.mido_channel & 0x0F
        if action.msg_type == "control_change":
            status = 0xB0 | ch
            data1 = action.number & 0x7F
            data2 = action.value & 0x7F
        elif action.msg_type == "note_on":
            status = 0x90 | ch
            data1 = action.number & 0x7F
            data2 = action.value & 0x7F
        elif action.msg_type == "note_off":
            status = 0x80 | ch
            data1 = action.number & 0x7F
            data2 = 0
        else:
            return

        packet = (ctypes.c_ubyte * 3)(status, data1, data2)
        self._dll.virtualMIDISendData(self._handle, packet, 3)

    def close(self):
        if self._handle:
            handle = self._handle
            self._handle = None
            try:
                self._dll.virtualMIDIShutdown(handle)
            except Exception:
                pass
            self._dll.virtualMIDIClosePort(handle)
