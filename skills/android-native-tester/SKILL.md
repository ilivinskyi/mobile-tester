---
name: android-native-tester
description: Use when the user wants an Android app tested on a phone or emulator, in any words ("test the X app", "explore X for 15 minutes", "reproduce PROJ-12", "run these test cases", "check what's fixed in 1.2", "review the UI") or via /android-native-tester - exploratory testing, running test cases, reproducing a bug, reviewing UI and accessibility, or retesting known issues on a new build, with onboarding on first use and a standard QA report. Load it before touching the device; it reads the project config (auto mode, reports folder, tester).
argument-hint: "[explore|test-case|repro|ui-review|retest|memory] [ticket, app, APK or test-case file]"
---

# Android native tester

Runs one test session on an Android device and ends with the standard report.
Start from the user's request (in Claude Code, the command arguments: $ARGUMENTS).

**REQUIRED:** follow the `android-human-input` skill for every UI action, and use the `android-device` skill for `adt` commands.
`adt` is the mobile-tester Android command line: the `adt` command when it is installed (`uv tool install`, see the README), otherwise, in the Claude Code plugin, `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/adt.py"`.
Shared files (onboarding, interview, modes, auto mode, report standard, templates) are in the `mobile-tester-shared` skill, next to this one: `../mobile-tester-shared/`. In them, `dt` means `adt`.
Questions to the user: use your agent's question tool when it has one (AskUserQuestion in Claude Code), otherwise ask in chat as a short numbered list with the recommended option first.

## Session flow

Work through these phases in order and keep the user's task list in step with them.

### 1. Project setup

1. Run `adt doctor`. Stop and help the user if no device is ready.
2. Read `.mobile-tester/config.yaml` in the project.
   If it doesn't exist, run onboarding first: [onboarding.md](../mobile-tester-shared/onboarding.md).
3. Note whether auto mode is on. In auto mode, apply the defaults from [auto-mode.md](../mobile-tester-shared/auto-mode.md) instead of asking at the decision points listed there.
   Guardrails are never automatic.

### 2. Session interview

Ask the questions in [session-interview.md](../mobile-tester-shared/session-interview.md), skipping what the arguments or the config already answer.
End with a one-paragraph session plan (charter, mode, device, build, start state, time box, evidence) and wait for the user's go, unless auto mode is on.

### 3. Preparation

1. Device: `adt -s SERIAL info`. Check it matches the device inventory; note `personal: true` devices.
2. App profile: read `.mobile-tester/apps/<package>/profile.yaml` (above all its `about` block) and `notes.md`, and list the open known issues with `adt issues list --package PKG`. Quirks and known issues save time: a known issue found again is linked, not re-reported.
3. Build:
   - Installed: compare `adt app info PKG` with the version the user expects.
   - From a file: `adt apk inspect FILE`. Do not install when the signers differ between splits, the signer differs from `expected_signer_sha256` in the profile, the package name doesn't match, or notable permissions don't fit the app. Report what you found and ask.
   - Install with `adt --fast app install FILE` (setup step).
4. Hooks: run `adt hook setup --package PKG` when the profile defines it.
5. Start the session: `adt session start --package PKG --mode MODE --charter "..." [--ticket KEY] --record --logcat`.
   Without `--dir` the run folder is `<reports dir from config.yaml>/<YYYY-MM-DD>-<app>-<mode>[-<ticket>]`, a new one per session; it prints the folder.
   It also fills the title and the tester from the profile and config. Then fill `session.json` with ticket details, time box and app install source (see [report-standard.md](../mobile-tester-shared/report-standard.md)).
6. Ask whether to turn on "Show taps" for this recording (always ask; on a phone pass the approval to `adt touches on --approval`).
7. Performance baseline (unless the user turned it off): `adt perf startup PKG` (three cold starts, each after a force-stop), then `adt perf frames PKG --reset`.
8. Bring the app to the start state (below). This also logs in when the profile's login needs it.

### Start state

