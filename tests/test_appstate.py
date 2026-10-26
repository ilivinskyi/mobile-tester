"""Runtime permissions and the background kill (Android)."""

import pytest

from mobiletester.android import appstate, device
from mobiletester.android.adb import AdbError

# Shaped like `dumpsys package <pkg>` on Android 14+.
DUMPSYS = """Packages:
  Package [com.example.pantry] (a1b2c3):
    install permissions:
      android.permission.INTERNET: granted=true
      android.permission.ACCESS_NETWORK_STATE: granted=true
    User 0: ceDataInode=1234 installed=true hidden=false
      runtime permissions:
        android.permission.POST_NOTIFICATIONS: granted=false, flags=[ USER_SENSITIVE_WHEN_GRANTED]
        android.permission.CAMERA: granted=true, flags=[ USER_SET|USER_SENSITIVE_WHEN_GRANTED]
        android.permission.ACCESS_FINE_LOCATION: granted=false, flags=[ USER_SET|USER_FIXED]
      disabledComponents:
        com.example.pantry.DebugActivity
"""


def test_only_runtime_permissions_are_listed():
    assert appstate.parse_runtime_permissions(DUMPSYS) == {
        "android.permission.POST_NOTIFICATIONS": False, "android.permission.CAMERA": True,
        "android.permission.ACCESS_FINE_LOCATION": False}


def test_short_names_expand():
    assert appstate.expand(["camera", "CAMERA", "android.permission.READ_CONTACTS"]) == [
        "android.permission.CAMERA", "android.permission.READ_CONTACTS"]
    assert appstate.expand(["location"]) == ["android.permission.ACCESS_FINE_LOCATION",
                                             "android.permission.ACCESS_COARSE_LOCATION"]


class FakeAdb:
    serial = "fake"

    def __init__(self, pid_answers=("4321",)):
        self.calls, self.pids = [], list(pid_answers)

    def shell(self, *args, check=True, timeout=None):
        self.calls.append(" ".join(args))
        if args[0] == "pidof":
            return self.pids.pop(0) if len(self.pids) > 1 else self.pids[0]
        return DUMPSYS if args[0].startswith("dumpsys") else ""

    def run(self, *args, timeout=30, check=True):
        self.calls.append(" ".join(args))
        return b"Success"


def test_reset_revokes_and_clears_dont_ask_again():
    adb = FakeAdb()
    assert len(appstate.reset(adb, "com.example.pantry")) == 3
    assert "pm revoke com.example.pantry android.permission.CAMERA" in adb.calls
    assert ("pm clear-permission-flags com.example.pantry android.permission.ACCESS_FINE_LOCATION user-set "
            "user-fixed") in adb.calls


def test_kill_reports_whether_the_process_is_gone(monkeypatch):
    monkeypatch.setattr(appstate.time, "sleep", lambda _s: None)
    assert appstate.kill_in_background(FakeAdb(["4321", ""]), "com.example.pantry") == ([4321], [])
    assert appstate.kill_in_background(FakeAdb(["4321", "4321"]), "com.example.pantry") == ([4321], [4321])
    with pytest.raises(AdbError, match="not running"):
        appstate.kill_in_background(FakeAdb([""]), "com.example.pantry")


def test_install_no_longer_grants_permissions():
    adb = FakeAdb()
    device.app_install(adb, "app.apk")
    device.app_install(adb, "app.apk", grant_all=True)
    assert adb.calls == ["install -r app.apk", "install -r -g app.apk"]
