"""The standard session report: validate session.json + findings.json, then write
index.html (the finding list), bugs/<id>.html (one page per finding), bugs/<id>.md (Jira drafts)
and findings.csv (Jira bulk import).

The field definitions live in skills/mobile-tester-shared/report-standard.md; keep both in sync.
Pages are rendered in report_html.py, the text formats in report_text.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import report_html, screens
from .report_text import (
    EVIDENCE_TYPES,
    PRIORITIES,
    SCOPES,
    SEVERITIES,
    STATUSES,
    TEST_RESULTS,
    TYPES,
    fileable,
    outside,
    render_jira_csv,
    render_jira_wiki,
    render_markdown,
)

_REQUIRED = {
    "bug": ("severity", "priority", "steps", "expected", "actual", "reproducibility"),
    "accessibility": ("severity", "expected", "actual"),
    "observation": ("actual",),
}


def _load(run: Path) -> tuple[dict, list[dict]]:
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    findings = json.loads((run / "findings.json").read_text(encoding="utf-8")).get("findings", [])
    return session, findings


def check(run: Path) -> list[str]:
    """Problems that would make the report incomplete or misleading. Empty list = ok."""
    problems: list[str] = []
    for name in ("session.json", "findings.json"):
        if not (run / name).is_file():
            problems.append(f"{name} is missing in {run}")
    if problems:
        return problems
    session, findings = _load(run)
    for field_name in ("title", "mode", "charter", "device", "app"):
        if not session.get(field_name):
            problems.append(f"session.json: '{field_name}' is empty")
    for i, r in enumerate(session.get("test_results", []), 1):
        if not r.get("case") or r.get("result") not in TEST_RESULTS:
            problems.append(f"session.json test_results[{i}]: needs 'case' and 'result' in {TEST_RESULTS}")
        if r.get("result") in ("fail", "blocked") and not (r.get("finding") or r.get("note")):
            problems.append(f"session.json test_results[{i}]: a {r['result']} step needs 'finding' or 'note'")
    seen: set[str] = set()
    for f in findings:
        fid = f.get("id") or "?"
        where = f"finding {fid}"
        if fid in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(fid)
        for key in ("id", "title", "type", "status"):
            if not f.get(key):
                problems.append(f"{where}: '{key}' is required")
        if f.get("type") not in TYPES:
            problems.append(f"{where}: type must be one of {TYPES}")
            continue
        if f.get("status") not in STATUSES:
            problems.append(f"{where}: status must be one of {STATUSES}")
        if f.get("scope", "in") not in SCOPES:
            problems.append(f"{where}: scope must be one of {SCOPES}")
        if f.get("known_issue") and not re.fullmatch(r"K-\d+", str(f["known_issue"])):
            problems.append(f"{where}: known_issue must look like 'K-3'")
        for i, h in enumerate(f.get("history", []), 1):
            if not (h.get("time") and h.get("action")):
                problems.append(f"{where}: history[{i}] needs 'time' and 'action'")
        for ev in f.get("evidence", []):
            if ev.get("type") not in EVIDENCE_TYPES:
                problems.append(f"{where}: evidence type must be one of {EVIDENCE_TYPES}")
            if not (run / ev.get("path", "")).is_file():
                problems.append(f"{where}: evidence file not found: {ev.get('path')}")
        if f["status"] == "Retracted":
            if not f.get("notes"):
                problems.append(f"{where}: a retracted finding must say why in 'notes'")
            continue
        if f.get("severity") and f["severity"] not in SEVERITIES:
            problems.append(f"{where}: severity must be one of {SEVERITIES}")
        if f.get("priority") and f["priority"] not in PRIORITIES:
            problems.append(f"{where}: priority must be one of {PRIORITIES}")
        if outside(f):
            # Noticed in passing: what was seen is enough; the team triages it.
            if not f.get("actual"):
                problems.append(f"{where}: 'actual' is required (what was seen, and where)")
            continue
        for key in _REQUIRED[f["type"]]:
            if not f.get(key):
                problems.append(f"{where}: '{key}' is required for type {f['type']}")
        repro = f.get("reproducibility") or {}
        if f["type"] == "bug" and not (repro.get("automated") or repro.get("manual")):
            problems.append(f"{where}: reproducibility needs 'automated' and/or 'manual' (e.g. '3/3')")
        if f["status"] == "Unconfirmed" and not repro.get("manual"):
            problems.append(f"{where}: an Unconfirmed finding must state the manual result "
                            "(e.g. '0/2' or 'not tried')")
        if f["type"] == "bug" and f["status"] == "Confirmed" and not repro.get("manual") \
                and f.get("severity") in ("Blocker", "Critical", "Major"):
            problems.append(f"{where}: a {f['severity']} bug confirmed only by automation should be Unconfirmed "
                            "until a person reproduces it")
    return problems



def build(run: Path) -> list[Path]:
    """Render every output; outputs of findings that no longer qualify (e.g. retracted since) are removed."""
    session, findings = _load(run)
    written: list[Path] = []

    def write(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        written.append(path)

    csv_path = run / "findings.csv"
    has_csv = any(fileable(f) for f in findings)
    write(run / "index.html", report_html.render_index(session, findings, csv=has_csv,
                                                       screens=screens.inventory(run)["screens"]))
    if has_csv:
        write(csv_path, render_jira_csv(session, findings))
    else:
        csv_path.unlink(missing_ok=True)
    (run / "bugs").mkdir(exist_ok=True)
    ordered = report_html.page_order(findings)
    for i, f in enumerate(ordered):
        md_path = run / "bugs" / f"{f['id']}.md"
        copies = None
        if fileable(f):
            write(md_path, render_markdown(session, f))
            copies = {"title": f"[{f['id']}] {f['title']}", "md": render_markdown(session, f, with_title=False),
                      "wiki": render_jira_wiki(session, f)}
        else:
            md_path.unlink(missing_ok=True)
        prev_f = ordered[i - 1] if i > 0 else None
        next_f = ordered[i + 1] if i + 1 < len(ordered) else None
        write(run / "bugs" / f"{f['id']}.html",
              report_html.render_bug_page(session, f, prev_f, next_f, i + 1, len(ordered), copies))
    return written
