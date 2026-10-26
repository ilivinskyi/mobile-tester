---
name: android-human-input
description: Use when tapping, typing, swiping, scrolling, navigating back or home, or launching apps on an Android phone or emulator during testing, bug reproduction, or evidence recording - any time UI input is sent to a device through adb.
---

# Human-like Android input

When the input is part of testing an app (a session, a bug reproduction, test cases), the `android-native-tester` skill runs the session; load it first if it isn't loaded.

## Overview

A test only means something if the app received the same input a person would give it.
Raw adb input is not that: `input tap` is a zero-length touch on an exact pixel, `input text` bypasses the keyboard, and `KEYCODE_BACK` is not a back swipe.
Bugs found that way may not exist for real users, and bugs real users hit may never show up.

**Core rule: all UI input goes through `adt` in its default human mode.**
`adt` presses for 60-150 ms at a random uncovered point near the element's center, pauses to "think" before each action, waits for the screen to settle, warns when an action changed nothing, uses the device's own navigation style (edge swipe or nav-bar key), and types through the on-screen keyboard.
**REQUIRED:** use the `android-device` skill for the commands.

## Rules

1. Never send UI input with raw `adb shell input ...` during a test. Use `adt tap/type/key/swipe/scroll`.
2. `--fast` is only for setup and reset: installing, clearing data, getting to the start state, deleting leftovers. Never for the steps under test or a bug's repro steps. Mark fast steps in `session.json` (`setup_steps_fast`).
3. Navigate the way the device's user does: `adt key back` and `adt key home` already pick an edge/bottom swipe in gesture mode and the nav-bar key in 3-button mode. Dismiss the keyboard the same way a person would (back, or the keyboard's hide key).
4. Type with `adt type`. When it exits with code 6 (`DECISION NEEDED`), ask the user, or apply the auto-mode default from `.mobile-tester/config.yaml`. Record in the finding when text was not typed through the keyboard.
5. After every action, read the warnings. "no visible change" means the action may not have landed: observe before the next step, and never count that step as done.
6. Keep a person's rhythm: one action, look at the result, next action. Don't chain blind actions without checking.
7. Prefer `adt observe --image-only` during bug reproduction. Full observes dump the UI through the accessibility layer, which can change how WebViews behave. Use them when you need element indices, not as a habit.
8. A bug that reproduces only through adb input is **Unconfirmed** until a person reproduces it by hand. Offer the manual-repro protocol (`android-native-tester` repro mode); report automated and manual N of M separately.
9. Every claim needs its raw source: `adt inspect --index N` for an element, the logcat lines, or the screenshot that proves it, before writing a finding.

## Rationalizations

| Thought | Reality |
|---|---|
| "`--fast` is quicker and it's just one step" | That step is now not what a user does. Fast only for setup. |
| "`input text` is the same as typing" | It skips the keyboard: no composition events, no autocorrect, no auto-capitalisation. Web apps react differently. |
| "BACK key = back gesture" | Not on gesture-navigation devices. The event path differs. |
| "I'll observe after a few actions" | A swallowed tap goes unnoticed and every later step is invalid. |
| "It reproduced 10 times, it's real" | 10 automated runs can share one artefact. A person's repro confirms it. |
| "The element must be there, the tap hit its center" | Centers can sit under toolbars, tab bars or overlays. Trust the change check, not the coordinates. |

## Red flags - stop and switch to adt human mode

- About to run `adb shell input tap/swipe/text/keyevent` during a test.
- Using `--fast` for a step that is part of the test or repro steps.
- Ignoring a "no visible change" warning.
- Writing a bug as Confirmed when only automation reproduced it.
- Claiming a missing label, value or element without checking it with `adt inspect`.
