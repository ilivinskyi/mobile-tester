import pytest

from mobiletester.ios import runner, simctl

LISTING = {"devices": {
    "com.apple.CoreSimulator.SimRuntime.iOS-27-0": [
        {"udid": "A", "name": "iPhone 17", "state": "Booted", "isAvailable": True},
        {"udid": "B", "name": "iPhone 17 Pro", "state": "Shutdown", "isAvailable": True},
        {"udid": "C", "name": "iPhone 16", "state": "Shutdown", "isAvailable": False},
    ],
    "com.apple.CoreSimulator.SimRuntime.watchOS-12-0": [
        {"udid": "W", "name": "Apple Watch", "state": "Booted", "isAvailable": True},
    ],
}}


def test_runtime_names():
    assert simctl.runtime_name("com.apple.CoreSimulator.SimRuntime.iOS-27-0") == "iOS 27.0"
    assert simctl.runtime_name("com.apple.CoreSimulator.SimRuntime.iOS-18-6-1") == "iOS 18.6.1"


def test_only_available_ios_simulators_are_listed():
    sims = simctl.parse_devices(LISTING)
    assert [(s.udid, s.runtime, s.booted) for s in sims] == [("A", "iOS 27.0", True), ("B", "iOS 27.0", False)]


def test_pick_the_only_booted_one_or_by_name():
    sims = simctl.parse_devices(LISTING)
    assert simctl.pick(sims, None).udid == "A"
    assert simctl.pick(sims, "iPhone 17").udid == "A"
    with pytest.raises(simctl.DeviceError, match="not booted"):
        simctl.pick(sims, "iPhone 17 Pro")
    with pytest.raises(simctl.DeviceError, match="no booted simulator"):
        simctl.pick([s for s in sims if not s.booted], None)


def test_several_booted_need_a_choice():
    sims = simctl.parse_devices(LISTING) + [simctl.Simulator("D", "iPad", "Booted", "iOS 27.0")]
    with pytest.raises(simctl.DeviceError, match="several simulators"):
        simctl.pick(sims, None)


def test_runner_port_is_stable_per_simulator_and_in_range():
    port = runner.port_for("AB64CA72-0FAA-47F0-846F-B2D82CA4C33A")
    assert port == runner.port_for("AB64CA72-0FAA-47F0-846F-B2D82CA4C33A")
    assert 22087 <= port < 22887
    assert port != runner.port_for("7AC79805-4D36-4F8B-921A-90B662F74602")


def test_simulator_helpers_call_simctl_once(monkeypatch, tmp_path):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, b"", b""

    monkeypatch.setattr(simctl, "xcrun", lambda: "xcrun")
    monkeypatch.setattr(simctl.subprocess, "run", lambda argv, **kw: calls.append(argv) or Done())
    photo = tmp_path / "p.jpg"
    simctl.privacy("U", "grant", "photos", "com.example")
    simctl.open_url("U", "example://x")
    simctl.ui_get("U", "appearance")
    simctl.ui_set("U", "appearance", "dark")
    simctl.add_media("U", photo)
    simctl.clipboard_get("U")
    simctl.clipboard_set("U", "hi")
    simctl.set_location("U", 52.37, 4.9)
    simctl.clear_location("U")
    assert len(calls) == 9
    for argv in calls:
        assert argv[:2] == ["xcrun", "simctl"] and argv[2] != "simctl", argv
    assert calls[1] == ["xcrun", "simctl", "openurl", "U", "example://x"]
