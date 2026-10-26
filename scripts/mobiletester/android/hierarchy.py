"""Turning a uiautomator XML dump into a compact list of elements an agent can act on."""

from __future__ import annotations

import xml.etree.ElementTree as ET

# The platform-neutral model and hit testing live in core.ui; re-exported so callers keep using `hierarchy.X`.
from ..core.ui import (  # noqa: F401
    MIN_VISIBLE_PX,
    Bounds,
    Element,
    Snapshot,
    element_at,
    find_by_id,
    find_by_text,
    human_point,
    risk,
    truncate,
    visible_point,
)


def _bool(node: ET.Element, attr: str) -> bool:
    return node.get(attr) == "true"


def _short_class(cls: str) -> str:
    return cls.rsplit(".", 1)[-1] or "View"


def _own_label(node: ET.Element) -> str:
    return (node.get("text") or "").strip() or (node.get("content-desc") or "").strip()


def _is_interactive(node: ET.Element) -> bool:
    cls = node.get("class", "")
    return _is_editable(cls) or any(_bool(node, a) for a in ("clickable", "long-clickable", "checkable", "scrollable"))


def _is_editable(cls: str) -> bool:
    return "EditText" in cls or "AutoCompleteTextView" in cls


def _descendant_label(node: ET.Element, limit: int = 3) -> str:
    """Containers like list rows are clickable while their text lives in child TextViews.

    Interactive descendants are listed on their own, so their texts don't belong to this label
    (a toolbar must not be called "Share | Close tab").
    """
    found: list[str] = []

    def collect(parent: ET.Element) -> None:
        for child in parent.findall("node"):
            if len(found) >= limit or _is_interactive(child):
                continue
            label = _own_label(child)
            if label and label not in found:
                found.append(label)
            collect(child)

    collect(node)
    return " | ".join(found)


def parse(xml: str, display: tuple[int, int] | None = None) -> Snapshot:
    """`display` is the natural (rotation 0) display size from `wm size`. Without it the screen size is
    guessed from the dumped window, which is wrong for dialogs and other non-fullscreen windows."""
    root = ET.fromstring(xml.strip().encode("utf-8"))
    rotation = int(root.get("rotation", "0") or 0)
    top_nodes = root.findall("node")
    if display:
        w, h = display
        screen = Bounds(0, 0, h, w) if rotation in (1, 3) else Bounds(0, 0, w, h)
    else:
        screen = Bounds(0, 0, 0, 0)
        for node in top_nodes:
            b = Bounds.parse(node.get("bounds", ""))
            screen = Bounds(0, 0, max(screen.right, b.right), max(screen.bottom, b.bottom))
    package = top_nodes[0].get("package", "") if top_nodes else ""

    elements: list[Element] = []

    def visit(node: ET.Element, depth: int, inside_interactive: bool, z: list[int]) -> None:
        bounds = Bounds.parse(node.get("bounds", "")).clip(screen)
        cls = node.get("class", "")
        editable = _is_editable(cls)
        interactive = _is_interactive(node)
        own_label = _own_label(node)
        # Rows cut off at the screen edge to a sliver can't be tapped reliably; scroll them in first.
        tappable = bounds.width >= MIN_VISIBLE_PX and bounds.height >= MIN_VISIBLE_PX
        # Text of any size is information, even when it is only there for screen readers.
        readable = bounds.area > 0
        # A plain TextView inside a clickable row is already described by the row's label.
        keep = (interactive and tappable) or (not interactive and readable and own_label and not inside_interactive)
        scrollable = _bool(node, "scrollable")
        if keep:
            # A list's label would just repeat its rows, which are listed on their own.
            label = own_label or (_descendant_label(node) if interactive and not scrollable else "")
            el = Element(
                index=len(elements),
                cls=_short_class(cls),
                text=(node.get("text") or "").strip(),
                desc=(node.get("content-desc") or "").strip(),
                resource_id=node.get("resource-id", ""),
                hint=(node.get("hint") or "").strip(),
                bounds=bounds,
                label=truncate(label),
                clickable=_bool(node, "clickable"),
                long_clickable=_bool(node, "long-clickable"),
                checkable=_bool(node, "checkable"),
                checked=_bool(node, "checked"),
                scrollable=_bool(node, "scrollable"),
                editable=editable,
                focused=_bool(node, "focused"),
                enabled=node.get("enabled", "true") == "true",
                password=_bool(node, "password"),
                selected=_bool(node, "selected"),
                depth=depth,
                sr_only=not interactive and not tappable,
                z=z,
            )
            if el.interactive:
                el.risk = risk(own_label, el.label, el.short_id)
            elements.append(el)
        # Scroll containers don't swallow their children's labels: rows inside a list must stay listed.
        swallows = interactive and not scrollable
        for position, child in enumerate(node.findall("node")):
            order = int(child.get("drawing-order") or 0)
            visit(child, depth + 1, inside_interactive or swallows, [*z, order, position])

    for position, node in enumerate(top_nodes):
        visit(node, 0, False, [int(node.get("drawing-order") or 0), position])
    return Snapshot(screen=screen, rotation=rotation, package=package, elements=elements)




def raw_node(xml: str, el: Element) -> tuple[dict, dict | None, list[dict]]:
    """The element's own node in the dump, its parent and its children: the proof `adt inspect` prints.

    `el.z` holds (drawing-order, position) per tree level, so the positions lead straight to the node.
    """
    root = ET.fromstring(xml.strip().encode("utf-8"))
    parent, node = None, root
    for position in el.z[1::2]:
        parent, node = node, node.findall("node")[position]
    return (dict(node.attrib), dict(parent.attrib) if parent is not None and parent is not root else None,
            [dict(child.attrib) for child in node.findall("node")])
