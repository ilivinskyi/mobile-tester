"""Typing through the on-screen keyboard, the way a person does.

Keys are found in the keyboard's own window (`uiautomator dump --windows`). Gboard labels letters with
the letter and symbols with their spoken names ("Dollar sign"), which depend on the system language;
names that aren't in NAMED_KEYS can't be typed and trigger the caller's fallback.
"""

from __future__ import annotations

import string
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field

from .hierarchy import Bounds

NAMED_KEYS = {
    "space": " ", "period": ".", "comma": ",", "number sign": "#", "dollar sign": "$", "underline": "_",
    "underscore": "_", "ampersand": "&", "dash": "-", "hyphen": "-", "minus": "-", "plus": "+",
    "left parenthesis": "(", "right parenthesis": ")", "slash": "/", "apostrophe": "'", "colon": ":",
    "semicolon": ";", "exclamation": "!", "question mark": "?", "tilde": "~", "grave accent": "`",
    "vertical line": "|", "bullet": "•", "square root": "√", "section sign": "§", "increment": "∆",
    "pound sign": "£", "circumflex accent": "^", "equals": "=", "left curly bracket": "{",
    "right curly bracket": "}", "backslash": "\\", "percent sign": "%", "check mark": "✓",
    "left square bracket": "[", "right square bracket": "]", "less-than sign": "<", "greater-than sign": ">",
    "asterisk": "*", "quotation mark": '"', "at sign": "@",
}

# Layer-switch and editing keys, by Gboard resource id suffix.
_SPECIAL_IDS = {
    "key_pos_del": "delete", "key_pos_switch_to_symbol": "to_symbols", "key_pos_back_to_prime": "to_letters",
    "key_pos_space": "space", "key_pos_ime_action": "action",
}

# Keys after which Gboard leaves a symbol layer for letters by itself.
RETURNS_TO_LETTERS = " '"

TYPABLE = set(string.ascii_letters + string.digits) | set(NAMED_KEYS.values()) | set("@*\",.")


@dataclass
class Key:
    name: str
    bounds: Bounds


@dataclass
class Layer:
    title: str
    chars: dict[str, Key] = field(default_factory=dict)
    specials: dict[str, Key] = field(default_factory=dict)
    bounds: Bounds | None = None  # the keyboard window on screen

    def key_at(self, x: int, y: int) -> Key | None:
        for key in (*self.chars.values(), *self.specials.values()):
            if key.bounds.contains(x, y):
                return key
        return None

    @property
    def kind(self) -> str:
        if "q" in self.chars or "Q" in self.chars:
            return "letters"
        if "1" in self.chars and "@" in self.chars:
            return "symbols"
        if "1" in self.chars and "a" not in self.chars and "~" not in self.chars:
            return "digits"
        return "more"

    @property
    def shifted(self) -> bool:
        letters = [c for c in self.chars if c.isalpha() and c.isascii()]
        return bool(letters) and all(c.isupper() for c in letters)

    def key_for(self, ch: str) -> Key | None:
        if ch in self.chars:
            return self.chars[ch]
        if ch.isalpha() and ch.isascii():
            return self.chars.get(ch.swapcase())
        return None


def parse_layer(xml: str, ime_package: str) -> Layer | None:
    """The keyboard layer currently shown, from a multi-window dump. None when no keyboard is visible."""
    root = ET.fromstring(xml.strip().encode("utf-8"))
    for window in root.iter("window"):
        nodes = [n for n in window.iter("node")
                 if n.get("package") == ime_package and n.get("clickable") == "true"]
        if not nodes:
            continue
        layer = Layer(title=window.get("title", ""), bounds=Bounds.parse(window.get("bounds", "")))
        for node in nodes:
            desc = (node.get("content-desc") or node.get("text") or "").strip()
            rid = (node.get("resource-id") or "").rsplit("/", 1)[-1]
            bounds = Bounds.parse(node.get("bounds", ""))
            key = Key(desc, bounds)
            if rid == "key_pos_shift":
                # The same physical key is Shift ("Shift", "Shift enabled") on letters and the page switch
                # ("More symbols", "Symbols") on symbol layers.
                layer.specials["shift" if desc.casefold().startswith("shift") else "page"] = key
            elif rid in _SPECIAL_IDS:
                layer.specials[_SPECIAL_IDS[rid]] = key
                if rid == "key_pos_space":
                    layer.chars[" "] = key
            elif len(desc) == 1:
                layer.chars[desc] = key
            elif desc.casefold() in NAMED_KEYS:
                layer.chars[NAMED_KEYS[desc.casefold()]] = key
        return layer
    return None


