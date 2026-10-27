"""Acting on the device like a person: pacing, press duration, finger position, system navigation, typing.

Everything a test does to the UI goes through Driver. `fast=True` is for setup steps only (install,
reset, reaching the start state); it uses instant adb input and is marked as such in the action log.
"""

from __future__ import annotations

import os
import random
import time
from datetime import datetime

from ..core import screen, session, state
from ..core.pace import PACES, Outcome
from . import applog, capture, device, keyboard, perf
from .adb import Adb
from .hierarchy import Bounds

# Session memory trend: a meminfo sample every N actions (about a second each); 0 turns it off.
MEMORY_EVERY = int(os.environ.get("ADT_MEMORY_EVERY", "10"))


def back_swipe_heights(height: int, keyboard_top: int | None) -> tuple[float, float]:
    """Where along the left edge a thumb starts the back swipe: the middle of the screen, but above the
    keyboard when it is open (a swipe that starts on the keyboard goes to the keyboard, not to back)."""
    low, high = height * 0.35, height * 0.65
    if keyboard_top is not None:
        high = min(high, keyboard_top - height * 0.03)
        low = min(low, high - height * 0.1)
    return max(low, height * 0.1), max(high, height * 0.15)


class Driver:
    def __init__(self, adb: Adb, pace: str = "human", fast: bool = False, verify: bool = True,
                 rng: random.Random | None = None):
        self.adb = adb
        self.pace = PACES[pace]
        self.fast = fast
        self.verify = verify and not fast
        self.rng = rng or random.Random()

    # --- primitives ------------------------------------------------------------------------------

    def _uniform(self, bounds: tuple[float, float]) -> float:
        return self.rng.uniform(*bounds)

    def _press(self, x: int, y: int, ms: int) -> None:
        if self.fast:
            self.adb.shell("input", "tap", str(x), str(y))
        else:
            # A swipe that doesn't move is a press held for `ms`: a real finger is never down for 0 ms.
            self.adb.shell("input", "swipe", str(x), str(y), str(x), str(y), str(ms))

    def _grab(self) -> bytes:
        return self.adb.exec_out("screencap", "-p", timeout=20)

    def _display(self) -> tuple[int, int]:
        """The screen as it is now: the natural size turned by the last observed rotation (`adt rotate`)."""
        w, h = device.facts(self.adb)["display"]
        last = device.last_observation(self.adb.serial) or {}
        return (h, w) if last.get("rotation") in (1, 3) else (w, h)

    def _log(self, action: str, outcome: Outcome, started: datetime, **details) -> None:
        entry = {"action": action, "mode": "fast" if self.fast else self.pace.name, **details}
        if outcome.changed is not None:
            entry["changed"] = outcome.changed
        if outcome.crash:
            entry["crash"] = outcome.crash
        if outcome.log_issues:
            entry["log_issues"] = outcome.log_issues
        session.log_action(self.adb.serial, entry, started=started)

    def _perform(self, action: str, do, verify: bool = True, **details) -> Outcome:
        """Think, act, then wait for the screen to settle and check that something changed."""
        started = time.monotonic()
        before = screen.signature(self._grab()) if self.verify and verify else None
        if not self.fast:
            time.sleep(max(0.0, self._uniform(self.pace.think) - (time.monotonic() - started)))
        acted = datetime.now().astimezone()
        do()
        outcome = Outcome()
        if before is not None:
            after, outcome.settled = screen.wait_stable(self._grab)
            outcome.changed = screen.differs(before, after)
        # Crash watch: a crash is caught at the step that caused it, not at wrap-up.
        if crash_lines := capture.new_crashes(self.adb):
            outcome.crash = capture.crash_summary(crash_lines)
        self._watch_session(outcome)
        self._log(action, outcome, acted, **details)
        return outcome

    def _watch_session(self, outcome: Outcome) -> None:
        """During a session: the app's new log issues, and a memory sample every MEMORY_EVERY actions."""
        run, package = session.run_dir(self.adb.serial), session.package(self.adb.serial)
        if run is None or package is None:
            return
        outcome.log_issues = [issue.short() for issue in applog.new_issues(self.adb, run, package)]
        counter_file = state.device_dir(self.adb.serial) / "memory_trend.json"
        counter = state.read_json(counter_file) or {}
        count = (counter.get("actions", 0) + 1) if counter.get("run") == str(run) else 1
        state.write_json(counter_file, {"run": str(run), "actions": count})
        if MEMORY_EVERY and count % MEMORY_EVERY == 0:
            sample = perf.memory(self.adb, package)
            perf.append(self.adb.serial, "memory_trend",
                        {"t": datetime.now().astimezone().isoformat(timespec="seconds"), "action": count, **sample})

    # --- actions ---------------------------------------------------------------------------------

    def tap(self, x: int, y: int, target: str = "", long: bool = False) -> Outcome:
        ms = round(self._uniform(self.pace.long_press_ms if long else self.pace.press_ms))
        return self._perform("long-press" if long else "tap", lambda: self._press(x, y, ms),
                             x=x, y=y, press_ms=None if self.fast else ms, target=target)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int | None = None, action: str = "swipe",
              verify: bool = True) -> Outcome:
        if not self.fast:
            # Fingers don't start or end on the exact pixel; wobble by up to 2% of the distance.
            wobble = max(3, round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 * 0.02))
            x1, y1, x2, y2 = (v + self.rng.randint(-wobble, wobble) for v in (x1, y1, x2, y2))
            ms = ms or round(self._uniform(self.pace.swipe_ms))
        ms = ms or 300
        w, h = self._display()
        x1, x2 = (min(max(v, 1), w - 2) for v in (x1, x2))
        y1, y2 = (min(max(v, 1), h - 2) for v in (y1, y2))
        return self._perform(action, lambda: self.adb.shell("input", "swipe", *map(str, (x1, y1, x2, y2, ms))),
                             verify=verify, x1=x1, y1=y1, x2=x2, y2=y2, ms=ms)

    def scroll(self, direction: str, area: Bounds) -> Outcome:
        cx, cy = area.center
        frac = 0.6 if self.fast else self._uniform((0.5, 0.7))
        dx, dy = round(area.width * frac / 2), round(area.height * frac / 2)
        moves = {
            "down": (cx, cy + dy, cx, cy - dy), "up": (cx, cy - dy, cx, cy + dy),
            "right": (cx + dx, cy, cx - dx, cy), "left": (cx - dx, cy, cx + dx, cy),
        }
        return self.swipe(*moves[direction], action=f"scroll-{direction}")

    def back(self) -> Outcome:
        """Back the way this device's user would do it: edge swipe in gesture mode, nav-bar key otherwise."""
        if self.fast or device.facts(self.adb)["nav_mode"] != "gesture":
            # The 3-button navigation bar sends exactly this key event.
            return self._perform("back", lambda: self.adb.shell("input", "keyevent", "KEYCODE_BACK"), via="key")
        w, h = self._display()
        keyboard = device.keyboard_bounds(self.adb)
        y = round(self._uniform(back_swipe_heights(h, keyboard.top if keyboard else None)))
        return self.swipe(2, y, round(w * self._uniform((0.3, 0.42))), y + self.rng.randint(-25, 25),
                          ms=round(self._uniform((160, 260))), action="back-gesture")

    def home(self) -> Outcome:
        if self.fast or device.facts(self.adb)["nav_mode"] != "gesture":
            return self._perform("home", lambda: self.adb.shell("input", "keyevent", "KEYCODE_HOME"), via="key")
        w, h = self._display()
        x = w // 2 + self.rng.randint(-30, 30)
        return self.swipe(x, h - 3, x, round(h * 0.6), ms=round(self._uniform((180, 260))), action="home-gesture")

    def key(self, name: str) -> Outcome:
        if name.lower() == "back":
            return self.back()
        if name.lower() == "home":
            return self.home()
        return self._perform(f"key-{name.lower()}", lambda: device.key(self.adb, name), via="key")

    # --- typing ----------------------------------------------------------------------------------

    def _press_key(self, key: keyboard.Key) -> None:
        b = key.bounds
        x = round(self.rng.gauss(b.center[0], b.width * 0.12))
        y = round(self.rng.gauss(b.center[1], b.height * 0.12))
        x = min(max(x, b.left + 2), b.right - 3)
        y = min(max(y, b.top + 2), b.bottom - 3)
        self._press(x, y, round(self._uniform(self.pace.key_press_ms)))
        time.sleep(self._uniform(self.pace.key_gap))

    def _typist(self) -> keyboard.Typist:
        ime_package = device.facts(self.adb)["ime"].split("/", 1)[0]
        return keyboard.Typist(lambda: device.dump_windows(self.adb), self._press_key, ime_package)

    def type_text(self, text: str, fallback: str = "ask", submit: bool = False,
                  log: dict | None = None) -> Outcome:
        """Type via on-screen keys. `fallback`: 'ask' raises CannotType, 'keyevents' types the rest
        one character at a time with key events, 'bulk' injects it at once."""
        method = "fast-bulk" if self.fast else "keyboard"

        def do() -> None:
            nonlocal method
            if not self.fast:
                typist = self._typist()
                try:
                    typist.type(text)
                    if submit:
                        typist.press_action()
                    return
                except (keyboard.CannotType, keyboard.NoKeyboard) as exc:
                    if fallback == "ask":
                        raise
                    method = f"keyboard+{fallback}"
                    text_left = text[exc.typed:] if isinstance(exc, keyboard.CannotType) else text
                    self._fallback_type(text_left, fallback)
            else:
                device.type_text(self.adb, text)
            if submit:
                device.key(self.adb, "enter")

        # `log`: the field and the text, hidden when it could be a credential (core/inputs.py).
        return self._perform("type", do, chars=len(text), method=method, submit=submit, **(log or {}))

    def _fallback_type(self, text: str, fallback: str) -> None:
        if fallback == "bulk":
            device.type_text(self.adb, text)
            return
        for ch in text:
            device.type_text(self.adb, ch)
            time.sleep(self._uniform(self.pace.key_gap))
