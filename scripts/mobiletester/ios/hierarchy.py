"""Turning the runner's XCUITest snapshot (JSON) into the shared screen model.

Coordinates are screen points, the unit XCUITest taps in. Tree order is paint order: later siblings are
drawn on top, so the path of child positions is the element's paint-order key, as on Android.
The on-screen keyboard lives in its own windows; it is kept out of the element list and returned as an
area that taps must avoid, plus the keys typing needs. A third-party keyboard (Grammarly, Gboard, ...) runs in
its own process: its window has Key elements but no Keyboard, and its frames start again at (0, 0) inside the
view that hosts it, so they are moved back onto the screen (to_screen).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.ui import MIN_VISIBLE_PX, Bounds, Element, Snapshot, risk, truncate

TAPPABLE = {
    "Button", "Cell", "Link", "Key", "Tab", "MenuItem", "CheckBox", "RadioButton", "PopUpButton", "MenuButton",
    "ToolbarButton", "Icon", "Switch", "Toggle", "Stepper", "PageIndicator", "Slider", "PickerWheel",
    "SegmentedControl",
}
EDITABLE = {"TextField", "SecureTextField", "TextView", "SearchField"}
SCROLLABLE = {"ScrollView", "Table", "CollectionView"}
CHECKABLE = {"Switch", "Toggle", "CheckBox"}
# Plain content worth listing when it has a label; containers (Other, Window, Toolbar...) only as leaves.
TEXTUAL = {"StaticText", "Image", "Alert"}
# The status bar's height on notched and Dynamic Island iPhones; titles start below it.
STATUS_BAR_PT = 54
# Navigation bars, tab bars and toolbars are drawn above the scroll view that extends under them.
BARS = {"NavigationBar", "TabBar", "Toolbar"}
ON_TOP = 1_000_000
_KEYBOARD_MARKERS = {"inputView", "SystemInputAssistantView"}


@dataclass(frozen=True)
class Key:
    """A key of the on-screen keyboard: what it types or does, and where it is."""

    label: str
    identifier: str
    bounds: Bounds


@dataclass
class Keyboard:
    area: Bounds
    keys: list[Key]
    third_party: bool = False


def _bounds(frame: list[float] | None) -> Bounds:
    if not frame:
        return Bounds(0, 0, 0, 0)
    x, y, w, h = frame
    return Bounds(round(x), round(y), round(x + w), round(y + h))


def _children(node: dict) -> list[dict]:
    return node.get("children", [])


def _walk(node: dict):
    yield node
    for child in _children(node):
        yield from _walk(child)


def _is_keyboard_window(window: dict) -> bool:
    return any(n.get("type") in ("Keyboard", "Key") or n.get("identifier") in _KEYBOARD_MARKERS
               for n in _walk(window))


def _remote_root(parent: list[float], child: list[float]) -> bool:
    """A child at (0, 0) with its off-origin parent's size: the start of another process's coordinates."""
    same_size = abs(parent[2] - child[2]) < 1 and abs(parent[3] - child[3]) < 1
    return parent[:2] != [0, 0] and child[:2] == [0, 0] and same_size


def to_screen(node: dict, offset: tuple[float, float] = (0, 0)) -> dict:
    """A copy of the subtree with every frame in screen points."""
    frame = node.get("frame")
    out = dict(node)
    if frame:
        out["frame"] = [frame[0] + offset[0], frame[1] + offset[1], *frame[2:]]
    children = []
    for child in _children(node):
        child_offset = offset
        if frame and child.get("frame") and _remote_root(out["frame"], child["frame"]):
            child_offset = (out["frame"][0], out["frame"][1])
        children.append(to_screen(child, child_offset))
    if children:
        out["children"] = children
    return out


def _is_interactive(node: dict) -> bool:
    t = node.get("type", "")
    return t in TAPPABLE or t in EDITABLE or t in SCROLLABLE


def _own_label(node: dict) -> str:
    """What a person sees or a screen reader says. Text fields go by their label or placeholder, never by what was
    typed into them (it may be a credential)."""
    if node.get("type") in EDITABLE:
        return node.get("label") or node.get("placeholder", "")
    return node.get("label") or (node.get("value", "") if node.get("type") == "StaticText" else "")


def _descendant_label(node: dict, limit: int = 3) -> str:
    """Cells and buttons often carry no label while their texts are child StaticTexts."""
    found: list[str] = []

    def collect(parent: dict) -> None:
        for child in _children(parent):
            if len(found) >= limit or _is_interactive(child):
                continue
            label = _own_label(child)
            if label and label not in found and child.get("type") in TEXTUAL:
                found.append(label)
            collect(child)

    collect(node)
    return " | ".join(found)


def _noise(node: dict) -> bool:
    # Scroll indicators carry an accessibility label ("Vertical scroll bar, 1 page") but are not content.
    return "scroll bar" in node.get("label", "").casefold()


def parse(data: dict, bundle_id: str = "") -> tuple[Snapshot, Keyboard | None]:
    """`data` is the runner's /tree answer: {"tree": app snapshot, "alerts": [SpringBoard alerts]}."""
    root = data["tree"]
    screen = _bounds(root.get("frame"))
    elements: list[Element] = []
    keyboard_areas: list[Bounds] = []
    keys: list[Key] = []
    third_party = False

    def visit(node: dict, depth: int, inside_interactive: bool, z: list[int]) -> None:
        t = node.get("type", "")
        bounds = _bounds(node.get("frame")).clip(screen)
        interactive = _is_interactive(node)
        own = _own_label(node)
        tappable = bounds.width >= MIN_VISIBLE_PX and bounds.height >= MIN_VISIBLE_PX
        leaf = not _children(node)
        textual = t in TEXTUAL or (leaf and t == "Other")
        keep = not _noise(node) and (
            (interactive and tappable)
            or (not interactive and textual and own and bounds.area > 0 and not inside_interactive)
        )
        if keep:
            label = own or (_descendant_label(node) if interactive and t not in SCROLLABLE else "")
            value = node.get("value", "")
            el = Element(
                index=len(elements),
                cls=t,
                text=value if t in EDITABLE else "",
                desc=node.get("label", ""),
                resource_id=node.get("identifier", ""),
                hint=node.get("placeholder", ""),
                bounds=bounds,
                label=truncate(label),
                clickable=t in TAPPABLE,
                checkable=t in CHECKABLE,
                checked=t in CHECKABLE and value in ("1", "true", "on"),
                scrollable=t in SCROLLABLE,
                editable=t in EDITABLE,
                enabled=node.get("enabled", True),
                password=t == "SecureTextField",
                selected=node.get("selected", False),
                depth=depth,
                z=z,
            )
            if el.interactive:
                el.risk = risk(own, el.label, el.resource_id)
            elements.append(el)
        swallows = interactive and t not in SCROLLABLE
        if t in BARS and len(z) > 2:
            # Bars float above the content scrolling under them, whatever their place in the tree.
            z = [*z[:2], ON_TOP, *z[2:]]
        for position, child in enumerate(_children(node)):
            visit(child, depth + 1, inside_interactive or swallows, [*z, position])

    for position, window in enumerate(_children(root)):
        if _is_keyboard_window(window):
            window = to_screen(window)
            if any(n.get("type") == "Keyboard" or n.get("identifier") in _KEYBOARD_MARKERS for n in _walk(window)):
                keyboard_areas.extend(_bounds(n.get("frame")).clip(screen) for n in _walk(window)
                                      if n.get("type") == "Keyboard" or n.get("identifier") in _KEYBOARD_MARKERS)
                for n in _walk(window):
                    if n.get("type") == "Keyboard":
                        keys.extend(_keys(n, screen))
            else:
                # A third-party keyboard: its area is everything in the window short of the full screen.
                third_party = True
                keyboard_areas.extend(b for n in _walk(window)
                                      if (b := _bounds(n.get("frame")).clip(screen)).area and b != screen)
                keys.extend(_keys(window, screen, only=("Key",)))
            continue
        visit(window, 1, False, [0, position])
    # System alerts (SpringBoard) are drawn above the app.
    for position, alert in enumerate(data.get("alerts", [])):
        visit(alert, 1, False, [1, position])

    keyboard = None
    if keyboard_areas:
        area = keyboard_areas[0]
        for b in keyboard_areas[1:]:
            area = Bounds(min(area.left, b.left), min(area.top, b.top), max(area.right, b.right),
                          max(area.bottom, b.bottom))
        keyboard = Keyboard(area=area, keys=keys, third_party=third_party)
    return Snapshot(screen=screen, rotation=0, package=bundle_id, elements=elements), keyboard


