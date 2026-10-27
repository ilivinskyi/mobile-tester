---
name: ios-native-tester
description: Use when the user wants an iOS app tested on an iPhone or iPad simulator or a real iPhone or iPad, in any words ("test the X app on iOS", "explore X on the iPhone simulator for 15 minutes", "test X on my iPhone", "reproduce PROJ-12 on iOS", "run these test cases on iOS", "check what's fixed in 1.2", "review the iOS UI") or via /ios-native-tester - exploratory testing, running test cases, reproducing a bug, reviewing UI and accessibility, or retesting known issues on a new build, with onboarding on first use and a standard QA report. Load it before touching the simulator or device; it reads the project config (autopilot, reports folder, tester).
argument-hint: "[explore|test-case|repro|ui-review|retest] [ticket, app, .app build or test-case file]"
---

# iOS native tester

Runs one test session on an iOS simulator or a real iPhone or iPad and ends with the standard report, the same report the Android tester writes.
Start from the user's request (in Claude Code, the command arguments: $ARGUMENTS).

**REQUIRED:** follow the `ios-human-input` skill for every UI action, and use the `ios-device` skill for `idt` commands.
`idt` is the mobile-tester iOS command line: the `idt` command when it is installed (`uv tool install`, see the README), otherwise, in the Claude Code plugin, `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/idt.py"`.
Shared files (onboarding, interview, modes, autopilot, report standard, templates) are in the `mobile-tester-shared` skill, next to this one: `../mobile-tester-shared/`. In them, `dt` means `idt`.
Questions to the user: use your agent's question tool when it has one (AskUserQuestion in Claude Code), otherwise ask in chat as a short numbered list with the recommended option first.

