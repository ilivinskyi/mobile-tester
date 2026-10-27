"""Observing the screen and acting on it."""

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..core import annotate, contrast, screens, session, state
from ..core.fingerprint import screen_fingerprint
from . import hierarchy, keyboard
from .adb import Adb, AdbError
from .hierarchy import Bounds, Snapshot

_REMOTE_DUMP = "/sdcard/adt_dump.xml"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_ACTIVITY_RE = re.compile(r"(?:topResumedActivity|mResumedActivity|mCurrentFocus)[=:].*?\s([\w.]+)/([\w.$]+)")


def dump_hierarchy(adb: Adb, attempts: int = 3) -> str:
    """uiautomator refuses to dump while the UI never goes idle (animations, video), so retry."""
    last = ""
    for attempt in range(attempts):
        last = adb.shell("uiautomator", "dump", _REMOTE_DUMP, check=False, timeout=30)
        if "dumped to" in last:
            xml = adb.exec_out("cat", _REMOTE_DUMP).decode("utf-8", errors="replace")
            if "<hierarchy" in xml:
                return xml
        time.sleep(0.6 * (attempt + 1))
    raise AdbError(f"uiautomator dump failed: {last.strip() or 'no output'}")


def dump_windows(adb: Adb) -> str:
    """Dump of every window on screen (app, keyboard, system bars). Only used for the keyboard: it
    goes through the accessibility layer like dump_hierarchy."""
    remote = "/sdcard/adt_windows.xml"
    out = adb.shell("uiautomator", "dump", "--windows", remote, check=False, timeout=30)
    if "dumped to" not in out:
        raise AdbError(f"uiautomator dump --windows failed: {out.strip() or 'no output'}")
    xml = adb.exec_out("cat", remote).decode("utf-8", errors="replace")
    _remember_keyboard(adb, xml)
    return xml


def _ime_package(adb: Adb) -> str:
    return facts(adb)["ime"].split("/", 1)[0]


def _remember_keyboard(adb: Adb, xml: str) -> None:
    layer = keyboard.parse_layer(xml, _ime_package(adb))
    if layer and layer.bounds and layer.bounds.area:
        b = layer.bounds
        state.write_json(state.device_dir(adb.serial) / "keyboard.json", {"bounds": [b.left, b.top, b.right, b.bottom]})


def keyboard_visible(adb: Adb) -> bool:
    out = adb.shell("dumpsys input_method | grep mInputShown", check=False)
    return "mInputShown=true" in out


def keyboard_bounds(adb: Adb) -> Bounds | None:
    """Where the on-screen keyboard is, or None when it's hidden.

    The app's hierarchy doesn't include the keyboard, so without this a tap on a key is attributed to
    the app element underneath, and an element under the keyboard looks tappable when it isn't.
    The position is cached; it's refreshed by every keyboard dump (e.g. while typing).
    """
    if not keyboard_visible(adb):
        return None
    cached = state.read_json(state.device_dir(adb.serial) / "keyboard.json")
    if not cached:
        dump_windows(adb)
        cached = state.read_json(state.device_dir(adb.serial) / "keyboard.json")
    return Bounds(*cached["bounds"]) if cached else None


def keyboard_key_at(adb: Adb, x: int, y: int) -> str:
    """Name of the keyboard key at a point, for logs ('Search', 'q', 'Delete')."""
    layer = keyboard.parse_layer(dump_windows(adb), _ime_package(adb))
    key = layer.key_at(x, y) if layer else None
    return key.name if key else "keyboard"


def screenshot(adb: Adb) -> bytes:
    png = adb.exec_out("screencap", "-p", timeout=20)
    if not png.startswith(_PNG_MAGIC):
        raise AdbError("screencap did not return a PNG (secure window or locked screen?)")
    return png


def foreground_activity(adb: Adb) -> tuple[str, str]:
    """Return (package, fully-qualified activity) of the resumed activity."""
    out = adb.shell("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity'", check=False)
    match = _ACTIVITY_RE.search(out)
    if not match:
        out = adb.shell("dumpsys window | grep mCurrentFocus", check=False)
        match = _ACTIVITY_RE.search(out)
    if not match:
        return "", ""
    package, activity = match.groups()
    if activity.startswith("."):
        activity = package + activity
    return package, activity


