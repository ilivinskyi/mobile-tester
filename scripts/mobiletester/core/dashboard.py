"""A live dashboard of a test session on 127.0.0.1: the screen, every action, findings, screens, the time box.

Nothing here talks to the agent. The tools already write each fact to the run folder as it happens
(session.json, findings.json, logs/actions.jsonl, logs/screens.json) and to the device's state folder
(latest.png from the last observation), so the server only reads those files and pushes a new state to the
page when one of them changes (server-sent events). The page's Pause, Stop and note box write the run's
control.json, which the CLI checks before each device action (core/control.py). For Claude Code the
session's transcript adds tokens, cost and the agent's latest message.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import control, screens, telemetry

HOST = "127.0.0.1"
_TAIL_BYTES = 400_000  # the agent's latest message is near the end of its transcript
_TOKENS_EVERY = 15.0  # seconds between transcript re-reads
_EVENTS_EVERY = 0.7
_LIVE_EVERY = 1.0  # at most one live screenshot a second
_IDLE_AFTER_END = 30 * 60  # the server stops itself this long after the session ended
_TYPES = {".html": "text/html; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".mp4": "video/mp4", ".json": "application/json", ".csv": "text/csv; charset=utf-8",
          ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
          ".log": "text/plain; charset=utf-8"}


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # missing, or caught mid-write: the next tick reads it again


def _actions(run: Path, limit: int) -> list[dict]:
    log = run / "logs" / "actions.jsonl"
    try:
        lines = log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _action_row(entry: dict) -> dict:
    """What the page shows for one action: when, what, on what, and how it went."""
    action = entry.get("action", "?")
    target = entry.get("target") or entry.get("title") or ""
    if action == "type":
        target = f"{entry.get('field') or 'a field'}: {entry['text']!r}" if "text" in entry else \
            f"{entry.get('chars', '?')} chars"
    row = {"t": (entry.get("t") or "")[11:19], "action": action, "target": target}
    for key in ("changed", "crash"):
        if key in entry:
            row[key] = entry[key]
    if entry.get("log_issues"):
        row["log_issues"] = len(entry["log_issues"])
    if "x" in entry and "y" in entry:
        row["point"] = [entry["x"], entry["y"]]
    return row


class Tokens:
    """Tokens, cost and the latest agent message from the Claude Code transcript, re-read now and then."""

    def __init__(self, transcript: Path | None):
        self.transcript = transcript
        self._at = 0.0
        self._stamp: float | None = None
        self.value: dict = {"available": False}

    def get(self, since: datetime | None) -> dict:
        if self.transcript is None or not self.transcript.is_file():
            return {"available": False}
        stamp = self.transcript.stat().st_mtime
        if stamp == self._stamp or time.monotonic() - self._at < _TOKENS_EVERY:
            return self.value
        self._at, self._stamp = time.monotonic(), stamp
        try:
            read = telemetry.read_transcript(self.transcript, since=since)
        except (OSError, ValueError):
            return self.value
        total: dict[str, int] = {}
        cost, priced = 0.0, True
        for model, tokens in read["by_model"].items():
            for key, value in tokens.items():
                total[key] = total.get(key, 0) + value
            dollars = telemetry.cost_usd(model, tokens)
            cost, priced = cost + (dollars or 0.0), priced and dollars is not None
        self.value = {"available": True, "agent": "Claude Code", "requests": total.get("requests", 0),
                      "input": total.get("input", 0) + total.get("cache_read", 0) + total.get("cache_write_5m", 0)
                      + total.get("cache_write_1h", 0), "output": total.get("output", 0),
                      "cost_usd": round(cost, 2) if priced else None, "peak_context": read["peak_context"],
                      "latest": _latest_message(self.transcript)}
        return self.value


def _latest_message(transcript: Path) -> str:
    """The last text the agent wrote, from the end of the transcript."""
    try:
        with transcript.open("rb") as fh:
            fh.seek(max(0, transcript.stat().st_size - _TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(tail):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        texts = [b.get("text", "") for b in (entry.get("message") or {}).get("content") or []
                 if isinstance(b, dict) and b.get("type") == "text"]
        if text := " ".join(t for t in texts if t).strip():
            return text if len(text) <= 600 else text[:599] + "…"
    return ""


def build_state(run: Path, device_dir: Path, tokens: Tokens | None = None, live: bool = False) -> dict:
    """Everything the page shows, from the run folder and the device's last observation."""
    session = _json(run / "session.json")
    findings = [f for f in _json(run / "findings.json").get("findings", []) if f.get("status") != "Retracted"]
    last = _json(device_dir / "latest.json")
    shot = device_dir / "latest.png"
    started = session.get("started")
    found = screens.inventory(run)
    app = session.get("app") or {}
    device = session.get("device") or {}
    return {
        "run": run.name,
        "session": {
            "title": session.get("title") or run.name, "mode": session.get("mode"), "charter": session.get("charter"),
            "started": started, "ended": session.get("ended"), "time_box_min": session.get("time_box_min"),
            "tester": session.get("tester"), "forbidden": session.get("forbidden") or [],
            "grants": session.get("grants") or [], "open_questions": session.get("open_questions") or [],
            "app": " ".join(str(app.get(k, "")) for k in ("package", "versionName")).strip(),
            "device": device.get("model") or device.get("name") or "",
        },
        "findings": [{k: f.get(k) for k in ("id", "title", "type", "severity", "status", "scope")} for f in findings],
        "actions": [_action_row(a) for a in reversed(_actions(run, 60)) if a.get("action") != "observe"][:40],
        "screens": found["screens"],
        "no_change": found["no_change"],
        "control": control.read(run),
        "screen": {"observed": shot.stat().st_mtime if shot.is_file() else None,
                   "size": last.get("screen"), "title": _last_title(run), "live": live},
        "report": (run / "index.html").is_file(),
        "tokens": (tokens.get(datetime.fromisoformat(started) if started else None) if tokens else
                   {"available": False}),
    }


