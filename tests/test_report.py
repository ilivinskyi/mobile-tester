import csv
import io
import json

import pytest

from mobiletester.core import report, report_html, report_text

SESSION = {
    "title": "Notes app Android - exploratory test", "mode": "explore", "charter": "Editing and sync",
    "tester": "Test Er", "ticket": {"key": "PROJ-1", "summary": "Editor"},
    "device": {"model": "Pixel 7a", "android": "17", "sdk": "37", "emulator": False, "navigation": "gesture",
               "keyboard": "com.google.android.inputmethod.latin/x", "locale": "en-US"},
    "app": {"package": "com.example.notes", "versionName": "1.0", "versionCode": "10"},
    "input": "adt human mode", "not_covered": ["Sync conflicts"],
}


def _bug(**over):
    bug = {
        "id": "B1", "title": "Number field sticks at 0", "type": "bug", "status": "Confirmed", "severity": "Medium",
        "priority": "P2", "steps": ["Open a note", "Type 999 in the counter"], "expected": "Capped",
        "actual": "Shows 0",
        "reproducibility": {"automated": "2/2", "manual": "1/1"},
        "evidence": [{"type": "screenshot", "path": "screenshots/b1.png", "caption": "stuck"}],
    }
    bug.update(over)
    return bug


@pytest.fixture
def run(tmp_path):
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "b1.png").write_bytes(b"\x89PNG")
    (tmp_path / "session.json").write_text(json.dumps(SESSION), encoding="utf-8")

    def write(findings):
        (tmp_path / "findings.json").write_text(json.dumps({"findings": findings}), encoding="utf-8")
        return tmp_path

    return write


FULL = [
    _bug(severity="Major"),
    _bug(id="B2", status="Unconfirmed", severity="Major", reproducibility={"automated": "17/18", "manual": "0/2"}),
    {"id": "A1", "title": "Label read twice", "type": "accessibility", "status": "Confirmed",
     "severity": "Minor", "expected": "Read once", "actual": "Read twice"},
    {"id": "O1", "title": "Odd copy", "type": "observation", "status": "Confirmed", "actual": "Mixed tone"},
    {"id": "O2", "title": "Settings icon misaligned", "type": "observation", "status": "Confirmed",
     "scope": "outside", "actual": "On Settings, the gear icon sits 4 px low."},
    {"id": "R1", "title": "Values missing", "type": "accessibility", "status": "Retracted",
     "notes": "Parser dropped them"},
]


def test_valid_run_passes_and_builds_list_and_pages(run):
    directory = run(FULL)
    assert report.check(directory) == []
    written = {p.name for p in report.build(directory)}
    assert written == {"index.html", "findings.csv", "B1.md", "B2.md", "A1.md",
                       "B1.html", "B2.html", "A1.html", "O1.html", "O2.html", "R1.html"}
    index = (directory / "index.html").read_text(encoding="utf-8")
    for fid in ("B1", "B2", "A1", "O1", "O2", "R1"):
        assert f'href="bugs/{fid}.html"' in index
    assert "Noticed outside the scope" in index and "Retracted" in index
    # Outside-scope findings are not counted in the headline.
    assert "1 bug," not in index and "2 bugs, 1 accessibility issue and 1 observation" in index
    md = (directory / "bugs" / "B1.md").read_text(encoding="utf-8")
    assert "**Steps to reproduce:**" in md and "1. Open a note" in md and "gesture navigation" in md
    assert "PROJ-1" in md


def test_bug_page_has_viewer_navigation_and_jira_copy(run):
    directory = run(FULL)
    report.build(directory)
    page = (directory / "bugs" / "B1.html").read_text(encoding="utf-8")
    assert 'href="../index.html"' in page
    assert '<dialog class="viewer"' in page and 'class="icon close"' in page and "Open original" in page
    assert 'data-full="../screenshots/b1.png"' in page
    for copy in ("copy-md", "copy-title", "copy-wiki"):
        assert f'data-copy="{copy}"' in page and f'<template id="{copy}">' in page
    # The description goes into Jira's Description field; the title has its own button.
    description = page.split('<template id="copy-md">', 1)[1].split("</template>", 1)[0]
    assert "Number field sticks at 0" not in description and "**Steps to reproduce:**" in description
    assert 'rel="next"' in page
    observation = (directory / "bugs" / "O1.html").read_text(encoding="utf-8")
    assert 'data-copy="' not in observation  # no Jira draft for observations


