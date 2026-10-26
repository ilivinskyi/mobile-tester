"""Report vocabulary and the plain-text outputs: Markdown drafts, Jira wiki markup, the Jira bulk-import CSV.

Shared by report.py (validation, build) and report_html.py (the pages).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

TYPES = ("bug", "accessibility", "observation")
SEVERITIES = ("Blocker", "Critical", "Major", "Minor", "Trivial")
PRIORITIES = ("P1", "P2", "P3", "P4")
STATUSES = ("Confirmed", "Unconfirmed", "Retracted")
SCOPES = ("in", "outside")
EVIDENCE_TYPES = ("screenshot", "video", "log", "xml", "other")
TEST_RESULTS = ("pass", "fail", "blocked", "skipped")
TYPE_NAMES = {"bug": "Bug", "accessibility": "Accessibility", "observation": "Observation"}
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}
RETEST_WORDS = {"pass": "Fixed", "fail": "Still reproduces", "blocked": "Can't verify", "skipped": "Skipped"}
# Jira's default priority scheme, for the bulk-import CSV.
JIRA_PRIORITIES = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}

_KEYBOARDS = {
    "com.google.android.inputmethod.latin": "Gboard",
    "com.samsung.android.honeyboard": "Samsung Keyboard",
    "com.touchtype.swiftkey": "Microsoft SwiftKey",
}


def outside(f: dict) -> bool:
    return f.get("scope") == "outside"


def seen_again(f: dict) -> bool:
    return bool(f.get("known_issue")) and not f.get("new_issue")


def fileable(f: dict) -> bool:
    """Findings someone may file as a ticket: bugs and accessibility issues that weren't retracted."""
    return f["status"] != "Retracted" and f["type"] != "observation"


def keyboard_name(ime: str) -> str:
    package = (ime or "?").split("/", 1)[0]
    return _KEYBOARDS.get(package, package)


def time_range(session: dict) -> str | None:
    """'23 Oct 2026, 14:40-14:52 (12 min, time box 15 min)' from the ISO start/end times."""
    if not session.get("started"):
        return None
    start = datetime.fromisoformat(session["started"])
    text = f"{start:%d %b %Y}, {start:%H:%M}"
    extra = []
    if session.get("ended"):
        end = datetime.fromisoformat(session["ended"])
        text += f"-{end:%H:%M}"
        extra.append(f"{round((end - start).total_seconds() / 60)} min")
    if session.get("time_box_min"):
        extra.append(f"time box {session['time_box_min']} min")
    return text + (f" ({', '.join(extra)})" if extra else "")


def repro(f: dict) -> str:
    r = f.get("reproducibility") or {}
    parts = [f"automated {r['automated']}" if r.get("automated") else "",
             f"manual {r['manual']}" if r.get("manual") else ""]
    return ", ".join(p for p in parts if p)


def summary(f: dict) -> str:
    """One line for the list: the finding's own summary, or the start of what was seen."""
    text = f.get("summary") or f.get("actual") or f.get("notes") or ""
    text = " ".join(str(text).split())
    return text if len(text) <= 200 else text[:199].rstrip() + "…"


def platform(session: dict) -> str:
    """'Android' or 'iOS'; run folders from before iOS support have no platform and are Android."""
    return session.get("platform") or (session.get("device") or {}).get("platform") or "Android"


def device_facts(dev: dict) -> dict[str, str]:
    """The device in display-ready words, whichever platform wrote it.

    Each platform writes `os`, `kind`, `screen`, `navigation` and `keyboard` as display text; Android run folders
    from before that only have the raw facts (android, sdk, emulator, density, nav mode, IME id).
    """
    if not dev:
        return {}
    os_ = dev.get("os") or (f"Android {dev['android']}" + (f" (API {dev['sdk']})" if dev.get("sdk") else "")
                            if dev.get("android") else "")
    screen = dev.get("screen", "")
    if screen and dev.get("density"):
        screen += f" at {dev['density']} dpi"
    navigation = dev.get("navigation", "")
    if navigation in ("gesture", "3-button", "2-button"):
        navigation += " navigation"
    return {
        "model": " ".join(p for p in (dev.get("manufacturer", ""), dev.get("model", "")) if p),
        "short_model": dev.get("model", ""),
        "os": os_,
        "screen": screen,
        "kind": dev.get("kind") or ("emulator" if dev.get("emulator") else "physical"),
        "personal": bool(dev.get("personal")),
        "navigation": navigation,
        "keyboard": keyboard_name(dev["keyboard"]) if dev.get("keyboard") else "",
        "locale": dev.get("locale", ""),
    }


