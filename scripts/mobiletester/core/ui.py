"""The platform-neutral model of a screen: elements with bounds, labels and flags, and how a finger finds them.

Each platform turns its own UI dump into a Snapshot (android/hierarchy.py, ios/hierarchy.py); hit testing,
human tap points and text search work the same on both.
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, field

from . import guard

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_MAX_LABEL = 80
# Rows cut off at the screen edge to a sliver can't be tapped reliably; scroll them in first.
MIN_VISIBLE_PX = 12
# Layout containers say nothing about what an element is; its flags (click, scroll) carry the meaning.
GENERIC_CLASSES = frozenset({"View", "ViewGroup", "LinearLayout", "FrameLayout", "RelativeLayout",
                             "ConstraintLayout", "Other", "Group"})


@dataclass(frozen=True)
class Bounds:
    left: int
    top: int
    right: int
    bottom: int

    @classmethod
    def parse(cls, raw: str) -> Bounds:
        match = _BOUNDS_RE.fullmatch(raw.strip())
        if not match:
            return cls(0, 0, 0, 0)
        return cls(*(int(g) for g in match.groups()))

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def clip(self, other: Bounds) -> Bounds:
        return Bounds(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )


@dataclass
class Element:
    index: int
    cls: str
    text: str
    desc: str
    resource_id: str
    hint: str
    bounds: Bounds
    label: str
    clickable: bool = False
    long_clickable: bool = False
    checkable: bool = False
    checked: bool = False
    scrollable: bool = False
    editable: bool = False
    focused: bool = False
    enabled: bool = True
    password: bool = False
    selected: bool = False
    risk: str | None = None
    depth: int = 0
    # Text too small to see: content for screen readers only (e.g. a value whose visible version is an image).
    sr_only: bool = False
    # Paint order key: (drawing-order, sibling position) per tree level. Higher = drawn later = on top;
    # an ancestor's key is a prefix of its descendants' keys.
    z: list[int] = field(default_factory=list)

    @property
    def short_id(self) -> str:
        return self.resource_id.split(":id/", 1)[-1]

    @property
    def interactive(self) -> bool:
        return self.clickable or self.long_clickable or self.checkable or self.scrollable or self.editable

    def flags(self) -> list[str]:
        out = []
        if self.clickable:
            out.append("click")
        if self.long_clickable:
            out.append("long")
        if self.checkable:
            out.append("checked" if self.checked else "unchecked")
        if self.scrollable:
            out.append("scroll")
        if self.editable:
            out.append("edit")
        if self.password:
            out.append("password")
        if self.focused:
            out.append("focused")
        if self.selected:
            out.append("selected")
        if not self.enabled:
            out.append("disabled")
        if self.sr_only:
            out.append("sr-only")
        if self.risk:
            out.append(f"RISK:{self.risk}")
        return out

    def describe(self, bounds: bool = False) -> str:
        """One line per element, e.g. `[3] Button "Sign in" #login_btn [click]`.

        Every observe prints one of these per element, so each word costs tokens for the whole session:
        position and size only with `bounds` (layout and touch-target checks), container classes never.
        """
        parts = [f"[{self.index}]"]
        if self.cls not in GENERIC_CLASSES:
            parts.append(self.cls)
        if self.label:
            parts.append(f'"{self.label}"')
        if self.short_id:
            parts.append(f"#{self.short_id}")
        if bounds:
            cx, cy = self.bounds.center
            parts.append(f"@({cx},{cy}) {self.bounds.width}x{self.bounds.height}")
        if flags := self.flags():
            parts.append(f"[{' '.join(flags)}]")
        return " ".join(parts)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["bounds"] = [self.bounds.left, self.bounds.top, self.bounds.right, self.bounds.bottom]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Element:
        data = dict(data)
        data["bounds"] = Bounds(*data["bounds"])
        return cls(**data)


@dataclass
class Snapshot:
    """Everything the agent learns from one hierarchy dump."""

    screen: Bounds
    rotation: int
    package: str
    elements: list[Element] = field(default_factory=list)

    def find(self, index: int) -> Element:
        for el in self.elements:
            if el.index == index:
                return el
        raise LookupError(f"no element [{index}] in the last observation")


def truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_LABEL else text[: _MAX_LABEL - 1] + "…"


def risk(own_label: str, label: str, short_id: str) -> str | None:
    """Only action-like wording counts: "Send feedback" is an action, "Allow X to send you ...?" is not."""
    parts = [own_label] if own_label else label.split(" | ")
    actions = [p for p in parts if guard.action_like(p)]
    return guard.classify(" | ".join(actions), short_id)


def _on_top(a: Element, b: Element) -> bool:
    return a.z > b.z


def _occluders(snapshot: Snapshot, target: Element) -> list[Element]:
    """Interactive elements drawn above `target` that would take a tap meant for it.

    Includes its own interactive descendants: tapping a card's "+" button doesn't open the card.
    """
    return [e for e in snapshot.elements
            if e is not target and e.interactive and _on_top(e, target) and e.bounds.area > 0]


def element_at(snapshot: Snapshot, x: int, y: int) -> Element | None:
    """The topmost interactive element under a point, i.e. the one a tap reaches."""
    hits = [e for e in snapshot.elements if e.interactive and e.bounds.contains(x, y)]
    return max(hits, key=lambda e: e.z, default=None)


_SAMPLE_FRACTIONS = (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9)


def _covering(snapshot: Snapshot, target: Element, blocked: tuple[Bounds, ...]) -> list[Bounds]:
    b = target.bounds
    regions = [e.bounds for e in _occluders(snapshot, target)] + list(blocked)
    return [r for r in regions if r.clip(b).area > 0]


def visible_point(snapshot: Snapshot, target: Element, blocked: tuple[Bounds, ...] = ()) -> tuple[int, int] | None:
    """A point inside `target` that no other interactive element covers, closest to its center.

    `blocked`: screen areas covered by something outside the app's hierarchy, such as the keyboard.
    None means the element is fully covered (e.g. a hidden button under another control, or a row
    behind the bottom navigation or the keyboard): scroll it into view or pick a different target.
    """
    b = target.bounds
    covering = _covering(snapshot, target, blocked)
    cx, cy = b.center
    candidates = sorted(
        {(b.left + round(b.width * fx), b.top + round(b.height * fy))
         for fx in _SAMPLE_FRACTIONS for fy in _SAMPLE_FRACTIONS},
        key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2,
    )
    for x, y in candidates:
        if b.contains(x, y) and not any(r.contains(x, y) for r in covering):
            return x, y
    return None


def human_point(snapshot: Snapshot, target: Element, rng: random.Random,
                blocked: tuple[Bounds, ...] = ()) -> tuple[int, int] | None:
    """Where a finger would land: near the center, never exactly on it, never on a covering control.

    Gaussian around the center (sigma 15% of the size), kept inside the middle 80% of the element.
    """
    b = target.bounds
    covering = _covering(snapshot, target, blocked)
    cx, cy = b.center
    for _ in range(40):
        x = round(rng.gauss(cx, b.width * 0.15))
        y = round(rng.gauss(cy, b.height * 0.15))
        inside = (b.left + b.width * 0.1 <= x <= b.right - b.width * 0.1
                  and b.top + b.height * 0.1 <= y <= b.bottom - b.height * 0.1)
        if inside and not any(r.contains(x, y) for r in covering):
            return x, y
    return visible_point(snapshot, target, blocked)


def _norm(text: str) -> str:
    # Web content uses non-breaking spaces ("€\xa01,99"); queries are typed with normal ones.
    return " ".join(text.replace("\xa0", " ").split()).casefold()


def _match_tier(e: Element, q: str) -> int | None:
    own = {_norm(s) for s in (e.text, e.desc, e.hint) if s}
    parts = {_norm(p) for p in e.label.split(" | ") if p} | {_norm(e.label)}
    every = own | parts
    if q in own:
        return 0
    if q in parts:
        return 1
    if any(s.startswith(q) for s in every):
        return 2
    if any(re.search(r"\b" + re.escape(q), s) for s in every):
        return 3
    if any(q in s for s in every):
        return 4
    return None


def find_by_text(snapshot: Snapshot, query: str) -> list[Element]:
    """Best matches for a visible text, case- and whitespace-insensitive.

    Ranking: exact own text/description > exact part of a merged label > label starting with the
    query > query at a word start > any substring. Within the best tier interactive elements win,
    so "Recipes" means the tab, not the page title.
    """
    q = _norm(query)
    ranked = [(t, e) for e in snapshot.elements if (t := _match_tier(e, q)) is not None]
    if not ranked:
        return []
    best = min(t for t, _ in ranked)
    matches = [e for t, e in ranked if t == best]
    interactive = [e for e in matches if e.interactive]
    return interactive or matches


def find_by_id(snapshot: Snapshot, rid: str) -> list[Element]:
    return [e for e in snapshot.elements if e.resource_id == rid or e.short_id == rid]


def _without_index(line: str) -> str:
    return line.split("] ", 1)[-1]


def listing(elements: list[Element], previous: list[Element] | None = None, bounds: bool = False,
            depth_step: int = 4) -> list[str]:
    """The `elements (...)` block of an observation.

    With `previous` (the last observation of the same screen), elements that look exactly as before are left
    out: on a screen the agent already read, only what changed is news. Indices still refer to the full list.
    """
    lines = [el.describe(bounds) for el in elements]
    indents = ["  " * min(el.depth // depth_step, 3) for el in elements]
    if previous is None:
        return [f"elements ({len(elements)}):", *(i + line for i, line in zip(indents, lines, strict=True))]
    seen = {_without_index(el.describe(bounds)) for el in previous}
    fresh = [(i, line) for i, line in zip(indents, lines, strict=True) if _without_index(line) not in seen]
    hidden = len(lines) - len(fresh)
    head = (f"elements ({len(elements)}; same screen as the last observe, {hidden} unchanged not shown, "
            f"`--full` lists all):")
    return [head, *(i + line for i, line in fresh)] if fresh else [head, "  (nothing changed)"]


_SKIP_ATTRS = {"index", "children", "package"}


def _attrs(node: dict) -> str:
    """Only the attributes that say something: no empty values, no false flags."""
    parts = []
    for key, value in node.items():
        if key in _SKIP_ATTRS or value in ("", "false", False, None, [], {}):
            continue
        if isinstance(value, list) and all(isinstance(v, (int, float)) for v in value):
            value = ",".join(f"{v:g}" for v in value)
        elif isinstance(value, dict):
            value = ",".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in value.items())
        text = str(value)
        parts.append(f'{key}="{text}"' if " " in text or not text else f"{key}={text}")
    return " ".join(parts)


def inspect_lines(el: Element, node: dict, parent: dict | None, children: list[dict], limit: int = 15) -> list[str]:
    """What `inspect` prints: the element as listed, then the raw node that proves it, its parent and children."""
    lines = [el.describe(bounds=True), f"node: {_attrs(node)}"]
    if parent is not None:
        lines.append(f"parent: {_attrs(parent)}")
    lines.append(f"children ({len(children)}):" if children else "children: none")
    lines += [f"  {_attrs(c)}" for c in children[:limit]]
    if len(children) > limit:
        lines.append(f"  ... {len(children) - limit} more")
    return lines