def test_problems_are_reported(run):
    directory = run([
        _bug(severity="Medium"),                                               # invalid severity
        _bug(id="B2", steps=[], evidence=[{"type": "video", "path": "videos/missing.mp4"}]),
        _bug(id="B3", status="Unconfirmed", reproducibility={"automated": "3/3"}),
        _bug(id="B4", severity="Major", reproducibility={"automated": "3/3"}),  # Major, automation only
        {"id": "R1", "title": "x", "type": "bug", "status": "Retracted"},       # no reason
        {"id": "O1", "title": "x", "type": "observation", "status": "Confirmed", "scope": "elsewhere"},
    ])
    problems = "\n".join(report.check(directory))
    assert "finding B1: severity must be one of" in problems
    assert "finding B2: 'steps' is required" in problems
    assert "evidence file not found: videos/missing.mp4" in problems
    assert "finding B3: an Unconfirmed finding must state the manual result" in problems
    assert "finding B4: a Major bug confirmed only by automation should be Unconfirmed" in problems
    assert "finding R1: a retracted finding must say why" in problems
    assert "finding O1: scope must be one of" in problems


def test_outside_scope_findings_need_only_what_was_seen(run):
    directory = run([{"id": "B9", "title": "Crash on Help screen", "type": "bug", "status": "Confirmed",
                      "scope": "outside", "actual": "Opening Help closes the app."}])
    assert report.check(directory) == []


def test_test_results_rendered_and_validated(run, tmp_path):
    session = dict(SESSION, mode="test-case", test_results=[
        {"case": "TC-1 Create a note", "step": 2, "result": "fail", "finding": "B1"},
        {"case": "TC-2 Search", "result": "pass"},
    ])
    (tmp_path / "session.json").write_text(json.dumps(session), encoding="utf-8")
    directory = run([_bug(severity="Minor")])
    assert report.check(directory) == []
    report.build(directory)
    page = (directory / "index.html").read_text(encoding="utf-8")
    assert "Test results" in page and 'href="bugs/B1.html">B1' in page and "Pass" in page

    session["test_results"].append({"case": "TC-3", "result": "blocked"})
    (tmp_path / "session.json").write_text(json.dumps(session), encoding="utf-8")
    assert any("needs 'finding' or 'note'" in p for p in report.check(directory))


def test_history_known_issue_and_performance_are_shown(run, tmp_path):
    session = dict(SESSION, performance={
        "startup": {"cold_start_ms": 812, "samples_ms": [790, 812, 905]},
        "frames": {"frames": 465, "janky": 17, "janky_pct": 3.66, "p50_ms": 7, "p90_ms": 12, "p99_ms": 48},
        "memory": {"pss_kb": 248054, "rss_kb": 445580}})
    (tmp_path / "session.json").write_text(json.dumps(session), encoding="utf-8")
    history = [{"time": "2026-10-24T09:12:00+02:00", "action": "manual-check", "result": "reproduced",
                "tries": "2/2", "by": "Ihor", "build": "1.0 (10)", "device": "Pixel 7a",
                "status": "Unconfirmed -> Confirmed"}]
    directory = run([_bug(severity="Minor", known_issue="K-3", history=history),
                     _bug(id="B2", severity="Minor", known_issue="K-4", new_issue=True)])
    assert report.check(directory) == []
    report.build(directory)
    index = (directory / "index.html").read_text(encoding="utf-8")
    assert "K-3 seen again" in index and "1 is a known issue seen again" in index
    assert "812 ms (median of 3 launches" in index and "3.66% janky (17 of 465 frames)" in index
    assert "242 MB PSS" in index
    page = (directory / "bugs" / "B1.html").read_text(encoding="utf-8")
    sentence = ("Manual check: reproduced 2/2 by Ihor, on Pixel 7a with build 1.0 (10). "
                "Status: Unconfirmed to Confirmed.")
    assert sentence in page and "Known issue K-3" in page
    md = (directory / "bugs" / "B1.md").read_text(encoding="utf-8")
    assert f"- 2026-10-24 09:12 {sentence}" in md and "**Known issue:** K-3 (seen again)" in md


def _check(result, tries, note="", time="2026-10-24T09:12:00+02:00"):
    entry = {"time": time, "action": "manual-check", "result": result, "tries": tries, "by": "Ihor",
             "build": "1.0 (10)", "device": "Pixel 7a"}
    return dict(entry, note=note) if note else entry


def test_manual_verdict_follows_the_checks():
    yes, no = _check("reproduced", "2/2"), _check("not-reproduced", "0/1")
    assert report_text.manual_verdict([], None) == "none"
    assert report_text.manual_verdict([yes], (2, 2)) == "yes"
    assert report_text.manual_verdict([no], (0, 1)) == "no"
    # No history entries, only the count the tester wrote in the finding.
    assert report_text.manual_verdict([], (1, 1)) == "yes"
    assert report_text.manual_verdict([], (0, 2)) == "no"
    assert report_text.manual_verdict([], (0, 0)) == "none"
    # A person reproduced it once: the bug is real, even if a later try failed.
    assert report_text.manual_verdict([yes, no], (2, 3)) == "yes"
    assert report_text.manual_verdict([no, no], (0, 2)) == "no"


