# Explore mode: exploratory testing

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Goal: find the most important problems within the time box, guided by the charter.

## Plan (2 minutes)

1. From the charter, the ticket and the app profile's `about` (main flows, rules, roles, integrations), list 3-6 areas or questions to explore, riskiest first.
   Every area should trace back to one of those sources; drop ideas that only make sense for other kinds of apps.
2. Read the app's `notes.md`: known issues are not new findings, risky areas get extra time.

## Explore

Work area by area, like a curious, slightly impatient user:
- **Main flows first** (`about.main_flows`), the way the users in `about.users` would go through them.
- **Rules:** try to break each rule in `about.rules`: the limits, validations and permissions it describes, from both sides.
- **Roles:** when `about.roles` lists several, check that each sees and can do only what it should.
- **Inputs:** empty, very long, special characters (`%`, `&`, quotes, `<b>`, `$(x)`), emoji, other scripts, numbers at limits (0, negative, 999, decimals).
- **Interruptions:** back in the middle of a flow (iOS: the edge swipe and the app's back button), app switch, stop and relaunch, rotate (emulator or simulator), notification permission denied.
  On Android also `adt app kill-background` in the middle of a flow (the process killed to free memory: the screen must come back as it was), and `permissions revoke` while the app is in the background.
- **Links:** `app links` lists the links the app declares; open them with `open` from a cold start (`--cold`) and while the app runs, then press back.
- **Offline:** on Android, `adt net offline` before a submit, a search or loading more, then `net online`: look for endless spinners, lost or doubled submissions, wrong messages.
- **State:** does entered data, login or unfinished work survive a restart? Do changes show up everywhere they should?
- **Prompts:** permissions, consent and rating prompts: follow the auto-mode defaults, note how they behave and what they cover.
- **External handoffs:** links that open the browser, login custom tabs, store pages: does the app recover when you come back?
- **Errors:** what does the user see when something fails, and is it true (a rejected search reported as "we're offline" is a bug)?

While exploring:
- One action, look, next action. Read every "no visible change" warning.
- When something looks wrong, check the raw source before writing it down; then reproduce it once more before calling it a bug.
- Write findings immediately; observations are welcome, they're cheap and useful.
- Keep a short trail in `logs/notes.md`: area, what you tried, what you saw.

## Stop

- At the time box (auto mode `time_box_end`), or when the charter's questions are answered.
- Before stopping, spend the last minutes re-checking each bug's reproduction, so every bug has its steps and a clip.

## Report extras

- `coverage`: the areas you went through.
- `not_covered`: what the charter implied but you didn't reach, and what you deliberately skipped (and why, e.g. guardrails).
