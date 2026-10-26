"""Command line interface. Output is plain text meant to be read by an agent; --json where scripts need it.

UI actions go through human.Driver: human-like by default, instant with the global --fast flag
(setup and reset steps only).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from ..core import clip, commands, project, restore, screen, session, state, ui
from ..core.commands import (
    EXIT_BLOCKED,
    EXIT_DECISION,
    EXIT_DEVICE,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    Blocked,
    NeedsDecision,
    NotFound,
)
from . import apkinfo, applog, apps, appstate, capture, device, entry_script, env, extras, hierarchy, keyboard, perf
from .adb import Adb, AdbError, DeviceError, find_adb, list_devices, run_adb
from .human import Driver, Outcome

# --- helpers ---------------------------------------------------------------------------------

def _print_observation(obs: device.Observation, as_json: bool, bounds: bool = False,
                       previous: list[ui.Element] | None = None) -> None:
    if as_json:
        print(json.dumps(obs.to_dict(), ensure_ascii=False))
        return
    s = obs.snapshot
    activity = obs.activity.removeprefix(obs.package) if obs.activity.startswith(obs.package) else obs.activity
    print(f"screen: {obs.package}/{activity}  fp={obs.fingerprint}  "
          f"{s.screen.right}x{s.screen.bottom} @{obs.density}dpi rot={s.rotation}")
    if obs.preview:
        print(f"preview: {obs.preview}  (scale {obs.scale:.3f}, numbers = element index)")
        print(f"screenshot: {obs.screenshot}")
    risky = [e for e in s.elements if e.risk]
    if risky:
        print(f"WARNING: {len(risky)} risky element(s) on screen: "
              + ", ".join(f"[{e.index}] {e.risk}" for e in risky))
    print("\n".join(ui.listing(s.elements, previous, bounds, depth_step=4)))


def _driver(adb: Adb, args) -> Driver:
    return Driver(adb, pace=args.pace, fast=args.fast, verify=not args.no_verify)


def _report_outcome(outcome: Outcome) -> None:
    if warning := outcome.warning():
        print(warning)


def _after(adb: Adb, args, outcome: Outcome | None = None) -> None:
    if outcome is not None:
        _report_outcome(outcome)
    if args.fast or outcome is None or outcome.changed is None:
        time.sleep(getattr(args, "settle", 0.5))
    if commands.observe_after(args, outcome.changed if outcome else None, session.mode(adb.serial)):
        before = device.last_observation(adb.serial)
        obs = device.observe(adb, save_dir=_session_shots(adb))
        _print_observation(obs, as_json=False, previous=commands.previous_elements(before, obs.fingerprint))


def _session_shots(adb: Adb) -> Path | None:
    directory = session.run_dir(adb.serial)
    return directory / "screenshots" if directory else None


def _fresh_snapshot(adb: Adb) -> hierarchy.Snapshot:
    return device.snapshot(adb)[0]


def _keyboard_area(adb: Adb) -> tuple[hierarchy.Bounds, ...]:
    bounds = device.keyboard_bounds(adb)
    return (bounds,) if bounds else ()


def _tap_point(snap: hierarchy.Snapshot, el: hierarchy.Element, args,
               blocked: tuple[hierarchy.Bounds, ...] = ()) -> tuple[int, int]:
    if hierarchy.visible_point(snap, el, blocked) is None:
        raise NotFound(f"{el.describe()} is covered by other controls (e.g. a toolbar, tab bar or the keyboard). "
                       "Scroll it into view, close the keyboard, or tap the control that covers it.")
    if args.fast:
        return hierarchy.visible_point(snap, el, blocked)
    return hierarchy.human_point(snap, el, random.Random(), blocked)


def _unique(matches: list[hierarchy.Element], what: str) -> hierarchy.Element:
    if not matches:
        raise NotFound(f"no element matches {what}")
    if len(matches) > 1:
        listing = "\n".join("  " + m.describe() for m in matches[:10])
        raise NotFound(f"{len(matches)} elements match {what}, use --index:\n{listing}")
    return matches[0]


def _matches(snap: hierarchy.Snapshot, args) -> list[hierarchy.Element]:
    return hierarchy.find_by_text(snap, args.text) if args.text is not None else hierarchy.find_by_id(snap, args.id)


def _search(adb: Adb, args, driver: Driver) -> tuple[hierarchy.Snapshot, hierarchy.Element]:
    """Fresh lookup by text/id; with --scroll, scroll the main list down until found or it stops moving."""
    what = f"text '{args.text}'" if args.text is not None else f"id '{args.id}'"
    snap = _fresh_snapshot(adb)
    for _ in range(args.scroll):
        if _matches(snap, args):
            break
        scrollables = [e for e in snap.elements if e.scrollable]
        if not scrollables:
            break
        driver.scroll("down", max(scrollables, key=lambda e: e.bounds.area).bounds)
        before, snap = snap, _fresh_snapshot(adb)
        if [e.label for e in snap.elements] == [e.label for e in before.elements]:
            break  # reached the end of the list
    return snap, _unique(_matches(snap, args), what)


def _resolve_target(adb: Adb, args, driver: Driver) -> tuple[int, int, hierarchy.Element | None, str]:
    """(x, y, app element or None, label for the output and the action log)."""
    keyboard_area = _keyboard_area(adb)
    if args.index is not None:
        snap, _ = device.last_snapshot(adb.serial)
        el = snap.find(args.index)
        return (*_tap_point(snap, el, args, keyboard_area), el, el.describe())
    if args.text is not None or args.id is not None:
        snap, el = _search(adb, args, driver)
        return (*_tap_point(snap, el, args, keyboard_area), el, el.describe())
    if args.xy:
        x, y = args.xy
    else:
        _, data = device.last_snapshot(adb.serial)
        scale = data.get("preview_scale") or 1.0
        x, y = round(args.preview_xy[0] / scale), round(args.preview_xy[1] / scale)
    if any(area.contains(x, y) for area in keyboard_area):
        # The app's hierarchy doesn't know the keyboard: whatever it has under this point is hidden.
        return x, y, None, f"keyboard key '{device.keyboard_key_at(adb, x, y)}'"
    try:
        snap, _ = device.last_snapshot(adb.serial)
        el = hierarchy.element_at(snap, x, y)
        return x, y, el, el.describe() if el else ""
    except LookupError:
        return x, y, None, ""


def _approval_log(adb: Adb, entry: dict) -> None:
    log = state.device_dir(adb.serial) / "guard_log.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), **entry}) + "\n")


def _guard(adb: Adb, el: hierarchy.Element | None, allow_reason: str | None, action: str) -> None:
    if el is None or not el.risk:
        return
    if not allow_reason:
        raise Blocked(
            f"BLOCKED: {action} on {el.describe()} looks like a {el.risk} action. "
            "Stop and ask the user. If they approve, rerun with --allow-risk \"<their approval>\"."
        )
    _approval_log(adb, {"action": action, "element": el.describe(), "risk": el.risk, "approval": allow_reason})


# --- commands --------------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    ok = True
    try:
        adb_path = find_adb()
        version = run_adb(adb_path, "version").splitlines()
        print(f"adb: {adb_path} ({version[1] if len(version) > 1 else version[0]})")
    except AdbError as exc:
        print(f"adb: MISSING - {exc}")
        return EXIT_DEVICE
    on_path = shutil.which("adb")
    if on_path and Path(on_path).resolve() != adb_path.resolve():
        print(f"note: another adb is first on PATH ({on_path}). Mixed adb versions restart each other's "
              "server; prefer the SDK one on PATH.")
    for tool in ("scrcpy", "ffmpeg", "emulator", "uv"):
        print(f"{tool}: {shutil.which(tool) or 'not on PATH'}")
    devices = list_devices(adb_path)
    if not devices:
        print("devices: none connected")
        ok = False
    for d in devices:
        print(f"device: {d.serial} {d.state} {d.model}")
        ok &= d.state == "device"
    return EXIT_OK if ok else EXIT_DEVICE


def cmd_devices(args) -> int:
    devices = list_devices(find_adb())
    if args.json:
        print(json.dumps([d.__dict__ for d in devices]))
    for d in devices if not args.json else []:
        kind = "emulator" if d.is_emulator else "physical"
        print(f"{d.serial}\t{d.state}\t{kind}\t{d.model}")
    return EXIT_OK if devices else EXIT_DEVICE


def cmd_info(args, adb: Adb) -> int:
    props = device.device_props(adb)
    print(json.dumps(props) if args.json else "\n".join(f"{k}: {v}" for k, v in props.items()))
    return EXIT_OK


def cmd_observe(args, adb: Adb) -> int:
    save_dir = Path(args.save_dir) if args.save_dir else (_session_shots(adb) if args.name else None)
    if args.image_only:
        target = (save_dir or state.device_dir(adb.serial)) / f"{args.name or 'latest'}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(device.screenshot(adb))
        print(f"screenshot: {target}  (no hierarchy dump: accessibility layer untouched)")
        return EXIT_OK
    before = None if args.full else device.last_observation(adb.serial)
    obs = device.observe(adb, save_dir=save_dir, name=args.name, with_image=not args.no_image,
                         marks=not args.no_marks)
    _print_observation(obs, args.json, args.bounds, commands.previous_elements(before, obs.fingerprint))
    return EXIT_OK


def cmd_inspect(args, adb: Adb) -> int:
    snap, _ = device.last_snapshot(adb.serial)
    el = commands.inspect_target(snap, args)
    xml = (state.device_dir(adb.serial) / "latest.xml").read_text(encoding="utf-8")
    print("\n".join(ui.inspect_lines(el, *hierarchy.raw_node(xml, el))))
    return EXIT_OK


def cmd_tap(args, adb: Adb) -> int:
    driver = _driver(adb, args)
    x, y, el, label = _resolve_target(adb, args, driver)
    action = "long-press" if args.long else "tap"
    _guard(adb, el, args.allow_risk, action)
    if el is not None and not el.enabled:
        print(f"note: target is disabled: {el.describe()}")
    outcome = driver.tap(x, y, target=label, long=args.long)
    print(f"{action} ({x},{y})" + (f" -> {label}" if label else ""))
    _after(adb, args, outcome)
    return EXIT_OK


def _check_typed(adb: Adb, expected: str) -> None:
    """Keyboards autocorrect and auto-capitalise, like for a real user. Report it, don't hide it."""
    focused = [e for e in _fresh_snapshot(adb).elements if e.editable and e.focused]
    if len(focused) != 1 or focused[0].password:
        return
    shown = focused[0].text
    if shown and shown != expected and shown != focused[0].hint:
        print(f"note: the field now shows {len(shown)} chars that differ from what was typed "
              "(autocorrect or auto-capitalisation?). Observe to check.")


