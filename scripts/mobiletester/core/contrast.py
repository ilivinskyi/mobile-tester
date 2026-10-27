"""Text contrast from the last screenshot: WCAG ratios for every element that shows text.

The hierarchy says where text is but not its colours, so each text box is read from the screenshot:
its most common colour is the background, and the colour that stands out most from it (among colours
covering a few percent of the box, so anti-aliased edges don't count) is the text.
"""

from __future__ import annotations

import io
from collections import Counter
from dataclasses import dataclass

from PIL import Image

from .ui import Element

AA_NORMAL = 4.5  # WCAG 2 AA, normal text
AA_LARGE = 3.0  # WCAG 2 AA, large text (24 px / 18.66 px bold and up, in CSS terms)
_MIN_SHARE = 0.01  # a colour covering less of the box is an edge or a speck, not the text
_MIN_PIXELS = 20
# A box with this many colours of 2% or more is a photo or a gradient: no single background to measure.
_PHOTO_COLOURS = 8


@dataclass
class Result:
    element: Element
    ratio: float
    text: str  # "#rrggbb"
    background: str

    @property
    def verdict(self) -> str:
        if self.ratio < AA_LARGE:
            return "fails at any size"
        if self.ratio < AA_NORMAL:
            return "passes only as large text"
        return "ok"


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def text_and_background(box: Image.Image) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    """(text colour, background colour) of a box of text, or None when it has only one colour."""
    raw = box.convert("RGB").tobytes()  # works on every Pillow, unlike getdata()
    pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
    if not pixels:
        return None
    # Group near-identical colours (compression noise), then use each group's mean colour.
    groups: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    for p in pixels:
        groups.setdefault((p[0] >> 4, p[1] >> 4, p[2] >> 4), []).append(p)
    counts = Counter({k: len(v) for k, v in groups.items()})

    def mean(key: tuple[int, int, int]) -> tuple[int, int, int]:
        members = groups[key]
        return tuple(round(sum(c[i] for c in members) / len(members)) for i in range(3))  # type: ignore[return-value]

    if sum(1 for n in counts.values() if n >= 0.02 * len(pixels)) > _PHOTO_COLOURS:
        return None
    background_key = counts.most_common(1)[0][0]
    background = mean(background_key)
    least = max(_MIN_PIXELS, _MIN_SHARE * len(pixels))
    candidates = [k for k, n in counts.items() if k != background_key and n >= least]
    if not candidates:
        return None
    text = max((mean(k) for k in candidates), key=lambda c: ratio(c, background))
    return text, background


def _shows_text(el: Element) -> bool:
    if el.sr_only or el.bounds.width < 4 or el.bounds.height < 4:
        return False
    return bool((el.text or "").strip()) or (bool(el.label) and not el.interactive)


def check(png: bytes, elements: list[Element], screen_width: int) -> list[Result]:
    """Contrast of every text element, lowest first. `screen_width` is in the elements' units (Android
    pixels, iOS points), so boxes map onto the screenshot whatever its resolution."""
    image = Image.open(io.BytesIO(png))
    factor = image.width / screen_width if screen_width else 1.0
    screen_area = image.width * image.height
    results = []
    for el in elements:
        if not _shows_text(el):
            continue
        b = el.bounds
        box = (round(b.left * factor), round(b.top * factor), round(b.right * factor), round(b.bottom * factor))
        if (box[2] - box[0]) * (box[3] - box[1]) > 0.4 * screen_area:
            continue  # a whole panel, not a text box
        colours = text_and_background(image.crop(box))
        if colours:
            text, background = colours
            results.append(Result(el, round(ratio(text, background), 2), _hex(text), _hex(background)))
    return sorted(results, key=lambda r: r.ratio)


def first_visit_note(png: bytes, elements: list[Element], screen_width: int, tool: str) -> str | None:
    """One line for `observe` on a screen's first visit, when some text is below 4.5:1; else None."""
    low = [r for r in check(png, elements, screen_width) if r.ratio < AA_NORMAL]
    if not low:
        return None
    shown = ", ".join(f"[{r.element.index}] {r.ratio}:1" for r in low[:6]) + (" ..." if len(low) > 6 else "")
    return (f"contrast: {len(low)} text(s) below 4.5:1 on this new screen: {shown} "
            f"(`{tool} contrast` for the colours; check the screenshot)")


def lines(results: list[Result], minimum: float = AA_NORMAL) -> list[str]:
    low = [r for r in results if r.ratio < minimum]
    if not low:
        return [f"contrast: all {len(results)} text elements reach {minimum}:1"]
    out = [f"contrast: {len(low)} of {len(results)} text elements below {minimum}:1 (WCAG AA: 4.5 normal, 3 large)"]
    for r in low:
        out.append(f"  [{r.element.index}] \"{r.element.label[:60]}\" {r.ratio}:1, text {r.text} on {r.background}"
                   f" ({r.verdict})")
    out.append("Check each on the screenshot before writing it down: a picture behind text or a selected state "
               "can fool the colour reading.")
    return out
