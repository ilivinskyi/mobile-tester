"""Screenshot preview for the agent: downscaled, with numbered boxes on interactive elements.

The numbers match the `[index]` in the element listing ("set-of-marks" prompting), so the
agent can connect what it sees with what it can tap. Evidence keeps the clean full-size PNG.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .ui import Element

PREVIEW_LONG_EDGE = 960
_PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#f032e6", "#9a6324"]


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def make_preview(png: bytes, elements: list[Element], out: Path, marks: bool = True, unit: float = 1.0) -> float:
    """Write a JPEG preview and return the scale factor (preview px per element unit).

    `unit` is screenshot pixels per element unit: 1 on Android (pixels), the screen scale on iOS (points).
    """
    image = Image.open(io.BytesIO(png)).convert("RGB")
    shrink = min(1.0, PREVIEW_LONG_EDGE / max(image.size))
    scale = shrink * unit
    if shrink < 1.0:
        image = image.resize((round(image.width * shrink), round(image.height * shrink)), Image.LANCZOS)
    if marks:
        draw = ImageDraw.Draw(image)
        font = _font(max(12, round(28 * shrink)))
        for el in elements:
            # Scroll containers span most of the screen and would hide the row numbers inside them.
            if not el.interactive or (el.scrollable and not el.clickable):
                continue
            color = "#ff0000" if el.risk else _PALETTE[el.index % len(_PALETTE)]
            box = [round(v * scale) for v in (el.bounds.left, el.bounds.top, el.bounds.right, el.bounds.bottom)]
            draw.rectangle(box, outline=color, width=2)
            tag = str(el.index)
            tw, th = draw.textbbox((0, 0), tag, font=font)[2:]
            draw.rectangle([box[0], box[1], box[0] + tw + 6, box[1] + th + 4], fill=color)
            draw.text((box[0] + 3, box[1] + 1), tag, fill="white", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "JPEG", quality=80)
    return scale