def density(adb: Adb) -> int:
    """Effective dpi; an override (Display size setting) wins over the physical value."""
    out = adb.shell("wm", "density")
    values = dict(re.findall(r"(Physical|Override) density: (\d+)", out))
    return int(values.get("Override") or values.get("Physical") or 160)


def display_size(adb: Adb) -> tuple[int, int]:
    """Natural (rotation 0) display size in pixels; an override wins over the physical value."""
    out = adb.shell("wm", "size")
    sizes = {kind: (int(w), int(h)) for kind, w, h in re.findall(r"(Physical|Override) size: (\d+)x(\d+)", out)}
    size = sizes.get("Override") or sizes.get("Physical")
    if not size:
        raise AdbError(f"cannot read display size: {out.strip()}")
    return size


NAV_MODES = {"0": "3-button", "1": "2-button", "2": "gesture"}


def _setting(adb: Adb, namespace: str, key: str) -> str:
    value = adb.shell("settings", "get", namespace, key, check=False).strip()
    return "" if value == "null" else value


def _display_info(adb: Adb, refresh: bool = False) -> dict:
    """Facts that only change with a settings change, cached per device (`adt info --refresh` re-reads)."""
    path = state.device_dir(adb.serial) / "device.json"
    cache = {} if refresh else (state.read_json(path) or {})
    if not {"density", "display", "nav_mode", "ime"} <= cache.keys():
        cache["density"] = density(adb)
        cache["display"] = list(display_size(adb))
        cache["nav_mode"] = NAV_MODES.get(_setting(adb, "secure", "navigation_mode"), "3-button")
        cache["ime"] = _setting(adb, "secure", "default_input_method")
        state.write_json(path, cache)
    return cache


def facts(adb: Adb, refresh: bool = False) -> dict:
    return _display_info(adb, refresh)


def snapshot(adb: Adb) -> tuple[Snapshot, str]:
    """Dump and parse the UI with the real display size. Returns the snapshot and the raw XML."""
    xml = dump_hierarchy(adb)
    return hierarchy.parse(xml, display=tuple(_display_info(adb)["display"])), xml


@dataclass
class Observation:
    snapshot: Snapshot
    package: str
    activity: str
    fingerprint: str
    density: int
    scale: float
    preview: Path | None
    screenshot: Path | None
    timestamp: str
    notes: list[str] = field(default_factory=list)  # one-line hints, e.g. low contrast on a new screen

    def to_dict(self) -> dict:
        s = self.snapshot
        return {
            "timestamp": self.timestamp,
            "package": self.package,
            "activity": self.activity,
            "fingerprint": self.fingerprint,
            "density": self.density,
            "screen": [s.screen.right, s.screen.bottom],
            "rotation": s.rotation,
            "preview_scale": self.scale,
            "preview": str(self.preview) if self.preview else None,
            "screenshot": str(self.screenshot) if self.screenshot else None,
            "elements": [e.to_dict() for e in s.elements],
        }


def observe(adb: Adb, save_dir: Path | None = None, name: str | None = None, with_image: bool = True,
            marks: bool = True) -> Observation:
    """Dump hierarchy + screenshot, write them to the device state dir (and save_dir if given)."""
    ddir = state.device_dir(adb.serial)
    snap, xml = snapshot(adb)
    package, activity = foreground_activity(adb)
    package = package or snap.package
    dpi = _display_info(adb)["density"]
    fp = screen_fingerprint(package, activity, snap.elements)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]

    (ddir / "latest.xml").write_text(xml, encoding="utf-8")
    preview = shot = None
    scale = 1.0
    if with_image:
        png = screenshot(adb)
        shot = ddir / "latest.png"
        shot.write_bytes(png)
        preview = ddir / "latest_preview.jpg"
        scale = annotate.make_preview(png, snap.elements, preview, marks=marks)

    obs = Observation(snap, package, activity, fp, dpi, scale, preview, shot, stamp)
    if save_dir is not None:
        obs = _save_copy(obs, xml, save_dir, name or stamp)
    state.write_json(ddir / "latest.json", obs.to_dict())
    # Screens visited: the session's screen list (`adt screens`) and `report diff` between runs.
    screen_title = screens.title(snap.elements, snap.screen.bottom)
    visits = screens.record(session.run_dir(adb.serial), fp, screen_title, screens.controls(snap.elements),
                            package)
    if visits == 1 and shot is not None:
        # A screen's first visit: flag unreadable text right away, with the screenshot already taken.
        note = contrast.first_visit_note(shot.read_bytes(), snap.elements, snap.screen.right, "adt")
        obs.notes = [note] if note else []
    session.log_action(adb.serial, {"action": "observe", "mode": "read", "fp": fp,
                                    "screen": f"{package}/{activity.removeprefix(package)}", "title": screen_title})
    return obs