A simulator runs builds made for it (`.app` from `xcodebuild -sdk iphonesimulator`), not App Store apps or `.ipa` files; built-in apps (Reminders, Contacts, ...) are always there.
Real-device support is new (tried on one iPhone, over USB and Wi-Fi): say so when the user picks a device. Before typing on a device, check that it uses Apple's keyboard; with another one, ask the user to switch for the session.
A real device runs App Store apps already on it and signed device builds (`.app`, or the `.app` inside an `.ipa`); it needs the one-time setup in the `ios-device` skill (pairing, Developer Mode, UI Automation, the user's signing team). That setup is the user's to do: tell them each step and wait.
A real device counts as personal unless your device list says it's a test device (`idt devices --save UDID --name NAME --test`); `kind: physical` and `personal` go into the report.

## Session flow

Work through these phases in order and keep the user's task list in step with them.

### 1. Project setup

1. Run `idt doctor`. It needs Xcode and a booted simulator or a ready device.
   - No booted simulator: list them with `idt devices` and ask which to boot; boot it with `xcrun simctl boot "<name>"` and suggest `open -a Simulator` so the user can watch.
   - A device with a `to do:` line: tell the user that step (Trust, Developer Mode, UI Automation) and wait; never work around it.
   - Runner not built: `idt runner build` (about a minute, once per Xcode version); for a device `idt -s UDID runner build --team TEAMID` with the team id the user gave you (ask; never pick one). `idt` starts the runner itself when a command needs it (about 15 s on a simulator, longer on a device).
2. Read `.mobile-tester/config.yaml` in the project.
   If it doesn't exist, run onboarding first: [onboarding.md](../mobile-tester-shared/onboarding.md).
3. Note whether autopilot is on (the default). With autopilot, the session plan's Go is the last question until the wrap-up: follow [autopilot.md](../mobile-tester-shared/autopilot.md) for decisions, never-done actions, grants, approvals and which questions may still be asked.

### 2. Session plan

Follow [session-plan.md](../mobile-tester-shared/session-plan.md): fill the plan from the request, the profile and the config, ask only for real gaps (one round), show the plan, and ask Go, Add notes, Cancel or Restart.
Start nothing on the device before Go.
Memory mode is Android only for now: offer explore mode on the same flows instead.

### 3. Preparation

1. Simulator or device: `idt -s UDID info`. Check it matches the device inventory; note a real device that is personal (or not in the inventory, which counts as personal).
2. App profile: read `.mobile-tester/apps/<bundle id>/profile.yaml` (above all its `about` block) and `notes.md`, and list the open known issues with `idt issues list --package BUNDLE`. Known issues found again are linked, not re-reported.
3. Build:
   - Installed: compare `idt app info BUNDLE` (versionName = marketing version, versionCode = build) with the version the user expects.
   - From a simulator `.app`: install with `idt --fast app install PATH.app` (setup step). It also remembers the path, which `clear-data` resets reinstall from.
   - An `.ipa` is a device build and can't run on a simulator: ask for a simulator build, or for the project to build one. On a device, unzip it and install the `.app` from its `Payload/` folder.
   - On a personal device installing needs the user's yes: `idt --fast app install PATH.app --allow-risk "<their approval>"`.
4. Hooks: run `idt hook setup --package BUNDLE` when the profile defines it.
5. Start the session: `idt session start --package BUNDLE --mode MODE --charter "..." [--ticket KEY] --record --log` (on a device there is no app log yet: it says so, and `logs/app.log` stays absent; write that in `not_covered`).
   Without `--dir` the run folder is `<reports dir from config.yaml>/<YYYY-MM-DD>-<app>-<mode>[-<ticket>]`, a new one per session; it prints the folder.
   It also fills the title, the tester, the platform and the device from the profile, config and simulator or device. Then set the ticket, the time box and where the build came from with `idt report set RUN ticket|time_box_min|install_source VALUE` (see [report-standard.md](../mobile-tester-shared/report-standard.md)).
6. Bring the app to the start state (below). This also logs in when the profile's login needs it.

### Start state

Every run that is compared with another starts from the same state: the session itself, each reproduction attempt, each test case, each retested known issue.
Use the strategy agreed in the interview (default: the profile's `reset.strategy`):

| Strategy | Command |
|---|---|
| `restart` | `idt app reset BUNDLE --level restart` |
| `clear-data` | `idt app reset BUNDLE --level clear-data` (uninstalls and reinstalls the `.app` idt installed last), then the login (secrets, login hook, or ask the user to log in on the simulator or device). On a personal device add `--allow-risk "<the user's yes from the interview>"`; without that yes use `restart` and say so in `not_covered` |
| `hook` | `idt hook reset --package BUNDLE` |
| `none` | nothing; check the state the user prepared |

Built-in apps can't be reinstalled: for them `clear-data` is not available, use `restart` or a hook and say so in `not_covered`.
Then do the profile's `reset.after` steps with `--fast`, and check the state you depend on with `idt observe --image-only` before the first step under test.
`idt app reset` adds itself to `setup_steps_fast`; add the other setup steps you ran yourself with `idt report add RUN setup_steps_fast "<step>"`.
"the app is not in the foreground" after a reset usually means a system alert (permissions, notifications) is on top: `idt observe` shows it, answer it as `app_permission_prompts` says, as part of the setup.

### 4. Testing

Follow the mode guide:

| Mode | Guide |
|---|---|
| explore | [modes/explore.md](../mobile-tester-shared/modes/explore.md) |
| test-case | [modes/test-case.md](../mobile-tester-shared/modes/test-case.md) |
| repro | [modes/repro.md](../mobile-tester-shared/modes/repro.md) |
| ui-review | [modes/ui-review.md](../mobile-tester-shared/modes/ui-review.md) |
| retest | [modes/retest.md](../mobile-tester-shared/modes/retest.md) |

Judging behaviour:
- Expected behaviour comes from the app profile's `about` (description, main flows, rules, glossary), the ticket, and what the app itself says on screen. Nothing else defines "correct".
- Don't bring in checks that belong to a different kind of app. Test ideas follow this app's flows and rules, plus the universal ones (crashes, data loss, wrong or misleading messages, state that doesn't persist, accessibility, layout).
- iOS conventions are part of "what the app says": the left-edge swipe goes back on pushed screens, sheets close by swiping down, destructive actions ask first. An app that breaks one of these without a reason is worth an observation.
- When you can't tell whether something is a bug because the expected behaviour isn't described, write it as an observation with the open question in `notes`, collect the question with `idt report add RUN open_questions "..."`, and ask it at the wrap-up (with autopilot off, you may ask right away). Record any assumption you make in the finding.
- Reaching something on the never-done list (paying, ordering, messaging, the profile's `forbidden`) that the plan didn't grant: don't do it and don't ask; note it with `idt report add RUN not_covered "<what, where>"` and test something else.

Problems outside the charter (another screen, an unrelated feature):
- Never report anything in an area listed in the profile's `outside_scope.not_ready`, not even as an observation.
- If `outside_scope.report` is false, don't report them.
- If it's true (the default), write them as findings with `"scope": "outside"`. They get their own report section and don't count as bugs.
  Note what you saw and where; don't spend session time reproducing them unless they block the charter.

While testing:
- Write each finding with `idt finding add RUN ...` as soon as it's verified, not at the end, and change it with `finding update` / `finding retract`; never edit `findings.json` or `session.json` by hand. Fields and severity scale: [report-standard.md](../mobile-tester-shared/report-standard.md).
- Before writing a finding, check the raw source that proves it: `idt inspect --index N` for an element (never the whole saved tree), the screenshot, the relevant lines of `logs/app.log` (search them, don't read the file whole), or the crash report. If a finding turns out wrong, set it to Retracted with the reason; never delete it.
- Save evidence with `idt observe --name <id>-<what>` and note the action log time for video clips.
- A finding that matches an open known issue (same behaviour in the same area): set `"known_issue": "K-n"` and keep it short; don't re-investigate. It shows as "seen again".
- `CRASH right after this action` in an action's output: the crash watch found a new crash report of the app. Capture evidence (`idt observe --image-only`, `idt crashes`), write the finding at once with the step that triggered it, then follow the `crash_found` decision (default: restart the app and continue).
- Explore mode starts with a breadth tour of every screen and does the screen checks on each first visit (typos, `idt contrast`, back, controls that do nothing): [modes/explore.md](../mobile-tester-shared/modes/explore.md). `idt screens RUN` shows where you haven't been.
- Watch the time box. Note the halfway point in your progress, and wrap up when it runs out (`time_box_end`).
- With autopilot, ask nothing mid-run unless testing can't go on at all (device gone, app won't start, a login only the user can do).

### 5. Wrap-up

1. `idt session end`: it stops the recording and the app log, and builds the report right away when `idt report check` passes (otherwise it lists what to fix). Run the teardown hook if the profile has one.
2. Cut one clip per bug: `idt clip --from <t of first repro step> --to <t of last> --out RUN/videos/<id>.mp4`, and add it to the finding's evidence.
3. `idt screens RUN`: screens never visited and untried controls that lead somewhere go into `not_covered` (`idt report add RUN not_covered ...`); a tap with no visible change that you didn't explain is a lead, not a finding.
4. `idt issues sync RUN --package BUNDLE`: new bugs and accessibility findings join the app's known issues (each with a regression test case draft in `.mobile-tester/apps/<bundle id>/tests/`), and known issues seen again get a sighting.
5. `idt report check RUN` and fix every problem. When the plan has telemetry on, run `idt report telemetry RUN`: it records the technical data (agent tokens and cost, time per phase, tool and device activity) in `session.json`, adds a row to `<reports dir>/telemetry.csv` and rebuilds the report.
   It reads the newest Claude Code transcript of the project; in another agent pass `--transcript` if it keeps a compatible one, otherwise the report says tokens weren't collected.
   Open `index.html` in a browser (the browser pane in Claude Code) and look at it; in autopilot `report_build` decides, and it never waits for a question.
6. Ask the collected questions in one round (at most four, the rest in a second): the `open_questions`, the manual reproduction of each Unconfirmed finding ([modes/repro.md](../mobile-tester-shared/modes/repro.md): on a simulator the person clicks in Simulator.app, on a device they use it by hand), and whether to prepare Jira issues. Record each answer (`idt finding update`, `idt report confirm`).
7. Jira: each finding page has Copy title and Copy for Jira buttons, the `bugs/<id>.md` files are paste-ready, and `findings.csv` imports them all through Jira's CSV import. Create issues through the Atlassian connector only when the user explicitly approves each one.
8. Append what you learned about the app (screen map, quirks, what a fresh start shows: `reset.after`) to the app's profile and `notes.md`, after telling the user.
9. Answer with: where the report is, the findings by severity, known issues seen again, unconfirmed items, what was skipped as never done, and what was not covered.

## Manual checks, now or later

Whenever the user reports trying a finding by hand, in this session or a later one ("B3 reproduced 2 of 2", "couldn't get B5 on my iPhone"), record it:
`idt report confirm RUN B3 --result reproduced|not-reproduced --tries 2/2 --by "<their name>" [--device "..."] [--build "..."] [--note "..."]`.
It adds an entry to the finding's history, updates the manual count and the status (a reproduced Unconfirmed finding becomes Confirmed), and rebuilds the report.
Never record a manual check the user didn't report.

## Never done without the user

The full list and what grants can lift: "Never done" in [autopilot.md](../mobile-tester-shared/autopilot.md). In short:
- Payments and orders, outgoing messages/posts/reviews, account deletion/logout/password changes, accepting terms or consent, and the profile's `forbidden`: skipped and noted (autopilot) or asked (autopilot off), unless the plan granted it.
- Signing in to the user's real accounts (Apple ID, iCloud) on the simulator: ask.
- Anything that needs the user's Apple ID, signing certificates, team id or a prompt on the device (Trust, Developer Mode, trusting the developer): the user does it; ask and wait.
- On a personal device: installing, uninstalling, clearing app data and changing system settings, only with the plan's approval.
- Creating Jira issues.