def _joined(*parts: str, sep: str = ", ") -> str:
    return sep.join(p for p in parts if p)


def environment(session: dict) -> list[tuple[str, str]]:
    dev, app = session.get("device") or {}, session.get("app") or {}
    facts = device_facts(dev)
    ticket = session.get("ticket")
    if isinstance(ticket, dict):
        ticket = " - ".join(str(ticket.get(k)) for k in ("key", "summary") if ticket.get(k))
    rows = [
        ("Charter", session.get("charter")),
        ("Mode", session.get("mode")),
        ("Ticket", ticket),
        ("Tester", session.get("tester")),
        ("Time", time_range(session)),
        ("App", " ".join(str(app.get(k, "")) for k in ("package", "versionName")).strip()
         + (f" ({app['versionCode']})" if app.get("versionCode") else "")),
        ("Install source", app.get("install_source")),
        ("Device", _joined(facts["model"], facts["os"], facts["screen"]) if dev else None),
        ("Device kind", facts.get("kind", "") + (", personal" if facts.get("personal") else "")),
        ("Navigation and keyboard", _joined(facts["navigation"], facts["keyboard"]) if dev else None),
        ("Locale", dev.get("locale")),
        ("Input", session.get("input")),
        ("Setup steps run fast", ", ".join(session.get("setup_steps_fast", [])) or None),
        ("Decided by autopilot", "; ".join(f"{d['key']} = {d['value']}" + (f" ({d['why']})" if d.get("why") else "")
                                           for d in session.get("decisions", [])) or None),
    ]
    return [(k, str(v)) for k, v in rows if v]


def environment_line(session: dict) -> str:
    facts = device_facts(session.get("device") or {}) or {"kind": "?"}
    app = session.get("app") or {}
    kind = "physical device" if facts["kind"] == "physical" else facts["kind"]
    if facts.get("personal"):
        kind = f"personal {kind}"
    device = _joined(facts.get("short_model") or "?", facts.get("os") or "?", kind, facts.get("navigation", ""),
                     f"keyboard {facts['keyboard']}" if facts.get("keyboard") else "",
                     f"locale {facts['locale']}" if facts.get("locale") else "")
    return (f"{device}; app {app.get('package', '?')} {app.get('versionName', '')} ({app.get('versionCode', '')}); "
            f"input: {session.get('input', 'adb')}")


def history_sentence(h: dict) -> str:
    """'Manual check: reproduced 2/2 by Ihor, on Pixel 7a with build 1.0 (10). Status: Unconfirmed to Confirmed.'"""
    what = {"manual-check": f"Manual check: {h.get('result', '').replace('-', ' ')} {h.get('tries', '')}".rstrip(),
            "retest": f"Retest: {h.get('result', '')}"}.get(h["action"], h["action"].replace("-", " ").capitalize())
    parts = [what + (f" by {h['by']}" if h.get("by") else "")]
    where = " with build ".join(v for v in (h.get("device"), h.get("build")) if v)
    if where:
        parts[0] += f", on {where}" if h.get("device") else f", build {where}"
    if h.get("status"):
        parts.append(f"Status: {h['status'].replace('->', 'to')}")
    if h.get("note"):
        parts.append(h["note"].rstrip("."))
    return ". ".join(parts) + "."


