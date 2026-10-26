"""Locating adb and running commands against one device."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..core.proc import detached_kwargs


class AdbError(RuntimeError):
    """An adb command failed."""


class DeviceError(AdbError):
    """No usable device, or the target device is ambiguous."""


def _sdk_candidates() -> Iterator[Path]:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if value := os.environ.get(var):
            yield Path(value)
    # Default SDK locations used by Android Studio. Checked even when the env var is
    # missing because a freshly `setx`-ed variable isn't visible to already running shells.
    if sys.platform == "win32":
        if local_app_data := os.environ.get("LOCALAPPDATA"):
            yield Path(local_app_data) / "Android" / "Sdk"
    elif sys.platform == "darwin":
        yield Path.home() / "Library" / "Android" / "sdk"
    else:
        yield Path.home() / "Android" / "Sdk"


def find_adb() -> Path:
    """Prefer the SDK's adb over whatever is on PATH (scrcpy bundles its own copy)."""
    if explicit := os.environ.get("ADB"):
        path = Path(explicit)
        if path.is_file():
            return path
        raise AdbError(f"ADB={explicit} does not point to a file")
    exe = "adb.exe" if sys.platform == "win32" else "adb"
    for sdk in _sdk_candidates():
        candidate = sdk / "platform-tools" / exe
        if candidate.is_file():
            return candidate
    if on_path := shutil.which("adb"):
        return Path(on_path)
    raise AdbError(
        "adb not found. Install Android SDK Platform-Tools (Android Studio > SDK Manager) "
        "and set ANDROID_HOME, or set ADB to the adb executable."
    )


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    product: str = ""

    @property
    def is_emulator(self) -> bool:
        return self.serial.startswith("emulator-")


def parse_devices(output: str) -> list[DeviceInfo]:
    """Parse `adb devices -l` output."""
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices", "*")):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        props = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        devices.append(
            DeviceInfo(
                serial=parts[0],
                state=parts[1],
                model=props.get("model", "").replace("_", " "),
                product=props.get("product", ""),
            )
        )
    return devices


def run_adb(adb_path: Path, *args: str, timeout: float = 30) -> str:
    """Run an adb command that isn't bound to a device (devices, version, kill-server)."""
    proc = subprocess.run([str(adb_path), *args], capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise AdbError(f"adb {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode("utf-8", errors="replace")


def list_devices(adb_path: Path) -> list[DeviceInfo]:
    return parse_devices(run_adb(adb_path, "devices", "-l"))


_STATE_HINTS = {
    "unauthorized": "accept the 'Allow USB debugging?' prompt on the phone",
    "offline": "reconnect the cable or run `adb kill-server`",
    "no permissions": "fix udev rules for the device (Linux)",
}


def pick_serial(devices: list[DeviceInfo], requested: str | None) -> str:
    if requested:
        match = next((d for d in devices if d.serial == requested), None)
        if match is None:
            raise DeviceError(f"device {requested} is not connected")
        if match.state != "device":
            raise DeviceError(f"device {requested} is {match.state}: {_STATE_HINTS.get(match.state, '')}")
        return requested
    ready = [d for d in devices if d.state == "device"]
    if len(ready) == 1:
        return ready[0].serial
    if not ready:
        if not devices:
            raise DeviceError("no device connected. Plug in the phone with USB debugging on, or boot an emulator.")
        details = "; ".join(f"{d.serial} is {d.state} ({_STATE_HINTS.get(d.state, '?')})" for d in devices)
        raise DeviceError(f"no ready device: {details}")
    listing = ", ".join(f"{d.serial} ({d.model or 'emulator'})" for d in ready)
    raise DeviceError(f"several devices connected, pass -s SERIAL: {listing}")


_DEVICE_GONE = re.compile(r"device '?[^']*'? not found|device offline|device unauthorized|no devices/emulators found")


class Adb:
    """adb bound to a single device serial."""

    def __init__(self, serial: str | None = None, adb_path: Path | None = None):
        self.path = adb_path or find_adb()
        requested = serial or os.environ.get("ANDROID_SERIAL")
        # A named device is used as is: listing devices first would cost one more adb call per command.
        # If it isn't there, the first command says so (see run).
        self.serial = requested or pick_serial(list_devices(self.path), None)

    def _command(self, *args: str) -> list[str]:
        return [str(self.path), "-s", self.serial, *args]

    def run(self, *args: str, timeout: float = 30, check: bool = True) -> bytes:
        try:
            proc = subprocess.run(self._command(*args), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb {' '.join(args)} timed out after {timeout}s") from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).decode(errors="replace").strip()
            if _DEVICE_GONE.search(err):
                # Even for check=False calls: an empty answer from a missing device would look like "nothing".
                pick_serial(list_devices(self.path), self.serial)  # raises with the device's actual state
                raise DeviceError(f"device {self.serial}: {err}")
            if check:
                raise AdbError(f"adb {' '.join(args)} failed ({proc.returncode}): {err}")
        return proc.stdout

    def shell(self, *args: str, timeout: float = 30, check: bool = True) -> str:
        """Run a device shell command. adb joins args with spaces and the device's sh
        re-parses them, so callers must escape shell metacharacters themselves."""
        return self.run("shell", *args, timeout=timeout, check=check).decode("utf-8", errors="replace")

    def exec_out(self, *args: str, timeout: float = 30) -> bytes:
        """Binary-safe variant of shell (no CRLF translation, no pty)."""
        return self.run("exec-out", *args, timeout=timeout)

    def popen(self, *args: str, stdout, stderr=subprocess.STDOUT) -> subprocess.Popen:
        return subprocess.Popen(self._command(*args), stdout=stdout, stderr=stderr, **detached_kwargs())

    def getprop(self, name: str) -> str:
        return self.shell("getprop", name).strip()