def _wait_for_keyboard(adb: Adb, timeout: float = 3.0) -> None:
    """A busy app shows the keyboard a moment after the field is tapped; a person waits for it too."""
    deadline = time.monotonic() + timeout
    while not device.keyboard_visible(adb) and time.monotonic() < deadline:
        time.sleep(0.25)


def cmd_type(args, adb: Adb) -> int:
    driver = _driver(adb, args)
    if args.index is not None:
        snap, _ = device.last_snapshot(adb.serial)
        el = snap.find(args.index)
        driver.tap(*_tap_point(snap, el, args, _keyboard_area(adb)), target=el.describe())
        _wait_for_keyboard(adb)
    try:
        outcome = driver.type_text(args.text, fallback=args.fallback, submit=args.submit)
    except keyboard.CannotType as exc:
        raise NeedsDecision(f"{exc}. Ask the user how to continue, or rerun with --fallback keyevents "
                            "(one key event per character) or --fallback bulk.") from exc
    except keyboard.NoKeyboard as exc:
        raise NeedsDecision(f"{exc}, or rerun with --fallback keyevents.") from exc
    # Never echo the text: it may be a credential from the secrets file.
    print(f"typed {len(args.text)} chars" + (" + submit" if args.submit else ""))
    if not args.no_verify and not args.submit:
        _check_typed(adb, args.text)
    _after(adb, args, outcome)
    return EXIT_OK


def cmd_key(args, adb: Adb) -> int:
    driver = _driver(adb, args)
    outcome = None
    for _ in range(args.repeat):
        outcome = driver.key(args.name)
    print(f"key {args.name} x{args.repeat}")
    _after(adb, args, outcome)
    return EXIT_OK


def cmd_swipe(args, adb: Adb) -> int:
    outcome = _driver(adb, args).swipe(*args.coords, ms=args.ms)
    print(f"swipe {args.coords}")
    _after(adb, args, outcome)
    return EXIT_OK


