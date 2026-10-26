"""The per-user device list and what it allows: test devices change settings freely, personal ones ask."""

from argparse import Namespace

import pytest

from mobiletester.android import cli as adt
from mobiletester.core import commands, devices, project
from mobiletester.core.commands import Blocked


@pytest.fixture(autouse=True)
def device_list(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_DEVICES", str(tmp_path / "devices.yaml"))
    monkeypatch.setenv("MT_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)


def test_save_forget_and_lookup():
    devices.save("3B181JEHN10205", "Pixel 7a", "Android", "physical", personal=False)
    devices.save("3B181JEHN10205", "Pixel 7a (work)", "Android", "physical", personal=False)  # replaces
    assert [d["name"] for d in devices.load()] == ["Pixel 7a (work)"]
    assert project.device_entry("3B181JEHN10205")["personal"] is False
    assert devices.forget("3B181JEHN10205") and devices.get("3B181JEHN10205") is None
    assert not devices.forget("3B181JEHN10205")


def test_unknown_physical_counts_as_personal():
    assert devices.personal(None, physical=True)
    assert not devices.personal(None, physical=False)
    assert not devices.personal({"personal": False}, physical=True)
    assert "not saved yet" in devices.describe(None, True)


def test_older_project_inventory_still_counts(tmp_path):
    (tmp_path / ".mobile-tester").mkdir()
    (tmp_path / ".mobile-tester" / "config.yaml").write_text(
        "devices:\n  - serial: \"OLD1\"\n    personal: false\n", encoding="utf-8")
    assert project.device_entry("OLD1", tmp_path)["personal"] is False


class _Adb:
    def __init__(self, serial):
        self.serial = serial

    def getprop(self, name):
        return ""


def test_system_changes_need_approval_only_on_personal_phones(monkeypatch):
    monkeypatch.setattr(adt, "_approval_log", lambda *a, **k: None)
    phone = _Adb("3B181JEHN10205")
    with pytest.raises(Blocked, match="unsaved physical device.*devices --save"):
        adt._system_change_allowed(phone, "net offline", None)
    devices.save(phone.serial, "Pixel 7a", "Android", "physical", personal=False)
    adt._system_change_allowed(phone, "net offline", None)  # a test device: no approval needed
    devices.save(phone.serial, "Pixel 7a", "Android", "physical", personal=True)
    with pytest.raises(Blocked, match="a personal physical device"):
        adt._system_change_allowed(phone, "net offline", None)
    adt._system_change_allowed(phone, "net offline", "user said yes")
    adt._system_change_allowed(_Adb("emulator-5554"), "net offline", None)


def test_save_needs_name_and_kind(capsys):
    args = Namespace(forget=None, save="X1", name=None, test=False, personal=False)
    assert commands.change_device_list(args, "Android", {}) == commands.EXIT_USAGE
    args = Namespace(forget=None, save="X1", name="Tablet", test=True, personal=False)
    assert commands.change_device_list(args, "Android", {"X1": "physical"}) == commands.EXIT_OK
    assert devices.get("X1") == {"id": "X1", "name": "Tablet", "platform": "Android", "kind": "physical",
                                 "personal": False}
    assert commands.change_device_list(Namespace(forget=None, save=None), "Android", {}) is None


def test_list_lives_outside_any_project_marker(monkeypatch):
    monkeypatch.delenv("MT_DEVICES")
    # A `.mobile-tester` folder marks a project; the user's list must never create one in the home folder.
    assert ".mobile-tester" not in devices.path().parts


def test_old_location_is_read_and_moved_on_save(tmp_path, monkeypatch):
    monkeypatch.delenv("MT_DEVICES")
    monkeypatch.setattr(devices.Path, "home", lambda: tmp_path)
    old = tmp_path / ".mobile-tester" / "devices.yaml"
    old.parent.mkdir()
    old.write_text("devices:\n- id: OLD1\n  name: Old phone\n  personal: false\n", encoding="utf-8")
    assert devices.get("OLD1")["name"] == "Old phone"
    devices.save("NEW1", "New phone", "Android", "physical", personal=True)
    assert not (tmp_path / ".mobile-tester").exists()
    assert devices.path() == tmp_path / ".config" / "mobile-tester" / "devices.yaml"
