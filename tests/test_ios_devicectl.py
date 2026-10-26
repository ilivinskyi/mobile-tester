import json
import plistlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mobiletester.ios import capture, crash, device, devicectl, runner, signing, simctl

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = json.loads((FIXTURES / "ios_devicectl_devices.json").read_text(encoding="utf-8"))["result"]
SIMS = [simctl.Simulator("SIM-A", "iPhone 17", "Booted", "iOS 27.0"),
        simctl.Simulator("SIM-B", "iPhone 17 Pro", "Shutdown", "iOS 27.0")]


def phones() -> list[devicectl.PhysicalDevice]:
    return devicectl.parse_devices(LISTING)


def test_only_physical_devices_are_listed_with_their_state():
    found = phones()
    assert [(d.udid, d.model, d.os_version, d.transport, d.developer_mode) for d in found] == [
        ("00008150-0011223344556677", "iPhone 17 Pro", "27.0", "wired", True),
        ("00008110-000A1B2C3D4E5F60", "iPad Pro 11-inch (M4)", "27.0.1", "localNetwork", False),
    ]
    iphone, ipad = found
    assert iphone.ready and iphone.state == "ready" and iphone.problem() is None
    assert ipad.reachable and not ipad.ready and ipad.state == "developer mode off"
    assert "Developer Mode" in ipad.problem()
    assert iphone.kind == "physical" and iphone.identifier == "66666666-7777-8888-9999-AAAAAAAAAAAA"


def test_unpaired_and_unreachable_devices_say_what_to_do():
    dev = phones()[0]
    dev.paired = False
    assert dev.state == "not paired" and "Trust" in dev.problem()
    dev.paired, dev.connection = True, "unavailable"
    assert dev.state == "unavailable" and "out of reach" in dev.problem()


def test_without_a_choice_a_usb_device_or_the_booted_simulator_is_used():
    iphone, ipad = phones()
    assert device.choose([SIMS[1]], [iphone, ipad], None) is iphone
    assert device.choose(SIMS, [ipad], None).udid == "SIM-A"
    with pytest.raises(simctl.DeviceError, match="several simulators or devices"):
        device.choose(SIMS, [iphone], None)


def test_a_wifi_device_is_only_used_when_named():
    iphone, ipad = phones()
    ipad.developer_mode = True
    with pytest.raises(simctl.DeviceError, match="on Wi-Fi: Test iPad .* pass -s UDID"):
        device.choose([SIMS[1]], [ipad], None)
    assert device.choose(SIMS, [ipad], "Test iPad") is ipad
    assert device.choose(SIMS, [ipad], ipad.identifier) is ipad


def test_a_named_device_must_be_ready():
    iphone, ipad = phones()
    with pytest.raises(simctl.DeviceError, match="Developer Mode is off"):
        device.choose(SIMS, [iphone, ipad], ipad.udid)
    with pytest.raises(simctl.DeviceError, match="no simulator or device"):
        device.choose(SIMS, [iphone], "Nobody's phone")
    assert device.choose(SIMS, [iphone], "SIM-A").udid == "SIM-A"


def test_a_name_shared_by_a_device_and_a_simulator_needs_the_udid():
    iphone = phones()[0]
    iphone.name = "iPhone 17"
    with pytest.raises(simctl.DeviceError, match="several devices are called"):
        device.choose(SIMS, [iphone], "iPhone 17")


APPS = {"apps": [
    {"bundleIdentifier": "com.github.aint.Habits", "name": "Habits", "version": "1.2", "bundleVersion": "7",
     "removable": True, "defaultApp": False,
     "url": "file:///private/var/containers/Bundle/Application/61181316-24E4/Habits%20Dev.app/"},
    {"bundleIdentifier": "com.apple.reminders", "name": "Reminders", "version": "27.0", "bundleVersion": "1",
     "removable": True, "defaultApp": True, "url": "file:///Applications/Reminders.app/"},
]}


def test_apps_take_the_shape_of_simctl_apps():
    found = devicectl.parse_apps(APPS)
    assert found["com.github.aint.Habits"]["CFBundleDisplayName"] == "Habits"
    assert found["com.github.aint.Habits"]["ApplicationType"] == "User"
    assert found["com.apple.reminders"]["ApplicationType"] == "System"


def test_app_info_names_the_executable_after_the_bundle(monkeypatch):
    monkeypatch.setattr(devicectl, "run", lambda *args, **kw: APPS)
    info = devicectl.app_info("UDID", "com.github.aint.Habits")
    assert info == {"package": "com.github.aint.Habits", "name": "Habits", "versionName": "1.2", "versionCode": "7",
                    "executable": "Habits Dev",
                    "bundle_path": "/private/var/containers/Bundle/Application/61181316-24E4/Habits Dev.app"}
    with pytest.raises(devicectl.DevicectlError, match="not installed"):
        devicectl.app_info("UDID", "com.example.missing")