def cmd_scroll(args, adb: Adb) -> int:
    snap, _ = device.last_snapshot(adb.serial)
    if args.index is not None:
        area = snap.find(args.index).bounds
    else:
        scrollables = [e for e in snap.elements if e.scrollable]
        area = max(scrollables, key=lambda e: e.bounds.area).bounds if scrollables else snap.screen
    outcome = _driver(adb, args).scroll(args.direction, area)
    print(f"scroll {args.direction} in {area}")
    _after(adb, args, outcome)
    return EXIT_OK


def cmd_wait(args, adb: Adb) -> int:
    deadline = time.monotonic() + args.timeout
    what = f"text '{args.text}'" if args.text else f"id '{args.id}'"
    while True:
        try:
            snap = _fresh_snapshot(adb)
        except AdbError:
            snap = None
        if snap is not None:
            found = hierarchy.find_by_text(snap, args.text) if args.text else hierarchy.find_by_id(snap, args.id)
            if bool(found) != args.gone:
                print(f"{'gone' if args.gone else 'found'}: {what}")
                return EXIT_OK
        if time.monotonic() > deadline:
            print(f"timeout after {args.timeout}s waiting for {what} to {'disappear' if args.gone else 'appear'}")
            return EXIT_NOT_FOUND
        time.sleep(0.5)


def cmd_app(args, adb: Adb) -> int:
    match args.app_cmd:
        case "launch":
            device.app_launch(adb, args.package)
            session.log_action(adb.serial, {"action": "app-launch", "mode": "intent", "package": args.package})
            print(f"launched {args.package} (launcher intent)")
            _after(adb, args)
        case "stop":
            device.app_stop(adb, args.package)
            session.log_action(adb.serial, {"action": "app-stop", "mode": "setup", "package": args.package})
            print(f"stopped {args.package}")
        case "clear":
            device.app_clear(adb, args.package)
            session.log_action(adb.serial, {"action": "app-clear", "mode": "setup", "package": args.package})
            print(f"cleared data of {args.package}")
        case "reset":
            return _app_reset(args, adb)
        case "install":
            path = Path(args.apk)
            if path.suffix.lower() in (".xapk", ".apks"):
                with tempfile.TemporaryDirectory() as tmp:
                    parts = apkinfo.extract_bundle(path, Path(tmp))
                    grant = ["-g"] if args.grant_all else []
                    out = adb.run("install-multiple", "-r", *grant, *map(str, parts), timeout=600)
                    print(out.decode(errors="replace").strip() + f" ({len(parts)} split APKs)")
            else:
                print(device.app_install(adb, path, grant_all=args.grant_all))
            session.log_action(adb.serial, {"action": "app-install", "mode": "setup", "file": path.name})
        case "list":
            print("\n".join(p for p in device.app_list(adb, not args.all) if args.filter in p))
        case "info":
            print(json.dumps(device.app_info(adb, args.package), indent=1))
        case "current":
            package, activity = device.foreground_activity(adb)
            print(f"{package} {activity}")
        case "find":
            return _app_find(args, adb)
        case "links":
            links = apkinfo.deep_links(apps.manifest(adb, args.package))
            print("\n".join(links) if links else f"{args.package} declares no deep links")
        case "kill-background":
            return _app_kill_background(args, adb)
    return EXIT_OK


def _app_reset(args, adb: Adb) -> int:
    started = datetime.now().astimezone()
    steps, foreground = device.app_reset(adb, args.package, args.level, timeout=args.timeout)
    _, settled = screen.wait_stable(lambda: adb.exec_out("screencap", "-p", timeout=20), timeout=8)
    session.log_action(adb.serial, {"action": "app-reset", "mode": "setup", "package": args.package,
                                    "level": args.level, "steps": steps}, started)
    session.note_fast_step(adb.serial, f"reset ({args.level})")
    print(f"reset {args.package} ({args.level}): {', '.join(steps)}")
    if foreground != args.package:
        print(f"note: a system permission dialog is on top ({foreground}); answering it is part of the setup")
    if not settled:
        print("note: the screen is still changing (splash, animation or video); observe before acting")
    return EXIT_OK


def _app_kill_background(args, adb: Adb) -> int:
    """Android kills background apps to free memory; coming back must restore the screen, not crash or reset."""
    before = device.last_observation(adb.serial)
    driver = _driver(adb, args)
    driver.home()
    time.sleep(args.wait)  # the app has stopped and saved its state by now
    killed_pids, alive = appstate.kill_in_background(adb, args.package)
    session.log_action(adb.serial, {"action": "app-kill-background", "mode": "setup", "package": args.package,
                                    "pids": killed_pids, "killed": not alive})
    if alive:
        print(f"not killed: {args.package} is still running (pid {alive}). Android keeps it alive, e.g. for a "
              "foreground service, so this can't test a low-memory kill. The app is in the background.")
        return EXIT_DECISION
    print(f"killed {args.package} in the background (pid {', '.join(map(str, killed_pids))}); returning to it")
    device.app_launch(adb, args.package)  # the launcher resumes the task; Android rebuilds its screen from saved state
    screen.wait_stable(lambda: adb.exec_out("screencap", "-p", timeout=20), timeout=8)
    if crash_lines := capture.new_crashes(adb):
        print(f"CRASH after returning: {capture.crash_summary(crash_lines)}. Capture evidence now.")
    obs = device.observe(adb, save_dir=_session_shots(adb))
    if before and before.get("fingerprint") not in (None, "-"):
        same = before["fingerprint"] == obs.fingerprint
        print("back on the same screen as before the kill" if same else
              "a different screen than before the kill: check whether the app should have restored it")
    _print_observation(obs, as_json=False, previous=commands.previous_elements(before, obs.fingerprint))
    return EXIT_OK


