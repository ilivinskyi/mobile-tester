---
name: ios-human-input
description: Use when tapping, typing, swiping, scrolling, going back or home, or launching apps on an iOS simulator or a real iPhone or iPad during testing, bug reproduction, or evidence recording - any time UI input is sent to an iPhone or iPad.
---

# Human-like iOS input

When the input is part of testing an app (a session, a bug reproduction, test cases), the `ios-native-tester` skill runs the session; load it first if it isn't loaded.

## Overview

A test only means something if the app received the same input a person would give it.
Shortcuts that skip the touch path are not that: `XCUIElement.typeText` and pasting bypass the keyboard, `simctl openurl` skips the screens a person passes, and a tap with no duration on an exact point is not a finger.
Bugs found that way may not exist for real users, and bugs real users hit may never show up.

**Core rule: all UI input goes through `idt` in its default human mode.**
`idt` sends real touches through its XCUITest runner: presses of 60-150 ms at a random uncovered point near the element's center, a "think" pause before each action, waiting for the screen to settle, a warning when an action changed nothing, back as the left-edge swipe, and typing key by key on the on-screen keyboard (shift and the number and symbol layers included).
**REQUIRED:** use the `ios-device` skill for the commands.

## Rules

1. Never drive the UI any other way during a test: no `simctl` URL tricks, no pasting, no AppleScript clicks on Simulator.app. Use `idt tap/type/key/swipe/scroll`.
2. `--fast` is only for setup and reset: installing, resetting, getting to the start state, deleting leftovers. Never for the steps under test or a bug's repro steps. Mark fast steps in `session.json` (`setup_steps_fast`).
3. Go back the way an iPhone user does: `idt key back` is the left-edge swipe. When it says the swipe didn't change the screen (the app turned the gesture off, or a sheet is open), tap the app's own back or close button, or swipe a sheet down. iOS has no system back key, so never report "back does nothing" without saying which of these you tried.
4. Type with `idt type`. It types on the on-screen keyboard; when it exits with code 6 (`DECISION NEEDED`), ask the user. A character on no key (accents need a long press, other scripts need another keyboard) is a decision, not something to paste.
5. If the on-screen keyboard doesn't appear, a hardware keyboard is in use: on a simulator ask the user to toggle the software keyboard (Simulator.app, I/O > Keyboard, cmd-K), on a device to disconnect the keyboard. Never type through the Mac keyboard during a test.
6. After every action, read the warnings. "no visible change" means the action may not have landed: observe before the next step, and never count that step as done.
7. Keep a person's rhythm: one action, look at the result, next action. Don't chain blind actions without checking.
8. A tap on a row goes to a random point near its center, as a finger would. Rows with small controls inside (check marks, toggles drawn as images) can take that tap: when the result is not what the row should do, observe and say which part was hit. If the inner control isn't in the element list, that itself is an accessibility finding.
9. Prefer `idt observe --image-only` during bug reproduction; full observes read the UI through the accessibility layer.
10. A bug that reproduces only through automation is **Unconfirmed** until a person reproduces it by hand (on a simulator: clicking in Simulator.app; on a device: with their own fingers). Offer the manual-repro protocol (repro mode); report automated and manual N of M separately.
11. Every claim needs its raw source: `idt inspect --index N` for an element, the app log, the crash report or the screenshot that proves it, before writing a finding.

## Rationalizations

| Thought | Reality |
|---|---|
| "`--fast` is quicker and it's just one step" | That step is now not what a user does. Fast only for setup. |
| "`typeText` is the same as typing" | It skips the keys: no shift state, no autocorrect, no auto-capitalisation, no key-by-key input events. |
| "Back didn't work, the app is broken" | The edge swipe may be turned off on that screen, or it's a sheet. Try the app's button, then decide. |
| "I'll observe after a few actions" | A swallowed tap goes unnoticed and every later step is invalid. |
| "It reproduced 10 times, it's real" | 10 automated runs can share one artefact. A person's repro confirms it. |
| "The tap hit the element's center, so it hit the element" | Centers can sit on inner controls or under bars and the keyboard. Trust the change check. |

## Red flags - stop and switch to idt human mode

- About to use `simctl openurl`, pasteboard tricks, or Simulator.app clicks to move through the app under test.
- Using `--fast` for a step that is part of the test or repro steps.
- Ignoring a "no visible change" warning.
- Writing a bug as Confirmed when only automation reproduced it.
- Claiming a missing label, trait or element without reading the saved tree.
