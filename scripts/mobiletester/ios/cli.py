"""idt, the iOS device tool. Output is plain text meant to be read by an agent; --json where scripts need it.

Same command names as adt where the concept exists. UI actions go through human.Driver: human-like by
default, quicker with the global --fast flag (setup and reset steps only).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ..core import clip, commands, devices, project, restore, screen, session, state, ui
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
from . import capture, crash, device, devicectl, entry_script, hierarchy, keyboard, runner, signing, simctl
from .device import Device
from .human import Driver
from .runner import Runner, RunnerError
from .simctl import DeviceError, SimctlError

MODES = ["explore", "test-case", "repro", "ui-review", "retest", "memory"]
DEVICE_RECORD_LIMIT = ("this device doesn't offer screen recording through Xcode's CoreDevice; screenshots "
                       "(`idt observe --name`) are the evidence")
DEVICE_LOG_LIMIT = ("streaming the app's log from a real device is not supported yet; crash reports are, "
                    "with `idt crashes`")


# --- helpers ---------------------------------------------------------------------------------

def _device(args) -> Device:
    return device.find(args.udid or os.environ.get("IDT_UDID"))


def _ready(dev: Device) -> Device:
    """UI commands need the runner; start it on demand (about 15 s on a simulator, longer on a device)."""
    if not dev.runner.alive():
        print(f"starting the runner on {dev.name}: {dev.runner.start()}")
    return dev


def _print_observation(obs: device.Observation, as_json: bool, bounds: bool = False,
                       previous: list[ui.Element] | None = None) -> None:
    if as_json:
        print(json.dumps(obs.to_dict(), ensure_ascii=False))
        return
    s = obs.snapshot
    where = obs.bundle_id + (f' "{obs.title}"' if obs.title else "")
    print(f"screen: {where}  fp={obs.fingerprint}  {s.screen.right}x{s.screen.bottom} pt")
    if obs.bundle_id == runner.SPRINGBOARD and obs.app_state is not None:
        print(f"note: the app is not in the foreground ({device.state_name(obs.app_state)}); this is SpringBoard "
              "(home screen or a system alert)")
    if obs.keyboard:
        print(f"keyboard: shown, {obs.keyboard.area.height} pt high from y={obs.keyboard.area.top} "
              "(type with `idt type`; taps below that line hit keys)")
    if obs.preview:
        print(f"preview: {obs.preview}  (scale {obs.scale:.3f} preview px per point, numbers = element index)")
        print(f"screenshot: {obs.screenshot}")
    risky = [e for e in s.elements if e.risk]
    if risky:
        print(f"WARNING: {len(risky)} risky element(s) on screen: "
              + ", ".join(f"[{e.index}] {e.risk}" for e in risky))
    for note in obs.notes:
        print(note)
    print("\n".join(ui.listing(s.elements, previous, bounds, depth_step=6)))


def _driver(dev: Device, args) -> Driver:
    return Driver(dev, pace=args.pace, fast=args.fast, verify=not args.no_verify)


def _after(dev: Device, args, outcome=None) -> None:
    if outcome is not None and (warning := outcome.warning()):
        print(warning)
    if args.fast or outcome is None or outcome.changed is None:
        time.sleep(getattr(args, "settle", 0.5))
    if commands.observe_after(args, outcome.changed if outcome else None, session.mode(dev.udid)):
        before = device.last_observation(dev.udid)
        obs = device.observe(dev, save_dir=_session_shots(dev))
        _print_observation(obs, as_json=False, previous=commands.previous_elements(before, obs.fingerprint))


def _session_shots(dev: Device) -> Path | None:
    directory = session.run_dir(dev.udid)
    return directory / "screenshots" if directory else None


def _tap_point(snap: ui.Snapshot, el: ui.Element, args, blocked: tuple[ui.Bounds, ...]) -> tuple[int, int]:
    if ui.visible_point(snap, el, blocked) is None:
        raise NotFound(f"{el.describe()} is covered by other controls or the keyboard. Scroll it into view, close "
                       "the keyboard, or tap the control that covers it.")
    if args.fast:
        return ui.visible_point(snap, el, blocked)
    return ui.human_point(snap, el, random.Random(), blocked)


def _unique(matches: list[ui.Element], what: str) -> ui.Element:
    if not matches:
        raise NotFound(f"no element matches {what}")
    if len(matches) > 1:
        listing = "\n".join("  " + m.describe() for m in matches[:10])
        raise NotFound(f"{len(matches)} elements match {what}, use --index:\n{listing}")
    return matches[0]


def _matches(snap: ui.Snapshot, args) -> list[ui.Element]:
    return ui.find_by_text(snap, args.text) if args.text is not None else ui.find_by_id(snap, args.id)


def _search(dev: Device, args, driver: Driver):
    """Fresh lookup by text/id; with --scroll, scroll the main list down until found or it stops moving."""
    what = f"text '{args.text}'" if args.text is not None else f"id '{args.id}'"
    snap, kb, *_ = device.read_screen(dev)
    for _ in range(args.scroll):
        if _matches(snap, args):
            break
        scrollables = [e for e in snap.elements if e.scrollable]
        if not scrollables:
            break
        driver.scroll("down", max(scrollables, key=lambda e: e.bounds.area).bounds)
        before = snap
        snap, kb, *_ = device.read_screen(dev)
        if [e.label for e in snap.elements] == [e.label for e in before.elements]:
            break  # reached the end of the list
    return snap, kb, _unique(_matches(snap, args), what)


def _resolve_target(dev: Device, args, driver: Driver) -> tuple[float, float, ui.Element | None, str]:
    """(x, y, element or None, label for the output and the action log)."""
    if args.index is not None:
        snap, kb, _ = device.last_snapshot(dev.udid)
        el = snap.find(args.index)
        return (*_tap_point(snap, el, args, (kb.area,) if kb else ()), el, el.describe())
    if args.text is not None or args.id is not None:
        snap, kb, el = _search(dev, args, driver)
        return (*_tap_point(snap, el, args, (kb.area,) if kb else ()), el, el.describe())
    snap, kb, data = device.last_snapshot(dev.udid)
    if args.xy:
        x, y = args.xy
    else:
        scale = data.get("preview_scale") or 1.0
        x, y = round(args.preview_xy[0] / scale), round(args.preview_xy[1] / scale)
    if kb and kb.area.contains(x, y):
        key = next((k for k in kb.keys if k.bounds.contains(x, y)), None)
        return x, y, None, f"keyboard key '{key.label}'" if key else "keyboard"
    el = ui.element_at(snap, x, y)
    return x, y, el, el.describe() if el else ""


def _approval_log(dev: Device, entry: dict) -> None:
    log = state.device_dir(dev.udid) / "guard_log.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), **entry}) + "\n")


def _guard(dev: Device, el: ui.Element | None, allow_reason: str | None, action: str) -> None:
    if el is None or not el.risk:
        return
    if not allow_reason:
        raise Blocked(f"BLOCKED: {action} on {el.describe()} looks like a {el.risk} action. "
                      "Stop and ask the user. If they approve, rerun with --allow-risk \"<their approval>\".")
    _approval_log(dev, {"action": action, "element": el.describe(), "risk": el.risk, "approval": allow_reason})


def _personal(dev: Device) -> bool:
    """A real device counts as personal unless your device list says it isn't; simulators never are."""
    return devices.personal(project.device_entry(dev.udid), dev.physical)


