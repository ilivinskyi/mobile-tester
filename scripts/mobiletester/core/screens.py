"""The screens of a session: what was visited, which controls on each were never tried, which taps did nothing.

Every observation records its screen in `logs/screens.json` (by fingerprint: title, visits, the labelled
controls outside lists). Comparing that with the taps in `logs/actions.jsonl` gives a checklist for the
breadth tour ("Projects", "Tags" and "Settings" on Home were never opened) and shows dead buttons (a tap
with no visible change). Screens are grouped by title, since one screen gets several fingerprints
(keyboard open, a banner, a dialog).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import state
from .fingerprint import content_lists, inside_any
from .ui import Element

_TARGET = re.compile(r'"(.*?)"')
_TOP_SHARE = 0.2  # a screen's title sits in the top fifth
_TAP_ACTIONS = ("tap", "long-press")


def _name(label: str) -> str:
    """A control's name as listed: the first part of a merged label, shortened."""
    first = label.split(" | ", 1)[0].strip()
    return first if len(first) <= 40 else first[:39].rstrip() + "…"


def _key(name: str) -> str:
    return name.rstrip("…").casefold()


def title(elements: list[Element], screen_height: int) -> str:
    """The screen's title: the topmost fixed text (not in a list, not a control) near the top."""
    lists = [e.z for e in content_lists(elements)]
    texts = [e for e in elements
             if e.label and not e.interactive and not e.sr_only and not inside_any(e.z, lists)
             and e.bounds.top < _TOP_SHARE * screen_height and 1 < len(e.label) <= 60]
    if not texts:
        return ""
    top = min(texts, key=lambda e: (e.bounds.top, e.bounds.left))
    return _name(top.label)


def _data_lists(elements: list[Element]) -> list[list[int]]:
    """Lists of content (tasks, messages). A row that scrolls sideways (wider than twice its height) holds
    chips or tabs: its items are controls."""
    return [e.z for e in content_lists(elements) if e.bounds.width <= 2 * e.bounds.height]


def controls(elements: list[Element]) -> list[str]:
    """Names of the labelled buttons, tabs, chips and switches outside content lists, in screen order."""
    lists = _data_lists(elements)
    names: list[str] = []
    for e in sorted(elements, key=lambda e: (e.bounds.top, e.bounds.left)):
        if not e.interactive or e.editable or e.scrollable or not e.label or inside_any(e.z, lists):
            continue
        name = _name(e.label)
        if name and name not in names:
            names.append(name)
    return names


def record(run: Path | None, fingerprint: str, screen_title: str, names: list[str], package: str = "") -> int:
    """Count a visit and return the screen's visits so far (0 when not counted). Only the app under test's
    screens count: not the lock screen, the launcher or a browser."""
    if run is None or fingerprint in ("", "-"):
        return 0
    app = (state.read_json(run / "session.json") or {}).get("package")
    if app and package and package != app:
        return 0
    path = run / "logs" / "screens.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = state.read_json(path) or {}
    entry = data.setdefault(fingerprint, {"title": screen_title, "visits": 0,
                                          "first": datetime.now().astimezone().isoformat(timespec="seconds"),
                                          "controls": []})
    entry["visits"] += 1
    entry["title"] = entry["title"] or screen_title
    entry["controls"] += [n for n in names if n not in entry["controls"]]
    state.write_json(path, data)
    return entry["visits"]


def _actions(run: Path) -> list[dict]:
    log = run / "logs" / "actions.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tapped(entry: dict) -> str:
    m = _TARGET.search(entry.get("target") or "")
    return _name(m.group(1)) if m else ""


def inventory(run: Path) -> dict:
    """{"screens": [{"title", "visits", "controls", "untried"}], "no_change": [{"time", "screen", "target"}]}."""
    seen = state.read_json(run / "logs" / "screens.json") or {}
    title_of = {fp: entry["title"] or f"screen {fp[:6]}" for fp, entry in seen.items()}
    tapped: dict[str, set[str]] = {}
    no_change = []
    current = ""
    for entry in _actions(run):
        if entry.get("action") == "observe":
            current = title_of.get(entry.get("fp", ""), current)
        elif entry.get("action") in _TAP_ACTIONS and (target := _tapped(entry)):
            tapped.setdefault(current, set()).add(_key(target))
            if entry.get("changed") is False:
                no_change.append({"time": entry["t"][11:19], "screen": current, "target": target})
    screens: dict[str, dict] = {}
    for fp, entry in seen.items():
        row = screens.setdefault(title_of[fp], {"title": title_of[fp], "visits": 0, "controls": []})
        row["visits"] += entry["visits"]
        row["controls"] += [c for c in entry["controls"] if c not in row["controls"]]
    # Controls on several screens (a bottom bar, a toolbar) lead to the same place from each: tapped once
    # anywhere is tried everywhere.
    shared = {_key(c) for c in _on_several(screens.values())}
    anywhere = set().union(*tapped.values()) if tapped else set()
    for row in screens.values():
        done = tapped.get(row["title"], set()) | (anywhere & shared)
        row["untried"] = [c for c in row["controls"] if _key(c) not in done]
    return {"screens": list(screens.values()), "no_change": no_change}


def _on_several(rows) -> set[str]:
    counts: dict[str, int] = {}
    for row in rows:
        for c in row["controls"]:
            counts[c] = counts.get(c, 0) + 1
    return {c for c, n in counts.items() if n > 1}


def lines(found: dict) -> list[str]:
    out = [f"Screens visited ({len(found['screens'])}):"]
    for row in found["screens"]:
        untried = ", ".join(row["untried"]) or "none"
        out.append(f"  {row['title']}  ({row['visits']} visit{'s' if row['visits'] != 1 else ''})  "
                   f"not tried: {untried}")
    if not found["screens"]:
        out.append("  none recorded: observe after each navigation")
    if found["no_change"]:
        out.append(f"Taps with no visible change ({len(found['no_change'])}): a missed tap, or a dead button?")
        out += [f"  {n['time']} on {n['screen'] or '?'}: \"{n['target']}\"" for n in found["no_change"]]
    return out
