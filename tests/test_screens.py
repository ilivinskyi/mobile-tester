"""The session's screens: titles, controls never tried, and taps that changed nothing."""

import json

from mobiletester.core import report, screens
from mobiletester.core.ui import Bounds, Element


def _el(label, box, clickable=False, z=(0,), scrollable=False):
    return Element(index=0, cls="android.view.View", text=label, desc="", resource_id="", hint="",
                   bounds=Bounds(*box), label=label, clickable=clickable, scrollable=scrollable, z=list(z))


HOME = [
    _el("TaskPulse", (40, 120, 400, 180), z=(0, 0)),
    _el("Productivty Overview", (40, 300, 600, 360), z=(0, 1)),
    _el("Projects", (40, 400, 300, 460), clickable=True, z=(0, 2)),
    _el("Tags | 4 tags", (320, 400, 600, 460), clickable=True, z=(0, 3)),
    _el("", (0, 500, 1080, 2000), scrollable=True, z=(0, 4)),
    _el("Buy milk", (40, 520, 1040, 600), clickable=True, z=(0, 4, 0)),  # a list row: content, not a control
    _el("Settings", (0, 2200, 360, 2400), clickable=True, z=(0, 5)),
]


def test_title_is_the_topmost_fixed_text_and_list_rows_are_not_controls():
    assert screens.title(HOME, 2400) == "TaskPulse"
    assert screens.controls(HOME) == ["Projects", "Tags", "Settings"]
    assert screens.title([_el("Only a button", (0, 100, 200, 150), clickable=True)], 2400) == ""


def _run(tmp_path):
    (tmp_path / "logs").mkdir()
    screens.record(tmp_path, "aaa", "TaskPulse", screens.controls(HOME))
    screens.record(tmp_path, "aaa", "TaskPulse", ["Projects", "Toggle Status"])  # a second visit adds controls
    screens.record(tmp_path, "bbb", "Project Detail", ["Back", "Export Project CSV"])
    actions = [
        {"t": "2026-10-27T10:00:01.000+01:00", "action": "observe", "fp": "aaa"},
        {"t": "2026-10-27T10:00:05.000+01:00", "action": "tap", "target": '[2] "Projects" [click]', "changed": True},
        {"t": "2026-10-27T10:00:07.000+01:00", "action": "observe", "fp": "bbb"},
        {"t": "2026-10-27T10:00:09.000+01:00", "action": "tap", "target": '[5] "Export Project CSV" [click]',
         "changed": False},
    ]
    (tmp_path / "logs" / "actions.jsonl").write_text("\n".join(json.dumps(a) for a in actions), encoding="utf-8")
    return tmp_path


def test_inventory_lists_untried_controls_and_dead_taps(tmp_path):
    found = screens.inventory(_run(tmp_path))
    home, detail = found["screens"]
    assert home == {"title": "TaskPulse", "visits": 2, "controls": ["Projects", "Tags", "Settings", "Toggle Status"],
                    "untried": ["Tags", "Settings", "Toggle Status"]}
    assert detail["untried"] == ["Back"]
    assert found["no_change"] == [{"time": "10:00:09", "screen": "Project Detail", "target": "Export Project CSV"}]
    text = "\n".join(screens.lines(found))
    assert "TaskPulse  (2 visits)  not tried: Tags, Settings, Toggle Status" in text
    assert 'on Project Detail: "Export Project CSV"' in text


def test_report_shows_the_screens_visited(tmp_path):
    run = _run(tmp_path)
    (run / "session.json").write_text(json.dumps({"title": "T", "mode": "explore", "charter": "c",
                                                  "device": {"model": "Pixel"}, "app": {"package": "p"}}))
    (run / "findings.json").write_text('{"findings": []}')
    report.build(run)
    index = (run / "index.html").read_text(encoding="utf-8")
    assert "<h2>Screens visited</h2>" in index and "<th>Project Detail</th><td>1</td><td>Back</td>" in index


def test_chips_in_a_sideways_row_are_controls():
    chips = [_el("", (0, 400, 1080, 520), scrollable=True, z=(0, 1)),
             _el("Tags", (20, 410, 300, 510), clickable=True, z=(0, 1, 0)),
             _el("", (0, 600, 1080, 2000), scrollable=True, z=(0, 2)),
             _el("Buy milk", (20, 620, 1060, 700), clickable=True, z=(0, 2, 0))]
    assert screens.controls(chips) == ["Tags"]


def test_other_apps_screens_and_shared_controls(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "session.json").write_text('{"package": "com.example.app"}')
    screens.record(tmp_path, "lock", "Carrier", ["Unlocked"], package="com.android.systemui")
    screens.record(tmp_path, "home", "Home", ["Settings", "Profile"], package="com.example.app")
    screens.record(tmp_path, "set", "Settings", ["Home", "Settings", "Wipe data"], package="com.example.app")
    actions = [{"t": "2026-10-27T10:00:01.000+01:00", "action": "observe", "fp": "home"},
               {"t": "2026-10-27T10:00:02.000+01:00", "action": "tap", "target": '[5] "Settings"', "changed": True},
               {"t": "2026-10-27T10:00:03.000+01:00", "action": "observe", "fp": "set"}]
    (tmp_path / "logs" / "actions.jsonl").write_text("\n".join(json.dumps(a) for a in actions), encoding="utf-8")
    found = {row["title"]: row["untried"] for row in screens.inventory(tmp_path)["screens"]}
    assert found == {"Home": ["Profile"], "Settings": ["Home", "Wipe data"]}  # no lock screen; Settings tried