def _last_title(run: Path) -> str:
    for entry in reversed(_actions(run, 30)):
        if entry.get("action") == "observe":
            return entry.get("title") or ""
    return ""


def _signature(run: Path, device_dir: Path) -> tuple:
    """Changes when anything the page shows changes."""
    files = [run / n for n in ("session.json", "findings.json", "control.json", "index.html")]
    files += [run / "logs" / n for n in ("actions.jsonl", "screens.json")] + [device_dir / "latest.png"]
    return tuple(f.stat().st_mtime if f.is_file() else 0 for f in files)


class Dashboard:
    def __init__(self, run: Path, device_dir: Path, grab: Callable[[], bytes] | None = None,
                 transcript: Path | None = None):
        self.run, self.device_dir, self.grab = run.resolve(), device_dir, grab
        self.tokens = Tokens(transcript)
        self._frame: bytes | None = None
        self._frame_at = 0.0
        self._lock = threading.Lock()

    def state(self) -> dict:
        return build_state(self.run, self.device_dir, self.tokens, live=self.grab is not None)

    def frame(self) -> bytes | None:
        """A live screenshot, at most one a second however many viewers ask."""
        if self.grab is None:
            return None
        with self._lock:
            if self._frame is None or time.monotonic() - self._frame_at >= _LIVE_EVERY:
                try:
                    self._frame, self._frame_at = self.grab(), time.monotonic()
                except Exception:  # noqa: BLE001 - a device hiccup leaves the last frame up
                    self._frame_at = time.monotonic()
            return self._frame

    def ended_long_ago(self) -> bool:
        ended = _json(self.run / "session.json").get("ended")
        if not ended:
            return False
        return (datetime.now().astimezone() - datetime.fromisoformat(ended)).total_seconds() > _IDLE_AFTER_END

    def run_file(self, rel: str) -> Path | None:
        """A file inside the run folder, never outside it."""
        target = (self.run / rel).resolve()
        return target if target.is_file() and target.is_relative_to(self.run) else None


def make_handler(board: Dashboard, page: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet: the worker's log only gets errors
            pass

        def _send(self, status: int, body: bytes, kind: str, cache: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=60" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - the http.server name
            url = urlparse(self.path)
            if url.path == "/":
                self._send(HTTPStatus.OK, page.encode("utf-8"), _TYPES[".html"])
            elif url.path == "/api/state":
                self._send(HTTPStatus.OK, json.dumps(board.state()).encode("utf-8"), _TYPES[".json"])
            elif url.path == "/events":
                self._events()
            elif url.path == "/screen.png":
                shot = board.device_dir / "latest.png"
                if shot.is_file():
                    self._send(HTTPStatus.OK, shot.read_bytes(), _TYPES[".png"])
                else:
                    self._send(HTTPStatus.NOT_FOUND, b"no observation yet", "text/plain")
            elif url.path == "/live.png":
                frame = board.frame()
                if frame:
                    self._send(HTTPStatus.OK, frame, _TYPES[".png"])
                else:
                    self._send(HTTPStatus.NOT_FOUND, b"no live view for this device", "text/plain")
            elif url.path.startswith("/run/"):
                target = board.run_file(unquote(url.path[len("/run/"):]))
                if target is None:
                    self._send(HTTPStatus.NOT_FOUND, b"not in this run", "text/plain")
                else:
                    kind = _TYPES.get(target.suffix.lower(), "application/octet-stream")
                    self._send(HTTPStatus.OK, target.read_bytes(), kind, cache=target.suffix != ".html")
            else:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/control":
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if body.get("state"):
                    control.set_state(board.run, body["state"])
                if body.get("note"):
                    control.add_note(board.run, str(body["note"])[:2000])
            except (ValueError, TypeError) as exc:
                self._send(HTTPStatus.BAD_REQUEST, str(exc).encode("utf-8"), "text/plain")
                return
            self._send(HTTPStatus.OK, json.dumps(control.read(board.run)).encode("utf-8"), _TYPES[".json"])

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen, beat = None, time.monotonic()
            try:
                while True:
                    now = _signature(board.run, board.device_dir)
                    if now != seen:
                        seen = now
                        self.wfile.write(b"data: " + json.dumps(board.state()).encode("utf-8") + b"\n\n")
                        self.wfile.flush()
                    elif time.monotonic() - beat > 15:
                        self.wfile.write(b": still here\n\n")  # keeps proxies and the browser from giving up
                        self.wfile.flush()
                        beat = time.monotonic()
                    time.sleep(_EVENTS_EVERY)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    return Handler


def serve(board: Dashboard, port: int, page: str, ready: Callable[[int], None] | None = None) -> None:
    """Serve until the session has been over for a while (or the process is stopped)."""
    server = ThreadingHTTPServer((HOST, port), make_handler(board, page))
    server.daemon_threads = True
    if ready:
        ready(server.server_address[1])

    def watch() -> None:
        while not board.ended_long_ago():
            time.sleep(30)
        server.shutdown()

    threading.Thread(target=watch, daemon=True).start()
    server.serve_forever(poll_interval=0.5)
    server.server_close()


def free_port(preferred: int) -> int:
    """`preferred` when free, else the next free one."""
    import socket

    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
                return port
            except OSError:
                continue
    raise OSError(f"no free port between {preferred} and {preferred + 49}")


def url(port: int) -> str:
    return f"http://{HOST}:{port}/"
