"""The project's mobile-tester configuration, as far as adt and idt need it.

The skills own the config (.mobile-tester/config.yaml, written by onboarding). The tools read the few values
that must not depend on which skill drove the session: where reports go and who the tester is.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from . import devices
from .state import PROJECT_DIR

CONFIG = Path(PROJECT_DIR) / "config.yaml"
MODE_TITLES = {"explore": "exploratory test", "test-case": "test cases", "repro": "bug reproduction",
               "ui-review": "UI review", "retest": "retest", "memory": "memory check"}


def find_config(start: Path | None = None) -> Path | None:
    """Like git: the nearest .mobile-tester/config.yaml in this folder or above it."""
    start = (start or Path.cwd()).resolve()
    for folder in (start, *start.parents):
        if (folder / CONFIG).is_file():
            return folder / CONFIG
    return None


def load(start: Path | None = None) -> tuple[dict, Path]:
    """The config and the project folder it belongs to; ({}, the start folder) without a config."""
    path = find_config(start)
    if path is None:
        return {}, (start or Path.cwd()).resolve()
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}, path.parent.parent


def tester(start: Path | None = None) -> str | None:
    config, _ = load(start)
    return (config.get("tester") or {}).get("name") or None


def device_entry(device_id: str, start: Path | None = None) -> dict | None:
    """The device's entry (name, kind, personal): the user's device list first, then the project's older inventory."""
    if entry := devices.get(device_id):
        return entry
    config, _ = load(start)
    return next((d for d in config.get("devices") or [] if str(d.get("id", d.get("serial", ""))) == device_id),
                None)


def app_name(root: Path, package: str) -> str:
    """The profile's app name, or the last part of the package id."""
    profile = root / PROJECT_DIR / "apps" / package / "profile.yaml"
    if profile.is_file():
        name = str((yaml.safe_load(profile.read_text(encoding="utf-8")) or {}).get("name") or "")
        if name and not name.startswith("<"):  # "<App name>" is the template's placeholder
            return name
    return package.rsplit(".", 1)[-1]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def default_run_dir(package: str | None, mode: str | None, ticket: str | None = None,
                    start: Path | None = None, today: date | None = None) -> Path:
    """<reports dir>/<YYYY-MM-DD>-<app>-<mode>[-<ticket>], with -2, -3... so a new session never reuses a folder."""
    config, root = load(start)
    reports = Path((config.get("reports") or {}).get("dir") or "reports")
    base = reports if reports.is_absolute() else root / reports
    parts = [(today or date.today()).isoformat(), _slug(app_name(root, package)) if package else "session",
             mode or "explore"]
    if ticket and (ticket_slug := _slug(ticket.rstrip("/").rsplit("/", 1)[-1])):
        parts.append(ticket_slug)
    stem = "-".join(p for p in parts if p)
    candidate, n = base / stem, 2
    while candidate.exists():
        candidate, n = base / f"{stem}-{n}", n + 1
    return candidate


def default_title(package: str | None, mode: str | None, start: Path | None = None,
                  platform: str = "Android") -> str:
    """'<App name> <platform> - <mode>', the standard report title."""
    _, root = load(start)
    name = app_name(root, package) if package else "App"
    return f"{name} {platform} - {MODE_TITLES.get(mode or 'explore', mode)}"
