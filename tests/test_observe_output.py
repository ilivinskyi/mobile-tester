"""Compact observe listings, act-and-observe rules and `inspect` on real UI dumps."""

import json
from argparse import Namespace
from pathlib import Path

from mobiletester.android import hierarchy as android
from mobiletester.core import commands, ui
from mobiletester.ios import hierarchy as ios


def _android(fixture_xml, name="jumbo_search_results.xml"):
    xml = fixture_xml(name)
    return xml, android.parse(xml)


def test_lines_leave_out_positions_and_container_classes(fixture_xml):
    _, snap = _android(fixture_xml)
    assert snap.find(1).describe() == '[1] EditText "Melk" #siteSearch [click edit]'
    assert snap.find(3).describe() == "[3] [scroll]"  # a View: its flag says what it is
    assert snap.find(1).describe(bounds=True) == '[1] EditText "Melk" #siteSearch @(539,178) 812x120 [click edit]'


def test_same_screen_lists_only_what_changed(fixture_xml):
    _, before = _android(fixture_xml, "jumbo_stepper_no_keyboard.xml")
    _, after = _android(fixture_xml, "jumbo_stepper.xml")
    full = ui.listing(after.elements)
    assert full[0] == f"elements ({len(after.elements)}):" and len(full) == len(after.elements) + 1
    diff = ui.listing(after.elements, previous=before.elements)
    assert "same screen as the last observe" in diff[0] and 1 < len(diff) < len(full)
    assert ui.listing(after.elements, previous=after.elements)[1] == "  (nothing changed)"


def test_previous_elements_only_for_the_same_known_screen(fixture_xml):
    _, snap = _android(fixture_xml)
    saved = {"fingerprint": "abc", "elements": [e.to_dict() for e in snap.elements]}
    assert len(commands.previous_elements(saved, "abc")) == len(snap.elements)
    assert commands.previous_elements(saved, "other") is None
    assert commands.previous_elements(dict(saved, fingerprint="-"), "-") is None
    assert commands.previous_elements(None, "abc") is None


def test_actions_list_the_new_screen_only_when_it_changed():
    plain = Namespace(observe=False, no_observe=False, fast=False)
    assert commands.observe_after(plain, True, "explore")
    assert not commands.observe_after(plain, False, "explore")
    assert not commands.observe_after(plain, None, None)
    assert not commands.observe_after(plain, True, "repro")  # keeps the accessibility layer off
    assert not commands.observe_after(Namespace(observe=False, no_observe=True, fast=False), True, None)
    assert not commands.observe_after(Namespace(observe=False, no_observe=False, fast=True), True, None)
    assert commands.observe_after(Namespace(observe=True, no_observe=False, fast=False), False, "repro")


def test_android_inspect_finds_the_exact_node(fixture_xml):
    xml, snap = _android(fixture_xml)
    for el in snap.elements:  # every listed element maps back to its node
        node, _, _ = android.raw_node(xml, el)
        assert node["bounds"].startswith("[") and node["class"].endswith(el.cls)
    lines = ui.inspect_lines(snap.find(12), *android.raw_node(xml, snap.find(12)))
    assert 'content-desc="Toevoegen aan mandje Jumbo Halfvolle Melk 2 L"' in lines[1]
    assert "checkable" not in lines[1]  # false flags are left out
    assert lines[2].startswith("parent: class=android.view.View")


def test_ios_inspect_finds_the_exact_node():
    data = json.loads((Path(__file__).parent / "fixtures" / "ios_habits_edit.json").read_text(encoding="utf-8"))
    snap, _ = ios.parse(data)
    for el in snap.elements:
        node, _, _ = ios.raw_node(data, el)
        assert node["type"] == el.cls
    field = ui.find_by_text(snap, "Name")[0]
    lines = ui.inspect_lines(field, *ios.raw_node(data, field))
    assert lines[1].startswith("node: frame=32,187.333,338,22 type=TextField placeholder=Name")