def cmd_open(args, adb: Adb) -> int:
    """Open a link the way a notification, a browser or another app does, and show where it landed."""
    if args.cold:
        if not args.package:
            print("error: --cold needs --package, the app to stop first")
            return EXIT_USAGE
        device.app_stop(adb, args.package)
    before = device.last_observation(adb.serial)
    command = ["am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", shlex.quote(args.uri)]
    if args.package:
        command += ["-p", args.package]
    out = adb.shell(*command, timeout=60, check=False)
    session.log_action(adb.serial, {"action": "open-link", "mode": "intent", "uri": args.uri,
                                    "package": args.package, "cold": args.cold})
    if "Error" in out or "unable to resolve" in out.casefold():
        print(f"no app opened {args.uri}: {out.strip().splitlines()[-1] if out.strip() else 'no answer'}")
        return EXIT_NOT_FOUND
    facts = dict(re.findall(r"^(Status|LaunchState|Activity|TotalTime): (.+)$", out, re.M))
    print(f"opened {args.uri}: " + ", ".join(f"{k} {v.strip()}" for k, v in facts.items()))
    screen.wait_stable(lambda: adb.exec_out("screencap", "-p", timeout=20), timeout=8)
    if crash_lines := capture.new_crashes(adb):
        print(f"CRASH after opening the link: {capture.crash_summary(crash_lines)}. Capture evidence now.")
    obs = device.observe(adb, save_dir=_session_shots(adb))
    _print_observation(obs, as_json=False, previous=commands.previous_elements(before, obs.fingerprint))
    print("next: press back and check where it goes (an empty back stack should leave the app, not show a blank "
          "or wrong screen)")
    return EXIT_OK


def cmd_permissions(args, adb: Adb) -> int:
    match args.perm_cmd:
        case "list":
            state = appstate.runtime_permissions(adb, args.package)
            if not state:
                print(f"{args.package} asks for no runtime permissions")
            for name, granted in sorted(state.items()):
                print(f"{'granted' if granted else 'denied ':8} {name}")
            return EXIT_OK
        case "reset":
            names = appstate.reset(adb, args.package)
            print(f"reset {len(names)} runtime permission(s) of {args.package}: the app asks again")
        case _:
            names = appstate.expand(args.permissions)
            (appstate.grant if args.perm_cmd == "grant" else appstate.revoke)(adb, args.package, names)
            print(f"{args.perm_cmd}: {', '.join(names)}"
                  + ("; Android killed the app's process if it was running" if args.perm_cmd == "revoke" else ""))
    session.log_action(adb.serial, {"action": f"permissions-{args.perm_cmd}", "mode": "setup",
                                    "package": args.package, "permissions": getattr(args, "permissions", None)})
    return EXIT_OK


def _app_find(args, adb: Adb) -> int:
    locale = adb.getprop("persist.sys.locale") or adb.getprop("ro.product.locale")
    matches = apps.find(adb, args.query, locale=locale)[:args.limit]
    if matches and matches[0].score == 100 and (len(matches) == 1 or matches[1].score < 100):
        matches = matches[:1]  # an exact name or package: the near misses are noise
    for m in matches:
        try:
            m.version = device.app_info(adb, m.package).get("versionName", "")
        except AdbError:
            m.version = ""
    if args.json:
        print(json.dumps([m.__dict__ for m in matches], ensure_ascii=False))
    elif not matches:
        print(f"no installed app matches '{args.query}'")
    else:
        sure = len(matches) == 1 and matches[0].score >= 85
        print("match:" if sure else f"{len(matches)} candidate(s), best first; ask the user to pick one:")
        for i, m in enumerate(matches, 1):
            print(f"{i}. {m.describe()}")
    return EXIT_OK if matches else EXIT_NOT_FOUND


def cmd_logcat(args, adb: Adb) -> int:
    match args.log_cmd:
        case "start":
            pid = capture.logcat_start(adb, Path(args.out), clear=not args.keep)
            print(f"logcat -> {Path(args.out).resolve()} (pid {pid})")
        case "stop":
            path = capture.logcat_stop(adb)
            print(f"logcat stopped: {path}" if path else "logcat was not running")
        case "crashes":
            text = capture.crashes(adb, args.package)
            print(text or "no crashes or ANRs")
        case "summary":
            return _logcat_summary(args, adb)
    return EXIT_OK


def _logcat_summary(args, adb: Adb) -> int:
    run = Path(args.run) if args.run else session.latest_run_dir(adb.serial)
    package = args.package or (json.loads((run / "session.json").read_text(encoding="utf-8")).get("package")
                                if run else None)
    if run is None or package is None:
        raise ValueError("no session found: pass --run RUN and --package PKG")
    groups = applog.session_summary(adb.serial, run, package)
    path = run / "session.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["log_summary"] = groups
    state.write_json(path, data)
    if not groups:
        print("no app errors or warnings in the session log")
    for g in groups:
        print(f"{g['count']:>4}x {g['kind']}, {g['tag']}: {g['text'][:150]} (first {g['first']})")
    print(f"saved to {path} (log_summary)")
    return EXIT_OK


def cmd_record(args, adb: Adb) -> int:
    match args.rec_cmd:
        case "start":
            pid = capture.record_start(adb, Path(args.out))
            print(f"recording -> {Path(args.out).resolve()} (worker pid {pid})")
        case "stop":
            path = capture.record_stop(adb, discard=args.discard)
            print("recording discarded" if args.discard else f"recording saved: {path}" if path
                  else "no recording was running")
    return EXIT_OK


def cmd_record_worker(args, adb: Adb) -> int:
    capture.record_worker(adb, Path(args.stop_flag))
    return EXIT_OK


def cmd_clip(args, adb: Adb) -> int:
    if args.video:
        video = Path(args.video)
    else:
        run = session.latest_run_dir(adb.serial)
        if run is None:
            raise NotFound("no session recording known for this device; pass --video PATH")
        video = run / "videos" / "session.mp4"
    start, end = clip.cut_clip(video, commands.parse_time(args.start), commands.parse_time(args.end), Path(args.out),
                               args.pad)
    print(f"clip {Path(args.out).resolve()} = {video.name} {start:.1f}-{end:.1f}s")
    return EXIT_OK


