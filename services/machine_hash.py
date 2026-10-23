"""A stable, anonymous id for this machine.

The backend uses it to notice two accounts on one machine (referral abuse).
Only the hash ever leaves Core, never the machine's own id.
"""

import hashlib
import platform
import re
import subprocess
import uuid
from os import path
from typing import Optional

from services.file import get_users_dir
from services.printr import Printr

SALT = "wingman-device-v1"
FALLBACK_FILE = ".machine_id"
"""In the version-independent user folder: a random id for machines whose own
id cannot be read, so the hash stays the same across updates."""


def _windows_machine_guid() -> Optional[str]:
    if platform.system() != "Windows":
        return None
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    ) as key:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(value)


def _macos_platform_uuid() -> Optional[str]:
    if platform.system() != "Darwin":
        return None
    output = subprocess.run(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
    return match.group(1) if match else None


def _linux_machine_id() -> Optional[str]:
    if platform.system() != "Linux":
        return None
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        if path.isfile(candidate):
            with open(candidate, encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
    return None


def _fallback_id(folder: str) -> str:
    file_path = path.join(folder, FALLBACK_FILE)
    try:
        with open(file_path, encoding="utf-8") as f:
            value = f.read().strip()
        if value:
            return value
    except OSError:
        pass
    value = uuid.uuid4().hex
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError as e:
        Printr().print(f"Could not store the machine id: {e}", server_only=True)
    return value


def machine_id(folder: Optional[str] = None) -> str:
    """The machine's own id, or a stored random one. Never send this."""
    for reader in (_windows_machine_guid, _macos_platform_uuid, _linux_machine_id):
        try:
            value = reader()
        except Exception:
            value = None
        if value:
            return value
    return _fallback_id(folder or get_users_dir())


def machine_hash(folder: Optional[str] = None) -> str:
    """sha256 of the machine id and SALT, hex."""
    return hashlib.sha256((machine_id(folder) + SALT).encode("utf-8")).hexdigest()
