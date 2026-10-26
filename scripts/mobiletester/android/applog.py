"""App log checks: the app's own errors and warnings in the session's logcat stream.

After every action adt reads only the new lines of logs/logcat.txt (a local file, no device round trip
for the log itself) and keeps the lines from the app's processes that matter. Many apps log harmless errors,
so the check reports and logs them; whether one is a finding stays a judgement call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..core import state
from .adb import Adb

# `logcat -v threadtime`: "10-23 15:04:31.120  4321  4330 E Tag: message"
_LINE = re.compile(r"^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(.*?)\s*: (.*)$")
# ActivityManager announces new processes: "Start proc 12345:com.example.app:remote/u0a123 for activity ..."
_START_PROC = re.compile(r"Start proc (\d+):([\w.]+)(?::[\w.]+)?/")
_JANK = re.compile(r"Skipped (\d+) frames")
_NETWORK = re.compile(r"\b(UnknownHostException|SocketTimeoutException|SSLHandshakeException|SSLException|"
                      r"ConnectException|NoRouteToHostException)\b")
_EXCEPTION_START = re.compile(r"^\s*(?:Caused by: )?[\w$.]+(?:Exception|Error)\b")
_NUMBERS = re.compile(r"0x[0-9a-f]+|\d+")
JANK_FRAMES = 30  # below this, "Skipped N frames" is routine on a busy main thread

# Most serious first: the order of the wrap-up summary.
KINDS = ("out of memory", "error", "exception", "network", "strict mode", "skipped frames")


@dataclass(frozen=True)
class LogIssue:
    time: str
    kind: str
    tag: str
    text: str

    @property
    def key(self) -> str:
        """Same problem, different numbers (ids, ports, timings) -> same key."""
        return f"{self.kind}|{self.tag}|{_NUMBERS.sub('#', self.text)[:160]}"

    def short(self) -> str:
        return f"{self.kind}, {self.tag}: {self.text[:140]}"


def classify(level: str, tag: str, message: str) -> str | None:
    if "OutOfMemoryError" in message:
        return "out of memory"
    if tag.startswith("StrictMode"):
        return "strict mode"
    if (m := _JANK.search(message)) and int(m.group(1)) >= JANK_FRAMES:
        return "skipped frames"
    if level in "WEF" and _NETWORK.search(message):
        return "network"
    if tag == "System.err" and _EXCEPTION_START.match(message):
        return "exception"  # caught and printed: the app survived, but something failed
    if level in "EF":
        return "error"
    return None


def app_pids(ps_output: str, package: str) -> set[int]:
    """PIDs of the app's processes (the main one and `package:name` ones) from `ps -A -o PID,NAME`."""
    pids = set()
    for line in ps_output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and (parts[1] == package or parts[1].startswith(package + ":")):
            pids.add(int(parts[0]))
    return pids


def parse(lines: list[str], pids: set[int], package: str) -> tuple[list[LogIssue], set[int]]:
    """Issues from the app's processes; processes the app starts meanwhile are picked up from 'Start proc'."""
    pids = set(pids)
    issues = []
    for line in lines:
        m = _LINE.match(line)
        if not m:
            continue
        when, pid, _tid, level, tag, message = m.groups()
        if (started := _START_PROC.search(message)) and started.group(2) == package:
            pids.add(int(started.group(1)))
            continue
        if int(pid) in pids and (kind := classify(level, tag.strip(), message)):
            issues.append(LogIssue(when, kind, tag.strip(), message.strip()))
    return issues, pids


def _seen_file(serial: str) -> Path:
    return state.device_dir(serial) / "applog_seen.json"


def new_issues(adb: Adb, run: Path, package: str) -> list[LogIssue]:
    """Issues in the lines logcat wrote since the last check. Lines still being written wait for the next one."""
    log = run / "logs" / "logcat.txt"
    if not log.is_file():
        return []
    seen = state.read_json(_seen_file(adb.serial)) or {}
    if seen.get("file") != str(log):
        seen = {"file": str(log), "offset": 0, "pids": []}
    pids = set(seen["pids"])
    if not seen["offset"]:
        # Processes started before logcat was cleared have no "Start proc" line: look them up once.
        # Later starts (relaunch after a crash, a new :service process) show up in the log itself.
        pids |= app_pids(adb.shell("ps", "-A", "-o", "PID,NAME", check=False), package)
    with log.open("rb") as fh:
        fh.seek(seen["offset"])
        data = fh.read()
    complete = data.rfind(b"\n") + 1
    issues, pids = parse(data[:complete].decode("utf-8", errors="replace").splitlines(), pids, package)
    state.write_json(_seen_file(adb.serial), {"file": str(log), "offset": seen["offset"] + complete,
                                              "pids": sorted(pids)})
    return issues


def summarize(issues: list[LogIssue]) -> list[dict]:
    """One entry per distinct problem, most serious kind first, then the most frequent."""
    groups: dict[str, dict] = {}
    for issue in issues:
        group = groups.setdefault(issue.key, {"kind": issue.kind, "tag": issue.tag, "text": issue.text[:300],
                                              "count": 0, "first": issue.time})
        group["count"] += 1
    return sorted(groups.values(), key=lambda g: (KINDS.index(g["kind"]), -g["count"], g["first"]))


def session_summary(serial: str, run: Path, package: str) -> list[dict]:
    """The whole session's log, with every app PID the per-action checks saw."""
    log = run / "logs" / "logcat.txt"
    if not log.is_file():
        return []
    seen = state.read_json(_seen_file(serial)) or {}
    pids = set(seen.get("pids", [])) if seen.get("file") == str(log) else set()
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return summarize(parse(lines, pids, package)[0])