def performance_rows(performance: dict) -> list[tuple[str, str]]:
    rows = []
    if s := performance.get("startup"):
        samples = s.get("samples_ms", [])
        rows.append(("Cold start", f"{s['cold_start_ms']} ms (median of {len(samples)} launches: "
                                   f"{', '.join(map(str, samples))} ms)"))
    if fr := performance.get("frames"):
        parts = []
        if "janky_pct" in fr:
            parts.append(f"{fr['janky_pct']}% janky ({fr.get('janky')} of {fr.get('frames')} frames)")
        pcts = [f"p{p} {fr[f'p{p}_ms']} ms" for p in (50, 90, 99) if f"p{p}_ms" in fr]
        if pcts:
            parts.append("frame time " + ", ".join(pcts))
        rows.append(("Rendering", "; ".join(parts)))
    if m := performance.get("memory"):
        mem = f"{round(m['pss_kb'] / 1024)} MB PSS" if "pss_kb" in m else ""
        if "rss_kb" in m:
            mem += f", {round(m['rss_kb'] / 1024)} MB RSS"
        rows.append(("Memory", mem))
    if trend := [s for s in performance.get("memory_trend", []) if "pss_kb" in s]:
        pss = [s["pss_kb"] for s in trend]
        text = (f"{_mb(pss[0])} to {_mb(pss[-1])} PSS over {len(pss)} samples, peak {_mb(max(pss))}")
        if activities := [s["activities"] for s in trend if "activities" in s]:
            text += f"; live Activities {min(activities)} to {max(activities)}"
        rows.append(("Memory during the session", text))
    for flow, leak in (performance.get("leaks") or {}).items():
        growing = "; ".join(f"{_OBJECT_NAMES.get(k, k)} " + " > ".join(_mb(v) if k == "pss_kb" else str(v)
                                                                       for v in values)
                            for k, values in leak.get("growing", {}).items())
        rows.append((f"Leak check: {flow}", f"{leak['verdict'].capitalize()} after {leak['cycles']} cycles"
                                            + (f" ({growing})" if growing else "")))
    return [(k, v) for k, v in rows if v]


