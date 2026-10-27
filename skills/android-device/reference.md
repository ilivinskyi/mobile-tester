# adt command reference

`adt` is the mobile-tester Android command line: the `adt` command when it is installed (`uv tool install`, see the README), otherwise, in the Claude Code plugin, `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/adt.py"`.

Global options (before or after the command):

| Option | Meaning |
|---|---|
| `-s SERIAL` | device (otherwise `ANDROID_SERIAL`, otherwise the only ready device) |
| `--fast` | instant adb input without pacing or checks. Setup and reset steps only |
| `--pace human\|slow` | human (default) or slow pacing; also `MT_PACE` |
| `--no-verify` | skip the did-the-screen-change check |

## Setup

| Command | Purpose |
|---|---|
| `doctor` | adb location and version, other tools, device states |
| `devices [--json]` | serial, state, physical/emulator, model, and how your device list knows it (test, personal, not saved yet) |
| `devices --save ID --name NAME --test\|--personal` / `devices --forget ID` | your device list (`~/.config/mobile-tester/devices.yaml`, every project): a test device's system settings change without approval (still restored at `session end`); a personal or unsaved physical device asks every time |
| `info [--json]` | model, Android version, screen, density, navigation mode, keyboard, locale, show taps, accessibility services |

## Observing

`observe [--name STEM] [--save-dir DIR] [--no-image] [--no-marks] [--image-only] [--json]`

- `--name` saves screenshot, preview and XML into the active session's `screenshots/`.
- `--image-only` takes only a screenshot: no hierarchy dump, so the accessibility layer stays off (use in repro runs).

- `--bounds` adds each element's position and size (ui-review, layout questions); `--full` lists every element even when the screen is the same as at the last observe (by default only new or changed ones are listed then).

Element line format:

```
[7] "Storage | 16% used" #storage_row [click RISK:payment]
[8] Button "Next" #next_btn [click]
```

With `--bounds`: `[7] "Storage | 16% used" #storage_row @(540,1396) 1080x195 [click RISK:payment]`.

- `"..."` label: own text or content description; clickable containers show their non-interactive children's texts joined by ` | `.
- Class names are left out for plain containers (`View`, `LinearLayout`, `FrameLayout`, ...); the flags say what they do.
- `#id` short resource id; with `--bounds`, `@(x,y)` center and `WxH` size in device pixels.
- Flags: `click long checked/unchecked scroll edit password focused selected disabled sr-only RISK:<category>`.
- `sr-only`: text too small to see, there for screen readers only (e.g. a value whose visible version is drawn as an image). Read it, don't tap it.
- `RISK:` is set for action-like wording (short labels, not questions or sentences) and resource ids.

`inspect --index N | --text T | --id ID` prints the raw XML node behind an element of the last observe, with its parent and children (no device call). Use it to prove a finding instead of reading `latest.xml`.

Actions (`tap`, `type`, `key`, `scroll`, `swipe`) end with the new element list when the screen changed: `--observe` always lists it, `--no-observe` never. Not in repro sessions or with `--fast`.

State files per device under `MT_HOME` (default `.mobile-tester/state/<serial>/` in the project): `latest.json`, `latest.xml`, `latest.png`, `latest_preview.jpg`, `device.json` (cached facts).

## Acting (human mode by default)

Every action: think pause (0.4-1.4 s), the action, then wait until the screen is stable and compare it with the screen before.
"no visible change" in the output means the action may not have landed.
After every action the crash buffer is checked; "CRASH right after this action" names the crashing process and exception.
During a session with `--logcat`, the app's new log lines are checked too: "app log: N new issue(s)" lists errors, caught exceptions, network failures, StrictMode violations, 30+ skipped frames and out-of-memory lines from the app's processes.
Every 10 actions (`ADT_MEMORY_EVERY`, 0 = off) the app's memory is sampled into the session's `performance.memory_trend`.
Taps on an element go to a random point near its center that no other control covers; a fully covered element is refused (exit 4).

| Command | Notes |
|---|---|
| `tap --index N` | element from the last observe |
| `tap --text "Label" [--scroll [MAX]]` | ranking: exact own text > exact part of a merged label > label starts with it > word start > substring; clickable elements win ties |
| `tap --id ID [--scroll [MAX]]` | full `pkg:id/name` or short `name` |
| `tap --xy X Y` / `tap --preview-xy X Y` | device / preview pixels; the guard checks the topmost element under the point |
| `tap ... --long` | long press, 0.7-1.0 s |
| `tap ... --allow-risk "APPROVAL"` | only after explicit user approval; logged to `guard_log.jsonl` |
| `type "TEXT" [--index N] [--submit] [--fallback ask\|keyevents\|bulk]` | with `--index`, taps the field and waits up to 3 s for the keyboard; types on the on-screen keyboard (letters, shift, symbol layers, and reads the keyboard again before leaving a symbol layer, since Gboard returns to letters by itself after some symbols, after a space or apostrophe on a symbol layer, and on getting back to letters, where Gboard decides Shift again); `--submit` taps the keyboard's action key; exit 6 when a character can't be typed and `--fallback ask`; warns when the field shows something else (autocorrect) |
| `key back` / `key home` | edge swipe / swipe up in gesture navigation, nav-bar key in 3-button navigation; the back swipe starts above the keyboard when it is open |
| `key NAME [--repeat N]` | `enter tab delete recents menu search escape power wakeup volume_up volume_down` or any `KEYCODE_*` |
| `scroll up/down/left/right [--index N]` | direction the content moves into view; default area is the largest scrollable |
| `swipe X1 Y1 X2 Y2 [--ms N]` | endpoints wobble slightly in human mode |
| `wait --text T / --id ID [--gone] [--timeout 10]` | polls the hierarchy |

