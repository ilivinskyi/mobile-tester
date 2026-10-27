"""Typing via Gboard, using real multi-window dumps of its three layers (Pixel 7a, English US)."""

import re

import pytest

from mobiletester.android import keyboard

IME = "com.google.android.inputmethod.latin"
LAYERS = {"letters": "gboard_letters.xml", "symbols": "gboard_symbols.xml", "more": "gboard_more_symbols.xml"}
# What the layer-switch keys do on the real keyboard.
SWITCHES = {"Symbol keyboard": "symbols", "More symbols": "more", "Symbols": "symbols", "Letter keyboard": "letters"}


class FakeGboard:
    def __init__(self, fixture_xml):
        self.xml = {name: fixture_xml(f) for name, f in LAYERS.items()}
        self.layer = "letters"
        self.pressed: list[str] = []
        self.dumps = 0

    def dump(self) -> str:
        self.dumps += 1
        return self.xml[self.layer]

    def press(self, key: keyboard.Key) -> None:
        self.pressed.append(key.name)
        self.layer = SWITCHES.get(key.name, self.layer)


def test_parse_letters_layer(fixture_xml):
    layer = keyboard.parse_layer(fixture_xml("gboard_letters.xml"), IME)
    assert layer.kind == "letters" and layer.title == "English (US) (QWERTY)"
    assert {"q", "a", "z", " ", "."} <= layer.chars.keys()
    assert {"shift", "delete", "to_symbols", "action"} <= layer.specials.keys()


def test_keyboard_window_bounds_and_key_at(fixture_xml):
    layer = keyboard.parse_layer(fixture_xml("gboard_letters.xml"), IME)
    assert (layer.bounds.top, layer.bounds.bottom) == (1517, 2400)
    assert layer.key_at(60, 1730).name == "q"
    assert layer.key_at(990, 2196).name == "Search"
    assert layer.key_at(540, 100) is None


def test_parse_symbol_layers_by_spoken_names(fixture_xml):
    symbols = keyboard.parse_layer(fixture_xml("gboard_symbols.xml"), IME)
    assert symbols.kind == "symbols" and {"1", "@", "#", "$", "(", "?"} <= symbols.chars.keys()
    assert symbols.specials["page"].name == "More symbols"
    more = keyboard.parse_layer(fixture_xml("gboard_more_symbols.xml"), IME)
    assert more.kind == "more" and {"~", "=", "{", "%", "<"} <= more.chars.keys()


def test_types_letters_digits_and_symbols(fixture_xml):
    gb = FakeGboard(fixture_xml)
    keyboard.Typist(gb.dump, gb.press, IME).type("Hi 7$~")
    assert gb.pressed == [
        "Shift", "h", "i", "Space",
        "Symbol keyboard", "7", "Dollar sign",
        "More symbols", "Tilde",
    ]


def test_returns_to_letters(fixture_xml):
    gb = FakeGboard(fixture_xml)
    keyboard.Typist(gb.dump, gb.press, IME).type("1a")
    assert gb.pressed == ["Symbol keyboard", "1", "Letter keyboard", "a"]


def test_layouts_are_cached_to_keep_typing_fast(fixture_xml):
    # A dump of the keyboard window takes ~2.4 s on a Pixel 7a; a person types a word in about one second.
    gb = FakeGboard(fixture_xml)
    keyboard.Typist(gb.dump, gb.press, IME).type("Wi-Fi 5G")
    assert gb.pressed == ["Shift", "w", "i", "Symbol keyboard", "Dash", "Letter keyboard", "Shift", "f", "i",
                          "Space", "Symbol keyboard", "5", "Letter keyboard", "Shift", "g"]
    # initial layer, first visit of the symbols layer, and a check before and after each return to letters
    # (Gboard decides Shift again there)
    assert gb.dumps == 6


def test_rereads_after_sentence_end_for_auto_capitalisation(fixture_xml):
    gb = FakeGboard(fixture_xml)
    keyboard.Typist(gb.dump, gb.press, IME).type("ok. go")
    assert gb.dumps == 2


