"""Technical data about how a run was produced: agent tokens and cost, time per phase, tool and device activity.

Written to session.json under "technical" by `report telemetry`, shown at the end of index.html, and appended to
<reports dir>/telemetry.csv (one row per run) so runs can be compared over time.
Token usage comes from the agent's transcript; only Claude Code's JSONL transcript is understood for now.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

# USD per million tokens at Anthropic API list prices: (input, output, cache read).
# Cache writes cost a multiple of the input price, depending on the cache TTL.
PRICES_AS_OF = "2026-10-06"
PRICES = {
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
CACHE_WRITE_5M, CACHE_WRITE_1H = 1.25, 2.0
TOKEN_KINDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
PHASES = ("onboarding", "session", "wrap_up")


def cost_usd(model: str, tokens: dict[str, int]) -> float | None:
    """What these tokens cost at API list prices, or None when the model's price is unknown.

    `tokens` has the TOKEN_KINDS keys; thinking is already part of "output".
    """
    # A dated snapshot id (claude-haiku-4-5-20251001) costs the same as its alias.
    price = PRICES.get(re.sub(r"-\d{8}$", "", model))
    if price is None:
        return None
    per_input, per_output, per_read = price
    dollars = (tokens.get("input", 0) * per_input + tokens.get("output", 0) * per_output
               + tokens.get("cache_read", 0) * per_read
               + tokens.get("cache_write_5m", 0) * per_input * CACHE_WRITE_5M
               + tokens.get("cache_write_1h", 0) * per_input * CACHE_WRITE_1H)
    return dollars / 1_000_000


def claude_code_transcript(project: Path) -> Path | None:
    """The newest Claude Code transcript of the project folder (~/.claude/projects/<folder with - for symbols>)."""
    folder = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))
    transcripts = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return transcripts[-1] if transcripts else None


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _phase(when: datetime, started: datetime | None, ended: datetime | None) -> str:
    if started and when < started:
        return "onboarding"
    if ended and when > ended:
        return "wrap_up"
    return "session"


def _usage_tokens(usage: dict) -> dict[str, int]:
    split = usage.get("cache_creation") or {}
    write_1h = split.get("ephemeral_1h_input_tokens", 0)
    # Older transcripts have no TTL split: count every write as the default 5-minute one.
    write_5m = split.get("ephemeral_5m_input_tokens", usage.get("cache_creation_input_tokens", 0) - write_1h)
    return {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0),
            "cache_read": usage.get("cache_read_input_tokens", 0), "cache_write_5m": write_5m,
            "cache_write_1h": write_1h,
            "thinking": (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0)}


def _add(total: dict[str, int], tokens: dict[str, int]) -> None:
    for key, value in tokens.items():
        total[key] = total.get(key, 0) + value


def _is_user_turn(entry: dict) -> bool:
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return any(block.get("type") == "text" for block in content or [] if isinstance(block, dict))


def read_transcript(path: Path, since: datetime | None = None, until: datetime | None = None,
                    started: datetime | None = None, ended: datetime | None = None) -> dict:
    """Tokens, requests, tool calls and user turns of a Claude Code transcript between `since` and `until`.

    One API response is written as several lines (one per content block) that repeat its usage, so responses
    are counted once by message id.
    """
    by_model: dict[str, dict[str, int]] = {}
    by_phase: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    tools: Counter[str] = Counter()
    efforts: Counter[str] = Counter()
    agent: dict[str, str] = {}
    tool_errors = user_turns = peak_context = 0
    first = last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not entry.get("timestamp"):
            continue
        when = _time(entry["timestamp"])
        if (since and when < since) or (until and when > until):
            continue
        first, last = first or when, when
        for key, field in (("version", "version"), ("session_id", "sessionId")):
            if entry.get(field):
                agent.setdefault(key, entry[field])
        match entry.get("type"):
            case "api-request":
                params = entry.get("params") or {}
                if effort := (params.get("output_config") or {}).get("effort"):
                    efforts[effort] += 1
                if "outputStyle:" in entry.get("querySource", ""):
                    agent.setdefault("output_style", entry["querySource"].rsplit("outputStyle:", 1)[1])
            case "assistant":
                message = entry.get("message") or {}
                for block in message.get("content") or []:
                    if block.get("type") == "tool_use":
                        tools[block.get("name", "?")] += 1
                if not message.get("usage") or message.get("id") in seen:
                    continue
                seen.add(message.get("id"))
                tokens = _usage_tokens(message["usage"])
                model = by_model.setdefault(message.get("model", "unknown"), {"requests": 0})
                model["requests"] += 1
                _add(model, tokens)
                _add(by_phase.setdefault(_phase(when, started, ended), {"requests": 0}), {"requests": 1, **tokens})
                context = tokens["input"] + tokens["cache_read"] + tokens["cache_write_5m"] + tokens["cache_write_1h"]
                peak_context = max(peak_context, context)
            case "user":
                user_turns += _is_user_turn(entry)
                content = (entry.get("message") or {}).get("content")
                if isinstance(content, list):
                    tool_errors += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_result"
                                       and b.get("is_error"))
    return {"agent": {"name": "Claude Code", **agent, "effort": efforts.most_common(1)[0][0] if efforts else ""},
            "start": first.isoformat() if first else "", "end": last.isoformat() if last else "",
            "by_model": by_model, "by_phase": by_phase, "peak_context": peak_context,
            "tool_calls": dict(tools.most_common()), "tool_errors": tool_errors, "user_turns": user_turns}


def _priced(tokens_by_key: dict[str, dict[str, int]], model_of) -> tuple[dict[str, float | None], list[str]]:
    costs, unpriced = {}, []
    for key, tokens in tokens_by_key.items():
        costs[key] = cost_usd(model_of(key), tokens)
        if costs[key] is None:
            unpriced.append(model_of(key))
    return costs, unpriced


def _run_activity(run: Path) -> dict:
    actions = []
    log = run / "logs" / "actions.jsonl"
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                actions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    decisions = run / "logs" / "decisions.md"
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    findings = json.loads((run / "findings.json").read_text(encoding="utf-8")).get("findings", []) \
        if (run / "findings.json").is_file() else []

    def size_mb(paths) -> float:
        return round(sum(p.stat().st_size for p in paths if p.is_file()) / 1_048_576, 1)

    screenshots = [p for p in (run / "screenshots").glob("*") if "_preview" not in p.name] \
        if (run / "screenshots").is_dir() else []
    return {
        "device_actions": {
            "total": len(actions),
            "by_action": dict(Counter(a.get("action", "?") for a in actions).most_common()),
            "by_mode": dict(Counter(a.get("mode", "?") for a in actions).most_common()),
            "fast": sum(1 for a in actions if a.get("mode") == "fast"),
            "no_visible_change": sum(1 for a in actions if a.get("changed") is False),
            "device_time_min": round(sum(a.get("duration_s", 0) for a in actions) / 60, 1),
        },
        # Runs from before `report decision` only have the hand-written log.
        "autopilot_decisions": len(session["decisions"]) if "decisions" in session else
        sum(1 for line in decisions.read_text(encoding="utf-8").splitlines() if line.startswith("- "))
        if decisions.is_file() else 0,
        "findings": dict(Counter(f.get("type", "?") for f in findings if f.get("status") != "Retracted")),
        "artifacts": {"screenshots": len(screenshots), "screenshots_mb": size_mb(screenshots),
                      "videos_mb": size_mb((run / "videos").glob("*")) if (run / "videos").is_dir() else 0,
                      "run_folder_mb": size_mb(run.rglob("*"))},
    }


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    return round((end - start).total_seconds() / 60, 1) if start and end else None


def collect(run: Path, transcript: Path | None, since: datetime | None = None,
            until: datetime | None = None) -> dict:
    """The "technical" block for session.json."""
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    started = _time(session["started"]) if session.get("started") else None
    ended = _time(session["ended"]) if session.get("ended") else None
    data: dict = {"collected": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
                  **_run_activity(run)}
    if transcript and transcript.is_file():
        t = read_transcript(transcript, since, until, started, ended)
        model_costs, unpriced = _priced(t["by_model"], lambda model: model)
        main_model = max(t["by_model"], key=lambda m: t["by_model"][m]["requests"]) if t["by_model"] else ""
        phase_costs, _ = _priced(t["by_phase"], lambda _phase: main_model)
        totals: dict[str, int] = {}
        for tokens in t["by_model"].values():
            _add(totals, {k: v for k, v in tokens.items()})
        start, end = _time(t["start"]) if t["start"] else None, _time(t["end"]) if t["end"] else None
        data.update({
            "agent": {**t["agent"], "models": list(t["by_model"]), "transcript": str(transcript)},
            "window": {"start": t["start"], "end": t["end"]},
            "minutes": {"total": _minutes(start, end), "onboarding": _minutes(start, started),
                        "session": _minutes(started, ended), "wrap_up": _minutes(ended, end)},
            "tokens": totals,
            "tokens_by_model": t["by_model"],
            "tokens_by_phase": t["by_phase"],
            "peak_context": t["peak_context"],
            "cost_usd": {"total": None if unpriced else round(sum(model_costs.values()), 2),
                         "by_model": model_costs, "by_phase": phase_costs, "prices_as_of": PRICES_AS_OF,
                         "unpriced_models": unpriced, "basis": "Anthropic API list prices"},
            "tool_calls": t["tool_calls"], "tool_errors": t["tool_errors"], "user_turns": t["user_turns"],
        })
    else:
        data["agent"] = {"name": "unknown", "note": "no agent transcript found: token and cost data not collected"}
        data["minutes"] = {"session": _minutes(started, ended)}
    return data


HISTORY_COLUMNS = ("run", "collected", "platform", "app", "version", "mode", "agent_version", "model", "effort",
                   "minutes_total", "minutes_onboarding", "minutes_session", "minutes_wrap_up", "requests",
                   "input", "output", "thinking", "cache_read", "cache_write_5m", "cache_write_1h", "peak_context",
                   "cost_usd", "tool_calls", "tool_errors", "user_turns", "device_actions", "fast_actions",
                   "no_visible_change", "autopilot_decisions", "bugs", "accessibility", "observations")


def history_row(run: Path, session: dict, tech: dict) -> dict:
    tokens, minutes, agent = tech.get("tokens") or {}, tech.get("minutes") or {}, tech.get("agent") or {}
    actions, findings = tech.get("device_actions") or {}, tech.get("findings") or {}
    return {
        "run": run.name, "collected": tech.get("collected", ""), "platform": session.get("platform", "Android"),
        "app": (session.get("app") or {}).get("package", ""),
        "version": (session.get("app") or {}).get("versionName", ""), "mode": session.get("mode", ""),
        "agent_version": agent.get("version", ""), "model": ",".join(agent.get("models", [])),
        "effort": agent.get("effort", ""),
        **{f"minutes_{k}": minutes.get(k, "") for k in ("total", "onboarding", "session", "wrap_up")},
        "requests": tokens.get("requests", ""),
        **{k: tokens.get(k, "") for k in ("input", "output", "thinking", "cache_read", "cache_write_5m",
                                         "cache_write_1h")},
        "peak_context": tech.get("peak_context", ""), "cost_usd": (tech.get("cost_usd") or {}).get("total", ""),
        "tool_calls": sum((tech.get("tool_calls") or {}).values()), "tool_errors": tech.get("tool_errors", ""),
        "user_turns": tech.get("user_turns", ""), "device_actions": actions.get("total", ""),
        "fast_actions": actions.get("fast", ""), "no_visible_change": actions.get("no_visible_change", ""),
        "autopilot_decisions": tech.get("autopilot_decisions", ""), "bugs": findings.get("bug", 0),
        "accessibility": findings.get("accessibility", 0), "observations": findings.get("observation", 0),
    }


def append_history(path: Path, row: dict) -> None:
    """Add the run's row to the CSV, replacing an earlier row of the same run."""
    rows = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("run") != row["run"]]
    rows.append(row)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)
