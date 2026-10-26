"""Measure how big `adt observe` / `idt observe` element listings are, on the UI dumps in tests/fixtures.

Run from the repo root: `uv run python scripts/measure_observe.py`. Tokens are estimated as characters / 4.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobiletester.android import hierarchy as android  # noqa: E402
from mobiletester.core import ui  # noqa: E402
from mobiletester.ios import hierarchy as ios  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
# Pairs of dumps of one screen before and after a step on it.
SAME_SCREEN = [("pantry_search_results.xml", "pantry_stepper_no_keyboard.xml"),
               ("pantry_home.xml", "pantry_home_with_card.xml"),
               ("pantry_stepper_no_keyboard.xml", "pantry_search_with_basket.xml")]


def listing(elements) -> str:
    return "\n".join(el.describe() for el in elements)


def main() -> None:
    rows = []
    for path in sorted(FIXTURES.glob("*.xml")):
        if path.name.startswith("gboard_"):
            continue  # keyboard windows, not app screens
        rows.append((path.name, listing(android.parse(path.read_text(encoding="utf-8")).elements)))
    for path in sorted(FIXTURES.glob("ios_*.json")):
        if "devicectl" in path.name or "keyboard_" in path.name:
            continue
        rows.append((path.name, listing(ios.parse(json.loads(path.read_text(encoding="utf-8")))[0].elements)))
    total = 0
    for name, text in rows:
        total += len(text)
        print(f"{name:34} {text.count(chr(10)) + 1:4} elements {len(text):6} chars ~{len(text) // 4:5} tokens")
    print(f"{'total':34} {'':14} {total:6} chars ~{total // 4:5} tokens")
    print("\nsame screen observed again (only changed elements listed):")
    for before, after in SAME_SCREEN:
        old = android.parse((FIXTURES / before).read_text(encoding="utf-8")).elements
        new = android.parse((FIXTURES / after).read_text(encoding="utf-8")).elements
        full, diff = "\n".join(ui.listing(new)), "\n".join(ui.listing(new, previous=old))
        print(f"{before} -> {after}: ~{len(full) // 4} -> ~{len(diff) // 4} tokens")


if __name__ == "__main__":
    main()