def _save_copy(obs: Observation, xml: str, save_dir: Path, name: str) -> Observation:
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / f"{name}.xml").write_text(xml, encoding="utf-8")
    if obs.screenshot:
        target = save_dir / f"{name}.png"
        target.write_bytes(obs.screenshot.read_bytes())
        obs.screenshot = target
    if obs.preview:
        target = save_dir / f"{name}_preview.jpg"
        target.write_bytes(obs.preview.read_bytes())
        obs.preview = target
    return obs


def last_observation(serial: str) -> dict | None:
    return state.read_json(state.device_dir(serial) / "latest.json")


def last_snapshot(serial: str) -> tuple[Snapshot, dict]:
    data = last_observation(serial)
    if not data:
        raise LookupError("no observation yet: run `observe` first")
    w, h = data["screen"]
    elements = [hierarchy.Element.from_dict(e) for e in data["elements"]]
    snap = Snapshot(hierarchy.Bounds(0, 0, w, h), data["rotation"], data["package"], elements)
    return snap, data


# --- actions ---------------------------------------------------------------------------------

KEY_ALIASES = {
    "back": "KEYCODE_BACK", "home": "KEYCODE_HOME", "enter": "KEYCODE_ENTER", "tab": "KEYCODE_TAB",
    "delete": "KEYCODE_DEL", "backspace": "KEYCODE_DEL", "recents": "KEYCODE_APP_SWITCH",
    "menu": "KEYCODE_MENU", "search": "KEYCODE_SEARCH", "escape": "KEYCODE_ESCAPE",
    "power": "KEYCODE_POWER", "wakeup": "KEYCODE_WAKEUP", "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
}

# Characters the device shell would interpret. `input text` additionally reads `%s` as a space.
_SHELL_SPECIAL = set("\\'\"`$&|;<>()[]{}*?!~#^")


def escape_input_text(text: str) -> str:
    if not text.isascii() or any(not ch.isprintable() for ch in text):
        raise ValueError(
            "`input text` only supports printable ASCII. Use separate `key enter` for new lines; "
            "non-Latin text needs an IME such as ADBKeyboard."
        )
    out = []
    for ch in text:
        if ch == " ":
            out.append("%s")
        elif ch in _SHELL_SPECIAL:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def tap(adb: Adb, x: int, y: int) -> None:
    adb.shell("input", "tap", str(x), str(y))


def long_press(adb: Adb, x: int, y: int, ms: int = 800) -> None:
    adb.shell("input", "swipe", str(x), str(y), str(x), str(y), str(ms))


def swipe(adb: Adb, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
    adb.shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))


def scroll(adb: Adb, direction: str, area: hierarchy.Bounds, fraction: float = 0.6) -> None:
    """Scroll content in `direction` (as reading direction: 'down' reveals content below)."""
    cx, cy = area.center
    dx, dy = round(area.width * fraction / 2), round(area.height * fraction / 2)
    moves = {
        "down": (cx, cy + dy, cx, cy - dy),
        "up": (cx, cy - dy, cx, cy + dy),
        "right": (cx + dx, cy, cx - dx, cy),
        "left": (cx - dx, cy, cx + dx, cy),
    }
    swipe(adb, *moves[direction], ms=400)


def key(adb: Adb, name: str) -> None:
    code = KEY_ALIASES.get(name.lower(), name if name.upper().startswith("KEYCODE_") else f"KEYCODE_{name.upper()}")
    adb.shell("input", "keyevent", code.upper())


def type_text(adb: Adb, text: str) -> None:
    adb.shell("input", "text", escape_input_text(text))


# --- apps ------------------------------------------------------------------------------------

def app_launch(adb: Adb, package: str) -> None:
    out = adb.shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1", check=False)
    if "No activities found" in out or "Error" in out:
        raise AdbError(f"cannot launch {package}: {out.strip()}")


def app_stop(adb: Adb, package: str) -> None:
    adb.shell("am", "force-stop", package)


