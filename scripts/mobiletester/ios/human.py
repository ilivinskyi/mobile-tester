"""Acting on the simulator like a person: pacing, press duration, finger position, back swipe, typing.

Everything a test does to the UI goes through Driver. Touches are XCUITest's synthesized touches at screen
points, held for a human time. `fast=True` is for setup steps only and is marked in the action log.
iOS has no system back: back is the left-edge swipe (or the app's own back button, tapped like any other).
"""

from __future__ import annotations

import random
import time
from datetime import datetime

from ..core import screen, session, state
from ..core.pace import PACES, Outcome
from ..core.ui import Bounds
from . import crash, keyboard
from .device import Device, read_screen
from .hierarchy import Key
from .runner import RunnerError
from .simctl import SimctlError

CRASH_COMMAND = "idt crashes"
REACTION_S = 0.3
# A device writes the crash report a few seconds after the app dies; look this long after it stopped running.
DEVICE_CRASH_WINDOW_S = 20


class Driver:
    def __init__(self, dev: Device, pace: str = "human", fast: bool = False, verify: bool = True,
                 rng: random.Random | None = None):
        self.dev = dev
        self.runner = dev.runner
        self.pace = PACES[pace]
        self.fast = fast
        self.verify = verify and not fast
        self.rng = rng or random.Random()

    # --- primitives ------------------------------------------------------------------------------

    def _uniform(self, bounds: tuple[float, float]) -> float:
        return self.rng.uniform(*bounds)

    def _press(self, x: float, y: float, ms: int) -> None:
        # Fast mode still presses: XCUITest has no zero-length touch. 50 ms is the shortest a finger manages.
        self.runner.press(x, y, (50 if self.fast else ms) / 1000)

    def _display(self) -> tuple[float, float]:
        w, h = self.dev.facts()["screen"]
        return w, h

    def _log(self, action: str, outcome: Outcome, started: datetime, **details) -> None:
        entry = {"action": action, "mode": "fast" if self.fast else self.pace.name, **details}
        if outcome.changed is not None:
            entry["changed"] = outcome.changed
        if outcome.crash:
            entry["crash"] = outcome.crash
        session.log_action(self.dev.udid, entry, started=started)

    def _perform(self, action: str, do, verify: bool = True, **details) -> Outcome:
        """Think, act, then wait for the screen to settle and check that something changed."""
        started = time.monotonic()
        before = screen.signature(self.runner.screenshot()) if self.verify and verify else None
        if not self.fast:
            time.sleep(max(0.0, self._uniform(self.pace.think) - (time.monotonic() - started)))
        acted = datetime.now().astimezone()
        do()
        outcome = Outcome(crash_command=CRASH_COMMAND)
        if before is not None:
            # XCUITest returns once the app is idle, which can be just before an animation (the keyboard
            # sliding in) starts; a person would see it a moment later.
            time.sleep(REACTION_S)
            after, outcome.settled = screen.wait_stable(self.runner.screenshot)
            outcome.changed = screen.differs(before, after)
        outcome.crash = self._new_crash()
        self._log(action, outcome, acted, **details)
        return outcome

    def _new_crash(self) -> str | None:
        """Crash watch: a crash report of the session's app written since the last action."""
        bundle = session.package(self.dev.udid)
        if not bundle:
            return None
        marker = state.device_dir(self.dev.udid) / "crash_watch.json"
        seen = state.read_json(marker) or {}
        executable = seen.get("executable") if seen.get("bundle") == bundle else None
        if executable is None:
            try:
                executable = self.dev.tool.app_info(self.dev.udid, bundle)["executable"]
            except SimctlError:
                return None
        since = seen.get("since") or time.time() - 2
        watch = {"bundle": bundle, "executable": executable, "since": since}
        directory = None
        if self.dev.physical:
            directory, watch["down_since"] = self._device_reports(bundle, executable, seen.get("down_since"))
            if directory is None:
                state.write_json(marker, watch)
                return None
        reports = crash.find(executable, bundle, since, directory)
        watch["since"] = max([since, *(p.stat().st_mtime for p in reports)])
        state.write_json(marker, watch)
        return crash.summary(reports[-1]) if reports else None

    def _device_reports(self, bundle: str, executable: str, down_since: float | None) -> tuple:
        """(local copy of the device's crash reports or None when there's no need to look, when the app was
        first seen not running). Listing them is a round trip to the device, and a crashed app isn't running,
        so only look while the app has been down for less than DEVICE_CRASH_WINDOW_S."""
        try:
            running = self.runner.app(bundle, "state") >= 2
        except RunnerError:
            running = False
        if running:
            return None, None
        down_since = down_since or time.time()
        if time.time() - down_since > DEVICE_CRASH_WINDOW_S:
            return None, down_since
        try:
            return crash.sync_device(self.dev.udid, executable), down_since
        except SimctlError:
            return None, down_since

    # --- actions ---------------------------------------------------------------------------------

    def tap(self, x: float, y: float, target: str = "", long: bool = False) -> Outcome:
        ms = round(self._uniform(self.pace.long_press_ms if long else self.pace.press_ms))
        return self._perform("long-press" if long else "tap", lambda: self._press(x, y, ms),
                             x=x, y=y, press_ms=None if self.fast else ms, target=target)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, ms: int | None = None, action: str = "swipe",
              verify: bool = True) -> Outcome:
        if not self.fast:
            # Fingers don't start or end on the exact point; wobble by up to 2% of the distance.
            wobble = max(2, round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 * 0.02))
            x2, y2 = (v + self.rng.randint(-wobble, wobble) for v in (x2, y2))
            if action != "back-gesture":  # the edge swipe must start at the edge
                x1, y1 = (v + self.rng.randint(-wobble, wobble) for v in (x1, y1))
            ms = ms or round(self._uniform(self.pace.swipe_ms))
        ms = ms or 300
        w, h = self._display()
        x1, x2 = (min(max(v, 0), w - 1) for v in (x1, x2))
        y1, y2 = (min(max(v, 1), h - 2) for v in (y1, y2))
        distance = max(1.0, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)
        # A person's finger rests a moment before it moves; longer than ~0.3 s would be a long press.
        hold = 0.02 if self.fast else self._uniform((0.03, 0.08))
        velocity = distance / (ms / 1000)
        return self._perform(action, lambda: self.runner.drag(x1, y1, x2, y2, hold, velocity), verify=verify,
                             x1=x1, y1=y1, x2=x2, y2=y2, ms=ms)

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
        """The interactive back swipe: from the left edge past the middle, at a natural height.

        Measured on an iOS 27 simulator: swipes to 75% of the width went back 17 of 18 times at 700-1400 pt/s;
        to 62% only 5 of 9. A person who means "back" swipes far.
        """
        w, h = self._display()
        y = round(h * self._uniform((0.35, 0.65)))
        return self.swipe(1, y, round(w * self._uniform((0.75, 0.88))), y + self.rng.randint(-15, 15),
                          ms=round(self._uniform((180, 280))), action="back-gesture")

    def home(self) -> Outcome:
        return self._perform("home", self.runner.home, via="home button")

    def key(self, name: str) -> Outcome:
        name = name.lower()
        if name == "back":
            return self.back()
        if name == "home":
            return self.home()
        labels = {"enter": "return", "return": "return", "delete": "delete", "backspace": "delete",
                  "space": "space"}
        if name not in labels:
            raise ValueError(f"unknown key '{name}': back, home, enter, delete or space")
        typist = self._typist()
        return self._perform(f"key-{name}", lambda: typist.press_named(labels[name]), via="keyboard")

    # --- typing ----------------------------------------------------------------------------------

    def _press_key(self, key: Key) -> None:
        b = key.bounds
        x = self.rng.gauss(b.center[0], b.width * 0.12)
        y = self.rng.gauss(b.center[1], b.height * 0.12)
        x = min(max(x, b.left + 2), b.right - 3)
        y = min(max(y, b.top + 2), b.bottom - 3)
        self._press(x, y, round(self._uniform(self.pace.key_press_ms)))
        if not self.fast:
            time.sleep(self._uniform(self.pace.key_gap))

    def _keys(self) -> list[Key]:
        _, kb, *_ = read_screen(self.dev)
        if kb and kb.third_party:
            raise keyboard.ThirdPartyKeyboard()
        return kb.keys if kb else []

    def _typist(self) -> keyboard.Typist:
        return keyboard.Typist(self._keys, self._press_key)

    def type_text(self, text: str, submit: bool = False,
                  log: dict | None = None) -> Outcome:
        """Type via on-screen keys, switching shift and layers like a person."""
        def do() -> None:
            typist = self._typist()
            typist.type(text)
            if submit:
                typist.press_named("return")

        # `log`: the field and the text, hidden when it could be a credential (core/inputs.py).
        return self._perform("type", do, chars=len(text), method="keyboard", submit=submit, **(log or {}))

