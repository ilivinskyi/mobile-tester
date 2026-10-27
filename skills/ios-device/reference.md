# idt command reference

`idt` is the mobile-tester iOS command line: the `idt` command when it is installed (`uv tool install`, see the README), otherwise, in the Claude Code plugin, `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/idt.py"`.

Global options (before or after the command):

| Option | Meaning |
|---|---|
| `-s UDID` | simulator or device UDID or name (otherwise `IDT_UDID`, otherwise the only booted simulator or USB-connected ready device; a device on Wi-Fi only when named) |
| `--fast` | no pacing or checks (presses still last 50 ms). Setup and reset steps only |
| `--pace human\|slow` | human (default) or slow pacing; also `MT_PACE` |
| `--no-verify` | skip the did-the-screen-change check (also skips waiting for the screen to settle) |

## Setup

| Command | Purpose |
|---|---|
| `doctor` | Xcode, ffmpeg, uv, whether the runner is built, booted simulators and their runner, paired devices with what each still needs (`to do:`), the signing team |
| `devices [--json]` | UDID, state, kind, name, iOS version of every paired device (`ready`, `developer mode off`, `unavailable`, `not paired`; USB or Wi-Fi; how your device list knows it) and every available simulator |
| `devices --save ID --name NAME --test\|--personal` / `devices --forget ID` | your device list (`~/.config/mobile-tester/devices.yaml`, every project): a test device's system settings change without approval (still restored at `session end`); a personal or unsaved physical device asks every time |
| `info [--json]` | model, iOS version, kind (`simulator` or `physical`), screen in points and scale, navigation, keyboard language, locale, languages; on a device also the connection (USB or Wi-Fi) |
| `runner build [--team TEAMID]` / `start` / `stop` / `status` | the XCUITest runner: built once per Xcode version into `~/Library/Caches/mobile-tester`, started on demand by any UI command, one port per simulator or device. On a device it is built for that device and signed by the user's team (`--team`, remembered in `~/Library/Application Support/mobile-tester/ios-signing.json`, or `MT_IOS_TEAM`); without a team every device command exits 6 (`DECISION NEEDED`). `start` rebuilds a device runner whose signing expires within a day (removing only that runner's cached profile in Xcode, so a fresh one is fetched); `build` and `status` print the expiry |

## Observing

`observe [--app BUNDLE] [--name STEM] [--save-dir DIR] [--no-image] [--no-marks] [--image-only] [--json]`

- Which app: `--app`, else the session's app, else the app `idt app launch`/`reset` last started. When it isn't in the foreground, the list is SpringBoard's (home screen, system alerts), with a note.
- `--name` saves screenshot, preview and the raw tree (`STEM.json`) into the active session's `screenshots/`.
- `--image-only` takes only a screenshot, without reading the tree (use in repro runs).

- `--bounds` adds each element's position and size (ui-review, layout questions); `--full` lists every element even when the screen is the same as at the last observe (by default only new or changed ones are listed then).

Element line format:

```
[1] Button "Add" #plus [click]
```

With `--bounds`: `[1] Button "Add" #plus @(374,79) 23x22 [click]`.

`inspect --index N | --text T | --id ID` prints the raw tree node behind an element of the last observe, with its parent and children (no device call). Use it to prove a finding instead of reading the saved tree JSON.

Actions (`tap`, `type`, `key`, `scroll`, `swipe`) end with the new element list when the screen changed: `--observe` always lists it, `--no-observe` never. Not in repro sessions or with `--fast`.

- Type: the XCUITest element type (`Button`, `Cell`, `TextField`, `StaticText`, `Image`, `Switch`, `CollectionView`, ...).
- `"..."` label: the accessibility label; text fields show their placeholder (never what was typed); cells and buttons without a label show their texts joined by ` | `.
- `#id` accessibility identifier; with `--bounds`, `@(x,y)` center and `WxH` size in points. `Other` containers show no type.
- Flags: `click checked/unchecked scroll edit password selected disabled RISK:<category>`.
- Navigation bars, tab bars and toolbars count as drawn above the content scrolling under them.
- System alerts (SpringBoard) are listed after the app's elements and are on top.
- The keyboard is not in the list: `observe` prints its area, and taps on elements behind it are refused.