## Apps (setup operations)

| Command | Notes |
|---|---|
| `app find QUERY [--limit 8] [--json]` | find an installed app by its name as on the launcher ("Gmail") or its package id; prints `match:` for one sure hit, otherwise numbered candidates (name, package, version) for the user to pick. Names are read from each APK on the device (first lookup takes a while, then cached) |
| `app list [FILTER] [--all]` | third-party packages unless `--all` |
| `app current` | foreground package and activity |
| `app info PKG` | versionName, versionCode, targetSdk |
| `app launch PKG` | launcher intent (not an icon tap) |
| `app stop PKG` | force-stop |
| `app clear PKG` | wipes app data: ask first on physical devices |
| `app reset PKG [--level restart\|clear-data] [--timeout 20]` | known start state: force-stop, clear data (`clear-data` only: ask first on personal devices), launch, wait until the app is in front and the screen settles; adds itself to the session's `setup_steps_fast`. Says so when a system permission dialog is on top |
| `app install FILE [--grant-all]` | `.apk`, or `.xapk` / `.apks` bundles (split APKs). Runtime permissions are not granted, so the app's own prompts appear; `--grant-all` grants them all (setup only) |
| `app links PKG` | deep links the app declares (browsable intent filters from its manifest); `(verified App Link)` for domains Android checks |
| `app kill-background PKG [--wait 2]` | home, then kill the process like Android does under memory pressure, return through the launcher, report a crash and whether it's the same screen as before (observe first). Exit 6 when Android keeps the process alive (foreground service) |
| `open URI [--package PKG] [--cold] [--no-observe]` | open a deep link, App Link, OAuth or payment callback as another app would; prints launch state (COLD/WARM/HOT), crash, and the screen (not with `--no-observe`). `--cold` stops the app first. Then press back: the back stack must make sense |
| `permissions list\|grant\|revoke\|reset PKG [NAMES...]` | runtime permissions: names like `camera`, `location`, `notifications`, `photos` or full `android.permission.*`. Revoking kills the app's process (a classic crash test: revoke while it's in the background, then return). `reset` revokes all and clears "don't ask again" |
| `env [--dark on\|off] [--font-scale 2.0] [--orientation landscape] [--rtl on] [--reset] [--approval "..."]` | config stress; originals are recorded and restored by `env --reset` or `session end`. A system setting: needs `--approval` on a personal or unsaved physical device, not on a saved test device |
| `net offline\|online [--approval "..."]` | airplane mode on/off, restored by `session end`; refused when adb runs over Wi-Fi (it would cut the connection) |
| `notifications [--package PKG]` | active notifications: app, title, text, action buttons |
| `media push FILE` | a photo or video into the gallery (for uploads and pickers) |
| `location LAT LON` / `bio match\|fail` | GPS position / fingerprint sensor, emulators only |
| `apk inspect FILE` | package, version, signing certificates per APK, permissions of note: run before installing a build from outside a store |

## Sessions and evidence

