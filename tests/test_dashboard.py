"""The live dashboard: its state from the run folder, the local server, and Pause, Stop and notes."""

import http.client
import json
import threading

import pytest

from mobiletester.core import control, dashboard
from mobiletester.core.dashboard_page import PAGE


@pytest.fixture
def run(tmp_path):
    folder = tmp_path / "2026-10-29-pantry-explore"
    (folder / "logs").mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({
        "title": "Pantry exploratory test", "mode": "explore", "charter": "Search", "time_box_min": 30,
        "started": "2026-10-29T10:00:00+01:00", "forbidden": ["placing an order"],
        "app": {"package": "com.example.pantry", "versionName": "1.4"}, "device": {"model": "Pixel 7a"}}))
    (folder / "findings.json").write_text(json.dumps({"findings": [
        {"id": "B1", "title": "Search crashes on '['", "type": "bug", "severity": "Critical", "status": "Confirmed"},
        {"id": "R1", "title": "Not a bug", "type": "bug", "status": "Retracted"}]}))
    actions = [
        {"t": "2026-10-29T10:00:05.000+01:00", "action": "observe", "fp": "home", "title": "Pantry"},
        {"t": "2026-10-29T10:00:07.000+01:00", "action": "tap", "x": 540, "y": 1200, "target": '[3] "Search"',
         "changed": True},
        {"t": "2026-10-29T10:00:09.000+01:00", "action": "type", "field": "Search items", "text": "[", "chars": 1,
         "crash": "PatternSyntaxException"},
        {"t": "2026-10-29T10:00:11.000+01:00", "action": "tap", "x": 100, "y": 200, "target": '[1] "Export"',
         "changed": False, "log_issues": ["error, Pantry: boom"]},
    ]
    (folder / "logs" / "actions.jsonl").write_text("\n".join(json.dumps(a) for a in actions), encoding="utf-8")
    (folder / "logs" / "screens.json").write_text(json.dumps(
        {"home": {"title": "Pantry", "visits": 1, "first": "", "controls": ["Search", "Export", "Settings"]}}))
    (folder / "bugs").mkdir()
    (folder / "bugs" / "B1.html").write_text("<p>bug page</p>")
    return folder


