"""Private deployment identity; no Core API or credentials are added to it."""

from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PROCESS_INSTANCE = uuid4().hex
LOADED = {}
CORE_FILES = ("wingman_core.py", "wingmen/open_ai_wingman.py",
              "services/tool_execution.py", "services/elite_runtime_identity.py",
              "services/config_manager.py", "services/config_service.py", "services/config_repair.py")
CONTROL_FILES = ("main.py", "runtime.py", "input.py", "bindings.py", "catalog.py", "routing.py", "result.py", "observation.py", "speech.py", "workflows.py", "__init__.py")


def fingerprint(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def capture(path):
    try:
        record = fingerprint(path)
    except OSError:
        # Frozen distributions may contain bytecode without adjacent source.
        # Keep Core usable; they cannot satisfy source deployment acceptance.
        record = {"path": str(Path(path).resolve()), "sha256": None, "source_unavailable": True}
    LOADED.setdefault(record["path"], record)
    return dict(LOADED[record["path"]])


def expected_files(root=ROOT):
    root = Path(root)
    files = {name: fingerprint(root / name) for name in CORE_FILES}
    files.update({"controls/" + name: fingerprint(root / "skills/elite_dangerous_controls" / name)
                  for name in CONTROL_FILES})
    files["telemetry/telemetry.py"] = fingerprint(root / "skills/elite_dangerous/telemetry.py")
    return files


def process_started(pid):
    """Read the OS process start time without adding a runtime dependency."""
    if platform.system() == "Windows":
        import ctypes
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise OSError("Cannot inspect Core process start time")
        try:
            values = [w.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
                raise OSError("Cannot inspect Core process start time")
            ticks = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
            return ticks / 10_000_000 - 11644473600
        finally:
            kernel.CloseHandle(handle)
    result = subprocess.run(["ps", "-p", str(int(pid)), "-o", "lstart="],
                            capture_output=True, text=True, check=True, timeout=3,
                            env={**os.environ, "LC_ALL": "C"})
    return datetime.strptime(result.stdout.strip(), "%a %b %d %H:%M:%S %Y").timestamp()


def write_identity(core):
    tower = core.tower
    files = {}
    for name in CORE_FILES:
        path = str((ROOT / name).resolve())
        if path in LOADED:
            files[name] = LOADED[path]
    skills, conflicts = [], []
    for wingman in tower.wingmen:
        for skill in wingman.skills:
            skills.append({"wingman": wingman.name, "name": skill.config.name,
                           "module": str(Path(inspect.getfile(type(skill))).resolve())})
            if skill.config.name == "EliteDangerousControls":
                files.update(getattr(skill, "loaded_files", {}))
        if any(s.config.name == "EliteDangerousControls" for s in wingman.skills):
            for command in wingman.config.commands or []:
                phrases = [command.name, *(command.instant_activation or [])]
                if any(p.casefold().startswith(("ship ", "srv ", "on foot ", "on_foot ")) for p in phrases):
                    conflicts.append(command.name)
    configs = core.config_manager.get_config_dirs()
    record = {"pid": os.getpid(), "process_started": process_started(os.getpid()),
              "instance": PROCESS_INSTANCE, "recorded_at": datetime.now(timezone.utc).isoformat(),
              "executable": sys.executable, "frozen": bool(getattr(sys, "frozen", False)),
              "source_root": str(ROOT), "profile": tower.config_dir.directory,
              "config_root": str(Path(core.config_manager.config_dir).resolve()),
              "schema_revision": 3, "control_semantics": "single_press", "files": files, "skills": skills,
              "duplicate_defaults": sum(c.is_default for c in configs) > 1,
              "legacy_commands": sorted(set(conflicts))}
    destination = Path(core.config_manager.config_dir).parent / "elite-runtime.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return record


def compare(record, expected, pid=None, process_started=None, profile=None, config_root=None):
    problems = []
    if record.get("frozen"):
        problems.append("packaged_core")
    if pid is not None and record.get("pid") != pid:
        problems.append("stale_pid")
    if process_started is not None and abs(record.get("process_started", 0) - process_started) > 0.01:
        problems.append("stale_process_start")
    if record.get("schema_revision") != 3:
        problems.append("stale_control_schema")
    if profile is not None and record.get("profile") != profile:
        problems.append("wrong_profile")
    if config_root is not None and Path(record.get("config_root", ".")).resolve() != Path(config_root).resolve():
        problems.append("wrong_config_root")
    for name, wanted in expected.items():
        actual = record.get("files", {}).get(name, {})
        if actual.get("sha256") != wanted["sha256"]:
            problems.append("stale_or_missing:" + name)
        elif name in CORE_FILES and Path(actual.get("path", ".")).resolve() != Path(wanted["path"]).resolve():
            problems.append("wrong_module_location:" + name)
    names = {s["name"] for s in record.get("skills", [])}
    for name in ("EliteDangerous", "EliteDangerousControls"):
        if name not in names:
            problems.append("missing_skill:" + name)
    if record.get("duplicate_defaults"):
        problems.append("duplicate_defaults")
    if record.get("legacy_commands"):
        problems.append("conflicting_legacy_commands")
    return problems


capture(__file__)