def test_shift_enabled_label_is_still_shift(fixture_xml):
    shifted = fixture_xml("gboard_letters.xml").replace('content-desc="Shift"', 'content-desc="Shift enabled"')
    layer = keyboard.parse_layer(shifted, IME)
    assert layer.specials["shift"].name == "Shift enabled" and "page" not in layer.specials


def test_untypable_chars_fail_before_typing(fixture_xml):
    gb = FakeGboard(fixture_xml)
    with pytest.raises(keyboard.CannotType) as exc:
        keyboard.Typist(gb.dump, gb.press, IME).type("Привіт")
    assert exc.value.typed == 0 and gb.pressed == []


def test_no_keyboard_visible(fixture_xml):
    xml = fixture_xml("pantry_search_results.xml")
    with pytest.raises(keyboard.NoKeyboard):
        keyboard.Typist(lambda: xml, lambda k: None, IME).type("a")


class AutoReturningGboard(FakeGboard):
    """Gboard goes back to letters by itself after an apostrophe, as in "O'Brien" (seen on a Pixel emulator)."""

    def press(self, key: keyboard.Key) -> None:
        super().press(key)
        if key.name == "Apostrophe":
            self.layer = "letters"


def test_a_keyboard_that_returns_to_letters_by_itself_is_read_again(fixture_xml):
    gb = AutoReturningGboard(fixture_xml)
    keyboard.Typist(gb.dump, gb.press, IME).type("O'Brien")
    typed = [name for name in gb.pressed if name not in SWITCHES and name != "Shift"]
    assert typed == ["o", "Apostrophe", "b", "r", "i", "e", "n"]
    assert gb.pressed.count("Letter keyboard") == 0  # it was already back on letters


class FieldGboard(FakeGboard):
    """Closer to the phone: taps land by position, auto-capitalised at the start of an empty field, a one-shot
    Shift that Gboard may turn on again when going back to letters, and back to letters by itself after a space
    or an apostrophe on a symbol page. Keeps the text that lands in the field."""

    def __init__(self, fixture_xml):
        super().__init__(fixture_xml)
        self.shifted = True
        self.text = ""
        self.xml["letters_shifted"] = re.sub(r'content-desc="([a-z])"', lambda m: f'content-desc="{m[1].upper()}"',
                                             self.xml["letters"])

    def dump(self) -> str:
        self.dumps += 1
        return self.xml["letters_shifted" if self.layer == "letters" and self.shifted else self.layer]

    def press(self, key: keyboard.Key) -> None:
        # A tap types what is under it on the page actually shown, whatever the typist thought was there.
        b = key.bounds
        shown = keyboard.parse_layer(self.xml[self.layer], IME)
        key = shown.key_at((b.left + b.right) // 2, (b.top + b.bottom) // 2)
        self.pressed.append(key.name)
        if key.name in SWITCHES:
            self.layer = SWITCHES[key.name]
            # Gboard decides Shift again on the way back; on the phone it came on after "<", "/" and "(".
            if self.layer == "letters" and self.text[-1:] in ("<", "/", "("):
                self.shifted = True
            return
        if key.name.startswith("Shift"):
            self.shifted = not self.shifted
            return
        ch = key.name.lower() if len(key.name) == 1 else keyboard.NAMED_KEYS[key.name.casefold()]
        self.text += ch.upper() if self.layer == "letters" and self.shifted else ch  # labels don't decide case
        self.shifted = False
        if self.layer != "letters" and ch in " '":
            self.layer = "letters"


def test_space_on_a_symbol_page_and_returning_to_letters_type_what_was_asked(fixture_xml):
    # Typed on a Pixel 7a as "<B>bold</B> & qpp% $(X) cquote'": the typist took the symbols page for granted
    # after Gboard had gone back to letters, and kept a Shift state from before the switch.
    text = "<b>bold</b> & 100% $(x) \"quote'"
    gb = FieldGboard(fixture_xml)
    keyboard.Typist(gb.dump, gb.press, IME).type(text)
    assert gb.text == text