@pytest.fixture
def device_dir(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    (folder / "latest.json").write_text(json.dumps({"screen": [1080, 2400]}))
    (folder / "latest.png").write_bytes(b"\x89PNG observed")
    return folder


def test_state_shows_the_session_as_it_stands(run, device_dir):
    state = dashboard.build_state(run, device_dir)
    assert state["session"]["title"] == "Pantry exploratory test" and state["session"]["time_box_min"] == 30
    assert state["session"]["app"] == "com.example.pantry 1.4" and state["session"]["device"] == "Pixel 7a"
    assert [f["id"] for f in state["findings"]] == ["B1"]  # retracted findings don't show
    first, typed, tap = state["actions"]  # newest first, observations left out
    assert first == {"t": "10:00:11", "action": "tap", "target": '[1] "Export"', "changed": False, "log_issues": 1,
                     "point": [100, 200]}
    assert typed["target"] == "Search items: '['" and typed["crash"] == "PatternSyntaxException"
    assert tap["point"] == [540, 1200]
    assert state["screens"][0]["untried"] == ["Settings"]
    assert state["no_change"][0]["target"] == "Export"
    assert state["screen"]["size"] == [1080, 2400] and state["screen"]["title"] == "Pantry"
    assert state["control"] == {"state": "running", "notes": []} and state["report"] is False
    assert state["tokens"] == {"available": False}


def test_notes_are_delivered_once_and_pause_blocks_only_device_actions(run):
    control.add_note(run, "  also check   Settings ")
    assert control.gate(run, "observe", "adt") == [
        "NOTE from the person watching the dashboard: also check Settings"]
    assert control.gate(run, "observe", "adt") == []  # read once
    control.set_state(run, "paused")
    assert control.gate(run, "screens", "adt") == []  # reading and reporting go on
    with pytest.raises(control.Halted, match="PAUSED from the dashboard.*`adt control wait`"):
        control.gate(run, "tap", "adt")
    control.set_state(run, "stopped")
    with pytest.raises(control.Halted, match="STOP requested.*Wrap up now"):
        control.gate(run, "type", "adt")
    assert control.gate(None, "tap", "adt") == []  # outside a session nothing is checked


def test_wait_returns_when_the_person_resumes(run):
    control.set_state(run, "paused")
    threading.Timer(0.3, control.set_state, (run, "running")).start()
    assert control.wait(run, timeout=5, poll=0.05) == "running"
    assert control.wait(run, timeout=0.2, poll=0.05) == "running"
    control.set_state(run, "paused")
    assert control.wait(run, timeout=0.2, poll=0.05) == "paused"  # gave up


class Server:
    def __init__(self, board):
        self.port = None
        ready = threading.Event()

        def started(port):
            self.port = port
            ready.set()

        threading.Thread(target=dashboard.serve, args=(board, 0, PAGE, started), daemon=True).start()
        assert ready.wait(5)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection(dashboard.HOST, self.port, timeout=5)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, response.getheader("Content-Type"), response.read()


def test_server_pages_state_screens_run_files_and_control(run, device_dir):
    grabs = []
    board = dashboard.Dashboard(run, device_dir, grab=lambda: grabs.append(1) or b"\x89PNG live")
    server = Server(board)
    status, kind, body = server.request("GET", "/")
    assert status == 200 and kind.startswith("text/html") and b"Note to the agent" in body
    status, _, body = server.request("GET", "/api/state")
    assert status == 200 and json.loads(body)["screen"]["live"] is True
    assert server.request("GET", "/screen.png")[2] == b"\x89PNG observed"
    assert server.request("GET", "/live.png")[2] == b"\x89PNG live"
    server.request("GET", "/live.png")
    assert len(grabs) == 1  # one device screenshot a second, however often the page asks
    assert server.request("GET", "/run/bugs/B1.html")[2] == b"<p>bug page</p>"
    assert server.request("GET", "/run/../state/latest.png")[0] == 404  # nothing outside the run folder
    assert server.request("GET", "/run/%2e%2e/state/latest.json")[0] == 404
    status, _, body = server.request("POST", "/api/control", {"state": "paused", "note": "look at Settings"})
    assert status == 200 and json.loads(body)["state"] == "paused"
    assert control.read(run)["notes"][0]["text"] == "look at Settings"
    assert server.request("POST", "/api/control", {"state": "asleep"})[0] == 400


def test_events_push_the_state_when_a_file_changes(run, device_dir):
    server = Server(dashboard.Dashboard(run, device_dir))
    conn = http.client.HTTPConnection(dashboard.HOST, server.port, timeout=5)
    conn.request("GET", "/events")
    response = conn.getresponse()
    assert response.getheader("Content-Type") == "text/event-stream"

    def event():
        lines = []
        while (line := response.fp.readline().decode()) != "\n":
            lines.append(line)
        return json.loads(lines[-1].removeprefix("data: "))

    assert event()["control"]["state"] == "running"
    control.set_state(run, "stopped")  # the page's Stop button, or `adt control stop`
    assert event()["control"]["state"] == "stopped"
    conn.close()


def test_without_a_live_view_and_without_an_observation(run, tmp_path):
    empty = tmp_path / "empty-state"
    empty.mkdir()
    server = Server(dashboard.Dashboard(run, empty))
    assert server.request("GET", "/live.png")[0] == 404
    assert server.request("GET", "/screen.png")[0] == 404
    assert json.loads(server.request("GET", "/api/state")[2])["screen"]["live"] is False


def test_one_dashboard_per_device_started_reused_and_stopped(run, tmp_path, monkeypatch):
    import sys
    import urllib.request

    from mobiletester.core import commands

    monkeypatch.setenv("MT_HOME", str(tmp_path / "home"))
    worker = [sys.executable, "-c", "import http.server,sys; "
              "http.server.HTTPServer(('127.0.0.1', int(sys.argv[2])), http.server.SimpleHTTPRequestHandler)"
              ".serve_forever()"]
    url = commands.dashboard_start("serial-1", run, worker, port=8790)
    try:
        assert url.startswith("http://127.0.0.1:") and urllib.request.urlopen(url, timeout=5).status == 200
        assert commands.dashboard_start("serial-1", run, worker, port=8790) == url  # same run: reused
    finally:
        assert commands.dashboard_stop("serial-1") is True
    assert commands.dashboard_stop("serial-1") is False


def test_a_paused_session_stops_adt_before_it_touches_the_device(run, monkeypatch, capsys):
    from mobiletester.android import cli

    class NoDevice:
        serial = "serial-2"

        def __init__(self, serial):
            pass

    touched = []
    monkeypatch.setattr(cli, "Adb", NoDevice)
    monkeypatch.setattr(cli.session, "run_dir", lambda serial: run)
    monkeypatch.setitem(cli._WITH_DEVICE, "tap", lambda args, adb: touched.append(1) or 0)
    control.add_note(run, "try the Export button")
    control.set_state(run, "paused")
    assert cli.main(["tap", "--index", "3"]) == 5 and touched == []
    err = capsys.readouterr().err
    assert "NOTE from the person watching the dashboard: try the Export button" in err and "PAUSED" in err
    control.set_state(run, "running")
    assert cli.main(["tap", "--index", "3"]) == 0 and touched == [1]
