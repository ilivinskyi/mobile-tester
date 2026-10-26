# Session interview

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Asked at the start of every session, after onboarding.
Ask with your question tool (AskUserQuestion in Claude Code) or as a numbered list in chat, at most four questions at a time, recommended option first.
Skip a question when the command arguments, the config, or the app profile already answer it.
In autopilot, ask only the questions marked **always**; the rest take the defaults shown.

## Questions

1. **What are we testing?** (always, unless given as an argument)
   The app by name or package (bundle id on iOS), or a build file: APK, XAPK or APKS on Android, a simulator `.app` on iOS.
   For a name or package, run `dt app find "<what the user typed>"`:
   - `match:` with one app: confirm it in one line ("Testing Gmail, com.google.android.gm 2026.09.28") and continue.
   - Several candidates: show the numbered list (name, package, version or kind) and let the user pick.
   - No match: say so, and ask whether the app needs to be installed from a file or the store first.
   Match the package to an app profile; offer to create one if missing.
   **If the profile has no `about.description`** (always, even in autopilot): ask the user to describe the app and how it works, as in "Describe the app" in [onboarding.md](onboarding.md), and save it to the profile.
   If they decline, write in `session.json` `not_covered` that expected behaviour was inferred without an app description.
2. **Ticket and context.** (always)
   A Jira key or URL, or "no ticket".
   - If Atlassian (Jira) tools are available in this session, read the ticket: summary, description, acceptance criteria, attachments list.
   - If the connector exists but isn't authorized, tell the user to authorize it via `/mcp`, and meanwhile ask them to paste the description.
   - Otherwise ask the user to paste the description.
   Also ask for any extra context: what changed in this build, known risks, what the developer is worried about.
3. **Mode.** Default: explore, or repro when the ticket is a bug report, or test-case when a test-case file was given, or retest when the user mentions a new build with fixes ("check what's fixed in 1.2"), or memory when the user asks about leaks, memory growth or the app getting slower over time.
4. **Charter and focus.** What to cover and what is out of scope. Default: derived from the ticket; for explore without a ticket, the first entries of `about.main_flows`. `about.not_in_scope` is always out of scope.
5. **Device.** Default: the only ready device (booted simulator on iOS), or the inventory's non-personal one.
   Mention when the chosen device is personal (stricter guardrails) and when an emulator or simulator would be better (config stress, data clearing).
6. **Build.** Is the build to test already installed (default when a matching version is installed) or should it be installed from a file?
7. **Login state.** Default from the profile: secrets file, guest, or the user logs in on the device before the session.
8. **Time box.** Default from the config.
9. **Evidence.** Screen recording, the app log (logcat on Android, the unified log on iOS) and the crash watch are on by default; on Android also performance numbers (cold start, rendering, memory). "Show taps" (Android) is asked separately in preparation.
10. **Start state.** Reset the app before the session and before every reproduction attempt, test case or retested issue? Default: the profile's `reset.strategy` (restart when the profile has none).
    Options: the profile's strategy, restart only, or keep the current state (the user prepared it by hand; `none` for this session).
    **Always** ask when the strategy is clear-data on a personal device: clearing needs an explicit yes, valid for this session.
    If the profile has no `reset` block, ask as in "Start state" in [onboarding.md](onboarding.md) and save the answer.
11. **App scripts.** Run the profile's setup hook (default yes when it exists). Offer to add scripts when the user describes a repeatable setup they do by hand.

## Session plan

Summarise in one paragraph, then wait for a go (in autopilot, continue right away):
charter, mode, app and build, device, login state, start state, time box, evidence, hooks, ticket.
Write the same values into `session.json` after `dt session start`.
