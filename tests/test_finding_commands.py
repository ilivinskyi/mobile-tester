"""`finding add|update|retract` and `report set|add` write the run files and validate at once."""

import json

import pytest

from mobiletester.android.cli import main


@pytest.fixture
def run(tmp_path):
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "b1.png").write_bytes(b"\x89PNG")
    (tmp_path / "findings.json").write_text('{"findings": []}', encoding="utf-8")
    (tmp_path / "session.json").write_text('{"mode": "explore"}', encoding="utf-8")
    return tmp_path


def _findings(run):
    return json.loads((run / "findings.json").read_text(encoding="utf-8"))["findings"]


def test_add_a_complete_bug(run, capsys):
    code = main(["finding", "add", str(run), "B1", "--type", "bug", "--title", "Counter sticks at 0",
                 "--severity", "Minor", "--priority", "P3", "--steps", "Open a note", "Type 999",
                 "--expected", "Capped at 99", "--actual", "Shows 0", "--automated", "2/2", "--manual", "not tried",
                 "--evidence", "screenshots/b1.png::Stuck at 0"])
    assert code == 0, capsys.readouterr().out
    [bug] = _findings(run)
    assert bug["steps"] == ["Open a note", "Type 999"] and bug["status"] == "Confirmed"
    assert bug["reproducibility"] == {"automated": "2/2", "manual": "not tried"}
    assert bug["evidence"] == [{"type": "screenshot", "path": "screenshots/b1.png", "caption": "Stuck at 0"}]


def test_problems_are_reported_when_written(run, capsys):
    code = main(["finding", "add", str(run), "B1", "--type", "bug", "--title", "Crash", "--severity", "Major"])
    out = capsys.readouterr().out
    assert code == 2 and "saved" in out and "problem: finding B1: 'steps' is required" in out
    assert len(_findings(run)) == 1  # kept, to be completed with `finding update`


def test_update_adds_evidence_and_retract_keeps_the_finding(run, capsys):
    main(["finding", "add", str(run), "O1", "--type", "observation", "--title", "Odd copy", "--actual", "Mixed"])
    assert main(["finding", "update", str(run), "O1", "--evidence", "screenshots/b1.png"]) == 0
    assert main(["finding", "update", str(run), "O1", "--evidence", "screenshots/b1.png"]) == 0  # no duplicate
    assert len(_findings(run)[0]["evidence"]) == 1
    assert main(["finding", "retract", str(run), "O1", "--reason", "Intended wording"]) == 0
    assert _findings(run)[0]["status"] == "Retracted" and _findings(run)[0]["notes"] == "Intended wording"
    assert main(["finding", "add", str(run), "O1", "--type", "observation", "--title", "x"]) == 2


def test_session_fields(run):
    assert main(["report", "set", str(run), "summary", "All main flows work."]) == 0
    assert main(["report", "set", str(run), "time_box_min", "30"]) == 0
    assert main(["report", "add", str(run), "not_covered", "Payments", "Sync"]) == 0
    assert main(["report", "add", str(run), "not_covered", "Sync"]) == 0
    data = json.loads((run / "session.json").read_text(encoding="utf-8"))
    assert data["summary"] == "All main flows work." and data["time_box_min"] == 30
    assert data["not_covered"] == ["Payments", "Sync"]