def cmd_session(args, adb: Adb) -> int:
    match args.session_cmd:
        case "start":
            props = device.device_props(adb)
            meta = {
                "mode": args.mode, "charter": args.charter, "ticket": args.ticket, "package": args.package,
                "platform": "Android", "device": props,
                "input": "adt human mode" + (f" (pace {args.pace})" if args.pace != "human" else ""),
            }
            if args.package:
                try:
                    meta["app"] = device.app_info(adb, args.package)
                except AdbError:
                    meta["app"] = {"package": args.package, "installed": False}
            # Folder, title and tester come from the project config, whichever skill (or person) started it.
            directory = Path(args.dir) if args.dir else project.default_run_dir(args.package, args.mode, args.ticket)
            defaults = {"title": project.default_title(args.package, args.mode, platform="Android"),
                        "tester": project.tester()}
            directory = session.start(adb.serial, directory, meta, defaults)
            started = []
            if args.logcat:
                capture.logcat_start(adb, directory / "logs" / "logcat.txt")
                started.append("logcat")
            if args.record:
                capture.record_start(adb, directory / "videos" / "session.mp4")
                started.append("recording")
            active = session.active(adb.serial)
            active["started_capture"] = started
            state.write_json(state.device_dir(adb.serial) / "session.json", active)
            print(f"session -> {directory}" + (f" ({', '.join(started)} running)" if started else ""))
        case "end":
            active = session.active(adb.serial)
            if not active:
                print("no active session")
                return EXIT_OK
            started = active.get("started_capture", [])
            if "recording" in started:
                print(f"recording: {capture.record_stop(adb, discard=args.discard_video)}")
            if "logcat" in started:
                print(f"logcat: {capture.logcat_stop(adb)}")
            run = session.end(adb.serial)
            print(f"session ended: {run}")
            if restored := env.restore_all(adb):
                print("restored device settings: " + ", ".join(restored))
            if run and not args.no_report:
                commands.report_after_session(run, "adt")
        case "status":
            active = session.active(adb.serial)
            print(json.dumps(active, indent=1) if active else "no active session")
    return EXIT_OK


def _physical(adb: Adb) -> bool:
    return not (adb.serial.startswith("emulator-") or adb.getprop("ro.kernel.qemu") == "1")


def _system_change_allowed(adb: Adb, what: str, approval: str | None) -> None:
    if _physical(adb) and not approval:
        raise Blocked(f"BLOCKED: {what} changes a system setting on a physical device. Ask the user; if they "
                      "approve, rerun with --approval \"<their approval>\". `session end` puts it back.")
    if approval:
        _approval_log(adb, {"action": what, "approval": approval})


def cmd_env(args, adb: Adb) -> int:
    if args.reset:
        restored = env.restore_all(adb, [k for k in restore.pending(adb.serial) if k != "connectivity/airplane"])
        print("restored: " + (", ".join(restored) or "nothing was changed"))
        return EXIT_OK
    wanted = {name: value for name, value in (("dark", args.dark), ("font_scale", args.font_scale),
                                               ("orientation", args.orientation), ("rtl", args.rtl)) if value}
    if not wanted:
        print("nothing to change: pass --dark, --font-scale, --orientation or --rtl (or --reset)")
        return EXIT_USAGE
    _system_change_allowed(adb, "env " + " ".join(f"{k}={v}" for k, v in wanted.items()), args.approval)
    for name, value in wanted.items():
        env.change(adb, name, value)
    session.log_action(adb.serial, {"action": "env", "mode": "setup", **wanted})
    print("changed: " + ", ".join(f"{k} {v}" for k, v in wanted.items())
          + ". Restart the app to see it everywhere; `env --reset` or `session end` puts it back."
          + (" RTL also needs the app restarted." if "rtl" in wanted else ""))
    return EXIT_OK


def cmd_net(args, adb: Adb) -> int:
    if args.state == "online":
        restored = env.restore_all(adb, ["connectivity/airplane"])
        print("back online" if restored else "the network wasn't changed by adt")
        return EXIT_OK
    if env.over_wifi(adb.serial):
        raise Blocked("BLOCKED: adb is connected over Wi-Fi; going offline would cut the connection to the device. "
                      "Connect it by USB first.")
    _system_change_allowed(adb, "net offline (airplane mode)", args.approval)
    env.change(adb, "network", "offline")
    session.log_action(adb.serial, {"action": "net-offline", "mode": "setup"})
    print("offline (airplane mode on). `net online` or `session end` turns it back.")
    return EXIT_OK


def cmd_notifications(args, adb: Adb) -> int:
    found = extras.notifications(adb, args.package)
    if not found:
        print("no active notifications" + (f" from {args.package}" if args.package else ""))
    for n in found:
        actions = f"  [{' | '.join(n['actions'])}]" if n["actions"] else ""
        print(f"{n['package']}: {n['title']!r} {n['text']!r}{actions}")
    return EXIT_OK


def cmd_media(args, adb: Adb) -> int:
    remote = extras.push_media(adb, Path(args.file))
    session.log_action(adb.serial, {"action": "media-push", "mode": "setup", "file": Path(args.file).name})
    print(f"pushed to {remote}; it shows in the gallery and photo pickers")
    return EXIT_OK


def cmd_location(args, adb: Adb) -> int:
    extras.set_location(adb, args.latitude, args.longitude)
    session.log_action(adb.serial, {"action": "location", "mode": "setup", "lat": args.latitude,
                                    "lon": args.longitude})
    print(f"GPS position set to {args.latitude}, {args.longitude}")
    return EXIT_OK


def cmd_bio(args, adb: Adb) -> int:
    extras.fingerprint(adb, args.result == "match")
    session.log_action(adb.serial, {"action": f"bio-{args.result}", "mode": "setup"})
    print(f"fingerprint: {'enrolled finger' if args.result == 'match' else 'unknown finger'} touched the sensor")
    return EXIT_OK


def cmd_touches(args, adb: Adb) -> int:
    """'Show taps' (Developer options) draws touch markers into recordings. It's a system setting."""
    physical = not (adb.serial.startswith("emulator-") or adb.getprop("ro.kernel.qemu") == "1")
    if args.state == "on" and physical and not args.approval:
        raise Blocked("BLOCKED: 'Show taps' changes a system setting on a physical device. Ask the user; "
                      "if they approve, rerun with --approval \"<their approval>\" and turn it off afterwards.")
    if args.approval:
        _approval_log(adb, {"action": f"show_touches {args.state}", "approval": args.approval})
    adb.shell("settings", "put", "system", "show_touches", "1" if args.state == "on" else "0")
    print(f"show taps: {args.state}")
    return EXIT_OK


