"""Two runs of the same app side by side, e.g. the last build and this one: what got slower, what's new, what's gone.

Screens are matched by their fingerprint (core/fingerprint.py), which every observation writes to the action log.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# (label, path into session.json performance, unit, True when a higher value is worse)
_METRICS = [
    ("cold start", ("startup", "cold_start_ms"), "ms", True),
    ("janky frames", ("frames", "janky_pct"), "%", True),
    ("memory (PSS)", ("memory", "pss_kb"), "KB", True),
]
WORSE_BY = 0.10  # a metric 10% worse than before is called out


def _load(run: Path, name: str) -> dict:
    path = run / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def screens(run: Path) -> dict[str, str]:
    """fingerprint -> screen name, from the observations in the run's action log."""
    found: dict[str, str] = {}
    log = run / "logs" / "actions.jsonl"
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line) if line.strip() else {}
            if entry.get("action") == "observe" and entry.get("fp") not in (None, "", "-"):
                found.setdefault(entry["fp"], entry.get("screen", ""))
    return found


def _metric(session: dict, path: tuple[str, str]):
    return (session.get("performance", {}).get(path[0]) or {}).get(path[1])


_NUMBERS = re.compile(r"0x[0-9a-f]+|\d+")


def _log_key(group: dict) -> str:
    return f"{group['kind']}|{group['tag']}|{_NUMBERS.sub('#', group['text'])[:160]}"


def _build(session: dict) -> str:
    return " ".join(str((session.get("app") or {}).get(k, "")) for k in ("versionName", "versionCode")).strip()


def compare(run_a: Path, run_b: Path) -> list[str]:
    sa, sb = _load(run_a, "session.json"), _load(run_b, "session.json")
    fa = [f for f in _load(run_a, "findings.json").get("findings", []) if f.get("status") != "Retracted"]
    fb = [f for f in _load(run_b, "findings.json").get("findings", []) if f.get("status") != "Retracted"]
    lines = [f"A: {run_a.name} (build {_build(sa) or '?'})", f"B: {run_b.name} (build {_build(sb) or '?'})", ""]

    lines.append("Performance (B compared with A):")
    rows = 0
    for label, path, unit, higher_worse in _METRICS:
        a, b = _metric(sa, path), _metric(sb, path)
        if a is None or b is None:
            continue
        rows += 1
        change = (b - a) / a if a else 0.0
        worse = change > WORSE_BY if higher_worse else change < -WORSE_BY
        lines.append(f"  {label}: {a} -> {b} {unit} ({change:+.0%})" + ("  WORSE" if worse else ""))
    if not rows:
        lines.append("  not measured in both runs")

    known_a = {f["known_issue"] for f in fa if f.get("known_issue")}
    known_b = {f["known_issue"] for f in fb if f.get("known_issue")}
    titles_a = {f.get("title", "").casefold() for f in fa}
    new = [f for f in fb if not (f.get("known_issue") in known_a or f.get("title", "").casefold() in titles_a)]
    lines += ["", f"Findings: {len(fa)} in A, {len(fb)} in B"]
    lines += [f"  new in B: [{f['id']}] {f.get('severity') or f.get('type')}: {f.get('title')}" for f in new]
    lines += [f"  known issue {k} seen in A, not in B (fixed, or not reached?)" for k in sorted(known_a - known_b)]
    lines += [f"  known issue {k} still seen in B" for k in sorted(known_a & known_b)]

    logs_a = {_log_key(g): g for g in sa.get("log_summary", [])}
    logs_b = {_log_key(g): g for g in sb.get("log_summary", [])}
    if logs_a or logs_b:
        lines += ["", f"App log: {sum(g['count'] for g in logs_a.values())} issue lines in A, "
                      f"{sum(g['count'] for g in logs_b.values())} in B"]
        lines += [f"  new in B: {g['count']}x {g['kind']}, {g['tag']}: {g['text'][:120]}"
                  for k, g in logs_b.items() if k not in logs_a]

    screens_a, screens_b = screens(run_a), screens(run_b)
    if screens_a or screens_b:
        lines += ["", f"Screens: {len(screens_a)} in A, {len(screens_b)} in B, {len(set(screens_a) & set(screens_b))} "
                      "in both"]
        lines += [f"  only in A: {name or fp}" for fp, name in screens_a.items() if fp not in screens_b]
        lines += [f"  only in B: {name or fp}" for fp, name in screens_b.items() if fp not in screens_a]
    return lines
