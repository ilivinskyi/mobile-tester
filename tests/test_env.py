"""Config and network changes always record the original and come back with restore."""

from mobiletester.android import env
from mobiletester.core import restore
from mobiletester.ios import simctl


class SettingsAdb:
    """A device with a settings table, night mode and airplane mode."""

    serial = "env-serial"

    def __init__(self):
        self.settings = {("system", "font_scale"): "1.0", ("system", "accelerometer_rotation"): "1"}
        self.night, self.airplane = "no", "0"

    def shell(self, *args, check=True, timeout=None):
        match args:
            case ("cmd", "uimode", "night"):
                return f"Night mode: {self.night}"
            case ("cmd", "uimode", "night", value):
                self.night = value
            case ("cmd", "connectivity", "airplane-mode", action):
                self.airplane = "1" if action == "enable" else "0"
            case ("settings", "get", "global", "airplane_mode_on"):
                return self.airplane
            case ("settings", "get", namespace, key):
                return self.settings.get((namespace, key), "null")
            case ("settings", "put", namespace, key, value):
                self.settings[(namespace, key)] = value
            case ("settings", "delete", namespace, key):
                self.settings.pop((namespace, key), None)
        return ""


def test_changes_are_restored_to_the_original(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_HOME", str(tmp_path))
    adb = SettingsAdb()
    env.change(adb, "dark", "on")
    env.change(adb, "font_scale", "2.0")
    env.change(adb, "font_scale", "1.3")  # a second change keeps the first original
    env.change(adb, "orientation", "landscape")
    env.change(adb, "rtl", "on")
    assert adb.night == "yes" and adb.settings[("system", "font_scale")] == "1.3"
    assert adb.settings[("system", "user_rotation")] == "1" and adb.settings[("global", "debug.force_rtl")] == "1"
    env.restore_all(adb)
    assert adb.night == "no" and adb.settings[("system", "font_scale")] == "1.0"
    assert adb.settings[("system", "accelerometer_rotation")] == "1"
    assert ("system", "user_rotation") not in adb.settings  # it had no value: deleted again
    assert ("global", "debug.force_rtl") not in adb.settings
    assert restore.pending(adb.serial) == {}


def test_network_restores_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_HOME", str(tmp_path))
    adb = SettingsAdb()
    env.change(adb, "network", "offline")
    env.change(adb, "dark", "on")
    assert adb.airplane == "1"
    env.restore_all(adb, ["connectivity/airplane"])
    assert adb.airplane == "0" and adb.night == "yes" and list(restore.pending(adb.serial)) == ["uimode/night"]


def test_wifi_adb_is_detected():
    assert env.over_wifi("192.168.1.20:5555")
    assert env.over_wifi("adb-3B181JEHN10205-abc._adb-tls-connect._tcp")
    assert not env.over_wifi("3B181JEHN10205") and not env.over_wifi("emulator-5554")


def test_ios_url_schemes_from_info_plist():
    plist = {"CFBundleURLTypes": [{"CFBundleURLSchemes": ["habits"]}, {"CFBundleURLSchemes": ["habits-dev"]}]}
    assert simctl.url_schemes(plist) == ["habits:", "habits-dev:"]
    assert simctl.url_schemes({}) == []