Every run that is compared with another starts from the same state: the session itself, each reproduction attempt, each test case, each retested known issue.
Use the strategy agreed in the interview (default: the profile's `reset.strategy`):

| Strategy | Command |
|---|---|
| `restart` | `adt app reset PKG --level restart` |
| `clear-data` | `adt app reset PKG --level clear-data`, then the login (secrets, login hook, or ask the user to log in on the device) |
| `hook` | `adt hook reset --package PKG` |
| `none` | nothing; check the state the user prepared |

Then do the profile's `reset.after` steps with `--fast`, and check the state you depend on with `adt observe --image-only` before the first step under test.
`adt app reset` adds itself to `setup_steps_fast`; add the other setup steps you ran yourself.
"a system permission dialog is on top" after a reset: answer it as `app_permission_prompts` says, as part of the setup.
Clearing app data on a personal device needs the user's yes from the interview; without it, fall back to `restart` and say so in `not_covered`.

### 4. Testing

Follow the mode guide:

| Mode | Guide |
|---|---|
| explore | [modes/explore.md](../mobile-tester-shared/modes/explore.md) |
| test-case | [modes/test-case.md](../mobile-tester-shared/modes/test-case.md) |
| repro | [modes/repro.md](../mobile-tester-shared/modes/repro.md) |
| ui-review | [modes/ui-review.md](../mobile-tester-shared/modes/ui-review.md) |
| retest | [modes/retest.md](../mobile-tester-shared/modes/retest.md) |
| memory | [modes/memory.md](../mobile-tester-shared/modes/memory.md) |

Judging behaviour:
- Expected behaviour comes from the app profile's `about` (description, main flows, rules, glossary), the ticket, and what the app itself says on screen. Nothing else defines "correct".
- Don't bring in checks that belong to a different kind of app. Test ideas follow this app's flows and rules, plus the universal ones (crashes, data loss, wrong or misleading messages, state that doesn't persist, accessibility, layout).
- When you can't tell whether something is a bug because the expected behaviour isn't described, ask the user (or, in auto mode, report it as an observation and write the open question in `notes`). Record any assumption you make in the finding.

Problems outside the charter (another screen, an unrelated feature):
- Never report anything in an area listed in the profile's `outside_scope.not_ready`, not even as an observation.
- If `outside_scope.report` is false, don't report them.
- If it's true (the default), write them as findings with `"scope": "outside"`. They get their own report section and don't count as bugs.
  Note what you saw and where; don't spend session time reproducing them unless they block the charter.

While testing:
- Write each finding into `findings.json` as soon as it's verified, not at the end. Fields and severity scale: [report-standard.md](../mobile-tester-shared/report-standard.md).
- Before writing a finding, check the raw source that proves it: `adt inspect --index N` for an element (never the whole `latest.xml`), the relevant logcat lines (search them, don't read the file whole), the screenshot. If a finding turns out wrong, set it to Retracted with the reason; never delete it.
- Save evidence with `adt observe --name <id>-<what>` and note the action log time for video clips.
- A finding that matches an open known issue (same behaviour in the same area): set `"known_issue": "K-n"` and keep it short; don't re-investigate. It shows as "seen again".
- `CRASH right after this action` in an action's output: the crash watch caught it at that step. Capture evidence (`adt observe`, `adt logcat crashes --package PKG`), write the finding at once with the step that triggered it, then follow the `crash_found` decision (default: restart the app and continue).
- `app log: N new issue(s)` in an action's output: the app logged errors or warnings (errors, caught exceptions, network failures, StrictMode, long frame drops, out of memory) right after that action. Many apps log harmless errors, so judge it: when it explains what you see, or it's an `OutOfMemoryError`, quote the line in the finding and save `logs/logcat.txt` as evidence; otherwise carry on. The wrap-up summary lists them all anyway.
- Watch the time box. Tell the user at the halfway point and when it runs out.

### 5. Wrap-up

1. Performance (if measured): `adt perf frames PKG` and `adt perf memory PKG` before ending the session. Then `adt logcat summary`: the app's log issues of the whole session, grouped, for the report's "App log" section.
2. `adt session end`: it stops capture and builds the report right away when `adt report check` passes (otherwise it lists what to fix). Run the teardown hook if the profile has one, and `adt touches off` if you turned it on.
3. Cut one clip per bug: `adt clip --from <t of first repro step> --to <t of last> --out videos/<id>.mp4`, and add it to the finding's evidence.
4. `adt issues sync RUN --package PKG`: new bugs and accessibility findings join the app's known issues (each with a regression test case draft in `.mobile-tester/apps/<package>/tests/`), and known issues seen again get a sighting.
5. `adt report check RUN`, fix every problem, then `adt report build RUN` (again: the steps above changed findings). Open `index.html` in a browser (the browser pane in Claude Code) and look at it; in auto mode `report_build` decides, and it never waits for a question.
6. For each Unconfirmed finding, offer the manual reproduction in [modes/repro.md](../mobile-tester-shared/modes/repro.md).
7. Offer Jira: each finding page has Copy title and Copy for Jira buttons, the `bugs/<id>.md` files are paste-ready, and `findings.csv` imports them all through Jira's CSV import. Create issues through the Atlassian connector only when the user explicitly approves each one.
8. Append what you learned about the app (screen map, quirks) to the app's `notes.md`, after telling the user.
9. Answer with: where the report is, the findings by severity, known issues seen again, unconfirmed items, and what was not covered.

## Manual checks, now or later

Whenever the user reports trying a finding by hand, in this session or a later one ("B3 reproduced 2 of 2", "couldn't get B5 on my Samsung"), record it:
`adt report confirm RUN B3 --result reproduced|not-reproduced --tries 2/2 --by "<their name>" [--device "..."] [--build "..."] [--note "..."]`.
It adds an entry to the finding's history, updates the manual count and the status (a reproduced Unconfirmed finding becomes Confirmed), and rebuilds the report.
Never record a manual check the user didn't report.

## Never automatic, never skipped

- Payments, outgoing messages/posts/reviews, account deletion/logout/password changes, accepting terms or consent: stop and ask.
- System-setting changes and clearing app data on a personal phone: ask.
- Installing a build that fails the checks in step 3.
- Creating Jira issues.
