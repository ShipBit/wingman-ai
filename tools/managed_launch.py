"""Hidden, single-instance launcher for this private Core and the installed GUI."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.printr import Printr
from services.elite_runtime_identity import compare, expected_files, process_started
from services.file import get_writable_dir

# pythonw has no console streams. Printr still writes its normal log file.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

PORT = 49111
CLIENT = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WingmanAI" / "WingmanAI.exe"
PYTHON = ROOT / ".venv-core" / "Scripts" / "python.exe"
STATE = ROOT / ".elite-local" / "managed-launch"


def powershell(script):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Unable to inspect the Core process: " + result.stderr[:300])
    return json.loads(result.stdout) if result.stdout.strip() else None


def port_owner():
    return powershell("$ErrorActionPreference='Stop'; $listener = Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 49111 | Select-Object -First 1; if ($listener) { Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener.OwningProcess) | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress }; exit 0")


def owns_core(owner, root=ROOT, python=PYTHON):
    if not owner or not owner.get("CommandLine"):
        return False
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    pointer = shell32.CommandLineToArgvW(owner["CommandLine"], ctypes.byref(count))
    if not pointer:
        return False
    try:
        arguments = [pointer[index] for index in range(count.value)]
    finally:
        kernel32.LocalFree(pointer)
    # Windows venv launchers redirect into their base interpreter. Accept that
    # exact interpreter from this venv's configuration, plus the absolute script.
    allowed = {os.path.normcase(str(python.resolve()))}
    config = root / ".venv-core" / "pyvenv.cfg"
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "executable":
                allowed.add(os.path.normcase(str(Path(value.strip()).resolve())))
    if len(arguments) < 2 or os.path.normcase(str(Path(arguments[0]).resolve())) not in allowed:
        return False
    script_index = 2 if arguments[1] == "-u" else 1
    return (len(arguments) > script_index and Path(arguments[script_index]).is_absolute()
            and os.path.normcase(str(Path(arguments[script_index]).resolve())) == os.path.normcase(str((root / "main.py").resolve())))


def ready():
    try:
        with urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=2) as response:
            result = json.load(response)
        return result.get("state") == "ready" or result.get("is_started") is True
    except (OSError, ValueError):
        return False


def inspect():
    owner = port_owner()
    return {"client_exists": CLIENT.is_file(), "python_exists": PYTHON.is_file(),
            "port_occupied": owner is not None, "matching_core": owns_core(owner),
            "ready": ready() if owns_core(owner) else False,
            "deployment_issues": deployment_issues(owner)}


def deployment_issues(owner):
    if not owner:
        return ["core_not_running"]
    if not owns_core(owner):
        return ["packaged_or_other_core"]
    try:
        record = json.loads((Path(get_writable_dir()) / "elite-runtime.json").read_text(encoding="utf-8"))
        return compare(record, expected_files(), pid=owner["ProcessId"],
                       process_started=process_started(owner["ProcessId"]),
                       config_root=Path(get_writable_dir()) / "configs")
    except (OSError, ValueError, KeyError):
        return ["runtime_identity_unavailable"]


def open_client():
    processes = powershell("Get-Process -Name WingmanAI -ErrorAction SilentlyContinue | Select-Object Id,Path,MainWindowHandle | ConvertTo-Json -Compress; exit 0") or []
    if isinstance(processes, dict):
        processes = [processes]
    existing = [p for p in processes if p.get("Path") and Path(p["Path"]).resolve() == CLIENT.resolve()]
    if existing:
        window = next((p.get("MainWindowHandle") for p in existing if p.get("MainWindowHandle")), None)
        if window:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            user32.ShowWindow(window, 9)
            user32.SetForegroundWindow(window)
        return False
    subprocess.Popen([str(CLIENT)], cwd=CLIENT.parent)
    return True


def launch(connect_only=False):
    if not CLIENT.is_file() or not PYTHON.is_file():
        raise RuntimeError("Wingman client or .venv-core is missing. Restore the installation before launching.")
    owner = port_owner()
    if owner and not owns_core(owner):
        raise RuntimeError("Another Core already occupies port 49111. Close Wingman and its old Core, then open Wingman again. No process was stopped.")
    child = None
    if not owner:
        if connect_only:
            raise RuntimeError("No running managed Core is available to connect to.")
        STATE.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        active = ROOT / ".elite-local/acceptance/active.json"
        if active.is_file():
            session = json.loads(active.read_text(encoding="utf-8"))
            trial_dir = (ROOT / ".elite-local/acceptance" / session["session"] / "events").resolve()
            if not trial_dir.is_relative_to((ROOT / ".elite-local/acceptance").resolve()):
                raise RuntimeError("Invalid private acceptance directory")
            environment["WINGMAN_ELITE_ACCEPTANCE_DIR"] = str(trial_dir)
        with (STATE / "core-startup.log").open("ab") as log:
            child = subprocess.Popen([str(PYTHON), str(ROOT / "main.py"), "--host", "127.0.0.1",
                                      "--port", str(PORT), "--sidecar"], cwd=ROOT,
                                     stdout=log, stderr=log, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 180
    while not ready():
        if child and child.poll() is not None:
            raise RuntimeError("Core exited during startup. See .elite-local/managed-launch/core-startup.log.")
        if time.monotonic() >= deadline:
            raise RuntimeError("Core is still starting. No second Core was started. Check its startup log, then open Wingman again.")
        time.sleep(0.5)
    if not owns_core(port_owner()):
        raise RuntimeError("Core process ownership changed during launch. The client was not opened.")
    # Wingman's GUI is the user's visible application; only the helper/Core are hidden.
    open_client()
    # Check that opening the installed client has not displaced the selected Core.
    time.sleep(3)
    if not owns_core(port_owner()):
        raise RuntimeError("The installed client did not retain the managed Core connection. Check Wingman's connection settings.")
    return {"started_core": child is not None, "matching_core": True, "ready": True,
            "deployment_issues": deployment_issues(port_owner()), "gameplay_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Read-only inspection; does not launch anything")
    parser.add_argument("--connect-only", action="store_true", help="Open the GUI only if this Core is already running")
    args = parser.parse_args()
    if args.check:
        Printr().print(json.dumps(inspect()), server_only=True)
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel32.CreateMutexW(None, True, "Local\\WingmanManagedLauncher49111")
    if not mutex:
        raise OSError("Cannot acquire Wingman launch lock")
    try:
        if ctypes.get_last_error() == 183:
            return
        result = launch(connect_only=args.connect_only)
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "last-launch.json").write_text(json.dumps(result), encoding="utf-8")
    except Exception as exc:
        Printr().print(str(exc), server_only=True)
        ctypes.windll.user32.MessageBoxW(None, str(exc), "Wingman startup", 0x10)
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