def _tokens_text(t: dict) -> str:
    total = sum(t.get(k, 0) for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"))
    writes = t.get("cache_write_5m", 0) + t.get("cache_write_1h", 0)
    return (f"{total:,} in {t.get('requests', 0)} requests: {t.get('output', 0):,} output "
            f"({t.get('thinking', 0):,} thinking), {t.get('input', 0):,} input, "
            f"{t.get('cache_read', 0):,} cache read, {writes:,} cache write")


def _usd(value) -> str:
    return "unknown" if value is None else f"${value:,.2f}"


def technical_rows(tech: dict) -> list[tuple[str, str]]:
    """The report's "Technical data" table: how the run was produced, for tracking the skill over time."""
    if not tech:
        return []
    rows = []
    agent = tech.get("agent") or {}
    rows.append(("Agent", " ".join(filter(None, [agent.get("name"), agent.get("version")]))
                 + (f"; {', '.join(agent['models'])}" if agent.get("models") else "")
                 + (f", effort {agent['effort']}" if agent.get("effort") else "")
                 + (f", output style {agent['output_style']}" if agent.get("output_style") else "")
                 + (f" ({agent['note']})" if agent.get("note") else "")))
    if m := tech.get("minutes"):
        parts = [f"{label} {m[key]} min" for key, label in
                 (("onboarding", "onboarding and interview"), ("session", "test session"), ("wrap_up", "wrap-up"))
                 if m.get(key) is not None]
        total = f"{m['total']} min in total" if m.get("total") is not None else ""
        rows.append(("Duration", total + (": " if total and parts else "") + ", ".join(parts)))
    if t := tech.get("tokens"):
        rows.append(("Tokens", _tokens_text(t)))
        reads = t.get("cache_read", 0)
        prompt = reads + t.get("input", 0) + t.get("cache_write_5m", 0) + t.get("cache_write_1h", 0)
        if prompt:
            rows.append(("Prompt cache", f"{round(100 * reads / prompt)}% of input tokens read from cache; "
                                         f"largest context {tech.get('peak_context', 0):,} tokens"))
    if c := tech.get("cost_usd"):
        text = f"{_usd(c.get('total'))} at {c.get('basis', 'API list prices')} as of {c.get('prices_as_of')}"
        if len(c.get("by_model") or {}) > 1:
            text += " (" + ", ".join(f"{k} {_usd(v)}" for k, v in c["by_model"].items()) + ")"
        if c.get("unpriced_models"):
            text += f"; no price for {', '.join(c['unpriced_models'])}"
        rows.append(("Cost", text))
    for phase, tokens in (tech.get("tokens_by_phase") or {}).items():
        cost = ((tech.get("cost_usd") or {}).get("by_phase") or {}).get(phase)
        rows.append((f"Phase: {phase.replace('_', '-')}", f"{_usd(cost)}; {_tokens_text(tokens)}"))
    if calls := tech.get("tool_calls"):
        top = ", ".join(f"{name} {n}" for name, n in list(calls.items())[:6])
        rows.append(("Agent tool calls", f"{sum(calls.values())} ({top}); {tech.get('tool_errors', 0)} failed; "
                                         f"{tech.get('user_turns', 0)} user messages"))
    if a := tech.get("device_actions"):
        top = ", ".join(f"{name} {n}" for name, n in list((a.get("by_action") or {}).items())[:6])
        modes = ", ".join(f"{mode} {n}" for mode, n in (a.get("by_mode") or {}).items()) \
            or f"fast {a.get('fast', 0)}"
        rows.append(("Device actions", f"{a.get('total', 0)} ({top}); by input mode: {modes}; "
                                       f"{a.get('no_visible_change', 0)} with no visible change; "
                                       f"{a.get('device_time_min', 0)} min on the device"))
    if "autopilot_decisions" in tech:
        rows.append(("Autopilot decisions", str(tech["autopilot_decisions"])))
    if art := tech.get("artifacts"):
        rows.append(("Evidence size", f"{art.get('screenshots', 0)} screenshots ({art.get('screenshots_mb', 0)} MB), "
                                      f"videos {art.get('videos_mb', 0)} MB, "
                                      f"run folder {art.get('run_folder_mb', 0)} MB"))
    if tech.get("collected"):
        rows.append(("Collected", tech["collected"]))
    return [(k, v) for k, v in rows if v]


_OBJECT_NAMES = {"activities": "Activities", "view_roots": "windows", "app_contexts": "app contexts",
                 "views": "Views", "webviews": "WebViews", "pss_kb": "PSS"}


def _mb(kb: int) -> str:
    return f"{round(kb / 1024)} MB"


def _ticket_key(session: dict) -> str:
    ticket = session.get("ticket")
    return (ticket.get("key") if isinstance(ticket, dict) else ticket) or ""


# --- Markdown --------------------------------------------------------------------------------

def render_markdown(session: dict, f: dict, with_title: bool = True) -> str:
    """The bug as Markdown. With with_title=False it's the Jira description: the title goes into Summary."""
    lines = [f"# [{f['id']}] {f['title']}", ""] if with_title else []
    head = [f"**Type:** {f['type']}", f"**Status:** {f['status']}"]
    if f.get("severity"):
        head.append(f"**Severity:** {f['severity']}")
    if f.get("priority"):
        head.append(f"**Priority (suggested):** {f['priority']}")
    lines += [" | ".join(head), "", f"**Environment:** {environment_line(session)}", ""]
    if f.get("area"):
        lines += [f"**Area:** {f['area']}", ""]
    if f.get("preconditions"):
        lines += ["**Preconditions:**", *[f"- {p}" for p in f["preconditions"]], ""]
    if f.get("steps"):
        lines += ["**Steps to reproduce:**", *[f"{i}. {s}" for i, s in enumerate(f["steps"], 1)], ""]
    if f.get("expected"):
        lines += [f"**Expected result:** {f['expected']}", ""]
    if f.get("actual"):
        lines += [f"**Actual result:** {f['actual']}", ""]
    if repro(f):
        lines += [f"**Reproducibility:** {repro(f)}", ""]
    if f.get("evidence"):
        lines += ["**Evidence (attach these files):**",
                  *[f"- {ev.get('caption') or ev['type']}: `{ev['path']}`" for ev in f["evidence"]], ""]
    if f.get("notes"):
        lines += [f"**Notes:** {f['notes']}", ""]
    if f.get("history"):
        lines += ["**History:**", *[f"- {h['time'][:16].replace('T', ' ')} {history_sentence(h)}"
                                     for h in f["history"]], ""]
    if f.get("known_issue"):
        lines += [f"**Known issue:** {f['known_issue']}" + ("" if f.get("new_issue") else " (seen again)"), ""]
    if key := _ticket_key(session):
        lines += [f"**Found while testing:** {key}", ""]
    return "\n".join(lines).rstrip() + "\n"


# --- Jira wiki markup (Jira Server / Data Center editors, and the CSV import) ----------------

def _wiki_escape(text: str) -> str:
    # Characters that start wiki markup when they open a line or wrap a word.
    return str(text).replace("{", "\\{").replace("}", "\\}").replace("[", "\\[").replace("]", "\\]")


def render_jira_wiki(session: dict, f: dict) -> str:
    """The Jira description in wiki markup (no title: that's the Summary field)."""
    e = _wiki_escape
    meta = [f"*Type:* {f['type']}", f"*Status:* {f['status']}"]
    if f.get("severity"):
        meta.append(f"*Severity:* {f['severity']}")
    if f.get("priority"):
        meta.append(f"*Priority (suggested):* {f['priority']}")
    lines = [" | ".join(meta), "", f"*Environment:* {e(environment_line(session))}", ""]
    if f.get("area"):
        lines += [f"*Area:* {e(f['area'])}", ""]
    if f.get("preconditions"):
        lines += ["*Preconditions:*", *[f"* {e(p)}" for p in f["preconditions"]], ""]
    if f.get("steps"):
        lines += ["*Steps to reproduce:*", *[f"# {e(s)}" for s in f["steps"]], ""]
    if f.get("expected"):
        lines += [f"*Expected result:* {e(f['expected'])}", ""]
    if f.get("actual"):
        lines += [f"*Actual result:* {e(f['actual'])}", ""]
    if repro(f):
        lines += [f"*Reproducibility:* {repro(f)}", ""]
    if f.get("evidence"):
        lines += ["*Evidence (attach these files):*",
                  *[f"* {e(ev.get('caption') or ev['type'])}: {{{{{ev['path']}}}}}" for ev in f["evidence"]], ""]
    if f.get("notes"):
        lines += [f"*Notes:* {e(f['notes'])}", ""]
    if f.get("history"):
        lines += ["*History:*", *[f"* {h['time'][:16].replace('T', ' ')} {e(history_sentence(h))}"
                                   for h in f["history"]], ""]
    if f.get("known_issue"):
        lines += [f"*Known issue:* {f['known_issue']}" + ("" if f.get("new_issue") else " (seen again)"), ""]
    if key := _ticket_key(session):
        lines += [f"*Found while testing:* {key}", ""]
    return "\n".join(lines).rstrip() + "\n"


# --- CSV for Jira's bulk import --------------------------------------------------------------

def render_jira_csv(session: dict, findings: list[dict]) -> str:
    """One row per fileable finding, with columns Jira's CSV importer maps directly.

    Several 'Labels' columns are Jira's way of importing multiple labels.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Summary", "Description", "Issue Type", "Priority", "Labels", "Labels", "Labels"])
    for f in findings:
        if not fileable(f):
            continue
        labels = [f"{platform(session).lower()}-tester", f"severity-{(f.get('severity') or 'none').lower()}",
                  f"type-{f['type']}"]
        if outside(f):
            labels[2] += "-outside-scope"
        writer.writerow([f"[{f['id']}] {f['title']}", render_jira_wiki(session, f), "Bug",
                         JIRA_PRIORITIES.get(f.get("priority", ""), ""), *labels])
    return out.getvalue()
