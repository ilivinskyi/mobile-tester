import csv
import json

import pytest

from mobiletester.core import report, report_text, telemetry

SESSION = {
    "title": "Shop Android - exploratory test", "mode": "explore", "charter": "Basket", "platform": "Android",
    "device": {"model": "Pixel 7a"}, "app": {"package": "com.example.shop", "versionName": "2.0"},
    "started": "2026-10-26T23:30:00+01:00", "ended": "2026-10-26T23:50:00+01:00",
}


def _usage(output, cache_read=1000, write_1h=0, thinking=0):
    return {"input_tokens": 10, "output_tokens": output, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": write_1h, "output_tokens_details": {"thinking_tokens": thinking},
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": write_1h}}


def _assistant(ts, mid, usage, blocks):
    return [{"type": "assistant", "timestamp": ts, "version": "2.1.311", "sessionId": "s-1",
             "message": {"id": mid, "model": "claude-opus-5-5", "usage": usage, "content": [block]}}
            for block in blocks]


TRANSCRIPT = [
    {"type": "user", "timestamp": "2026-10-26T22:20:00Z", "message": {"content": "test the shop app"}},
    {"type": "api-request", "timestamp": "2026-10-26T22:20:01Z", "querySource": "repl_main_thread:outputStyle:Learning",
     "params": {"output_config": {"effort": "medium"}}},
    # One response written as three lines (thinking, text, tool call) that repeat the same usage.
    *_assistant("2026-10-26T22:20:05Z", "m1", _usage(100, write_1h=5000, thinking=40),
                [{"type": "thinking"}, {"type": "text"}, {"type": "tool_use", "name": "PowerShell"}]),
    {"type": "user", "timestamp": "2026-10-26T22:35:00Z",
     "message": {"content": [{"type": "tool_result", "is_error": True}]}},
    *_assistant("2026-10-26T22:35:05Z", "m2", _usage(200), [{"type": "tool_use", "name": "PowerShell"}]),
    *_assistant("2026-10-26T22:55:00Z", "m3", _usage(300), [{"type": "tool_use", "name": "Read"}]),
    {"type": "user", "timestamp": "2026-10-26T23:30:00Z", "message": {"content": "later, unrelated work"}},
    *_assistant("2026-10-26T23:30:05Z", "m4", _usage(999), [{"type": "text"}]),
]


@pytest.fixture
def run(tmp_path):
    folder = tmp_path / "reports" / "2026-10-26-shop-explore"
    (folder / "logs").mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps(SESSION), encoding="utf-8")
    (folder / "findings.json").write_text(json.dumps({"findings": [
        {"id": "B1", "title": "Total wrong", "type": "bug", "status": "Confirmed", "actual": "0,00"},
        {"id": "O1", "title": "Slow list", "type": "observation", "status": "Confirmed", "actual": "2 s"},
        {"id": "O2", "title": "Odd icon", "type": "observation", "status": "Retracted", "notes": "Intended"}]}),
        encoding="utf-8")
    actions = [{"action": "tap", "mode": "human", "changed": True, "duration_s": 30},
               {"action": "tap", "mode": "fast", "changed": False, "duration_s": 30},
               {"action": "observe", "mode": "read"}]
    (folder / "logs" / "actions.jsonl").write_text("\n".join(map(json.dumps, actions)), encoding="utf-8")
    (folder / "logs" / "decisions.md").write_text("- 23:31 consent = reject\n- 23:32 login = guest\n",
                                                  encoding="utf-8")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(map(json.dumps, TRANSCRIPT)) + "\nnot json\n", encoding="utf-8")
    return folder, transcript


def test_transcript_counts_each_response_once_and_splits_phases(run):
    folder, transcript = run
    started, ended = (telemetry._time(SESSION[k]) for k in ("started", "ended"))
    t = telemetry.read_transcript(transcript, until=telemetry._time("2026-10-26T23:00:00Z"),
                                  started=started, ended=ended)
    opus = t["by_model"]["claude-opus-5-5"]
    assert opus["requests"] == 3
    assert opus["output"] == 600 and opus["thinking"] == 40 and opus["cache_write_1h"] == 5000
    assert {p: v["requests"] for p, v in t["by_phase"].items()} == {"onboarding": 1, "session": 1, "wrap_up": 1}
    assert t["tool_calls"] == {"PowerShell": 2, "Read": 1}
    assert t["tool_errors"] == 1 and t["user_turns"] == 1
    assert t["agent"] == {"name": "Claude Code", "version": "2.1.311", "session_id": "s-1",
                          "output_style": "Learning", "effort": "medium"}
    assert t["peak_context"] == 6010


def test_cost_of_known_model_at_list_prices():
    tokens = {"input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000, "cache_write_5m": 1_000_000,
              "cache_write_1h": 1_000_000}
    # 4 input + 20 output + 0.20 read + 4 * 1.25 + 4 * 2
    assert telemetry.cost_usd("claude-opus-5-5", tokens) == pytest.approx(37.20)


def test_cost_of_dated_snapshot_uses_its_alias_price():
    assert telemetry.cost_usd("claude-haiku-4-5-20251001", {"output": 1_000_000}) == pytest.approx(5.00)


def test_cost_of_unknown_model_is_none():
    assert telemetry.cost_usd("some-other-model", {"input": 1, "output": 1}) is None


def test_collect_writes_activity_and_history(run):
    folder, transcript = run
    tech = telemetry.collect(folder, transcript, until=telemetry._time("2026-10-26T23:00:00Z"))
    assert tech["minutes"] == {"total": 35.0, "onboarding": 10.0, "session": 20.0, "wrap_up": 5.0}
    assert tech["device_actions"] == {"total": 3, "by_action": {"tap": 2, "observe": 1},
                                      "by_mode": {"human": 1, "fast": 1, "read": 1}, "fast": 1,
                                      "no_visible_change": 1, "device_time_min": 1.0}
    assert tech["autopilot_decisions"] == 2
    assert tech["findings"] == {"bug": 1, "observation": 1}
    assert tech["cost_usd"]["total"] is not None

    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    history = folder.parent / "telemetry.csv"
    telemetry.append_history(history, telemetry.history_row(folder, session, tech))
    telemetry.append_history(history, telemetry.history_row(folder, session, tech))
    rows = list(csv.DictReader(history.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["run"] == "2026-10-26-shop-explore" and rows[0]["output"] == "600"


def test_without_transcript_the_report_says_so(run):
    folder, _ = run
    tech = telemetry.collect(folder, None)
    assert "tokens" not in tech
    rows = dict(report_text.technical_rows(tech))
    assert "no agent transcript" in rows["Agent"]
    assert rows["Duration"] == "test session 20.0 min"


def test_report_shows_technical_data_at_the_end(run):
    folder, transcript = run
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    session["technical"] = telemetry.collect(folder, transcript, until=telemetry._time("2026-10-26T23:00:00Z"))
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8")
    report.build(folder)
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert "<h2>Technical data</h2>" in page
    assert page.index("Technical data") > page.index("Session details")
    assert "Phase: wrap-up" in page and "Device actions" in page


def test_no_technical_section_when_not_collected():
    assert report_text.technical_rows({}) == []
