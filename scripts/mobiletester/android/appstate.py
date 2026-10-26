"""App state a person can't see but bugs hide in: runtime permissions, and the process Android kills to free memory."""

from __future__ import annotations

import re
import shlex
import time

from .adb import Adb, AdbError

# Short names people use for the permissions apps ask about most.
ALIASES = {
    "camera": ["android.permission.CAMERA"],
    "microphone": ["android.permission.RECORD_AUDIO"],
    "location": ["android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION"],
    "notifications": ["android.permission.POST_NOTIFICATIONS"],
    "contacts": ["android.permission.READ_CONTACTS"],
    "photos": ["android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO"],
    "phone": ["android.permission.CALL_PHONE"],
    "calendar": ["android.permission.READ_CALENDAR", "android.permission.WRITE_CALENDAR"],
    "bluetooth": ["android.permission.BLUETOOTH_CONNECT"],
}
_PERMISSION_LINE = re.compile(r"^\s+([\w.]+): granted=(true|false)")


def expand(names: list[str]) -> list[str]:
    """'camera', 'CAMERA' or 'android.permission.CAMERA' -> full permission names."""
    full: list[str] = []
    for name in names:
        if name.casefold() in ALIASES:
            full += ALIASES[name.casefold()]
        elif "." in name:
            full.append(name)
        else:
            full.append(f"android.permission.{name.upper()}")
    return list(dict.fromkeys(full))


def parse_runtime_permissions(dumpsys: str) -> dict[str, bool]:
    """The 'runtime permissions:' section of `dumpsys package <pkg>`: name -> granted.

    Install-time permissions are granted at install and listed in their own section; only runtime ones
    are asked for while the app runs, so only those can be granted or revoked.
    """
    found: dict[str, bool] = {}
    inside = False
    for line in dumpsys.splitlines():
        if line.strip() == "runtime permissions:":
            inside = True
            continue
        if inside:
            if match := _PERMISSION_LINE.match(line):
                found[match.group(1)] = match.group(2) == "true"
            elif line.strip():
                inside = False
    return found


def runtime_permissions(adb: Adb, package: str) -> dict[str, bool]:
    return parse_runtime_permissions(adb.shell(f"dumpsys package {shlex.quote(package)}", timeout=30))


def grant(adb: Adb, package: str, permissions: list[str]) -> None:
    for permission in permissions:
        adb.shell("pm", "grant", package, permission)


def revoke(adb: Adb, package: str, permissions: list[str]) -> None:
    """Revoking a runtime permission kills the app's process; returning to it tests that path."""
    for permission in permissions:
        adb.shell("pm", "revoke", package, permission)


def reset(adb: Adb, package: str) -> list[str]:
    """Back to never asked: revoke every runtime permission and clear 'don't ask again', so prompts show again."""
    names = list(runtime_permissions(adb, package))
    for permission in names:
        adb.shell("pm", "revoke", package, permission, check=False)
        adb.shell("pm", "clear-permission-flags", package, permission, "user-set", "user-fixed", check=False)
    return names


def pids(adb: Adb, package: str) -> list[int]:
    out = adb.shell("pidof", package, check=False).split()
    return [int(p) for p in out if p.isdigit()]


def kill_in_background(adb: Adb, package: str) -> tuple[list[int], list[int]]:
    """Kill the app's process the way Android does under memory pressure: only works while it's in the background.

    Returns the process ids before and after; an empty "after" means the process is gone.
    """
    before = pids(adb, package)
    if not before:
        raise AdbError(f"{package} is not running")
    adb.shell("am", "kill", package)
    time.sleep(0.5)
    return before, pids(adb, package)