def test_manual_check_is_marked_on_the_list_and_on_top_of_the_page(run):
    directory = run([
        _bug(severity="Major", history=[_check("reproduced", "2/2", note="Also on the tablet layout.")],
             reproducibility={"automated": "2/2", "manual": "2/2"}),
        _bug(id="B2", status="Unconfirmed", severity="Major", reproducibility={"automated": "3/3", "manual": "0/1"},
             history=[_check("not-reproduced", "0/1")]),
        _bug(id="B3", severity="Minor", reproducibility={"automated": "2/2"}),
        _bug(id="B4", status="Unconfirmed", severity="Major",
             reproducibility={"automated": "3/3", "manual": "not tried"}),
    ])
    assert report.check(directory) == []
    report.build(directory)
    index = (directory / "index.html").read_text(encoding="utf-8")
    assert 'data-id="B1"' in index and 'data-manual="yes"' in index and 'data-manual="no"' in index
    assert index.count('class="pill manual manual-yes"') == 1 and index.count('class="pill manual manual-no"') == 1
    assert "<legend>Manual check</legend>" in index and "Not checked by hand" in index

    b1 = (directory / "bugs" / "B1.html").read_text(encoding="utf-8")
    block = b1[b1.index('class="manual-check manual-yes"'):]
    assert "Reproduced by hand" in block and "2 of 2 tries by Ihor on 2026-10-24, Pixel 7a, build 1.0 (10)." in block
    assert "Also on the tablet layout." in block
    assert b1.index("manual-check") < b1.index('class="bug-grid"')

    b2 = (directory / "bugs" / "B2.html").read_text(encoding="utf-8")
    assert "Not reproduced by hand" in b2 and "Automation still reproduces it (automated 3/3, manual 0/1)" in b2
    assert "Needs a manual reproduction" not in b2

    b3 = (directory / "bugs" / "B3.html").read_text(encoding="utf-8")
    assert 'class="manual-check manual-none"' in b3 and "Only automation reproduced this (automated 2/2)." in b3
    b4 = (directory / "bugs" / "B4.html").read_text(encoding="utf-8")
    assert "Needs a manual reproduction" in b4 and 'class="manual-check' not in b4


def test_retest_results_use_bug_lifecycle_words(run, tmp_path):
    session = dict(SESSION, mode="retest", test_results=[
        {"case": "K-3 Field resets after rotation", "issue": "K-3", "result": "pass"},
        {"case": "K-4 Crash on Help", "issue": "K-4", "result": "fail", "note": "Still crashes"},
    ])
    (tmp_path / "session.json").write_text(json.dumps(session), encoding="utf-8")
    directory = run([])
    report.build(directory)
    index = (directory / "index.html").read_text(encoding="utf-8")
    assert "Retest results" in index and "Fixed" in index and "Still reproduces" in index


def test_bad_known_issue_and_history_are_reported(run):
    directory = run([_bug(severity="Minor", known_issue="3", history=[{"action": "manual-check"}])])
    problems = "\n".join(report.check(directory))
    assert "known_issue must look like 'K-3'" in problems and "history[1] needs 'time' and 'action'" in problems


def test_html_escapes_content(run):
    directory = run([_bug(severity="Minor", title="<script>alert(1)</script>",
                          notes="ends </script> early")])
    report.build(directory)
    for page in ("index.html", "bugs/B1.html"):
        text = (directory / page).read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in text
    bug_page = (directory / "bugs" / "B1.html").read_text(encoding="utf-8")
    # The copy texts are escaped inside <template>, so the page keeps exactly its one script.
    assert bug_page.count("</script>") == 1 and "ends &lt;/script&gt; early" in bug_page


def test_list_is_grouped_by_severity_and_pages_follow_it(run):
    directory = run([
        _bug(id="B10", severity="Minor", priority="P3"),
        _bug(id="B2", severity="Major", priority="P2"),
        _bug(id="B3", severity="Major", priority="P1"),
        {"id": "O1", "title": "Odd copy", "type": "observation", "status": "Confirmed", "actual": "Mixed tone"},
        _bug(id="B1", severity="Minor", priority="P3"),
    ])
    report.build(directory)
    index = (directory / "index.html").read_text(encoding="utf-8")
    positions = [index.index(f'data-id="{fid}"') for fid in ("B3", "B2", "B1", "B10", "O1")]
    assert positions == sorted(positions)
    assert index.index(">Major<") < index.index(">Minor<") < index.index(">Observations<")
    page = (directory / "bugs" / "B2.html").read_text(encoding="utf-8")
    assert 'id="prev" rel="prev" href="B3.html"' in page and 'id="next" rel="next" href="B1.html"' in page
    assert "2 of 5" in page