def _guard_personal(dev: Device, args, action: str) -> None:
    """Changing what is installed on someone's own phone, or wiping an app's data there, needs their yes."""
    if not _personal(dev):
        return
    approval = getattr(args, "allow_risk", None)
    if not approval:
        raise Blocked(f"BLOCKED: {action} on {dev.name}, a personal device. Stop and ask the user. If they approve, "
                      "rerun with --allow-risk \"<their approval>\".")
    _approval_log(dev, {"action": action, "device": dev.udid, "risk": "personal device", "approval": approval})


# --- commands without a device ---------------------------------------------------------------

def cmd_doctor(args) -> int:
    ok = True
    developer = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True)
    print(f"xcode-select: {developer.stdout.strip() or 'MISSING - install Xcode'}")
    xcodebuild = shutil.which("xcodebuild")
    if xcodebuild:
        version = subprocess.run([xcodebuild, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        print(f"xcodebuild: {version}")
    else:
        print("xcodebuild: MISSING - install Xcode")
        return EXIT_DEVICE
    for tool in ("ffmpeg", "ffprobe", "uv"):
        print(f"{tool}: {shutil.which(tool) or 'not on PATH'}")
    try:
        runner.xctestrun(build=False)
        print("runner (simulator): built")
    except RunnerError:
        print("runner (simulator): not built yet (`idt runner build`, about a minute, once per Xcode version)")
    booted = [s for s in simctl.list_devices() if s.booted]
    for sim in booted:
        alive = Runner(sim.udid).alive()
        print(f"simulator: {sim.udid} {sim.name} {sim.runtime} booted, runner {'running' if alive else 'stopped'}")
    phones = devicectl.list_devices()
    team = signing.team()
    if phones:
        print(f"signing team for devices: {team or 'not set (ask the user for it, then `idt runner build --team ID`)'}")
    for phone in phones:
        _doctor_device(phone, team)
    if not booted and not any(p.ready for p in phones):
        print("simulators: none booted (`xcrun simctl boot \"iPhone 17\"`, names in `idt devices`); "
              "devices: none ready")
        ok = False
    return EXIT_OK if ok else EXIT_DEVICE


def _signed_until(testrun: Path) -> str:
    """', signed until <local time>' for a device runner, with a word on what happens when it runs out."""
    expiry = runner.profile_expiry(testrun)
    if expiry is None:
        return ""
    soon = " (rebuilt at the next runner start)" if runner.needs_rebuild(expiry) else ""
    return f", signed until {runner.local_time(expiry)}{soon}"


def _doctor_device(phone: devicectl.PhysicalDevice, team: str | None) -> None:
    via = "USB" if phone.transport == "wired" else "Wi-Fi" if phone.transport == "localNetwork" else phone.transport
    print(f"device: {phone.udid} {phone.model} \"{phone.name}\" {phone.runtime} via {via}: {phone.state}")
    if problem := phone.problem():
        print(f"  to do: {problem}")
        return
    if team:
        try:
            built = "built" + _signed_until(runner.xctestrun(build=False, device=phone.udid, team=team))
        except RunnerError:
            built = f"not built yet (`idt -s {phone.udid} runner build`)"
        alive = Runner(phone.udid, physical=True).alive()
        print(f"  runner: {built}, {'running' if alive else 'stopped'}")
    print("  on the device, once: Settings > Developer > Enable UI Automation; keep it unlocked while testing")


def cmd_devices(args) -> int:
    sims, phones = simctl.list_devices(), devicectl.list_devices()
    kinds = {**{s.udid: "simulator" for s in sims}, **{p.udid: "physical" for p in phones}}
    if (code := commands.change_device_list(args, "iOS", kinds)) is not None:
        return code
    if args.json:
        print(json.dumps([{**s.__dict__, "kind": s.kind} for s in [*phones, *sims]]))
        return EXIT_OK
    for p in phones:
        print(f"{p.udid}\t{p.state}\tphysical\t{p.model} \"{p.name}\"\t{p.runtime}\t"
              f"{'USB' if p.transport == 'wired' else 'Wi-Fi'}\t{devices.describe(devices.get(p.udid), True)}")
    for s in sorted(sims, key=lambda s: (not s.booted, s.runtime, s.name)):
        print(f"{s.udid}\t{s.state}\tsimulator\t{s.name}\t{s.runtime}")
    return EXIT_OK if sims or phones else EXIT_DEVICE


# --- commands on a device --------------------------------------------------------------------

def cmd_runner(args, dev: Device) -> int:
    match args.runner_cmd:
        case "build":
            if not dev.physical:
                print(f"runner built: {runner.xctestrun()}")
                return EXIT_OK
            # The team is the user's answer, saved for the next builds; never guessed.
            team = signing.save_team(args.team) if args.team else signing.team()
            print(f"building the runner for {dev.name} signed by team {team or '?'} (about a minute)...")
            testrun = runner.xctestrun(device=dev.udid, team=team)
            print(f"runner built{_signed_until(testrun)}: {testrun}")
        case "start":
            print(dev.runner.start())
        case "stop":
            print(dev.runner.stop())
        case "status":
            signed = ""
            if dev.physical and (team := signing.team()):
                try:
                    signed = _signed_until(runner.xctestrun(build=False, device=dev.udid, team=team))
                except RunnerError:
                    signed = ", not built yet"
            print(f"runner on port {dev.runner.port}: {'running' if dev.runner.alive() else 'stopped'}{signed}")
    return EXIT_OK


def cmd_info(args, dev: Device) -> int:
    props = device.device_props(_ready(dev))
    print(json.dumps(props) if args.json else "\n".join(f"{k}: {v}" for k, v in props.items()))
    return EXIT_OK


def cmd_observe(args, dev: Device) -> int:
    _ready(dev)
    save_dir = Path(args.save_dir) if args.save_dir else (_session_shots(dev) if args.name else None)
    if args.image_only:
        target = (save_dir or state.device_dir(dev.udid)) / f"{args.name or 'latest'}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(dev.runner.screenshot())
        print(f"screenshot: {target}  (no tree read: accessibility untouched)")
        return EXIT_OK
    before = None if args.full else device.last_observation(dev.udid)
    obs = device.observe(dev, bundle_id=args.app, save_dir=save_dir, name=args.name, with_image=not args.no_image,
                         marks=not args.no_marks)
    _print_observation(obs, args.json, args.bounds, commands.previous_elements(before, obs.fingerprint))
    return EXIT_OK


def cmd_inspect(args, dev: Device) -> int:
    snap, _, _ = device.last_snapshot(dev.udid)
    el = commands.inspect_target(snap, args)
    tree = json.loads((state.device_dir(dev.udid) / "latest_tree.json").read_text(encoding="utf-8"))
    print("\n".join(ui.inspect_lines(el, *hierarchy.raw_node(tree, el))))
    return EXIT_OK


def cmd_contrast(args, dev: Device) -> int:
    return commands.print_contrast(device.last_observation(dev.udid), args.min, "idt")


def cmd_tap(args, dev: Device) -> int:
    driver = _driver(_ready(dev), args)
    x, y, el, label = _resolve_target(dev, args, driver)
    action = "long-press" if args.long else "tap"
    _guard(dev, el, args.allow_risk, action)
    if el is not None and not el.enabled:
        print(f"note: target is disabled: {el.describe()}")
    outcome = driver.tap(x, y, target=label, long=args.long)
    print(f"{action} ({x:.0f},{y:.0f})" + (f" -> {label}" if label else ""))
    _after(dev, args, outcome)
    return EXIT_OK


def _wait_for_keyboard(dev: Device, timeout: float = 3.0) -> None:
    """A busy app shows the keyboard a moment after the field is tapped; a person waits for it too."""
    deadline = time.monotonic() + timeout
    while device.read_screen(dev)[1] is None and time.monotonic() < deadline:
        time.sleep(0.25)


def cmd_type(args, dev: Device) -> int:
    driver = _driver(_ready(dev), args)
    if args.index is not None:
        snap, kb, _ = device.last_snapshot(dev.udid)
        el = snap.find(args.index)
        driver.tap(*_tap_point(snap, el, args, (kb.area,) if kb else ()), target=el.describe())
        _wait_for_keyboard(dev)
    try:
        outcome = driver.type_text(args.text, submit=args.submit)
    except keyboard.CannotType as exc:
        raise NeedsDecision(f"{exc}. Ask the user how to continue (they may type it on the "
                            f"{'device' if dev.physical else 'simulator'}).") from exc
    except keyboard.ThirdPartyKeyboard as exc:
        raise NeedsDecision(f"{exc}. Ask the user to switch to Apple's keyboard for the session (the globe key on "
                            "the keyboard), or to type this text themselves.") from exc
    except keyboard.NoKeyboard as exc:
        if dev.physical:
            raise NeedsDecision(f"{exc}. A hardware keyboard connected to the device hides the on-screen one: "
                                "ask the user to disconnect it.") from exc
        raise NeedsDecision(f"{exc}. In Simulator.app, I/O > Keyboard > Toggle Software Keyboard (cmd-K) shows it "
                            "while the Mac keyboard is connected.") from exc
    # Never echo the text: it may be a credential from the secrets file.
    print(f"typed {len(args.text)} chars" + (" + return" if args.submit else ""))
    _after(dev, args, outcome)
    return EXIT_OK


def cmd_key(args, dev: Device) -> int:
    driver = _driver(_ready(dev), args)
    outcome = None
    for _ in range(args.repeat):
        outcome = driver.key(args.name)
    print(f"key {args.name} x{args.repeat}" + (" (left-edge swipe)" if args.name.lower() == "back" else ""))
    if args.name.lower() == "back" and outcome.changed is False:
        print("note: the back swipe didn't change the screen. Some screens turn the gesture off or have nothing to go "
              "back to: observe, then tap the app's own back button if there is one.")
    _after(dev, args, outcome)
    return EXIT_OK


def cmd_swipe(args, dev: Device) -> int:
    outcome = _driver(_ready(dev), args).swipe(*args.coords, ms=args.ms)
    print(f"swipe {args.coords}")
    _after(dev, args, outcome)
    return EXIT_OK


def cmd_scroll(args, dev: Device) -> int:
    _ready(dev)
    snap, _, _ = device.last_snapshot(dev.udid)
    if args.index is not None:
        area = snap.find(args.index).bounds
    else:
        scrollables = [e for e in snap.elements if e.scrollable]
        area = max(scrollables, key=lambda e: e.bounds.area).bounds if scrollables else snap.screen
    outcome = _driver(dev, args).scroll(args.direction, area)
    print(f"scroll {args.direction} in {area}")
    _after(dev, args, outcome)
    return EXIT_OK


def cmd_wait(args, dev: Device) -> int:
    _ready(dev)
    deadline = time.monotonic() + args.timeout
    what = f"text '{args.text}'" if args.text else f"id '{args.id}'"
    while True:
        snap, *_ = device.read_screen(dev)
        found = ui.find_by_text(snap, args.text) if args.text else ui.find_by_id(snap, args.id)
        if bool(found) != args.gone:
            print(f"{'gone' if args.gone else 'found'}: {what}")
            return EXIT_OK
        if time.monotonic() > deadline:
            print(f"timeout after {args.timeout}s waiting for {what} to {'disappear' if args.gone else 'appear'}")
            return EXIT_NOT_FOUND
        time.sleep(0.5)


def _check_build(app: Path, dev: Device) -> None:
    """A simulator runs builds made for it and a device builds signed for it: catch a mix-up before installing."""
    if app.suffix == ".ipa":
        raise ValueError("unzip the .ipa and install the .app inside it (Payload/<name>.app)" if dev.physical else
                         ".ipa files are for real devices; a simulator needs the .app built for it "
                         "(xcodebuild -sdk iphonesimulator)")
    platforms = simctl.info_plist(app).get("CFBundleSupportedPlatforms", [])
    if dev.physical and "iPhoneSimulator" in platforms:
        raise ValueError(f"{app.name} is a simulator build; a device needs a build signed for it (xcodebuild -sdk "
                         "iphoneos with the team's signing)")
    if not dev.physical and "iPhoneOS" in platforms:
        raise ValueError(f"{app.name} is a device build; a simulator needs the .app built for it "
                         "(xcodebuild -sdk iphonesimulator)")


def _installed_app(dev: Device, bundle_id: str) -> Path | None:
    """The .app idt last installed for this bundle id: what clear-data reinstalls."""
    known = (state.read_json(state.device_dir(dev.udid) / "installs.json") or {}).get(bundle_id)
    return Path(known) if known and Path(known).is_dir() else None


def cmd_open(args, dev: Device) -> int:
    """Open a link the way Safari, a notification or another app does, and show where it landed."""
    if dev.physical:
        print("error: opening links is supported on simulators only for now; on a device open it from Notes or "
              "Safari by hand")
        return EXIT_USAGE
    if args.cold:
        if not args.package:
            print("error: --cold needs --package, the app to stop first")
            return EXIT_USAGE
        dev.tool.terminate(dev.udid, args.package)
    before = device.last_observation(dev.udid)
    simctl.open_url(dev.udid, args.uri)
    session.log_action(dev.udid, {"action": "open-link", "mode": "intent", "uri": args.uri,
                                  "package": args.package, "cold": args.cold})
    if args.package:
        dev.remember_app(args.package)
    time.sleep(1.5)
    print(f"opened {args.uri}")
    if not args.no_observe:
        obs = device.observe(dev, bundle_id=args.package, save_dir=_session_shots(dev))
        _print_observation(obs, as_json=False, previous=commands.previous_elements(before, obs.fingerprint))
    print("next: go back (left-edge swipe or the app's back button) and check where it goes; then `idt crashes`")
    return EXIT_OK


def cmd_env(args, dev: Device) -> int:
    if dev.physical:
        print("error: appearance and text size can only be changed on a simulator; on a device use Settings > "
              "Display & Brightness and Settings > Accessibility > Display & Text Size yourself")
        return EXIT_USAGE
    if args.reset:
        restored = simctl.ui_restore(dev.udid)
        print("restored: " + (", ".join(restored) or "nothing was changed"))
        return EXIT_OK
    wanted = {k: v for k, v in (("appearance", {"on": "dark", "off": "light"}.get(args.dark)),
                                ("content_size", args.text_size)) if v}
    if not wanted:
        print("nothing to change: pass --dark or --text-size (or --reset)")
        return EXIT_USAGE
    for setting, value in wanted.items():
        restore.remember(dev.udid, setting, simctl.ui_get(dev.udid, setting))
        simctl.ui_set(dev.udid, setting, value)
    session.log_action(dev.udid, {"action": "env", "mode": "setup", **wanted})
    print("changed: " + ", ".join(f"{k} {v}" for k, v in wanted.items())
          + ". `env --reset` or `session end` puts it back.")
    return EXIT_OK


def _simulator_only(dev: Device, what: str) -> int | None:
    if dev.physical:
        print(f"error: {what} works on simulators only; on an iPhone or iPad do it by hand")
        return EXIT_USAGE
    return None


def cmd_media(args, dev: Device) -> int:
    if (code := _simulator_only(dev, "adding media")) is not None:
        return code
    simctl.add_media(dev.udid, Path(args.file))
    session.log_action(dev.udid, {"action": "media-add", "mode": "setup", "file": Path(args.file).name})
    print(f"added {Path(args.file).name} to Photos")
    return EXIT_OK


def cmd_clipboard(args, dev: Device) -> int:
    if (code := _simulator_only(dev, "the clipboard")) is not None:
        return code
    if args.clip_cmd == "get":
        print(simctl.clipboard_get(dev.udid))
    else:
        simctl.clipboard_set(dev.udid, args.text)
        print("clipboard set")
    return EXIT_OK


def cmd_location(args, dev: Device) -> int:
    if (code := _simulator_only(dev, "setting the location")) is not None:
        return code
    if args.clear:
        simctl.clear_location(dev.udid)
        print("location cleared")
        return EXIT_OK
    if args.latitude is None or args.longitude is None:
        print("error: pass LATITUDE LONGITUDE, or --clear")
        return EXIT_USAGE
    simctl.set_location(dev.udid, args.latitude, args.longitude)
    session.log_action(dev.udid, {"action": "location", "mode": "setup", "lat": args.latitude,
                                  "lon": args.longitude})
    print(f"location set to {args.latitude}, {args.longitude}")
    return EXIT_OK


def cmd_bio(args, dev: Device) -> int:
    if (code := _simulator_only(dev, "Face ID / Touch ID")) is not None:
        return code
    simctl.biometrics(dev.udid, args.action)
    session.log_action(dev.udid, {"action": f"bio-{args.action}", "mode": "setup"})
    print({"enroll": "Face ID / Touch ID enrolled", "match": "a matching face/finger was presented",
           "fail": "a non-matching face/finger was presented"}[args.action])
    return EXIT_OK


def cmd_permissions(args, dev: Device) -> int:
    if dev.physical:
        print("error: permissions can only be changed on a simulator; on an iPhone or iPad change them in "
              "Settings > Privacy & Security yourself, or reinstall the app to see its prompts again")
        return EXIT_USAGE
    services = args.services or ["all"]
    for service in services:
        simctl.privacy(dev.udid, args.perm_cmd, service, args.package)
    session.log_action(dev.udid, {"action": f"permissions-{args.perm_cmd}", "mode": "setup",
                                  "package": args.package, "services": services})
    print(f"{args.perm_cmd}: {', '.join(services)} for {args.package}"
          + ("; iOS ends the app if it was running" if args.perm_cmd == "revoke" else ""))
    return EXIT_OK


def cmd_app(args, dev: Device) -> int:
    match args.app_cmd:
        case "launch":
            pid = dev.tool.launch(dev.udid, args.package)
            dev.remember_app(args.package)
            session.log_action(dev.udid, {"action": "app-launch", "mode": "setup", "package": args.package})
            print(f"launched {args.package} (pid {pid})")
            _after(dev, args)
        case "stop":
            was = dev.tool.terminate(dev.udid, args.package)
            session.log_action(dev.udid, {"action": "app-stop", "mode": "setup", "package": args.package})
            print(f"stopped {args.package}" if was else f"{args.package} was not running")
        case "reset":
            return _app_reset(args, dev)
        case "install":
            app = Path(args.app).resolve()
            _check_build(app, dev)
            _guard_personal(dev, args, f"installing {app.name}")
            facts = simctl.bundle_of(app)
            dev.tool.install(dev.udid, app)
            installs = state.device_dir(dev.udid) / "installs.json"
            state.write_json(installs, {**(state.read_json(installs) or {}), facts["package"]: str(app)})
            session.log_action(dev.udid, {"action": "app-install", "mode": "setup", "file": app.name})
            print(f"installed {facts['package']} {facts['versionName']} ({facts['versionCode']}) from {app}")
        case "uninstall":
            _guard_personal(dev, args, f"uninstalling {args.package}")
            dev.tool.uninstall(dev.udid, args.package)
            print(f"uninstalled {args.package}")
        case "info":
            print(json.dumps(dev.tool.app_info(dev.udid, args.package), indent=1))
        case "links":
            if args.app:
                app = Path(args.app)
            elif dev.physical:
                print("error: on a device the app's files can't be read: pass --app with its .app build")
                return EXIT_USAGE
            else:
                app = simctl.app_path(dev.udid, args.package)
            found = simctl.links(app)
            print("\n".join(found) if found else f"{args.package} declares no URL schemes or Universal Links")
        case "list":
            for bundle, info in sorted(dev.tool.apps(dev.udid).items()):
                if info.get("ApplicationType") == "System" and not args.all:
                    continue
                if args.filter.casefold() in (bundle + info.get("CFBundleName", "")).casefold():
                    print(f"{bundle}\t{info.get('CFBundleDisplayName') or info.get('CFBundleName', '')}\t"
                          f"{info.get('ApplicationType', '')}")
        case "find":
            return _app_find(args, dev)
        case "current":
            bundle = dev.last_app() or session.package(dev.udid)
            if not bundle:
                print("no app known: pass one to `idt observe --app BUNDLE` or launch it with idt")
                return EXIT_NOT_FOUND
            print(f"{bundle} {device.state_name(_ready(dev).runner.app(bundle, 'state'))}")
    return EXIT_OK


def _app_reset(args, dev: Device) -> int:
    started = datetime.now().astimezone()
    steps = []
    if dev.tool.terminate(dev.udid, args.package):
        steps.append("terminate")
    if args.level == "clear-data":
        _guard_personal(dev, args, f"clearing {args.package}'s data (uninstall and reinstall)")
        app = _installed_app(dev, args.package)
        if app is None:
            raise NotFound(f"clear-data reinstalls the app, but idt doesn't know where {args.package}'s .app is: "
                           "install it once with `idt app install PATH` (built-in apps can't be reset this way)")
        dev.tool.uninstall(dev.udid, args.package)
        dev.tool.install(dev.udid, app)
        steps += ["uninstall", "install"]
    dev.tool.launch(dev.udid, args.package)
    dev.remember_app(args.package)
    steps.append("launch")
    _ready(dev)
    _, settled = screen.wait_stable(dev.runner.screenshot, timeout=8)
    app_state = dev.runner.app(args.package, "state")
    session.log_action(dev.udid, {"action": "app-reset", "mode": "setup", "package": args.package,
                                  "level": args.level, "steps": steps}, started)
    session.note_fast_step(dev.udid, f"reset ({args.level})")
    print(f"reset {args.package} ({args.level}): {', '.join(steps)}")
    if app_state != runner.FOREGROUND:
        print("note: the app is not in the foreground; a system alert may be on top (observe, then answer it as "
              "the profile's permission rule says)")
    if not settled:
        print("note: the screen is still changing (splash, animation or video); observe before acting")
    return EXIT_OK


def _app_find(args, dev: Device) -> int:
    query = args.query.casefold()
    scored = []
    for bundle, info in dev.tool.apps(dev.udid).items():
        names = [n for n in (info.get("CFBundleDisplayName"), info.get("CFBundleName")) if n]
        haystack = [bundle.casefold(), *(n.casefold() for n in names)]
        score = 100 if query in haystack else 85 if any(h.startswith(query) for h in haystack) else \
            60 if any(query in h for h in haystack) else 0
        if score:
            scored.append((score, bundle, names[0] if names else "", info.get("ApplicationType", "")))
    scored.sort(key=lambda s: (-s[0], s[1]))
    if scored and scored[0][0] == 100 and (len(scored) == 1 or scored[1][0] < 100):
        scored = scored[:1]
    scored = scored[:args.limit]
    if args.json:
        print(json.dumps([{"package": b, "name": n, "type": t, "score": s} for s, b, n, t in scored]))
    elif not scored:
        print(f"no installed app matches '{args.query}'")
    else:
        sure = len(scored) == 1 and scored[0][0] >= 85
        print("match:" if sure else f"{len(scored)} candidate(s), best first; ask the user to pick one:")
        for i, (_, bundle, name, kind) in enumerate(scored, 1):
            print(f"{i}. {name} ({bundle}, {kind.lower() or 'app'})")
    return EXIT_OK if scored else EXIT_NOT_FOUND


def cmd_log(args, dev: Device) -> int:
    match args.log_cmd:
        case "start":
            if dev.physical:
                raise ValueError(DEVICE_LOG_LIMIT)
            process = args.process or simctl.app_info(dev.udid, args.package)["executable"]
            pid = capture.log_start(dev.udid, process, Path(args.out))
            print(f"app log ({process}) -> {Path(args.out).resolve()} (pid {pid})")
        case "stop":
            path = capture.log_stop(dev.udid)
            print(f"app log stopped: {path}" if path else "the app log was not running")
    return EXIT_OK


def cmd_crashes(args, dev: Device) -> int:
    bundle = args.package or session.package(dev.udid) or dev.last_app()
    if not bundle:
        raise ValueError("pass --package BUNDLE (no session or launched app known)")
    executable = dev.tool.app_info(dev.udid, bundle)["executable"]
    since = args.since if args.since is not None else _session_start(dev)
    directory = crash.sync_device(dev.udid, executable) if dev.physical else None
    reports = crash.find(executable, bundle, since, directory)
    if not reports:
        print(f"no crash reports of {bundle} since {datetime.fromtimestamp(since):%Y-%m-%d %H:%M:%S}")
    for path in reports:
        print(f"{path}\n  {crash.summary(path, frames=8)}")
    return EXIT_OK


def _session_start(dev: Device) -> float:
    run = session.latest_run_dir(dev.udid)
    data = state.read_json(run / "session.json") if run else None
    if data and data.get("started"):
        return datetime.fromisoformat(data["started"]).timestamp()
    return time.time() - 3600


def cmd_record(args, dev: Device) -> int:
    match args.rec_cmd:
        case "start":
            if dev.physical and not dev.found.can_record:
                raise capture.CaptureError(DEVICE_RECORD_LIMIT)
            pid = capture.record_start(dev.udid, Path(args.out), physical=dev.physical)
            print(f"recording -> {Path(args.out).resolve()} (pid {pid})")
        case "stop":
            path = capture.record_stop(dev.udid, discard=args.discard)
            print("recording discarded" if args.discard else f"recording saved: {path}" if path
                  else "no recording was running")
    return EXIT_OK


def cmd_clip(args, dev: Device) -> int:
    if args.video:
        video = Path(args.video)
    else:
        run = session.latest_run_dir(dev.udid)
        if run is None:
            raise NotFound("no session recording known for this device; pass --video PATH")
        video = run / "videos" / "session.mp4"
    start, end = clip.cut_clip(video, commands.parse_time(args.start), commands.parse_time(args.end), Path(args.out),
                               args.pad)
    print(f"clip {Path(args.out).resolve()} = {video.name} {start:.1f}-{end:.1f}s")
    return EXIT_OK


def cmd_session(args, dev: Device) -> int:
    match args.session_cmd:
        case "start":
            props = device.device_props(_ready(dev))
            if dev.physical:
                testrun = runner.xctestrun(build=False, device=dev.udid, team=signing.team())
                if signed := _signed_until(testrun):
                    print(f"runner{signed.replace(',', ':', 1)}")
                props["personal"] = _personal(dev)
                if not project.device_entry(dev.udid):
                    print("note: this device is not in your device list, so it counts as personal: no data "
                          f"clearing, installs or system settings without asking. A test device? `idt devices --save "
                          f"{dev.udid} --name NAME --test`")
            meta = {
                "mode": args.mode, "charter": args.charter, "ticket": args.ticket, "package": args.package,
                "platform": "iOS", "device": props,
                "input": "idt human mode (XCUITest touches)" + (f", pace {args.pace}" if args.pace != "human" else ""),
            }
            if args.package:
                try:
                    meta["app"] = dev.tool.app_info(dev.udid, args.package)
                    meta["app"].pop("bundle_path", None)
                except SimctlError:
                    meta["app"] = {"package": args.package, "installed": False}
            directory = Path(args.dir) if args.dir else project.default_run_dir(args.package, args.mode, args.ticket)
            defaults = {"title": project.default_title(args.package, args.mode, platform="iOS"),
                        "tester": project.tester()}
            directory = session.start(dev.udid, directory, commands.apply_plan(args, meta), defaults)
            (state.device_dir(dev.udid) / "crash_watch.json").unlink(missing_ok=True)
            started = []
            if args.log and dev.physical:
                print(f"note: no app log: {DEVICE_LOG_LIMIT}")
            elif args.log and args.package and meta["app"].get("executable"):
                capture.log_start(dev.udid, meta["app"]["executable"], directory / "logs" / "app.log")
                started.append("app log")
            if args.record and dev.physical and not dev.found.can_record:
                print(f"note: no recording: {DEVICE_RECORD_LIMIT}")
            elif args.record:
                capture.record_start(dev.udid, directory / "videos" / "session.mp4", physical=dev.physical)
                started.append("recording")
            active = session.active(dev.udid)
            active["started_capture"] = started
            state.write_json(state.device_dir(dev.udid) / "session.json", active)
            print(f"session -> {directory}" + (f" ({', '.join(started)} running)" if started else ""))
        case "end":
            active = session.active(dev.udid)
            if not active:
                print("no active session")
                return EXIT_OK
            started = active.get("started_capture", [])
            if "recording" in started:
                saved = capture.record_stop(dev.udid, discard=args.discard_video)
                print(f"recording: {saved or ('discarded' if args.discard_video else 'none saved, see recording.log')}")
            if "app log" in started:
                print(f"app log: {capture.log_stop(dev.udid)}")
            run = session.end(dev.udid)
            print(f"session ended: {run}")
            if not dev.physical and (restored := simctl.ui_restore(dev.udid)):
                print("restored simulator settings: " + ", ".join(restored))
            if run and not args.no_report:
                commands.report_after_session(run, "idt")
        case "status":
            active = session.active(dev.udid)
            print(json.dumps(active, indent=1) if active else "no active session")
    return EXIT_OK


def cmd_script(args, dev: Device) -> int:
    """Run an app-profile script: .mobile-tester/apps/<bundle id>/<hooks|checks>/<name>.(py|sh)."""
    kind = "hooks" if args.cmd == "hook" else "checks"
    app_dir = Path(args.config_dir).resolve() / "apps" / args.package
    candidates = [app_dir / kind / f"{args.name}{ext}" for ext in (".py", ".sh")]
    script = next((c for c in candidates if c.is_file()), None)
    if script is None:
        raise NotFound(f"no {kind[:-1]} '{args.name}' in {app_dir / kind}")
    idt_entry = entry_script()
    env = {
        **os.environ, "IDT_UDID": dev.udid, "MT_PLATFORM": "iOS", "MT_PACKAGE": args.package,
        "MT_APP_DIR": str(app_dir), "MT_RUN_DIR": str(session.run_dir(dev.udid) or ""),
        "IDT": f'"{sys.executable}" "{idt_entry}"', "MT_PYTHON": sys.executable, "MT_SCRIPT": str(idt_entry),
    }
    secrets = app_dir / "secrets.local.yaml"
    if secrets.is_file():
        env["MT_SECRETS"] = str(secrets)
    if script.suffix == ".py":
        uv = shutil.which("uv")
        cmd = [uv, "run", "-q", "--script", str(script)] if uv else [sys.executable, str(script)]
    else:
        cmd = ["bash", str(script)]
    session.log_action(dev.udid, {"action": f"{kind[:-1]}-{args.name}", "mode": "setup", "script": script.name})
    return subprocess.run([*cmd, *args.script_args], env=env).returncode


# --- parser ----------------------------------------------------------------------------------

def _add_settle(p: argparse.ArgumentParser, observe: bool = True) -> None:
    p.add_argument("--settle", type=float, default=0.5,
                   help="seconds to wait after the action when the screen isn't checked (fast mode)")
    if observe:
        p.add_argument("--observe", action="store_true",
                       help="always list the screen after the action (default: only when it changed)")
        p.add_argument("--no-observe", action="store_true", help="don't list the screen after the action")


def _global_flags(parser: argparse.ArgumentParser, suppress: bool) -> None:
    def default(value):
        return argparse.SUPPRESS if suppress else value

    parser.add_argument("-s", "--udid", default=default(None),
                        help="simulator or device UDID or name (default: IDT_UDID, else the only booted simulator "
                             "or USB-connected device)")
    parser.add_argument("--fast", action="store_true", default=default(False),
                        help="no pacing or checks: ONLY for setup/reset steps, never for the test itself")
    parser.add_argument("--pace", choices=["human", "slow"], default=default(os.environ.get("MT_PACE", "human")))
    parser.add_argument("--no-verify", action="store_true", default=default(False),
                        help="skip the did-the-screen-change check")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idt", description="iOS device tool for agent-driven testing (simulators "
                                                              "and real devices)")
    _global_flags(parser, suppress=False)
    common = argparse.ArgumentParser(add_help=False)
    _global_flags(common, suppress=True)
    sub = commands.subparsers(parser, common, dest="cmd", required=True)

    sub.add_parser("doctor", help="check Xcode, the runner, booted simulators and connected devices")
    p = sub.add_parser("devices", help="list real devices and simulators; save or forget one in your device list")
    p.add_argument("--json", action="store_true")
    commands.add_device_list_args(p)
    p = sub.add_parser("runner", help="the XCUITest runner that drives the simulator or device (started on demand)")
    run = commands.subparsers(p, common, dest="runner_cmd", required=True)
    rp = run.add_parser("build", help="build the runner (for a real device: signed by the user's team)")
    rp.add_argument("--team", help="the user's Apple development team id, remembered for later builds (ask the "
                                   "user; never guess)")
    for name in ("start", "stop", "status"):
        run.add_parser(name)
    p = sub.add_parser("info", help="device facts for reports (model, iOS, kind, screen, keyboard, locale)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("observe", help="read the screen: elements + screenshot with numbered boxes")
    p.add_argument("--app", help="bundle id to read (default: the session's app, else the last launched one)")
    p.add_argument("--save-dir", help="also copy tree/png/preview into this directory (evidence)")
    p.add_argument("--name", help="file name stem (saved into the session's screenshots/ when a session is active)")
    p.add_argument("--no-image", action="store_true", help="elements only, skip the screenshot")
    p.add_argument("--no-marks", action="store_true", help="preview without numbered boxes")
    p.add_argument("--bounds", action="store_true", help="add each element's position and size (layout checks)")
    p.add_argument("--full", action="store_true", help="list every element, also when the screen is unchanged")
    p.add_argument("--image-only", action="store_true", help="screenshot only, no tree read (for repro runs)")
    p.add_argument("--json", action="store_true")

    commands.add_inspect_parser(sub, "idt", "UI tree")
    commands.add_contrast_parser(sub)

    p = sub.add_parser("tap", help="tap an element or point (points, not pixels)")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--index", type=int, help="element index from the last observe")
    target.add_argument("--text", help="visible text / accessibility label (fresh lookup)")
    target.add_argument("--id", help="accessibility identifier (fresh lookup)")
    target.add_argument("--xy", type=float, nargs=2, metavar=("X", "Y"), help="screen points")
    target.add_argument("--preview-xy", type=int, nargs=2, metavar=("X", "Y"), help="pixels in the preview image")
    p.add_argument("--scroll", type=int, nargs="?", const=8, default=0, metavar="MAX",
                   help="with --text/--id: scroll down up to MAX times (default 8) to find the target")
    p.add_argument("--long", action="store_true", help="long-press instead of tap")
    p.add_argument("--allow-risk", metavar="APPROVAL", help="user's approval for a guarded element")
    _add_settle(p)

    p = sub.add_parser("type", help="type text key by key on the on-screen keyboard")
    p.add_argument("text")
    p.add_argument("--index", type=int, help="tap this element first to focus it")
    p.add_argument("--submit", action="store_true", help="press return afterwards")
    _add_settle(p)

    p = sub.add_parser("key", help="back (left-edge swipe), home (home button), enter, delete, space")
    p.add_argument("name")
    p.add_argument("--repeat", type=int, default=1)
    _add_settle(p)

    p = sub.add_parser("swipe", help="swipe between two screen points")
    p.add_argument("coords", type=float, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
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

    p = sub.add_parser("media", help="add photos or videos to Photos for upload and picker tests (simulators)")
    med = commands.subparsers(p, common, dest="media_cmd", required=True)
    mp = med.add_parser("add")
    mp.add_argument("file")
    p = sub.add_parser("clipboard", help="read or set the simulator's clipboard (copy buttons, pasted codes)")
    clip_sub = commands.subparsers(p, common, dest="clip_cmd", required=True)
    clip_sub.add_parser("get")
    cp = clip_sub.add_parser("set")
    cp.add_argument("text")
    p = sub.add_parser("location", help="set or clear the simulated location (simulators)")
    p.add_argument("latitude", type=float, nargs="?")
    p.add_argument("longitude", type=float, nargs="?")
    p.add_argument("--clear", action="store_true")
    p = sub.add_parser("bio", help="Face ID / Touch ID on a simulator: enroll, then present a match or a failure")
    p.add_argument("action", choices=["enroll", "match", "fail"])

    p = sub.add_parser("env", help="config stress on a simulator: dark mode, text size (restored at session end)")
    p.add_argument("--dark", choices=["on", "off"])
    p.add_argument("--text-size", dest="text_size", choices=list(simctl.CONTENT_SIZES))
    p.add_argument("--reset", action="store_true", help="put back everything env changed")

    p = sub.add_parser("permissions", help="grant, revoke or reset an app's privacy permissions (simulators)")
    perm = commands.subparsers(p, common, dest="perm_cmd", required=True)
    for name in ("grant", "revoke", "reset"):
        pp = perm.add_parser(name)
        pp.add_argument("package", help="bundle id")
        pp.add_argument("services", nargs="*", choices=list(simctl.PRIVACY_SERVICES), metavar="SERVICE",
                        help="one or more of: " + ", ".join(simctl.PRIVACY_SERVICES) + " (default: all)")

    p = sub.add_parser("app", help="app management (setup operations)")
    app = commands.subparsers(p, common, dest="app_cmd", required=True)
    personal_help = "the user's approval, needed on a personal device"
    ap = app.add_parser("links", help="URL schemes and Universal Link domains the app declares")
    ap.add_argument("package", help="bundle id")
    ap.add_argument("--app", help="read this .app build instead of the installed one (needed on devices)")
    p_open = sub.add_parser("open", help="open a link (URL scheme, Universal Link, OAuth callback) and show the "
                                         "screen (simulators)")
    p_open.add_argument("uri")
    p_open.add_argument("--package", help="bundle id of the app that should handle it")
    p_open.add_argument("--cold", action="store_true", help="stop the app first, to open the link from a cold start")
    p_open.add_argument("--no-observe", action="store_true", help="don't list the screen where the link landed")
    for name in ("launch", "stop", "uninstall", "info"):
        ap = app.add_parser(name)
        ap.add_argument("package", help="bundle id")
        if name == "launch":
            _add_settle(ap, observe=False)
        if name == "uninstall":
            ap.add_argument("--allow-risk", metavar="APPROVAL", help=personal_help)
    ap = app.add_parser("reset", help="known start state: terminate, reinstall (clear-data), launch, wait")
    ap.add_argument("package")
    ap.add_argument("--level", choices=["restart", "clear-data"], default="restart",
                    help="restart keeps the app's data; clear-data reinstalls the .app idt installed last")
    ap.add_argument("--allow-risk", metavar="APPROVAL", help=personal_help + " for clear-data")
    ap = app.add_parser("install", help="install a .app (a simulator build, or a signed device build)")
    ap.add_argument("app")
    ap.add_argument("--allow-risk", metavar="APPROVAL", help=personal_help)
    ap = app.add_parser("list")
    ap.add_argument("filter", nargs="?", default="")
    ap.add_argument("--all", action="store_true", help="include built-in apps")
    app.add_parser("current", help="the app idt works with and its state")
    ap = app.add_parser("find", help="find an installed app by name or bundle id")
    ap.add_argument("query")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true")

    p = sub.add_parser("log", help="stream the app's unified log into a file (simulators only)")
    log = commands.subparsers(p, common, dest="log_cmd", required=True)
    lp = log.add_parser("start")
    lp.add_argument("--out", required=True)
    who = lp.add_mutually_exclusive_group(required=True)
    who.add_argument("--package", help="bundle id (its executable's log is streamed)")
    who.add_argument("--process", help="process name")
    log.add_parser("stop")

    p = sub.add_parser("crashes", help="the app's crash reports since the session started")
    p.add_argument("--package", help="default: the session's app")
    p.add_argument("--since", type=float, help="epoch seconds (default: the session start)")

    p = sub.add_parser("record", help="screen recording of the simulator or device")
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
    sp.add_argument("--package", help="bundle id of the app under test")
    sp.add_argument("--mode", choices=MODES)
    sp.add_argument("--charter")
    sp.add_argument("--ticket")
    sp.add_argument("--record", action="store_true", help="record the screen to videos/session.mp4")
    commands.add_plan_args(sp)
    sp.add_argument("--log", action="store_true", help="stream the app's log to logs/app.log (simulators only)")
    sp = ses.add_parser("end", help="stop capture and build the report (when report check passes)")
    sp.add_argument("--discard-video", action="store_true")
    sp.add_argument("--no-report", action="store_true", help="don't build the report now")
    ses.add_parser("status")

    for name, kind in (("hook", "hooks"), ("check", "checks")):
        p = sub.add_parser(name, help=f"run an app-profile script from .mobile-tester/apps/<bundle id>/{kind}/")
        p.add_argument("name")
        p.add_argument("--package", required=True)
        p.add_argument("--config-dir", default=state.PROJECT_DIR)
        p.add_argument("script_args", nargs="*", help="arguments for the script, after --")

    commands.add_parsers(sub, common)
    return parser


_NO_DEVICE = {"doctor": cmd_doctor, "devices": cmd_devices, "report": commands.cmd_report,
              "issues": commands.cmd_issues, "finding": commands.cmd_finding,
              "screens": commands.cmd_screens}
_WITH_DEVICE = {
    "runner": cmd_runner, "info": cmd_info, "observe": cmd_observe, "inspect": cmd_inspect, "contrast": cmd_contrast,
    "tap": cmd_tap,
    "type": cmd_type, "key": cmd_key, "swipe": cmd_swipe, "scroll": cmd_scroll, "wait": cmd_wait, "app": cmd_app,
    "permissions": cmd_permissions, "env": cmd_env, "media": cmd_media, "clipboard": cmd_clipboard,
    "location": cmd_location, "bio": cmd_bio, "open": cmd_open, "log": cmd_log, "crashes": cmd_crashes,
    "record": cmd_record, "clip": cmd_clip, "session": cmd_session, "hook": cmd_script, "check": cmd_script,
}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.cmd in _NO_DEVICE:
            return _NO_DEVICE[args.cmd](args)
        return _WITH_DEVICE[args.cmd](args, _device(args))
    except Blocked as exc:
        print(exc, file=sys.stderr)
        return EXIT_BLOCKED
    except (NeedsDecision, signing.MissingTeam) as exc:
        print(f"DECISION NEEDED: {exc}", file=sys.stderr)
        return EXIT_DECISION
    except (NotFound, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except (DeviceError, RunnerError) as exc:
        print(f"device error: {exc}", file=sys.stderr)
        return EXIT_DEVICE
    except (SimctlError, capture.CaptureError, clip.ClipError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE if isinstance(exc, ValueError) else EXIT_DEVICE