def app_clear(adb: Adb, package: str) -> None:
    out = adb.shell("pm", "clear", package)
    if "Success" not in out:
        raise AdbError(f"pm clear {package}: {out.strip()}")


RESET_LEVELS = ("restart", "clear-data")
# Runtime permission dialogs belong to the permission controller, not to the app that asked.
PERMISSION_UI = ("com.google.android.permissioncontroller", "com.android.permissioncontroller")


def reset_ready(foreground: str, package: str) -> bool:
    """Whether a relaunched app counts as up, given the package in the foreground.

    After clear-data the app is like a fresh install, so a system permission dialog may sit on top of it.
    """
    # The dialog only appears once the app runs and asks; answering it is part of the setup, not a failure.
    return foreground == package or foreground in PERMISSION_UI


def app_reset(adb: Adb, package: str, level: str, timeout: float = 20.0) -> tuple[list[str], str]:
    """Back to a known start: force-stop, clear the app's data (clear-data only), launch, wait until it's up.

    Returns the steps done and the foreground package at the end.
    """
    if level not in RESET_LEVELS:
        raise ValueError(f"level must be one of {RESET_LEVELS}")
    app_info(adb, package)  # fails early when the package isn't installed
    app_stop(adb, package)
    steps = ["force-stop"]
    if level == "clear-data":
        app_clear(adb, package)
        steps.append("clear data")
    app_launch(adb, package)
    steps.append("launch")
    deadline = time.monotonic() + timeout
    foreground = ""
    while time.monotonic() < deadline:
        foreground = foreground_activity(adb)[0]
        if reset_ready(foreground, package):
            return steps, foreground
        time.sleep(0.5)
    raise AdbError(f"{package} did not come to the foreground within {timeout:.0f}s "
                   f"(foreground: {foreground or 'unknown'})")


def app_install(adb: Adb, apk: Path, grant_all: bool = False) -> str:
    """Install without granting runtime permissions, so the app's own prompts appear like on a fresh install."""
    grant = ["-g"] if grant_all else []
    return adb.run("install", "-r", *grant, str(apk), timeout=300).decode(errors="replace").strip()


def app_list(adb: Adb, third_party: bool = True) -> list[str]:
    out = adb.shell("pm", "list", "packages", *(["-3"] if third_party else []))
    return sorted(line.removeprefix("package:").strip() for line in out.splitlines() if line.strip())


def app_info(adb: Adb, package: str) -> dict:
    fields = "versionName|versionCode|targetSdk|firstInstallTime"
    out = adb.shell(f"dumpsys package {shlex.quote(package)} | grep -E '{fields}'")
    info: dict[str, str] = {"package": package}
    for key_, value in re.findall(r"(versionName|versionCode|targetSdk|minSdk|firstInstallTime)=(\S+)", out):
        info.setdefault(key_, value)
    if len(info) == 1:
        raise AdbError(f"package {package} is not installed")
    return info


def device_props(adb: Adb) -> dict:
    props = {
        "platform": "Android",
        "serial": adb.serial,
        "model": adb.getprop("ro.product.model"),
        "manufacturer": adb.getprop("ro.product.manufacturer"),
        "android": adb.getprop("ro.build.version.release"),
        "sdk": adb.getprop("ro.build.version.sdk"),
        "emulator": adb.serial.startswith("emulator-") or adb.getprop("ro.kernel.qemu") == "1",
    }
    # The report's neutral keys (core/report_text.py device_facts); the raw ones stay for tools and old readers.
    props["os"] = f"Android {props['android']} (API {props['sdk']})"
    props["kind"] = "emulator" if props["emulator"] else "physical"
    size = adb.shell("wm", "size")
    sizes = dict(re.findall(r"(Physical|Override) size: (\d+x\d+)", size))
    props["screen"] = sizes.get("Override") or sizes.get("Physical", "")
    cached = facts(adb, refresh=True)
    props["density"] = cached["density"]
    props["navigation"] = cached["nav_mode"]
    props["keyboard"] = cached["ime"]
    props["locale"] = adb.getprop("persist.sys.locale") or adb.getprop("ro.product.locale")
    props["show_taps"] = _setting(adb, "system", "show_touches") == "1"
    props["accessibility_services"] = _setting(adb, "secure", "enabled_accessibility_services") or "none"
    return props