State files per simulator or device under `MT_HOME` (default `.mobile-tester/state/<udid>/` in the project): `latest.json`, `latest_tree.json`, `latest.png`, `latest_preview.jpg`, `facts.json`, `runner.json`, `runner.log`.

## Acting (human mode by default)

Every action: think pause (0.4-1.4 s), the action, a 0.3 s reaction pause, then wait until the screen is stable and compare it with the screen before.
"no visible change" in the output means the action may not have landed.
During a session, every action also looks for a new crash report of the app; "CRASH right after this action" summarises it.
Taps on an element go to a random point near its center that no other control covers; a fully covered element is refused (exit 4).

| Command | Notes |
|---|---|
| `tap --index N` | element from the last observe |
| `tap --text "Label" [--scroll [MAX]]` | ranking as in adt: exact own text > exact part of a merged label > starts with it > word start > substring; controls win ties |
| `tap --id ID [--scroll [MAX]]` | accessibility identifier |
| `tap --xy X Y` / `tap --preview-xy X Y` | screen points / preview pixels; the guard checks the topmost element under the point |
| `tap ... --long` | long press, 0.7-1.0 s |
| `tap ... --allow-risk "APPROVAL"` | only after explicit user approval; logged to `guard_log.jsonl` |
| `type "TEXT" [--index N] [--submit]` | Apple's keyboard only (a third-party keyboard exits 6); taps the field first with `--index` and waits up to 3 s for the keyboard, then presses each key on the on-screen keyboard, switching shift and the number and symbol layers; `--submit` presses return; exit 6 when a character is on no key, or no keyboard is shown |
| `key back` | left-edge swipe to 75-88% of the width; prints a note when the screen didn't change |
| `key home` | the home button |
| `key enter\|delete\|space [--repeat N]` | the keyboard's return, delete or space key |
| `scroll up/down/left/right [--index N]` | direction the content moves into view; default area is the largest scrollable |
| `swipe X1 Y1 X2 Y2 [--ms N]` | screen points; endpoints wobble slightly in human mode |
| `wait --text T / --id ID [--gone] [--timeout 10]` | polls the tree |

## Apps (setup operations)

| Command | Notes |
|---|---|
| `app find QUERY [--limit 8] [--json]` | by name ("Reminders") or bundle id, built-in apps included; `match:` for one sure hit, otherwise numbered candidates |
| `app list [FILTER] [--all]` | installed apps; built-in ones only with `--all` |
| `app current` | the app idt works with and its state (foreground, background, not running) |
| `app info BUNDLE` | name, versionName (marketing version), versionCode (build), executable, minimum iOS |
| `app launch BUNDLE` | through simctl or devicectl (not an icon tap); remembered as the app to observe |
| `app stop BUNDLE` | terminate |
| `app reset BUNDLE [--level restart\|clear-data] [--allow-risk "APPROVAL"]` | known start state: terminate, reinstall (`clear-data`: the `.app` idt installed last), launch, wait until the screen settles; adds itself to the session's `setup_steps_fast`. Says so when the app isn't in front afterwards (a system alert). `clear-data` on a personal device needs `--allow-risk` |
| `app install PATH.app [--allow-risk "APPROVAL"]` | a simulator build on a simulator, a signed device build on a device (a mix-up is refused); `.ipa`: unzip it and install `Payload/<name>.app`. On a personal device needs `--allow-risk` |
| `app uninstall BUNDLE [--allow-risk "APPROVAL"]` | on a personal device needs `--allow-risk` |
| `app links BUNDLE [--app PATH]` | URL schemes (Info.plist) and Universal Link domains (entitlements, via codesign); on a device pass the `.app` |
| `open URI [--package BUNDLE] [--cold] [--no-observe]` | open a URL scheme, Universal Link or callback (simulators), then show the screen (not with `--no-observe`); `--cold` stops the app first |
| `permissions grant\|revoke\|reset BUNDLE [SERVICE...]` | simulators: `calendar contacts location location-always photos photos-add media-library microphone motion reminders siri` (default `all`). Camera and notifications can't be set: reinstall to see those prompts again |
| `env [--dark on\|off] [--text-size SIZE] [--reset]` | simulators: appearance and Dynamic Type size (`extra-small` ... `accessibility-extra-extra-extra-large`); restored by `env --reset` or `session end` |
| `media add FILE` / `clipboard get\|set TEXT` / `location LAT LON\|--clear` / `bio enroll\|match\|fail` | simulators: Photos, clipboard, simulated location, Face ID / Touch ID |