| Command | Notes |
|---|---|
| `session start [--dir RUN] [--package P] [--mode explore\|test-case\|repro\|ui-review\|retest\|memory] [--charter C] [--ticket T] [--record] [--logcat]` | creates `screenshots/ videos/ logs/ bugs/`, `session.json`, `findings.json`; actions log to `logs/actions.jsonl`. Without `--dir`: a new folder `<reports dir from .mobile-tester/config.yaml>/<date>-<app>-<mode>[-<ticket>]`. Fills `title` and `tester` from the profile and config when missing |
| `session end [--discard-video] [--no-report]` | stops recording and logcat started by the session, then builds the report when `report check` passes (or lists the problems) |
| `session status` | active run folder |
| `record start --out FILE.mp4` / `record stop [--discard]` | 3-minute chunks joined with ffmpeg; writes `FILE.timeline.json` |
| `clip --from T --to T --out FILE [--video V] [--pad 3]` | T = `t` from actions.jsonl, `HH:MM:SS` today, or epoch; default video is the session's; the clip runs at 30 fps and holds the last frame through still screens, so it always covers the whole range |
| `logcat start --out FILE [--keep]` / `logcat stop` | background stream |
| `logcat crashes [--package PKG]` | crash buffer + FATAL/ANR lines since the last clear |
| `logcat summary [--package PKG] [--run RUN]` | the app's errors, caught exceptions, network failures, StrictMode, long frame drops and out-of-memory lines in the session log, grouped and most serious first; saved as `log_summary` for the report |
| `touches on --approval "..."` / `touches off` | "Show taps" markers in recordings; a system setting, needs approval on phones |
| `hook NAME --package P [-- ARGS]` | runs `.mobile-tester/apps/P/hooks/NAME.(py\|sh\|ps1)` |
| `check NAME --package P [-- ARGS]` | runs `.mobile-tester/apps/P/checks/NAME.(py\|sh\|ps1)` |
| `report check RUN` / `report build RUN` | validate / render `index.html` (finding list), `bugs/<id>.html` (one page per finding), `bugs/<id>.md` (Jira drafts) and `findings.csv` (Jira CSV import) |
| `report confirm RUN ID --result reproduced\|not-reproduced --by NAME [--tries N/M] [--note] [--device] [--build]` | record a person's manual check in the finding's history, update its manual count and status, rebuild the report |
| `issues list --package P [--status open\|fixed\|wont-fix\|duplicate\|all] [--json]` | the app's known issues (`.mobile-tester/apps/P/known-issues.json`) |
| `issues sync RUN --package P` | register a run's new bugs and accessibility findings (with regression test case drafts in `tests/`), record sightings of known issues, reopen fixed ones found again |
| `issues set K-n --package P --status fixed [--build] [--run] [--note]` | change an issue's status (e.g. after a retest) |
| `perf startup PKG [--runs 3]` | median cold start (force-stops the app first) |
| `perf frames PKG [--reset]` | janky frames and frame-time percentiles since the last reset |
| `perf memory PKG [--flow NAME] [--settle 5]` | PSS, RSS and live objects (Activities, windows, app contexts, Views, WebViews); all perf commands save into the active session's `performance`. With `--flow`: a leak-check sample of that flow (baseline, then one after each cycle), taken after `--settle` seconds |
| `perf leak PKG [--flow NAME]` | leak verdict per flow from its samples: "suspected leak" when object counts never drop and grow (Activities by 2+, Views by 100+) or PSS grows steadily by 10% and 8 MB; needs a baseline and 3+ cycles |

Hook and check scripts receive `ANDROID_SERIAL`, `ADB`, `ADT` (command line for adt), `MT_PLATFORM` (`Android`), `MT_PYTHON` and `MT_SCRIPT` (to call adt from Python), `MT_PACKAGE`, `MT_APP_DIR`, `MT_RUN_DIR`, and `MT_SECRETS` when `secrets.local.yaml` exists.
Python scripts run with `uv run --script`, so they may declare their own dependencies (PEP 723).

## Findings and session facts (no file editing)

| Command | Notes |
|---|---|
| `finding add RUN ID --type T --title "..." [--severity] [--priority] [--status] [--area] [--steps S1 S2 ...] [--expected] [--actual] [--automated N/M] [--manual N/M] [--evidence PATH[::CAPTION] ...] [--preconditions ...] [--notes] [--scope outside] [--known-issue K-n]` | appends to `findings.json` and runs the report checks on it at once: `problem:` lines and exit 2 mean saved but incomplete |
| `finding update RUN ID [same flags]` | changes the given fields; `--evidence` adds files (`--clear-evidence` first to replace) |
| `finding retract RUN ID --reason "..."` | status Retracted with the reason; findings are never deleted |
| `report set RUN FIELD VALUE` | session.json `title`, `subtitle`, `summary`, `charter`, `tester`, `mode`, `ticket`, `time_box_min`, and the app's `install_source` |
| `report add RUN FIELD VALUE ...` | adds to `worked_well`, `coverage`, `not_covered`, `setup_steps_fast` |
| `report decision RUN KEY VALUE [--why "..."]` | logs an autopilot decision (key from autopilot.md) in session.json and `logs/decisions.md`; the report lists them |
| `report telemetry RUN [--transcript F] [--since T] [--until T]` | technical data of the run: agent tokens and cost at API list prices (from the Claude Code transcript), time per phase, tool calls, device actions, evidence size; into `session.json` ("Technical data" in the report) and one row per run in `<reports dir>/telemetry.csv` |
| `report diff RUN_A RUN_B` | two runs side by side (e.g. two builds): performance changes (10% worse is called out), new findings, known issues no longer seen, new app log issues, screens reached in only one run |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | bad input or report problems |
| 3 | device or adb problem |
| 4 | element not found, ambiguous, covered, or wait timed out |
| 5 | blocked by a guardrail: ask the user |
| 6 | decision needed: ask the user or apply the autopilot default |