def test_csv_and_wiki_markup_for_jira(run):
    directory = run(FULL)
    report.build(directory)
    rows = list(csv.reader(io.StringIO((directory / "findings.csv").read_text(encoding="utf-8"))))
    assert rows[0] == ["Summary", "Description", "Issue Type", "Priority", "Labels", "Labels", "Labels"]
    by_summary = {r[0]: r for r in rows[1:]}
    assert set(by_summary) == {"[B1] Number field sticks at 0", "[B2] Number field sticks at 0",
                               "[A1] Label read twice"}  # no observations, nothing retracted
    b1 = by_summary["[B1] Number field sticks at 0"]
    assert b1[2:] == ["Bug", "High", "android-tester", "severity-major", "type-bug"]
    assert "*Steps to reproduce:*\n# Open a note\n# Type 999 in the counter" in b1[1]
    wiki = report_text.render_jira_wiki(SESSION, _bug(notes="See [this] {code}"))
    assert r"*Notes:* See \[this\] \{code\}" in wiki and "{{screenshots/b1.png}}" in wiki


def test_outputs_of_findings_that_no_longer_qualify_are_removed(run):
    directory = run([_bug(severity="Minor")])
    report.build(directory)
    assert (directory / "bugs" / "B1.md").is_file() and (directory / "findings.csv").is_file()
    run([_bug(severity="Minor", status="Retracted", notes="Expected behaviour")])
    report.build(directory)
    assert not (directory / "bugs" / "B1.md").exists() and not (directory / "findings.csv").exists()
    page = (directory / "bugs" / "B1.html").read_text(encoding="utf-8")
    assert "Why it was retracted" in page and "Expected behaviour" in page


def test_page_order_puts_outside_scope_then_retracted_last():
    findings = [{"id": "R1", "title": "x", "type": "bug", "status": "Retracted"},
                {"id": "B9", "title": "x", "type": "bug", "status": "Confirmed", "scope": "outside",
                 "severity": "Blocker"},
                _bug(id="B1", severity="Trivial")]
    assert [f["id"] for f in report_html.page_order(findings)] == ["B1", "B9", "R1"]


def test_app_log_section_lists_grouped_issues(run, tmp_path):
    session = dict(SESSION, log_summary=[{"kind": "network", "tag": "System.err", "count": 3,
                                          "text": "java.net.SocketTimeoutException: timeout", "first": "10-23 15:04"}])
    (tmp_path / "session.json").write_text(json.dumps(session), encoding="utf-8")
    directory = run([])
    report.build(directory)
    index = (directory / "index.html").read_text(encoding="utf-8")
    assert "<h2>App log</h2>" in index and "3x network" in index and "SocketTimeoutException" in index


IOS_SESSION = {
    **SESSION, "title": "Habits iOS - exploratory test", "platform": "iOS", "input": "idt human mode",
    "device": {"platform": "iOS", "model": "iPhone 17", "os": "iOS 27.0", "kind": "simulator",
               "screen": "402x874 pt @3x", "navigation": "back by left-edge swipe or the app's back button",
               "keyboard": "iOS keyboard (en_US)", "locale": "en_US"},
    "app": {"package": "com.github.aint.Habits", "versionName": "1.0", "versionCode": "1"},
}


def test_environment_of_an_ios_session_has_no_android_words():
    rows = dict(report_text.environment(IOS_SESSION))
    assert rows["Device"] == "iPhone 17, iOS 27.0, 402x874 pt @3x"
    assert rows["Device kind"] == "simulator"
    assert rows["Navigation and keyboard"] == "back by left-edge swipe or the app's back button, iOS keyboard (en_US)"
    line = report_text.environment_line(IOS_SESSION)
    assert "Android" not in line and "API" not in line
    assert line.startswith("iPhone 17, iOS 27.0, simulator")


def test_environment_of_an_android_session_is_unchanged():
    rows = dict(report_text.environment(SESSION))
    # Missing facts are left out instead of leaving gaps ("at  dpi").
    assert rows["Device"] == "Pixel 7a, Android 17 (API 37)"
    assert rows["Device kind"] == "physical"
    assert rows["Navigation and keyboard"] == "gesture navigation, Gboard"
    assert report_text.environment_line(SESSION).startswith("Pixel 7a, Android 17 (API 37), physical device")


def test_csv_labels_name_the_platform(tmp_path):
    rows = list(csv.reader(io.StringIO(report_text.render_jira_csv(IOS_SESSION, [_bug(severity="Major")]))))
    assert rows[1][4] == "ios-tester"
