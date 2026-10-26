"""`report diff`: two runs of the same app compared."""

import json

from mobiletester.core import diff


def _run(path, version, perf, findings, logs, screens):
    (path / "logs").mkdir(parents=True)
    (path / "session.json").write_text(json.dumps({
        "app": {"versionName": version, "versionCode": "1"}, "performance": perf, "log_summary": logs}),
        encoding="utf-8")
    (path / "findings.json").write_text(json.dumps({"findings": findings}), encoding="utf-8")
    (path / "logs" / "actions.jsonl").write_text("".join(
        json.dumps({"action": "observe", "fp": fp, "screen": name}) + "\n" for fp, name in screens), encoding="utf-8")
    return path


def test_compare_two_builds(tmp_path):
    a = _run(tmp_path / "a", "1.0", {"startup": {"cold_start_ms": 800}, "frames": {"janky_pct": 4.0}},
             [{"id": "B1", "title": "Counter sticks at 0", "status": "Confirmed", "known_issue": "K-1"},
              {"id": "B2", "title": "Crash on Help", "status": "Confirmed", "known_issue": "K-2"}],
             [{"kind": "network", "tag": "System.err", "text": "SocketTimeoutException after 10000ms", "count": 2}],
             [("aaa", "Home"), ("bbb", "Search")])
    b = _run(tmp_path / "b", "1.1", {"startup": {"cold_start_ms": 1000}, "frames": {"janky_pct": 4.1}},
             [{"id": "B1", "title": "Counter sticks at 0", "status": "Confirmed", "known_issue": "K-1"},
              {"id": "B2", "title": "Basket total wrong after removing an item", "status": "Confirmed",
               "severity": "Major"}],
             [{"kind": "network", "tag": "System.err", "text": "SocketTimeoutException after 20000ms", "count": 1},
              {"kind": "error", "tag": "Checkout", "text": "Price mismatch", "count": 3}],
             [("aaa", "Home"), ("ccc", "Checkout")])
    out = "\n".join(diff.compare(a, b))
    assert "build 1.0 1" in out and "build 1.1 1" in out
    assert "cold start: 800 -> 1000 ms (+25%)  WORSE" in out
    assert "janky frames: 4.0 -> 4.1 % (+2%)" in out and "4.1 % (+2%)  WORSE" not in out
    assert "new in B: [B2] Major: Basket total wrong after removing an item" in out
    assert "known issue K-2 seen in A, not in B" in out and "known issue K-1 still seen in B" in out
    assert "new in B: 3x error, Checkout: Price mismatch" in out
    app_log = out.split("App log")[1].split("Screens")[0]
    assert "SocketTimeout" not in app_log  # same problem, other numbers: not new
    assert "only in A: Search" in out and "only in B: Checkout" in out and "1 in both" in out