def cmd_script(args, adb: Adb) -> int:
    """Run an app-profile script: .mobile-tester/apps/<package>/<hooks|checks>/<name>.(py|sh|ps1)."""
    kind = "hooks" if args.cmd == "hook" else "checks"
    app_dir = Path(args.config_dir).resolve() / "apps" / args.package
    candidates = [app_dir / kind / f"{args.name}{ext}" for ext in (".py", ".sh", ".ps1")]
    script = next((c for c in candidates if c.is_file()), None)
    if script is None:
        raise NotFound(f"no {kind[:-1]} '{args.name}' in {app_dir / kind}")
    adt_entry = entry_script()
    env = {
        **os.environ, "ANDROID_SERIAL": adb.serial, "ADB": str(adb.path), "MT_PLATFORM": "Android",
        "MT_PACKAGE": args.package, "MT_APP_DIR": str(app_dir), "MT_RUN_DIR": str(session.run_dir(adb.serial) or ""),
        # Shell scripts use $ADT; Python hooks call [MT_PYTHON, MT_SCRIPT, ...] (adt here, idt on iOS).
        "ADT": f'"{sys.executable}" "{adt_entry}"', "MT_PYTHON": sys.executable, "MT_SCRIPT": str(adt_entry),
    }
    secrets = app_dir / "secrets.local.yaml"
    if secrets.is_file():
        env["MT_SECRETS"] = str(secrets)
    if script.suffix == ".py":
        uv = shutil.which("uv")
        cmd = [uv, "run", "-q", "--script", str(script)] if uv else [sys.executable, str(script)]
    elif script.suffix == ".sh":
        cmd = ["bash", str(script)]
    else:
        cmd = ["pwsh", "-NoProfile", "-File", str(script)]
    session.log_action(adb.serial, {"action": f"{kind[:-1]}-{args.name}", "mode": "setup", "script": script.name})
    return subprocess.run([*cmd, *args.script_args], env=env).returncode


def cmd_perf(args, adb: Adb) -> int:
    match args.perf_cmd:
        case "startup":
            result = perf.startup(adb, args.package, runs=args.runs)
            print(f"cold start: {result['cold_start_ms']} ms (median of {result['samples_ms']})")
        case "frames":
            result = perf.frames(adb, args.package, reset=args.reset)
            if args.reset:
                print("frame stats reset")
            else:
                print(json.dumps(result))
        case "leak":
            return _perf_leak(args, adb)
        case _:
            if args.flow:
                time.sleep(args.settle)  # let the app go idle (and garbage-collect) after the cycle
            result = perf.memory(adb, args.package)
            print(json.dumps(result))
            if args.flow:
                session.log_action(adb.serial, {"action": "perf-memory", "mode": "measure", "flow": args.flow,
                                                **result})
                path = perf.append(adb.serial, "leak_samples", {"flow": args.flow, **result})
                print(f"sample for '{args.flow}' saved to {path}" if path else "no active session: not saved")
                return EXIT_OK
    session.log_action(adb.serial, {"action": f"perf-{args.perf_cmd}", "mode": "measure", **result})
    if not result.get("reset") and (path := perf.record(adb.serial, args.perf_cmd, result)):
        print(f"saved to {path}")
    return EXIT_OK


def _perf_leak(args, adb: Adb) -> int:
    run = session.run_dir(adb.serial)
    if run is None:
        raise ValueError("no active session: leak samples live in its session.json")
    path = run / "session.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = data.get("performance", {}).get("leak_samples", [])
    flows = [args.flow] if args.flow else list(dict.fromkeys(s["flow"] for s in samples))
    if not flows:
        print("no leak samples yet: run `adt perf memory PKG --flow NAME` before and after each cycle")
        return EXIT_OK
    leaks = data.setdefault("performance", {}).setdefault("leaks", {})
    for flow in flows:
        verdict = perf.leak_verdict([s for s in samples if s["flow"] == flow])
        leaks[flow] = verdict
        detail = "; ".join(f"{k} {' > '.join(map(str, v))}" for k, v in verdict["growing"].items())
        print(f"{flow}: {verdict['verdict']} after {verdict['cycles']} cycle(s)" + (f" ({detail})" if detail else ""))
    state.write_json(path, data)
    print(f"saved to {path} (performance.leaks)")
    return EXIT_OK


def cmd_apk(args) -> int:
    result = apkinfo.inspect(Path(args.file))
    print(json.dumps(result, indent=1) if args.json else apkinfo.to_text(result))
    return EXIT_OK if result["same_signer_for_all"] else EXIT_BLOCKED


# --- parser ----------------------------------------------------------------------------------

def _add_settle(p: argparse.ArgumentParser, observe: bool = True) -> None:
    p.add_argument("--settle", type=float, default=0.5,
                   help="seconds to wait after the action when the screen isn't checked (fast mode)")
    if observe:
        p.add_argument("--observe", action="store_true",
                       help="always list the screen after the action (default: only when it changed)")
        p.add_argument("--no-observe", action="store_true", help="don't list the screen after the action")


