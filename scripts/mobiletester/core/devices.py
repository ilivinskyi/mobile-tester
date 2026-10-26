"""The user's device list: every phone, emulator and simulator they test on, saved once for all projects.

Lives in ~/.mobile-tester/devices.yaml (MT_DEVICES overrides it), keyed by Android serial or iOS UDID.
The tools read it to tell a test device (system settings may change, restored at session end) from a personal
phone (every system change needs the user's yes). An unknown physical device counts as personal.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_HEADER = ("# mobile-tester devices: used by every project on this computer. Keyed by Android serial or iOS UDID.\n"
           "# personal: true means system changes, data clearing and installs always ask first.\n")


def path() -> Path:
    return Path(os.environ.get("MT_DEVICES") or Path.home() / ".mobile-tester" / "devices.yaml")


def load() -> list[dict]:
    file = path()
    if not file.is_file():
        return []
    return (yaml.safe_load(file.read_text(encoding="utf-8")) or {}).get("devices") or []


def get(device_id: str) -> dict | None:
    return next((d for d in load() if str(d.get("id", "")) == device_id), None)


def save(device_id: str, name: str, platform: str, kind: str, personal: bool) -> dict:
    """Add or replace a device; returns its entry."""
    entry = {"id": device_id, "name": name, "platform": platform, "kind": kind, "personal": personal}
    kept = [d for d in load() if str(d.get("id", "")) != device_id]
    _write([*kept, entry])
    return entry


def forget(device_id: str) -> bool:
    current = load()
    kept = [d for d in current if str(d.get("id", "")) != device_id]
    _write(kept)
    return len(kept) != len(current)


def _write(entries: list[dict]) -> None:
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".yaml.tmp")
    tmp.write_text(_HEADER + yaml.safe_dump({"devices": entries}, sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    os.replace(tmp, file)


def personal(entry: dict | None, physical: bool) -> bool:
    """Emulators and simulators never are; a physical device is personal unless its entry says otherwise."""
    if not physical:
        return False
    return bool(entry.get("personal", True)) if entry else True


def describe(entry: dict | None, physical: bool) -> str:
    """'Pixel 7a, test device' / 'personal device' / 'not saved yet (counts as personal)'."""
    if not physical:
        return "emulator or simulator"
    if entry is None:
        return "not saved yet (counts as personal: save it with `devices --save`)"
    return f"{entry.get('name') or '?'}, {'personal device' if personal(entry, True) else 'test device'}"
