---
name: ios-device
description: Use when a task needs to look at or operate an iOS simulator or a real iPhone or iPad - listing devices, reading the screen, tapping or typing, launching or installing apps, the app's log, crash reports, screenshots or screen recordings, cutting video clips, or running app setup scripts.
---

# iOS device

All simulator and device work goes through one CLI, `idt`, run in the shell.
- Installed as a command (`uv tool install`, any agent): `idt <command> [options]`.
- In the Claude Code plugin without that install: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/idt.py" <command> [options]` (Claude Code fills in the path).

Try `idt doctor` first; if the command isn't found, use the plugin form. Below, `idt` stands for whichever works.
Full options for every command: [reference.md](reference.md).
**REQUIRED:** follow the `ios-human-input` skill for every UI action.

**Testing an app is not this skill's job.** When the user wants an app tested (exploring it, test cases, reproducing a bug, a UI review, a retest, or anything that should end in a report), load the `ios-native-tester` skill first and follow it.
It reads the project config (auto mode, reports folder, tester, guardrails) and runs the interview, the session and the report; this skill is the command reference it uses.
Use this skill on its own only for one-off tasks: a screenshot, checking what's installed, a crash report, a quick tap.

## How it works

`idt` drives the simulator or device through MTRunner, a small XCUITest runner that ships with it.
`idt` builds it once per Xcode version (`idt runner build`, about a minute) and starts it when a command needs it (about 15 s on a simulator, longer on a device); it then keeps running until the simulator shuts down, the device disconnects, or `idt runner stop`.
On a real device the runner must be signed by the user's Apple development team, and `idt` reaches it through CoreDevice's tunnel to the device (USB or Wi-Fi); it accepts no connections from the network, and every request carries a token from `idt`.
Coordinates are screen points (402x874 on an iPhone 17), not pixels.

## Before anything else

1. Run `idt doctor`. It must show Xcode and a booted simulator or a ready device.
   - No booted simulator: `idt devices` lists them; boot one with `xcrun simctl boot "iPhone 17"` and `open -a Simulator` to watch it.
   - Xcode missing: ask the user to install it; never install it yourself.
2. Without `-s`, `idt` uses the only booted simulator or USB-connected ready device. With several, or for a device on Wi-Fi, pass `-s UDID` (or the name) on every command.
3. Run `idt info` once; it reports model, iOS version, kind (simulator or physical), screen, keyboard language and locale for the report.

### A real iPhone or iPad

Every step that touches the user's Apple ID, signing or the device itself is theirs: tell them what to do and wait, never do it for them or guess.
`idt doctor` prints a `to do:` line for each device that isn't ready yet.
1. The device is paired with this Mac: connected by cable, unlocked, Trust tapped (the person holding it does this).
2. Developer Mode is on (Settings > Privacy & Security > Developer Mode, then a restart), and so is Settings > Developer > Enable UI Automation.
3. The user's Apple ID is signed in to Xcode (Xcode > Settings > Accounts).
4. Ask the user for their development team id, then `idt -s UDID runner build --team TEAMID`. It is remembered on this Mac; the build is per device. Xcode creates a development certificate and profile in that team and registers the device: say so when you ask.
   `DECISION NEEDED: ... team` from any command means no team is known yet: ask, never pick one from the hints it prints.
5. With a free personal team the device asks to trust the developer the first time: Settings > General > VPN & Device Management (the user does this).
   Its signing expires after 7 days: `idt runner start` renews it by itself in the last day (about 20 s), and `idt doctor`, `runner status` and `session start` show the date.
6. Keep the device unlocked while testing: a locked device stops the runner.

## The loop: observe, act, check

1. `idt observe` reads the app's element tree and takes a screenshot, and prints the screen identity and a numbered element list.
   It reads the session's app, or the app `idt` last launched, or `--app BUNDLE`; when that app isn't in front it shows SpringBoard (home screen, system alerts) and says so.
2. Read the element list first; it is enough for most steps. Open the `preview:` image (numbered boxes match the `[index]`) only when it adds something: a screen you haven't seen yet, elements without labels, a layout or visual question, a judgement about what a person sees, and in ui-review mode. Every image stays in the conversation for the rest of the session.
3. Act on one element: `idt tap --index N`, `idt type "text" --index N`, `idt scroll down`, `idt key back`.
   Human mode is the default: pacing, press duration, finger position and the back swipe are handled for you.
