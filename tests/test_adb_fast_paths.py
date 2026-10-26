"""adb overhead per command: no device listing when the serial is known, no `ps` after the first log check."""

import subprocess
from pathlib import Path

import pytest

from mobiletester.android import adb as adb_module
from mobiletester.android import applog
from mobiletester.android.adb import Adb, DeviceError


def test_known_serial_skips_listing(monkeypatch):
    monkeypatch.setattr(adb_module, "list_devices", lambda _p: pytest.fail("adb devices should not run"))
    assert Adb("SERIAL1", adb_path=Path("adb")).serial == "SERIAL1"


def test_missing_device_is_reported_even_without_check(monkeypatch):
    monkeypatch.setattr(adb_module, "list_devices", lambda _p: [])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, b"", b"adb: device 'SERIAL1' not found"))
    adb = Adb("SERIAL1", adb_path=Path("adb"))
    with pytest.raises(DeviceError, match="SERIAL1 is not connected"):
        adb.shell("getprop", check=False)


class _Adb:
    serial = "log-serial"

    def __init__(self):
        self.ps_calls = 0

    def shell(self, *args, check=True, timeout=None):
        self.ps_calls += 1
        return "  PID NAME\n 4321 com.example.notes\n"


def test_ps_runs_only_on_the_first_check(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_HOME", str(tmp_path / "state"))
    log = tmp_path / "run" / "logs" / "logcat.txt"
    log.parent.mkdir(parents=True)
    line = "10-23 15:04:31.120  4321  4321 E SyncWorker: Upload failed\n"
    log.write_text(line, encoding="utf-8")
    adb = _Adb()
    assert [i.kind for i in applog.new_issues(adb, tmp_path / "run", "com.example.notes")] == ["error"]
    log.write_text(line * 2, encoding="utf-8")
    assert len(applog.new_issues(adb, tmp_path / "run", "com.example.notes")) == 1  # pid remembered
    assert adb.ps_calls == 1