def _keys(keyboard: dict, screen: Bounds, only: tuple[str, ...] = ("Key", "Button")) -> list[Key]:
    out = []
    for n in _walk(keyboard):
        if n.get("type") not in only:
            continue
        b = _bounds(n.get("frame")).clip(screen)
        if b.area > 0:
            out.append(Key(label=n.get("label", ""), identifier=n.get("identifier", ""), bounds=b))
    return out


def screen_title(snapshot: Snapshot) -> str:
    """A stand-in for Android's Activity name in screen fingerprints: the topmost static title, if any.

    The status bar (clock, carrier) is above STATUS_BAR_PT and changes on its own, so it never counts.
    """
    texts = [e for e in snapshot.elements if e.cls == "StaticText"
             and STATUS_BAR_PT <= e.bounds.top < snapshot.screen.height * 0.2]
    return min(texts, key=lambda e: e.bounds.top).label if texts else ""


def raw_node(data: dict, el: Element) -> tuple[dict, dict | None, list[dict]]:
    """The element's own node in the runner's tree, its parent and its children: the proof `idt inspect` prints.

    `el.z` starts with 0 for the app's windows or 1 for system alerts, then the child position per level
    (ON_TOP marks bars drawn above the content and is not a position).
    """
    path = [p for p in el.z[1:] if p != ON_TOP]
    siblings = _children(data["tree"]) if el.z[0] == 0 else data.get("alerts", [])
    parent, node = None, None
    for position in path:
        parent, node = node, siblings[position]
        siblings = _children(node)

    def flat(n: dict) -> dict:
        return {k: v for k, v in n.items() if k != "children"}

    return flat(node), flat(parent) if parent is not None else None, [flat(c) for c in _children(node)]