4. Read the action's output. When the screen changed, it ends with the new element list (only what changed when it's the same screen), so no separate `idt observe` is needed; `--no-observe` skips it.
   "no visible change" means it may not have landed: observe before continuing.
   In repro sessions actions don't list the screen (reading the tree turns on the accessibility layer); check with `idt observe --image-only`.
5. To prove a finding about an element (a missing label, a wrong value, a disabled state), run `idt inspect --index N`: the raw tree node, its parent and children, in a few lines. Don't read the saved tree files whole.

Choosing a target, in order of preference:
- `--index N` from the latest observation.
- `--text "Label"` (label, placeholder or value) or `--id identifier` (fresh lookup); add `--scroll` when it may be below the fold.
- `--preview-xy X Y` read off the preview image, only when the element is absent from the tree.

When the keyboard is up, `observe` says so; taps below its top edge would hit keys, so targets behind it are refused (exit 4).
Exit codes: 4 not found or covered, 5 guardrail block, 6 decision needed (e.g. a character no key types).

## Guardrails - never bypass

- Elements marked `RISK:payment`, `RISK:message` or `RISK:account` are refused (exit 5, `BLOCKED`).
- On `BLOCKED`, or whenever you judge a screen to be a purchase, outgoing message/post/review, account deletion/logout/password change, or accepting terms: stop and ask the user.
- Only after explicit approval of that one action, rerun with `--allow-risk "<quote of the user's approval>"`.
- The classifier knows English labels only; judge other languages and unlabelled icons yourself.
- Signing in to an Apple ID on the simulator uses the user's real account: ask first.
- A real device counts as personal unless the device inventory (`.mobile-tester/config.yaml`) says `personal: false`. On a personal device `app install`, `app uninstall` and `app reset --level clear-data` are refused (exit 5) until the user approves that step: rerun with `--allow-risk "<their approval>"`. System settings on it are never changed without asking.

## Sessions and evidence

- `idt session start --package BUNDLE --mode MODE --record --log` creates the standard run folder, records the screen, streams the app's log (simulators only), and logs every action to `RUN/logs/actions.jsonl`.
- `idt observe --name step-03` saves the screenshot, preview and tree JSON into the session; `idt observe --image-only` takes a screenshot without reading the tree.
- `idt clip --from T1 --to T2 --out RUN/videos/bug-1.mp4` cuts a clip using the `t` values from the action log.
- `idt crashes` lists the app's crash reports since the session started (on a device it copies them from the device first); every action also checks for new ones (on a device: when the app has stopped running).
- `idt session end` stops the recording and the log, and builds the report.
- `idt report check RUN` and `idt report build RUN` validate and render the standard report.

## Known limits

- Real-device support is new (tried on one iPhone, over USB and Wi-Fi): if a step fails in a way these instructions don't cover, tell the user what failed instead of working around it.
- Real devices: no app log streaming yet; crash reports work.
  Video only where Xcode offers recording for the device (`note: no recording` at session start otherwise, e.g. on an iPhone 15 Pro Max): screenshots are the evidence then.
  `.ipa` files must be unzipped to the `.app` inside first.
- Typing needs Apple's keyboard. With a third-party keyboard (Grammarly, Gboard, ...) `type` stops with `DECISION NEEDED`: ask the user to switch keyboards with the globe key, or to type the text themselves.
- The guardrail classifier knows English labels only: on a Dutch app "Toevoegen aan mandje" (add to basket) is not marked `RISK`; judge such buttons yourself.
- Over Wi-Fi a device is slower than over USB: every action takes screenshots through the tunnel.
- Each key press takes about half a second (XCUITest waits for the app to go idle), so long texts type slowly.
- Typing knows the keys on the letter, number and symbol layers; accented letters (long press) and other keyboard languages stop with a decision.
- No performance, memory or leak measurements on iOS yet.
- `app launch` starts the app through `simctl` or `devicectl`, not by tapping its icon. To reproduce launch-related bugs, tap the icon on the home screen instead.
