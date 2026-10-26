---
name: android-device
description: Use when a task needs to look at or operate a connected Android phone or emulator - checking devices, reading the screen, tapping or typing, launching apps, capturing logcat, crashes, screenshots or screen recordings, cutting video clips, or running app setup scripts.
---

# Android device

All device work goes through one CLI, `adt`, run in the shell.
- Installed as a command (`uv tool install`, any agent): `adt <command> [options]`.
- In the Claude Code plugin without that install: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/adt.py" <command> [options]` (Claude Code fills in the path).

Try `adt doctor` first; if the command isn't found, use the plugin form. Below, `adt` stands for whichever works.
Full options for every command: [reference.md](reference.md).
**REQUIRED:** follow the `android-human-input` skill for every UI action.

**Testing an app is not this skill's job.** When the user wants an app tested (exploring it, test cases, reproducing a bug, a UI review, a retest, or anything that should end in a report), load the `android-native-tester` skill first and follow it.
It reads the project config (autopilot, reports folder, tester, guardrails) and runs the interview, the session and the report; this skill is the command reference it uses.
Without it, sessions miss the config: wrong folder, no tester, and decisions the user automated get asked again.
Use this skill on its own only for one-off device tasks: a screenshot, checking what's installed, reading logcat, a quick tap.

## Before anything else

1. Run `adt doctor`. It must show adb and at least one device in state `device`.
   - `unauthorized`: ask the user to accept the "Allow USB debugging?" prompt on the phone.
   - adb missing: ask the user to install Platform-Tools; never install it yourself.
2. With several devices connected, pass `-s SERIAL` on every command (from `adt devices`).
3. Run `adt info` once; it reports navigation mode, keyboard, locale and accessibility state for the report.

## The loop: observe, act, check

1. `adt observe` dumps the UI hierarchy and takes a screenshot, and prints the screen identity and a numbered element list.
2. Read the element list first; it is enough for most steps. Open the `preview:` image (numbered boxes match the `[index]`) only when it adds something: a screen you haven't seen yet, elements without labels, a layout or visual question, a judgement about what a person sees, and in ui-review mode. Every image stays in the conversation for the rest of the session.
3. Act on one element: `adt tap --index N`, `adt type "text" --index N`, `adt scroll down`, `adt key back`.
   Human mode is the default: pacing, press duration, finger position and navigation style are handled for you.
4. Read the action's output. When the screen changed, it ends with the new element list (only what changed when it's the same screen), so no separate `adt observe` is needed; `--no-observe` skips it.
   "no visible change" means it may not have landed: observe before continuing.
   In repro sessions actions don't list the screen (reading the hierarchy turns on the accessibility layer); check with `adt observe --image-only`.
5. To prove a finding about an element (a missing label, a wrong value, a disabled state), run `adt inspect --index N`: the raw hierarchy node, its parent and children, in a few lines. Don't read the saved hierarchy files whole.

Choosing a target, in order of preference:
- `--index N` from the latest observation.
- `--text "Label"` or `--id short_id` (fresh lookup); add `--scroll` when it may be below the fold.
- `--preview-xy X Y` read off the preview image, only when the element is absent from the hierarchy.

Exit codes: 4 not found or covered, 5 guardrail block, 6 decision needed (e.g. a character the keyboard can't type).

## Guardrails - never bypass

- Elements marked `RISK:payment`, `RISK:message` or `RISK:account` are refused (exit 5, `BLOCKED`).
- On `BLOCKED`, or whenever you judge a screen to be a purchase, outgoing message/post/review, account deletion/logout/password change, or accepting terms: stop and ask the user.
- Only after explicit approval of that one action, rerun with `--allow-risk "<quote of the user's approval>"`.
- The classifier knows English labels only; judge other languages and unlabelled icons yourself.
- `adt app clear` and `adt app reset --level clear-data` wipe app data and `adt touches on` changes a system setting: on a physical device ask first.

## Sessions and evidence

- `adt session start --dir RUN --package PKG --mode MODE --record --logcat` creates the standard run folder, records the screen, streams logcat, and logs every action to `RUN/logs/actions.jsonl`.
- `adt observe --name step-03` saves the screenshot into the session; `adt observe --image-only` takes a screenshot without touching the accessibility layer.
- `adt clip --from T1 --to T2 --out RUN/videos/bug-1.mp4` cuts a clip using the `t` values from the action log.
- `adt logcat crashes --package PKG` lists crashes and ANRs.
- `adt session end` stops recording and logcat.
- `adt report check RUN` and `adt report build RUN` validate and render the standard report.

## Known limits

- On-screen typing knows Gboard with English key names; other keyboards or languages need the fallback (exit 6).
- Screens with FLAG_SECURE give black screenshots and recordings; rely on the hierarchy there.
- A UI that never goes idle can make the hierarchy dump fail. Retry once, then use the screenshot and `--preview-xy`.
- `app launch` starts the app through its launcher intent, not by tapping the icon. To reproduce launch-related bugs, tap the icon on the home screen instead.
