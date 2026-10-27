"""Config stress (dark mode, font scale, orientation, RTL) and going offline, always restorable.

Each change records the original value first (core/restore.py), so a test never leaves a phone at 200% font
or in airplane mode: `session end` puts everything back.
"""

from __future__ import annotations

from ..core import restore
from .adb import Adb

# Surface rotation per orientation name, as `settings system user_rotation` takes it.
ROTATIONS = {"portrait": "0", "landscape": "1", "reverse-portrait": "2", "reverse-landscape": "3"}

# A change by name -> the device settings it sets ("namespace/key" -> value).
CHANGES = {
    "dark": lambda v: {"uimode/night": "yes" if v == "on" else "no"},
    "font_scale": lambda v: {"system/font_scale": v},
    # Auto-rotate off, then a fixed rotation: works the same on a phone on the desk and on an emulator.
    "orientation": lambda v: {"system/accelerometer_rotation": "0", "system/user_rotation": ROTATIONS[v]},
    "rtl": lambda v: {"global/debug.force_rtl": "1" if v == "on" else "0"},
    "network": lambda v: {"connectivity/airplane": "on" if v == "offline" else "off"},
}


def get(adb: Adb, key: str) -> str | None:
    if key == "uimode/night":
        return adb.shell("cmd", "uimode", "night").rsplit(":", 1)[-1].strip()
    if key == "connectivity/airplane":
        return "on" if adb.shell("settings", "get", "global", "airplane_mode_on").strip() == "1" else "off"
    namespace, name = key.split("/", 1)
    value = adb.shell("settings", "get", namespace, name).strip()
    return None if value in ("", "null") else value


def put(adb: Adb, key: str, value: str | None) -> None:
    if key == "uimode/night":
        adb.shell("cmd", "uimode", "night", value or "no")
    elif key == "connectivity/airplane":
        adb.shell("cmd", "connectivity", "airplane-mode", "enable" if value == "on" else "disable")
    else:
        namespace, name = key.split("/", 1)
        if value is None:
            adb.shell("settings", "delete", namespace, name)
        else:
            adb.shell("settings", "put", namespace, name, value)


def change(adb: Adb, name: str, value: str) -> dict[str, str]:
    settings = CHANGES[name](value)
    for key, new in settings.items():
        restore.remember(adb.serial, key, get(adb, key))
        put(adb, key, new)
    return settings


def restore_all(adb: Adb, keys: list[str] | None = None) -> dict[str, str | None]:
    """Put recorded settings back (all, or only `keys`); returns what was restored."""
    saved = restore.pending(adb.serial)
    done = {k: v for k, v in saved.items() if keys is None or k in keys}
    for key, original in done.items():
        put(adb, key, original)
    restore.forget(adb.serial, list(done))
    return done


def over_wifi(serial: str) -> bool:
    """adb connected over the network (host:port or a wireless-debugging name): going offline would cut it."""
    return ":" in serial or "adb-tls-connect" in serial