## Sessions and evidence

| Command | Notes |
|---|---|
| `session start [--dir RUN] [--package BUNDLE] [--mode explore\|test-case\|repro\|ui-review\|retest] [--charter C] [--ticket T] [--record] [--log]` | creates `screenshots/ videos/ logs/ bugs/`, `session.json` (platform, device with kind and, for a real device, `personal`, app), `findings.json`; actions log to `logs/actions.jsonl`. Without `--dir`: `<reports dir from .mobile-tester/config.yaml>/<date>-<app>-<mode>[-<ticket>]`. `--log` is skipped with a note on a device |
| `session end [--discard-video] [--no-report]` | stops the recording and the app log, then builds the report when `report check` passes |
| `session status` | active run folder |
| `record start --out FILE.mp4` / `record stop [--discard]` | `simctl io recordVideo`, on a device `devicectl device capture screen-record` (only where the device offers it, otherwise refused with a reason); writes `FILE.timeline.json` with the wall-clock start |
| `clip --from T --to T --out FILE [--video V] [--pad 3]` | T = `t` from actions.jsonl, `HH:MM:SS` today, or epoch; default video is the session's; the clip runs at 30 fps and holds the last frame through still screens, so it always covers the whole range |
| `log start --out FILE (--package BUNDLE \| --process NAME)` / `log stop` | the app's unified log, streamed in the background (simulators only) |
| `crashes [--package BUNDLE] [--since EPOCH]` | the app's crash reports (`~/Library/Logs/DiagnosticReports/<executable>-*.ips`; on a device copied from its crash logs into `.mobile-tester/state/<udid>/crashes/`) since the session started, with exception and top frames |
| `hook NAME --package P [-- ARGS]` | runs `.mobile-tester/apps/P/hooks/NAME.(py\|sh)` |
| `check NAME --package P [-- ARGS]` | runs `.mobile-tester/apps/P/checks/NAME.(py\|sh)` |
| `report check RUN` / `report build RUN` / `report confirm ...` | as in adt: the same report on both platforms |
| `finding add\|update\|retract`, `report set\|add\|diff` | as in adt: findings and session facts without editing files, and two runs compared |
| `issues list\|sync\|set ...` | as in adt: the app's known issues in `.mobile-tester/apps/P/known-issues.json` |

Hook and check scripts receive `IDT_UDID`, `IDT` (command line for idt), `MT_PLATFORM` (`iOS`), `MT_PYTHON` and `MT_SCRIPT` (to call idt from Python), `MT_PACKAGE`, `MT_APP_DIR`, `MT_RUN_DIR`, and `MT_SECRETS` when `secrets.local.yaml` exists.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | bad input or report problems |
| 3 | simulator, device, Xcode or runner problem |
| 4 | element not found, ambiguous, covered, or wait timed out |
| 5 | blocked by a guardrail: ask the user |
| 6 | decision needed: ask the user |