class NoKeyboard(Exception):
    def __init__(self) -> None:
        super().__init__("no on-screen keyboard is visible: tap a text field first")


class CannotType(Exception):
    def __init__(self, chars: str, typed: int):
        super().__init__(f"cannot locate on-screen key(s) for {chars!r} (typed {typed} chars so far)")
        self.chars = chars
        self.typed = typed


# Which layer a switch key leads to. Layouts don't move between visits, so a known layer is reused
# without another dump (a dump of the keyboard window takes ~2.4 s).
_TRANSITIONS = {
    ("letters", "to_symbols"): "symbols", ("symbols", "page"): "more", ("more", "page"): "symbols",
    ("symbols", "to_letters"): "letters", ("more", "to_letters"): "letters", ("digits", "to_letters"): "letters",
}


class Typist:
    """Types text key by key. `dump` returns a multi-window XML dump; `press` taps a key.

    The keyboard is only read where it can change on its own: at the start, after a sentence end
    (auto-capitalisation), after a space or an apostrophe on a symbol layer (Gboard goes back to letters by
    itself, as in "& 100" or "O'Brien"), before leaving a symbol layer, and on getting back to letters (Gboard
    decides Shift again there, e.g. after "<" or "("). Everything else is predicted from layouts already seen.
    """

    def __init__(self, dump: Callable[[], str], press: Callable[[Key], None], ime_package: str):
        self._dump = dump
        self._press = press
        self._ime = ime_package
        self._layouts: dict[str, Layer] = {}
        self._kind: str | None = None
        self._shifted = False
        # A key on a symbol layer was pressed since the last read: the keyboard may have switched back.
        self._unsure = False
        # A key that makes Gboard go back to letters was pressed on a symbol layer: read before the next key,
        # even one the predicted layer has (it would land on a letter in the same place).
        self._stale = False

    def _read(self) -> Layer:
        self._unsure = self._stale = False
        layer = parse_layer(self._dump(), self._ime)
        if layer is None:
            raise NoKeyboard()
        self._layouts[layer.kind] = layer
        self._kind = layer.kind
        self._shifted = layer.shifted
        return layer

    def _current(self) -> Layer:
        return self._layouts[self._kind] if self._kind else self._read()

    def _switch(self, special: str) -> bool:
        key = self._current().specials.get(special)
        if key is None:
            return False
        self._press(key)
        if special == "shift":
            self._shifted = not self._shifted
            return True
        target = _TRANSITIONS.get((self._kind, special))
        if target in self._layouts and target != "letters":
            self._kind = target
        else:
            self._read()
        return True

    def _route(self, ch: str) -> list[str]:
        if ch.isalpha() and ch.isascii():
            return ["to_letters"]
        if self._kind == "letters":
            return ["to_symbols", "page"]
        return ["page", "page"]  # "page" toggles symbols <-> more symbols

    def _find(self, ch: str) -> Key | None:
        if self._stale:
            self._read()
        if key := self._current().key_for(ch):
            return key
        # About to switch layers on a guess: pressing a switch key where it isn't would type a symbol.
        if self._unsure and (key := self._read().key_for(ch)):
            return key
        for special in self._route(ch):
            if not self._switch(special):
                continue
            if key := self._current().key_for(ch):
                return key
        # A prediction may be off (keyboards switch back on their own sometimes): read once and retry.
        if key := self._read().key_for(ch):
            return key
        for special in self._route(ch):
            if self._switch(special) and (key := self._current().key_for(ch)):
                return key
        return None

    def type(self, text: str) -> None:
        unknown = "".join(sorted({c for c in text if c not in TYPABLE}))
        if unknown:
            raise CannotType(unknown, 0)
        for typed, ch in enumerate(text):
            sentence_start = typed >= 2 and text[typed - 1] == " " and text[typed - 2] in ".!?"
            if sentence_start and ch.isalpha():
                self._read()  # the keyboard may have auto-capitalised
            key = self._find(ch)
            if key is None:
                raise CannotType(ch, typed)
            is_letter = ch.isalpha() and ch.isascii()
            if is_letter and ch.isupper() != self._shifted:
                self._switch("shift")
            self._press(key)
            if is_letter:
                self._shifted = False  # Gboard's shift is one-shot
            elif self._kind != "letters":
                self._unsure = True
                self._stale = ch in RETURNS_TO_LETTERS

    def press_action(self) -> None:
        key = self._current().specials.get("action") or self._read().specials.get("action")
        if key is None:
            raise CannotType("<enter>", 0)
        self._press(key)