def _global_flags(parser: argparse.ArgumentParser, suppress: bool) -> None:
    # On subcommands the defaults are suppressed, so `adt tap --fast` and `adt --fast tap` both work
    # without the subcommand resetting a flag given before it.
    def default(value):
        return argparse.SUPPRESS if suppress else value

    parser.add_argument("-s", "--serial", default=default(None),
                        help="device serial (default: ANDROID_SERIAL or the only device)")
    parser.add_argument("--fast", action="store_true", default=default(False),
                        help="instant adb input, no pacing: ONLY for setup/reset steps, never for the test itself")
    parser.add_argument("--pace", choices=["human", "slow"], default=default(os.environ.get("MT_PACE", "human")))
    parser.add_argument("--no-verify", action="store_true", default=default(False),
                        help="skip the did-the-screen-change check")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adt", description="Android device tool for agent-driven testing")
    _global_flags(parser, suppress=False)
    common = argparse.ArgumentParser(add_help=False)
    _global_flags(common, suppress=True)
    sub = commands.subparsers(parser, common, dest="cmd", required=True)

    sub.add_parser("doctor", help="check adb, tools and connected devices")
    p = sub.add_parser("devices", help="list devices")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("info", help="device facts for reports (navigation mode, keyboard, locale, ...)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("observe", help="dump UI hierarchy + screenshot with numbered elements")
    p.add_argument("--save-dir", help="also copy xml/png/preview into this directory (evidence)")
    p.add_argument("--name", help="file name stem (saved into the session's screenshots/ when a session is active)")
    p.add_argument("--no-image", action="store_true", help="hierarchy only, skip the screenshot")
    p.add_argument("--no-marks", action="store_true", help="preview without numbered boxes")
    p.add_argument("--bounds", action="store_true", help="add each element's position and size (layout checks)")
    p.add_argument("--full", action="store_true", help="list every element, also when the screen is unchanged")
    p.add_argument("--image-only", action="store_true",
                   help="screenshot only, no hierarchy dump (keeps the accessibility layer off; for repro runs)")
    p.add_argument("--json", action="store_true")

    commands.add_inspect_parser(sub, "adt", "uiautomator XML")

    p = sub.add_parser("tap", help="tap an element or point")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--index", type=int, help="element index from the last observe")
    target.add_argument("--text", help="visible text / content description (fresh lookup)")
    target.add_argument("--id", help="resource id, full or short (fresh lookup)")
    target.add_argument("--xy", type=int, nargs=2, metavar=("X", "Y"), help="device pixels")
    target.add_argument("--preview-xy", type=int, nargs=2, metavar=("X", "Y"), help="pixels in the preview image")
    p.add_argument("--scroll", type=int, nargs="?", const=8, default=0, metavar="MAX",
                   help="with --text/--id: scroll down up to MAX times (default 8) to find the target")
    p.add_argument("--long", action="store_true", help="long-press instead of tap")
    p.add_argument("--allow-risk", metavar="APPROVAL", help="user's approval for a guarded element")
    _add_settle(p)

    p = sub.add_parser("type", help="type text through the on-screen keyboard")
    p.add_argument("text")
    p.add_argument("--index", type=int, help="tap this element first to focus it")
    p.add_argument("--submit", action="store_true", help="press the keyboard's action key afterwards")
    p.add_argument("--fallback", choices=["ask", "keyevents", "bulk"], default="ask",
                   help="when keys can't be located: stop and ask (exit 6), key events per char, or bulk input")
    _add_settle(p)

    p = sub.add_parser("key", help="back / home (gesture or nav-bar per device), enter, delete, tab, or KEYCODE_*")
    p.add_argument("name")
    p.add_argument("--repeat", type=int, default=1)
    _add_settle(p)

    p = sub.add_parser("swipe", help="swipe between two device points")
    p.add_argument("coords", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    p.add_argument("--ms", type=int, help="duration (default: human range, or 300 in fast mode)")
    _add_settle(p)

    p = sub.add_parser("scroll", help="scroll content (down = reveal content below)")
    p.add_argument("direction", choices=["up", "down", "left", "right"])
    p.add_argument("--index", type=int, help="scroll inside this element (default: largest scrollable)")
    _add_settle(p)

    p = sub.add_parser("wait", help="wait until an element appears (or disappears with --gone)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--id")
    p.add_argument("--gone", action="store_true")
    p.add_argument("--timeout", type=float, default=10)

    p = sub.add_parser("app", help="app management (setup operations)")
    app = commands.subparsers(p, common, dest="app_cmd", required=True)
    for name in ("launch", "stop", "clear", "info"):
        ap = app.add_parser(name)
        ap.add_argument("package")
        if name == "launch":
            _add_settle(ap)
    ap = app.add_parser("reset", help="known start state: force-stop, clear data (clear-data), launch, wait")
    ap.add_argument("package")
    ap.add_argument("--level", choices=device.RESET_LEVELS, default="restart",
                    help="restart keeps the app's data; clear-data makes it like a fresh install (ask first on "
                         "personal devices)")
    ap.add_argument("--timeout", type=float, default=20, help="seconds to wait for the app to come up")
    ap = app.add_parser("install")
    ap.add_argument("apk")
    ap.add_argument("--grant-all", action="store_true",
                    help="grant every runtime permission at install (skips the app's permission prompts; "
                         "setup only)")
    ap = app.add_parser("kill-background", help="home, then kill the app's process like Android does under memory "
                                                "pressure, return to it and compare the screen")
    ap.add_argument("package")
    ap.add_argument("--wait", type=float, default=2, help="seconds in the background before the kill (default 2)")

    ap = app.add_parser("links", help="deep links the app declares (from its manifest on the device)")
    ap.add_argument("package")

    p = sub.add_parser("open", help="open a link (deep link, App Link, OAuth or payment callback) and show the screen")
    p.add_argument("uri", help="e.g. myapp://checkout/return?status=ok or https://example.com/item/42")
    p.add_argument("--package", help="the app that should handle it (otherwise Android picks or asks)")
    p.add_argument("--cold", action="store_true", help="stop the app first, to open the link from a cold start")

    p = sub.add_parser("permissions", help="the app's runtime permissions: list, grant, revoke, reset")
    perm = commands.subparsers(p, common, dest="perm_cmd", required=True)
    pp = perm.add_parser("list")
    pp.add_argument("package")
    for name in ("grant", "revoke"):
        pp = perm.add_parser(name)
        pp.add_argument("package")
        pp.add_argument("permissions", nargs="+", help="e.g. camera, location, notifications, "
                                                      "android.permission.READ_CONTACTS")
    pp = perm.add_parser("reset", help="revoke all and clear 'don't ask again': the app asks again")
    pp.add_argument("package")
    ap = app.add_parser("list")
    ap.add_argument("filter", nargs="?", default="")
    ap.add_argument("--all", action="store_true", help="include system packages")
    app.add_parser("current")
    ap = app.add_parser("find", help="find an installed app by name (as on the launcher) or package id")
    ap.add_argument("query")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true")

    p = sub.add_parser("logcat", help="background logcat capture and crash extraction")
    log = commands.subparsers(p, common, dest="log_cmd", required=True)
    lp = log.add_parser("start")
    lp.add_argument("--out", required=True, help="file to stream logcat into")
    lp.add_argument("--keep", action="store_true", help="don't clear the device log buffer first")
    log.add_parser("stop")
    lp = log.add_parser("crashes")
    lp.add_argument("--package", help="only crash blocks mentioning this package")
    lp = log.add_parser("summary", help="the app's errors and warnings in the session log, grouped; saved for the "
                                        "report")
    lp.add_argument("--package", help="default: the session's package")
    lp.add_argument("--run", help="default: the active or last session")

    p = sub.add_parser("record", help="screen recording, chunked past the 3 min screenrecord limit")
    rec = commands.subparsers(p, common, dest="rec_cmd", required=True)
    rp = rec.add_parser("start")
    rp.add_argument("--out", required=True, help="target .mp4")
    rp = rec.add_parser("stop")
    rp.add_argument("--discard", action="store_true", help="delete the video (test passed)")

    p = sub.add_parser("clip", help="cut a clip from a recording by wall-clock time (action log 't' values)")
    p.add_argument("--from", dest="start", required=True, help="ISO time, HH:MM:SS or epoch")
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--video", help="default: the active session's videos/session.mp4")
    p.add_argument("--pad", type=float, default=3.0, help="seconds added before and after (default 3)")

    p = sub.add_parser("session", help="standard run folder, action log, capture")
    ses = commands.subparsers(p, common, dest="session_cmd", required=True)
    sp = ses.add_parser("start")
    sp.add_argument("--dir", help="run folder (default: <reports dir from the config>/<date>-<app>-<mode>"
                                  "[-<ticket>])")
    sp.add_argument("--package")
    sp.add_argument("--mode", choices=["explore", "test-case", "repro", "ui-review", "retest", "memory"])
    sp.add_argument("--charter")
    sp.add_argument("--ticket")
    sp.add_argument("--record", action="store_true", help="record the screen to videos/session.mp4")
    sp.add_argument("--logcat", action="store_true", help="stream logcat to logs/logcat.txt")
    sp = ses.add_parser("end", help="stop capture and build the report (when report check passes)")
    sp.add_argument("--discard-video", action="store_true")
    sp.add_argument("--no-report", action="store_true", help="don't build the report now")
    ses.add_parser("status")

    p = sub.add_parser("env", help="config stress: dark mode, font scale, orientation, RTL (restored at session end)")
    p.add_argument("--dark", choices=["on", "off"])
    p.add_argument("--font-scale", dest="font_scale", choices=["0.85", "1.0", "1.15", "1.3", "1.5", "2.0"])
    p.add_argument("--orientation", choices=["portrait", "landscape"])
    p.add_argument("--rtl", choices=["on", "off"], help="force right-to-left layout (restart the app afterwards)")
    p.add_argument("--reset", action="store_true", help="put back everything env changed")
    p.add_argument("--approval", metavar="APPROVAL", help="user's approval, required on a physical device")
    p = sub.add_parser("net", help="go offline (airplane mode) and back online; restored at session end")
    p.add_argument("state", choices=["offline", "online"])
    p.add_argument("--approval", metavar="APPROVAL", help="user's approval, required on a physical device")

    p = sub.add_parser("notifications", help="active notifications: app, title, text, action buttons")
    p.add_argument("--package", help="only this app's")
    p = sub.add_parser("media", help="put photos or videos in the gallery for upload and picker tests")
    med = commands.subparsers(p, common, dest="media_cmd", required=True)
    mp = med.add_parser("push")
    mp.add_argument("file")
    p = sub.add_parser("location", help="set the GPS position (emulators)")
    p.add_argument("latitude", type=float)
    p.add_argument("longitude", type=float)
    p = sub.add_parser("bio", help="touch the fingerprint sensor with the enrolled or an unknown finger (emulators)")
    p.add_argument("result", choices=["match", "fail"])

    p = sub.add_parser("touches", help="'Show taps' markers for recordings (system setting: needs approval on phones)")
    p.add_argument("state", choices=["on", "off"])
    p.add_argument("--approval", metavar="APPROVAL", help="user's approval, required to turn it on on a phone")

    for name, kind in (("hook", "hooks"), ("check", "checks")):
        p = sub.add_parser(name, help=f"run an app-profile script from .mobile-tester/apps/<package>/{kind}/")
        p.add_argument("name")
        p.add_argument("--package", required=True)
        p.add_argument("--config-dir", default=".mobile-tester")
        p.add_argument("script_args", nargs="*", help="arguments for the script, after --")

    p = sub.add_parser("perf", help="cold start time, frame stats and memory (saved into the active session)")
    prf = commands.subparsers(p, common, dest="perf_cmd", required=True)
    pp = prf.add_parser("startup", help="median cold start of N launches (force-stops the app first)")
    pp.add_argument("package")
    pp.add_argument("--runs", type=int, default=3)
    pp = prf.add_parser("frames", help="rendered/janky frames and frame-time percentiles since the last reset")
    pp.add_argument("package")
    pp.add_argument("--reset", action="store_true", help="start counting now (session start)")
    pp = prf.add_parser("memory", help="PSS/RSS and live objects (Activities, Views, ...) of the app")
    pp.add_argument("package")
    pp.add_argument("--flow", help="leak check: save this as a sample of the named flow (baseline, then after "
                                   "each cycle)")
    pp.add_argument("--settle", type=float, default=5, help="seconds to wait before a --flow sample (default 5)")
    pp = prf.add_parser("leak", help="leak verdict per flow from the --flow samples (needs 3+ cycles)")
    pp.add_argument("package")
    pp.add_argument("--flow", help="only this flow")

    p = sub.add_parser("apk", help="inspect APK / .xapk / .apks files (no device needed)")
    apk = commands.subparsers(p, common, dest="apk_cmd", required=True)
    ap = apk.add_parser("inspect", help="package, version, signers per APK, permissions of note")
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true")

    commands.add_parsers(sub, common)

    p = sub.add_parser("_record-worker", help=argparse.SUPPRESS)
    p.add_argument("stop_flag")
    return parser


_NO_DEVICE = {"doctor": cmd_doctor, "devices": cmd_devices, "report": commands.cmd_report, "apk": cmd_apk,
              "issues": commands.cmd_issues, "finding": commands.cmd_finding}
_WITH_DEVICE = {
    "info": cmd_info, "observe": cmd_observe, "inspect": cmd_inspect, "tap": cmd_tap, "type": cmd_type,
    "key": cmd_key, "swipe": cmd_swipe, "scroll": cmd_scroll, "wait": cmd_wait, "app": cmd_app,
    "permissions": cmd_permissions, "open": cmd_open, "logcat": cmd_logcat, "record": cmd_record, "clip": cmd_clip,
    "session": cmd_session, "touches": cmd_touches, "env": cmd_env, "net": cmd_net,
    "notifications": cmd_notifications, "media": cmd_media, "location": cmd_location, "bio": cmd_bio,
    "hook": cmd_script, "check": cmd_script, "perf": cmd_perf, "_record-worker": cmd_record_worker,
}


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page; app labels contain arbitrary Unicode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.cmd in _NO_DEVICE:
            return _NO_DEVICE[args.cmd](args)
        adb = Adb(args.serial)
        return _WITH_DEVICE[args.cmd](args, adb)
    except Blocked as exc:
        print(exc, file=sys.stderr)
        return EXIT_BLOCKED
    except NeedsDecision as exc:
        print(f"DECISION NEEDED: {exc}", file=sys.stderr)
        return EXIT_DECISION
    except (NotFound, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except DeviceError as exc:
        print(f"device error: {exc}", file=sys.stderr)
        return EXIT_DEVICE
    except (AdbError, clip.ClipError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_DEVICE if isinstance(exc, AdbError) else EXIT_USAGE
