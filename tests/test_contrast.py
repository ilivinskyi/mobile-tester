"""Text contrast read from the screenshot: the colours under each text element, as WCAG ratios."""

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from mobiletester.core import commands, contrast
from mobiletester.core.ui import Bounds, Element


def _el(index, label, box, text=None):
    return Element(index=index, cls="android.widget.TextView", text=label if text is None else text, desc="",
                   resource_id="", hint="", bounds=Bounds(*box), label=label)


def _screen(scale=2):
    """A 300x200-unit screen at `scale` px per unit: pale grey on near white (like a 'Danger Zone' card),
    black on white, and an empty box."""
    img = Image.new("RGB", (300 * scale, 200 * scale), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14 * scale)
    draw.rectangle((0, 0, 300 * scale, 50 * scale), fill="#F5F5F5")
    draw.text((10 * scale, 12 * scale), "Wipe Local Database", fill="#E2E2E2", font=font)
    draw.text((10 * scale, 72 * scale), "Notification Preferences", fill="#000000", font=font)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


ELEMENTS = [_el(1, "Wipe Local Database", (0, 0, 300, 50)), _el(2, "Notification Preferences", (0, 60, 300, 100)),
            _el(3, "Empty", (0, 140, 300, 190))]


def test_ratios_match_the_drawn_colours():
    results = contrast.check(_screen(), ELEMENTS, screen_width=300)
    by_label = {r.element.label: r for r in results}
    assert "Empty" not in by_label  # one colour: nothing to measure
    pale, dark = by_label["Wipe Local Database"], by_label["Notification Preferences"]
    assert pale.ratio == pytest.approx(contrast.ratio((0xE2,) * 3, (0xF5,) * 3), abs=0.1)
    assert pale.background == "#F5F5F5" and pale.verdict == "fails at any size"
    assert dark.ratio > 15 and dark.verdict == "ok"
    assert results[0] is pale  # lowest first


def test_known_wcag_values():
    assert contrast.ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert contrast.ratio((0x76, 0x76, 0x76), (255, 255, 255)) == pytest.approx(4.54, abs=0.01)


def test_command_lists_only_low_contrast_texts(tmp_path, capsys):
    shot = tmp_path / "latest.png"
    shot.write_bytes(_screen())
    last = {"screenshot": str(shot), "screen": [300, 200], "elements": [e.to_dict() for e in ELEMENTS]}
    assert commands.print_contrast(last, 4.5, "adt") == 0
    out = capsys.readouterr().out
    assert "1 of 2 text elements below 4.5:1" in out and '[1] "Wipe Local Database"' in out
    assert "Notification Preferences" not in out
    assert commands.print_contrast({"screenshot": None}, 4.5, "adt") == 2
