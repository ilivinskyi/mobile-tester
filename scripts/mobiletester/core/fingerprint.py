"""Screen identity: the same logical screen should get the same fingerprint across visits.

Used for the exploration coverage map ("have I been here?") and as the key of the
selector cache for Markdown test cases ("which element did this step resolve to on this screen?").
"""

from __future__ import annotations

import hashlib
import re

from .ui import Element


def screen_fingerprint(package: str, activity: str, elements: list[Element]) -> str:
    """Return a short stable id for the logical screen described by these inputs.

    Same screen, different content (typed text, scroll position, a new chat message) -> same id.
    Different screen inside one Activity (tabs, Compose navigation, dialogs) -> different id.

    Walls and doors in, visitors out: fixed controls (class + id), input fields (by hint) and texts outside
    lists count; list rows, typed text, check/focus state, digits and screen-reader-only text don't.
    Anything that visibly adds or removes fixed parts is a different state, e.g. an app hiding its tab bar
    while the keyboard is open, or a banner over the screen.
    """
    lists = [e.z for e in content_lists(elements)]
    parts = {f"activity:{activity}"}
    for el in elements:
        if el.sr_only or inside_any(el.z, lists):
            continue  # list rows and screen-reader text are content
        if el.editable:
            parts.add(f"field:{el.cls}#{el.short_id}:{_stable(el.hint)}")  # never the typed text
        elif el.interactive:
            # Controls by class and id only: their labels carry counts and names ("Inbox, 3 new").
            parts.add(f"control:{el.cls}#{el.short_id}" + (":list" if el.scrollable else ""))
        elif el.label:
            parts.add(f"text:{_stable(el.label)}")  # titles and fixed texts outside lists
    return _digest([package, *sorted(parts)])


def content_lists(elements: list[Element]) -> list[Element]:
    """Scroll containers that hold content. A scroll container wrapping another one of about its own size
    is the page itself (web pages become scrollable when the keyboard opens) and holds the fixed parts too."""
    scrollables = [e for e in elements if e.scrollable]
    return [
        s for s in scrollables
        if not any(inside_any(t.z, [s.z]) and t.bounds.area >= 0.7 * s.bounds.area for t in scrollables)
    ]


def inside_any(z: list[int], containers: list[list[int]]) -> bool:
    # An ancestor's paint-order key is a strict prefix of its descendants' keys.
    return any(len(c) < len(z) and z[:len(c)] == c for c in containers)


def _stable(text: str) -> str:
    """Text without the parts that change on a screen that stays the same: digits and case."""
    return re.sub(r"\d+", "#", text).casefold()


def _digest(parts: list[str], length: int = 12) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:length]
