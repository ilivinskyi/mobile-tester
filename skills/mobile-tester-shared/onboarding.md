# Onboarding

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Runs once per project, on the first `/android-native-tester` or `/ios-native-tester` when `.mobile-tester/config.yaml` is missing, or when the user asks to redo it.
One config serves both platforms: a project that already has it skips the parts that are done and only adds what the new platform needs (its devices, its app profiles).
Ask with your question tool (AskUserQuestion in Claude Code) or as a numbered list in chat, at most four questions at a time, recommended option first.
Write the answers into the files below as you go, so an interrupted onboarding keeps what it has.

## 1. Tester and team defaults

Ask:
- Tester name for reports (default: the user's name if known).
- Reports folder (default `reports/`) and report language (default English).
- Default time box for sessions (15, 30, 60 minutes).
- Jira: project key and site URL, or "no Jira".
  Tell the user that drafts are written as Markdown and issues are only created with explicit approval each time.
- Team-specific severity rules, if any, on top of the standard scale in [report-standard.md](report-standard.md).

## 2. Devices

Devices are saved once per user, not per project, in `~/.mobile-tester/devices.yaml`: every project folder on this computer knows them.
1. Run `dt devices`: each connected device shows how the list knows it (test device, personal device, or not saved yet).
2. Ask only about physical devices that are not saved yet: a short name, and whether it is a **personal** device or a test device.
   Personal devices get stricter guardrails: no system-setting changes, no clearing app data, no installing builds without asking.
   Test devices may change settings without asking (always restored at `session end`). Simulators and emulators are never personal.
3. Save each answer: `dt devices --save <serial or UDID> --name "<name>" --test` (or `--personal`).
   Run `dt -s DEVICE info` for the facts the report needs (navigation, keyboard); they don't go into the list.
   Android: if the keyboard isn't Gboard, warn that on-screen typing may need the fallback (see `keyboard_fallback` in autopilot).

## 3. App profiles

Ask whether to set up an app profile now (it can also be created at the first session for that app).
For each app, create `.mobile-tester/apps/<package>/` from the templates:
- `profile.yaml`: name, platform, package, store URL, expected signer (Android), login method, reset strategy (see "Start state" below), which hooks run when, risky areas,
  and the `about` block (see "Describe the app" below).
- `notes.md`: what testers learn over time (screen map, quirks, known issues, test accounts by name only). The app's purpose and rules belong in `about`, not here.
- `hooks/` and `checks/` with the example scripts, only when the user wants scripts.
- `secrets.local.yaml` only when the login method is `secrets`; the user fills it in themselves. Never ask for passwords in chat.

The same app on both platforms gets two profiles (package and bundle id usually differ); the second can copy the first one's `about` block after the user confirms the apps behave the same.

Android: to fill `expected_signer_sha256`, install the app from the store on a trusted device and inspect it later, or take the signer from a build the team trusts (`adt apk inspect`).

### Describe the app

This is the most important part of the profile: without it the model can only guess what correct behaviour is.
1. Ask an open question, not a multiple choice: "Describe the app and how it works: what it is for, who uses it, the main things people do in it, and the rules it must follow. Paste docs or links if you have them."
2. Put the answer in `about.description` in the user's own words; don't summarise it away.
3. Ask follow-ups only for what the answer leaves open, and fill the structured fields from it: `users`, `main_flows`, `rules`, `roles`, `integrations`, `not_in_scope`, `glossary`.
   Use the app's own terms; don't add flows or rules the user didn't mention.
4. Read back the main flows and rules in one short list and ask whether they're right.
5. If the user prefers not to describe it now, leave `about` empty. The first session then asks for it (see the session interview).

### Start state

Reruns are only comparable when each one starts from the same state.
Ask: "How should I bring the app back to a known start state before each run?" and save the answer as `reset.strategy`:
- **Clear data** (recommended when the login can be redone without the user: guest, secrets or a login hook): like a fresh install every time. Android clears the app's data; iOS reinstalls the `.app` that `idt app install` installed last (built-in iOS apps can't be reset this way). On a personal device it still asks first, once per session.
- **Restart**: stop and relaunch. Keeps data and login; choose it when the user logs in by hand or the data is slow to set up.
- **Script**: an app-specific reset hook that removes only what tests leave behind (e.g. items added to a list) and keeps the login. Copy `templates/hooks/reset.py` and set `hooks.reset`.
- **Never**: the user prepares the state by hand.

Then ask what a fresh start looks like (intro screens, region or language choice) and how to get past it, and save the steps in plain words as `reset.after`.
Anything that accepts terms or consent stays a guardrail: it is asked each time, never written into `reset.after`.

### Problems outside the session's scope

Sessions have a charter, but testers notice things elsewhere too. Ask two questions for each app:
1. "When I notice a problem outside the session's scope (another screen, an unrelated feature), should I report it?"
   Yes (recommended): it goes into a separate "Outside scope" section of the report, not counted as a bug, for the team to triage.
   No: such problems are not mentioned at all.
   Save as `outside_scope.report`.
2. "Are there screens or features that are still being built, which should never be reported even when they look broken?"
   Save the list in the user's own words as `outside_scope.not_ready`.

## 4. Autopilot

Ask: "Would you like autopilot? Then I won't stop at routine decisions and use the defaults you approve now."
- No: write `autopilot.enabled: false`. The skill asks at each decision point.
- Yes: show the whole catalog from [autopilot.md](autopilot.md) as one list (decision, default, options) and let the user change any default.
  Also show the "never automatic" list so it's clear what will still stop the session.
  Write `autopilot.enabled: true` and every decision with its chosen value.

## 5. Files and ignores

1. Write `.mobile-tester/config.yaml` from `templates/config.yaml`.
2. Offer to add these lines to the project's `.gitignore` (ask before editing it):
   ```
   .mobile-tester/state/
   .mobile-tester/**/secrets.local.yaml
   ```
   Reports may contain screenshots of personal data; ask whether `reports/` should be ignored too.
3. Summarise what was set up and continue with the session interview.
