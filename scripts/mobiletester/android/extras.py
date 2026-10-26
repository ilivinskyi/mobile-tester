"""OS handoffs a test needs: notifications, gallery media, and on emulators a GPS position and a fingerprint."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .adb import Adb, AdbError

_RECORD = re.compile(r"^\s*NotificationRecord\(0x[0-9a-f]+: pkg=(\S+)", re.M)
_EXTRA = re.compile(r"^\s*android\.(title|text|bigText|subText)=\S+ \((.*)\)\s*$", re.M)
_ACTION = re.compile(r'^\s*\[\d+\] "(.*?)"', re.M)


def parse_notifications(dumpsys: str, package: str | None = None) -> list[dict]:
    """Active notifications from `dumpsys notification --noredact`: package, title, text, action buttons."""
    starts = [m.start() for m in _RECORD.finditer(dumpsys)] + [len(dumpsys)]
    found = []
    for begin, end in zip(starts, starts[1:], strict=False):
        block = dumpsys[begin:end]
        pkg = _RECORD.match(block).group(1)
        if package and pkg != package:
            continue
        extras = dict(_EXTRA.findall(block))
        # The action list ends at a line with only "}"; its entries contain braces of their own.
        actions_part = ""
        if "actions={" in block:
            actions_part = block.split("actions={", 1)[1]
            actions_part = re.split(r"^\s*\}\s*$", actions_part, maxsplit=1, flags=re.M)[0]
        found.append({"package": pkg, "title": extras.get("title", ""),
                      "text": extras.get("bigText") or extras.get("text", ""),
                      "actions": _ACTION.findall(actions_part)})
    return found


def notifications(adb: Adb, package: str | None = None) -> list[dict]:
    return parse_notifications(adb.shell("dumpsys", "notification", "--noredact", timeout=30), package)


_MEDIA_DIRS = {".mp4": "Movies", ".mov": "Movies", ".mkv": "Movies", ".webm": "Movies"}


def push_media(adb: Adb, file: Path) -> str:
    """Put a photo or video in the gallery: push it to the shared storage and ask the media scanner to index it."""
    folder = _MEDIA_DIRS.get(file.suffix.lower(), "Pictures")
    remote = f"/sdcard/{folder}/{file.name}"
    adb.run("push", str(file), remote, timeout=300)
    adb.shell("am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d",
              shlex.quote(f"file://{remote}"), check=False)
    return remote


def _emulator_only(adb: Adb, what: str) -> None:
    if not adb.serial.startswith("emulator-"):
        raise AdbError(f"{what} can only be faked on an emulator; on a phone it needs a mock-location app or a "
                       "real finger")


def set_location(adb: Adb, latitude: float, longitude: float) -> None:
    _emulator_only(adb, "a GPS position")
    adb.run("emu", "geo", "fix", str(longitude), str(latitude))  # the emulator console takes longitude first


def fingerprint(adb: Adb, match: bool) -> None:
    """Touch the emulator's fingerprint sensor with the enrolled finger (id 1), or an unknown one."""
    _emulator_only(adb, "a fingerprint")
    adb.run("emu", "finger", "touch", "1" if match else "99")