def test_pids_of_the_app_are_found_by_its_bundle_path():
    processes = {"runningProcesses": [
        {"processIdentifier": 1, "executable": "file:///sbin/launchd"},
        {"processIdentifier": 812, "executable": "file:///var/containers/Bundle/Application/61181316-24E4/"
                                                 "Habits%20Dev.app/Habits%20Dev"},
        {"processIdentifier": 813, "executable": "file:///private/var/containers/Bundle/Application/61181316-24E4/"
                                                 "Habits%20Dev.app/PlugIns/Widget.appex/Widget"},
        {"processIdentifier": 900, "executable": "file:///private/var/containers/Bundle/Application/61181316-24E4/"
                                                 "Habits%20Dev.app.other/x"},
        {"processIdentifier": 901},
    ]}
    path = "/private/var/containers/Bundle/Application/61181316-24E4/Habits Dev.app"
    assert devicectl.parse_pids(processes, path) == [812, 813]


def test_errors_read_coredevice_s_description_first():
    data = {"error": {"userInfo": {"NSLocalizedDescription": {"string": "The device is locked."}}}}
    assert devicectl.error_message(data, b"ERROR: something else") == "The device is locked."
    assert devicectl.error_message({}, b"\nERROR: The developer disk image could not be mounted.\n  more") == \
        "The developer disk image could not be mounted."


def test_crash_log_files_of_the_app_only():
    def entry(path, directory=False):  # the shape devicectl 642 writes on an iPhone with iOS 27
        return {"name": path.rsplit("/", 1)[-1], "relativePath": path, "metadata": {"size": 96},
                "resources": {"isDirectory": directory, "isHidden": False, "isReadable": True}}

    listing = {"files": [
        entry("Habits-2026-10-24-091201.ips"),
        entry("Retired/Habits-2026-10-20-101010.ips"),
        entry("Retired", directory=True),
        entry("HabitsWidget-2026-10-24-091201.ips"),
        entry("JetsamEvent-2026-10-24-091201.ips"),
        entry("Habits-2026-10-24-091300.ips.synced"),
    ]}
    names = devicectl.parse_files(listing)
    assert "Retired" not in names
    assert crash.wanted_on_device(names, "Habits") == ["Habits-2026-10-24-091201.ips",
                                                       "Retired/Habits-2026-10-20-101010.ips"]


