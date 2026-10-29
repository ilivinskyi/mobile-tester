"""Pause, Stop and notes from the dashboard (or `dt control`), passed to the agent through the run folder.

The agent can't be interrupted from outside, but every device action goes through `adt` or `idt`, so the
CLI checks `control.json` in the active run before each one: a pause or a stop blocks the action with a
message the agent acts on, and a note from the person watching is printed once with the next command.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

STATES = ("running", "paused", "stopped")
# Commands that change the device or the app: blocked while paused or stopped. Reading the screen, writing
# findings and ending the session stay allowed, so the agent can always wrap up.
ACTING = {"tap", "type", "key", "swipe", "scroll", "app", "open", "rotate", "env", "net", "permissions",
          "media", "location", "bio", "clipboard", "touches", "hook", "check", "perf", "record"}


def path(run: Path) -> Path:
    return run / "control.json"


def read(run: Path) -> dict:
    try:
        data = json.loads(path(run).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"state": data.get("state") if data.get("state") in STATES else "running",
            "notes": data.get("notes") or []}


def _write(run: Path, data: dict) -> None:
    tmp = path(run).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path(run))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def set_state(run: Path, state: str) -> dict:
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    data = read(run)
    data["state"] = state
    _write(run, data)
    return data


def add_note(run: Path, text: str) -> dict:
    text = " ".join(text.split())
    if not text:
        raise ValueError("a note needs some text")
    data = read(run)
    data["notes"].append({"time": _now(), "text": text, "delivered": False})
    _write(run, data)
    return data


def take_notes(run: Path) -> list[str]:
    """Notes the agent hasn't seen yet, marked as seen."""
    data = read(run)
    fresh = [n for n in data["notes"] if not n.get("delivered")]
    if not fresh:
        return []
    for n in fresh:
        n["delivered"] = True
    _write(run, data)
    return [n["text"] for n in fresh]


class Halted(Exception):
    """A pause or stop from the dashboard blocks this action."""


def gate(run: Path | None, command: str, tool: str) -> list[str]:
    """Lines to print before a command: new notes from the dashboard. Raises Halted for an acting command
    while the session is paused or stopped."""
    if run is None:
        return []
    lines = [f"NOTE from the person watching the dashboard: {text}" for text in take_notes(run)]
    state = read(run)["state"]
    if command in ACTING and state == "paused":
        raise Halted("\n".join(lines + [
            f"PAUSED from the dashboard: don't act on the device. Run `{tool} control wait` (it returns when "
            "the person resumes or stops the session), then carry on or wrap up."]))
    if command in ACTING and state == "stopped":
        raise Halted("\n".join(lines + [
            "STOP requested from the dashboard: no more testing. Wrap up now: end the session, finish the "
            "findings and the report, and ask the collected questions."]))
    return lines


def wait(run: Path, timeout: float = 600, poll: float = 1.0) -> str:
    """Block while paused; return the state the session left the pause with ('paused' on timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read(run)["state"]
        if state != "paused":
            return state
        time.sleep(poll)
    return "paused"
