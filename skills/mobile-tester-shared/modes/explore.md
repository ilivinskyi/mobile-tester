# Explore mode: exploratory testing

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Goal: find the most important problems within the time box, guided by the charter.

## Plan (2 minutes)

1. From the charter, the ticket and the app profile's `about` (main flows, rules, roles, integrations), list 3-6 areas or questions to explore, riskiest first.
   Every area should trace back to one of those sources; drop ideas that only make sense for other kinds of apps.
2. Read the app's `notes.md`: known issues are not new findings, risky areas get extra time.

## Breadth tour (the first fifth of the time box)

Before going deep, open every screen once: cheap defects (typos, dead buttons, back-navigation traps, unreadable text) sit on screens a deep dive never reaches.
1. From the start screen, open every top-level destination: tabs and bottom bar, chips and quick links, the drawer and overflow menus, the profile icon, every entry in Settings.
   Observe after each navigation: that records the screen for the screen list.
2. On the first visit of each screen, do the screen checks below.
3. `dt screens RUN` lists the screens seen and, per screen, the controls never tapped yet: open those that lead somewhere new.
   A screen you saw but didn't open goes into `not_covered`.
4. Then go deep, area by area, riskiest first. A charter about one area still gets the tour, shorter: the screens that area links to.

### Screen checks (first visit)

- **Text:** read every title, label, button, hint and placeholder for typos and wrong words; tap empty fields once to see their hints.
- **Contrast:** `dt contrast` lists texts below 4.5:1 on the last observed screen. Check each one on the screenshot before writing it down.
- **Back:** the top-bar back arrow and the system back (iOS: the edge swipe) must both leave the screen to where you came from. Back that stays, lands on the same screen again (a loop), or does nothing (a dead end) is a bug.
- **Every control does something:** a tap with no visible change is a dead button or a missed tap. Read every "no visible change" warning, try it once more, and before wrap-up read the "Taps with no visible change" part of `dt screens RUN`.
- **Layout:** clipped, overlapping or cut-off text, controls under other controls.

## Explore

Work area by area, like a curious, slightly impatient user:
- **Main flows first** (`about.main_flows`), the way the users in `about.users` would go through them.
- **Rules:** try to break each rule in `about.rules`: the limits, validations and permissions it describes, from both sides.
- **Roles:** when `about.roles` lists several, check that each sees and can do only what it should.
- **Inputs:** every input field gets the checks for its kind, not just the first field of a form. Keep a field list in `logs/notes.md` and tick it off.

  | Field | Try |
  |---|---|
  | Any text | empty, only spaces, very long, `%`, `&`, quotes, `<b>`, `$(x)`, emoji, another script |
  | Search and filters | the text set, plus regex and wildcard characters: `[`, `(`, `?`, `*`, `\`, `.*` |
  | Numbers (hours, amounts, counts, days) | 0, -1, -50, a decimal, a huge value (999999), letters |
  | Dates and times | past, today, far future, the end of a month |
  | Names, labels, tags | empty and only spaces (a nameless item must not be created), a duplicate |

  After saving, check where the value shows up elsewhere (totals, lists, statistics): a negative hours value that makes a total negative is a bug in both places.
- **Lists:** do each row action (open, edit, delete, archive, restore) on the first, a middle and the last item, and on a list of one. Off-by-one bugs hit the wrong item, or crash on the last.
- **Interruptions:** back in the middle of a flow (iOS: the edge swipe and the app's back button), app switch, stop and relaunch, notification permission denied.
  Rotate with unsaved input on every form and on screens with state (typed text, a selection, a scroll position): on Android `adt rotate landscape`, then `adt rotate portrait`; it works on phones too, and a test device needs no approval. Typed text, selections and open dialogs must survive. (iOS: no rotation command yet.)
  On Android also `adt app kill-background` in the middle of a flow (the process killed to free memory: the screen must come back as it was), and `permissions revoke` while the app is in the background.
- **Links:** `app links` lists the links the app declares; open them with `open` from a cold start (`--cold`) and while the app runs, then press back.
- **Offline:** on Android, `adt net offline` before a submit, a search or loading more, then `net online`: look for endless spinners, lost or doubled submissions, wrong messages.
- **State:** does entered data, login or unfinished work survive a restart? Do changes show up everywhere they should?
- **Prompts:** permissions, consent and rating prompts: follow the autopilot defaults, note how they behave and what they cover.
- **External handoffs:** links that open the browser, login custom tabs, store pages: does the app recover when you come back?
- **Errors:** what does the user see when something fails, and is it true (a rejected search reported as "we're offline" is a bug)?

While exploring:
- One action, look, next action. Read every "no visible change" warning.
- When something looks wrong, check the raw source before writing it down; then reproduce it once more before calling it a bug.
- Write findings immediately; observations are welcome, they're cheap and useful.
- Keep a short trail in `logs/notes.md`: area, what you tried, what you saw.

## Stop

- At the time box (autopilot `time_box_end`), or when the charter's questions are answered.
- Before stopping, spend the last minutes re-checking each bug's reproduction, so every bug has its steps and a clip.
- Run `dt screens RUN` once more: screens never visited and untried controls that lead somewhere go into `not_covered`; taps with no visible change you didn't explain get one more try.

## Report extras

- `coverage`: the areas you went through. The report also lists the screens visited, with the controls never tried on each.
- `not_covered`: what the charter implied but you didn't reach, and what you deliberately skipped (and why, e.g. guardrails).