def test_copied_crash_reports_keep_the_crash_time(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_HOME", str(tmp_path))
    source = FIXTURES / "Habits-2026-10-24-091201.ips"
    monkeypatch.setattr(devicectl, "crash_logs", lambda udid: ["Habits-2026-10-24-091201.ips", "Other-1.ips"])
    copied = []

    def copy(udid, name, destination):
        copied.append(name)
        destination.write_bytes(source.read_bytes())
        return destination

    monkeypatch.setattr(devicectl, "copy_crash_log", copy)
    local = crash.sync_device("UDID", "Habits")
    report = local / "Habits-2026-10-24-091201.ips"
    assert copied == ["Habits-2026-10-24-091201.ips"]
    assert report.stat().st_mtime == crash.crash_time(report) == 1792825921.0
    crash.sync_device("UDID", "Habits")
    assert copied == ["Habits-2026-10-24-091201.ips"]  # already here: not copied again
    assert crash.find("Habits", "com.github.aint.Habits", since=1792825920, directory=local) == [report]
    assert crash.find("Habits", "com.github.aint.Habits", since=1792825922, directory=local) == []


def test_recording_command_and_start_marker_per_kind(monkeypatch):
    # The command line is what's tested, not the machine: it must pass where Xcode isn't installed too.
    monkeypatch.setattr(capture, "xcrun", lambda: "/usr/bin/xcrun")
    out = Path("/tmp/session.mp4")
    assert capture._record_command("U", out, physical=True)[1:6] == ["devicectl", "device", "capture",
                                                                       "screen-record", "--device"]
    assert "recordVideo" in capture._record_command("U", out, physical=False)
    assert capture.recording_started("Recording started")
    assert not capture.recording_started("")
    # devicectl's error names the feature "Screen Recording": that must not count as started.
    error = "ERROR: The capability \u201cScreen Recording\u201d is not supported by this device."
    assert not capture.recording_started(error, physical=True, running_for=5)
    assert not capture.recording_started("", physical=True, running_for=0.5)
    assert capture.recording_started("", physical=True, running_for=2.5)


def test_recording_is_offered_only_by_devices_that_list_it():
    iphone, ipad = phones()
    assert not iphone.can_record
    iphone.capabilities = frozenset({"com.apple.coredevice.feature.screenrecording"})
    assert iphone.can_record
    assert "com.apple.coredevice.feature.connectdevice" in ipad.capabilities


def test_xcode_teams_are_hints_sorted_paid_first():
    prefs = {"IDEProvisioningTeamByIdentifier": {
        "acct-1": [{"teamID": "AAAAAAAAAA", "teamName": "Ihor Personal", "isFreeProvisioningTeam": True}],
        "acct-2": [{"teamID": "BBBBBBBBBB", "teamName": "Acme Inc", "isFreeProvisioningTeam": False},
                   {"teamID": "AAAAAAAAAA", "teamName": "Ihor Personal", "isFreeProvisioningTeam": True}],
    }}
    assert signing.parse_xcode_teams(prefs) == [{"id": "BBBBBBBBBB", "name": "Acme Inc", "free": False},
                                                {"id": "AAAAAAAAAA", "name": "Ihor Personal", "free": True}]
    assert signing.parse_xcode_teams({}) == []


def test_the_team_is_validated_and_remembered(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("MT_IOS_TEAM", raising=False)
    assert signing.team() is None
    with pytest.raises(ValueError, match="not a team id"):
        signing.save_team("my team")
    assert signing.save_team(" ab12cd34ef ") == "AB12CD34EF"
    assert signing.team() == "AB12CD34EF"
    monkeypatch.setenv("MT_IOS_TEAM", "ZZZZZZZZZZ")
    assert signing.team() == "ZZZZZZZZZZ"


def test_the_report_names_a_personal_physical_device():
    from mobiletester.core import report_text

    session = {"device": {"platform": "iOS", "model": "iPhone 17 Pro", "os": "iOS 27.0", "kind": "physical",
                          "personal": True}, "app": {"package": "com.example"}}
    assert ("Device kind", "physical, personal") in report_text.environment(session)
    assert "personal physical device" in report_text.environment_line(session)
    session["device"].update(kind="simulator", personal=False)
    assert ("Device kind", "simulator") in report_text.environment(session)


def test_the_profile_expiry_is_read_from_the_decoded_profile():
    profile = {"Name": "iOS Team Provisioning Profile", "ExpirationDate": datetime(2026, 10, 31, 13, 33)}
    decoded = plistlib.dumps(profile)
    assert runner.parse_profile(decoded) == datetime(2026, 10, 31, 13, 33, tzinfo=UTC)
    assert runner.parse_profile(plistlib.dumps({"Name": "x"})) is None
    assert runner.parse_profile(b"not a plist") is None


def test_a_runner_is_rebuilt_only_within_a_day_of_expiry():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    assert not runner.needs_rebuild(now + timedelta(days=3), now)
    assert runner.needs_rebuild(now + timedelta(hours=20), now)
    assert runner.needs_rebuild(now - timedelta(hours=1), now)
    assert not runner.needs_rebuild(None, now)


def _fake_builds(monkeypatch, tmp_path, expiries):
    """Each build gets the next expiry from the list; returns the list of builds made."""
    builds = []
    monkeypatch.setattr(runner, "build_dir", lambda device, team: tmp_path / "build")

    def xctestrun(device=None, team=None, build=True):
        directory = tmp_path / "build"
        if not directory.exists():
            directory.mkdir()
            builds.append(expiries[len(builds)])
            (directory / "expiry").write_text(builds[-1].isoformat())
        return directory / "MTRunner.xctestrun"

    monkeypatch.setattr(runner, "xctestrun", xctestrun)
    monkeypatch.setattr(runner, "forget_cached_profiles", lambda team: [])
    monkeypatch.setattr(runner, "profile_expiry",
                        lambda testrun: datetime.fromisoformat((testrun.parent / "expiry").read_text()))
    return builds


def test_an_expiring_runner_is_rebuilt_once_at_start(monkeypatch, tmp_path):
    soon = datetime.now(UTC) + timedelta(hours=5)
    later = datetime.now(UTC) + timedelta(days=7)
    builds = _fake_builds(monkeypatch, tmp_path, [soon, later])
    runner.xctestrun(device="D", team="T")  # the existing build
    _, note = runner.fresh_device_build("D", "T")
    assert builds == [soon, later]
    assert "expires" in note and "rebuilt it with team T" in note and "valid until" in note
    _, note = runner.fresh_device_build("D", "T")
    assert builds == [soon, later] and note is None


def test_a_profile_xcode_keeps_is_not_rebuilt_again_until_it_expires(monkeypatch, tmp_path):
    soon = datetime.now(UTC) + timedelta(hours=5)
    builds = _fake_builds(monkeypatch, tmp_path, [soon, soon, soon])
    runner.xctestrun(device="D", team="T")
    _, note = runner.fresh_device_build("D", "T")
    assert "same profile back" in note and len(builds) == 2
    _, note = runner.fresh_device_build("D", "T")
    assert note is None and len(builds) == 2


def test_only_this_runner_s_cached_profile_is_forgotten(monkeypatch, tmp_path):
    monkeypatch.setenv("MT_PROFILES_DIR", str(tmp_path))
    ours, other = tmp_path / "ours.mobileprovision", tmp_path / "other.mobileprovision"
    ours.write_bytes(b"ours")
    other.write_bytes(b"other")
    ids = {str(ours): "AB12CD34EF.dev.mobiletester.MTRunner.ab12cd34ef.xctrunner",
           str(other): "AB12CD34EF.com.example.app"}

    class Done:
        def __init__(self, path):
            self.returncode = 0
            self.stdout = plistlib.dumps({"Entitlements": {"application-identifier": ids[path]}})

    monkeypatch.setattr(runner.subprocess, "run", lambda cmd, capture_output: Done(cmd[-1]))
    assert runner.forget_cached_profiles("AB12CD34EF") == [ours]
    assert not ours.exists() and other.exists()
