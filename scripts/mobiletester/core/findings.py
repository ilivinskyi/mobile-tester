"""Writing findings.json and session.json through commands, not by editing the files.

Each change is validated with the report's own checks right away, so a missing field shows up when the
finding is written, not at wrap-up; and an agent never has to read or rewrite the whole file.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import report

SCALAR_FIELDS = ("title", "type", "status", "severity", "priority", "area", "summary", "expected", "actual",
                 "notes", "scope", "known_issue")
LIST_FIELDS = ("preconditions", "steps")
SESSION_TEXT = ("title", "subtitle", "summary", "charter", "tester", "mode", "ticket")
SESSION_INT = ("time_box_min",)
# Facts about the app under test that `session start` can't know, such as where the build came from.
SESSION_APP = ("install_source",)
# What the session plan agreed (forbidden, grants, approvals) and the questions kept for the wrap-up.
SESSION_LISTS = ("worked_well", "coverage", "not_covered", "setup_steps_fast", "forbidden", "grants", "approvals",
                 "open_questions")
_EVIDENCE_TYPES = {".png": "screenshot", ".jpg": "screenshot", ".jpeg": "screenshot", ".mp4": "video",
                   ".mov": "video", ".txt": "log", ".log": "log", ".xml": "xml", ".json": "other"}


class FindingError(ValueError):
    pass


def write_json(path: Path, data: dict) -> None:
    """Write via a temporary file, so an interrupted write never leaves half a file behind."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load(run: Path, name: str) -> dict:
    path = run / name
    if not path.is_file():
        raise FindingError(f"{path} not found: is {run} a run folder (adt/idt session start)?")
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_entry(spec: str) -> dict:
    """'screenshots/b1.png' or 'screenshots/b1.png::Blank Start tab' -> an evidence entry."""
    path, _, caption = spec.partition("::")
    entry = {"type": _EVIDENCE_TYPES.get(Path(path).suffix.lower(), "other"), "path": path.replace("\\", "/")}
    if caption:
        entry["caption"] = caption
    return entry


def apply(finding: dict, values: dict) -> dict:
    """Set the given fields. Lists replace the old ones; evidence is added to what is there."""
    for key in SCALAR_FIELDS + LIST_FIELDS:
        if values.get(key) is not None:
            finding[key] = values[key]
    repro = dict(finding.get("reproducibility") or {})
    for key in ("automated", "manual"):
        if values.get(key) is not None:
            repro[key] = values[key]
    if repro:
        finding["reproducibility"] = repro
    if values.get("clear_evidence"):
        finding["evidence"] = []
    for spec in values.get("evidence") or []:
        entry = evidence_entry(spec)
        evidence = finding.setdefault("evidence", [])
        if all(e["path"] != entry["path"] for e in evidence):
            evidence.append(entry)
    return finding


def problems_of(run: Path, fid: str) -> list[str]:
    return [p for p in report.check(run) if p.startswith(f"finding {fid}:")]


def add(run: Path, fid: str, values: dict) -> list[str]:
    data = _load(run, "findings.json")
    findings = data.setdefault("findings", [])
    if any(f.get("id") == fid for f in findings):
        raise FindingError(f"finding {fid} already exists: use `finding update`")
    findings.append(apply({"id": fid}, values))
    write_json(run / "findings.json", data)
    return problems_of(run, fid)


def update(run: Path, fid: str, values: dict) -> list[str]:
    data = _load(run, "findings.json")
    finding = next((f for f in data.get("findings", []) if f.get("id") == fid), None)
    if finding is None:
        raise FindingError(f"no finding {fid} in {run / 'findings.json'}")
    apply(finding, values)
    write_json(run / "findings.json", data)
    return problems_of(run, fid)


def retract(run: Path, fid: str, reason: str) -> list[str]:
    return update(run, fid, {"status": "Retracted", "notes": reason})


def session_set(run: Path, field: str, value: str) -> None:
    data = _load(run, "session.json")
    if field in SESSION_INT:
        data[field] = int(value)
    elif field in SESSION_TEXT:
        data[field] = value
    elif field in SESSION_APP:
        data.setdefault("app", {})[field] = value
    else:
        raise FindingError(f"`set` takes one of {SESSION_TEXT + SESSION_INT + SESSION_APP}; lists go through `add`")
    write_json(run / "session.json", data)


def record_decision(run: Path, key: str, value: str, why: str) -> dict:
    """An autopilot decision: in session.json for the report, and in logs/decisions.md for people."""
    data = _load(run, "session.json")
    entry = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "key": key, "value": value,
             "why": why}
    data.setdefault("decisions", []).append(entry)
    write_json(run / "session.json", data)
    log = run / "logs" / "decisions.md"
    log.parent.mkdir(exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"- {entry['time'][11:19]} {key} = {value}" + (f": {why}" if why else "") + "\n")
    return entry


def record_result(run: Path, case: str, result: str, step: str = "", issue: str = "", finding: str = "",
                  note: str = "") -> dict:
    """A test case (or retested known issue) result in session.json `test_results`.

    Recording the same case and step again replaces the earlier result: a rerun gives the case's final word.
    """
    if result not in report.TEST_RESULTS:
        raise FindingError(f"result must be one of {report.TEST_RESULTS}")
    if result in ("fail", "blocked") and not (finding or note):
        raise FindingError(f"a {result} result needs --finding or --note")
    if issue and not re.fullmatch(r"K-\d+", issue):
        raise FindingError(f"--issue looks like K-3, not {issue!r}")
    if finding and not any(f.get("id") == finding for f in _load(run, "findings.json").get("findings", [])):
        raise FindingError(f"no finding {finding} in this run: write it first (`finding add`)")
    data = _load(run, "session.json")
    entry = {"case": case, "result": result}
    entry.update({k: v for k, v in (("step", step), ("issue", issue), ("finding", finding), ("note", note)) if v})
    results = [r for r in data.get("test_results", [])
               if (r.get("case"), r.get("step", "")) != (case, step)]
    data["test_results"] = [*results, entry]
    write_json(run / "session.json", data)
    return entry


def session_add(run: Path, field: str, values: list[str]) -> None:
    if field not in SESSION_LISTS:
        raise FindingError(f"`add` takes one of {SESSION_LISTS}")
    data = _load(run, "session.json")
    items = data.setdefault(field, [])
    items.extend(v for v in values if v not in items)
    write_json(run / "session.json", data)
