"""What was typed into which field, for the action log, without ever logging a credential.

Testers need to see which inputs each field got (empty, negative, regex characters...), so `type` logs the
field and the text. The text is hidden when it could be a credential: a password field, a field whose name
looks like a login, a code or a card, or a value from the app's secrets file.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import project
from .ui import Element

HIDDEN = "(hidden)"
_SENSITIVE = re.compile(r"pass|pin\b|otp|one.time|code|token|secret|card|cvv|cvc|iban|account|e-?mail|user ?name|"
                        r"login|phone", re.IGNORECASE)
_MAX = 80


def field_name(el: Element | None) -> str:
    """The field's name: its hint, else its label. An empty Compose field shows its placeholder as the label;
    once it has text, the label is the text, so `screens` names a field by its first entry at that place."""
    if el is None:
        return ""
    name = el.hint or el.label.split(" | ", 1)[0] or el.short_id
    return name.strip()[:40]


def focused_field(elements: list[Element]) -> Element | None:
    """The field the keyboard types into: the focused editable element."""
    return next((e for e in elements if e.editable and e.focused), None)


def _scalars(value) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _scalars(v)]
    if isinstance(value, list):
        return [s for v in value for s in _scalars(v)]
    return [str(value)] if value not in (None, "") else []


def secret_values(package: str | None, start: Path | None = None) -> set[str]:
    """Every value in the app's `secrets.local.yaml`, so none of them is ever logged."""
    config = project.find_config(start)
    if not package or config is None:
        return set()
    path = config.parent / "apps" / package / "secrets.local.yaml"
    if not path.is_file():
        return set()
    try:
        return set(_scalars(yaml.safe_load(path.read_text(encoding="utf-8"))))
    except yaml.YAMLError:
        return {"*"}  # unreadable: treat every text as secret


def log_fields(text: str, field: Element | None, secrets: set[str]) -> dict:
    """{"field", "text"} for the `type` entry of the action log."""
    name = field_name(field)
    sensitive = (field is not None and field.password) or bool(_SENSITIVE.search(name)) or "*" in secrets \
        or text in secrets or any(s and s in text for s in secrets)
    shown = HIDDEN if sensitive else (text if len(text) <= _MAX else text[:_MAX - 1] + "…")
    entry = {"field": name, "text": shown}
    if field is not None:
        entry["at"] = [field.bounds.left, field.bounds.top]  # ties a field without a hint to its earlier name
    return entry
