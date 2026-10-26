# Session plan

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Every session starts here (after onboarding, the first time). It ends with one question, and after Go the session runs without stopping until the wrap-up (see [autopilot.md](autopilot.md)).

## 1. What to test

- **When the request already says it** (the app and what to do: "explore Jumbo for 30 minutes", a ticket, a test-case file, "check what's fixed in 1.2"): ask nothing and go to the plan.
- **Otherwise** ask one open question: "What should I test this time?"

Fill in the rest from the answer, the app profile, the config and the device list:

| Item | From |
|---|---|
| App | the name or package: `dt app find "<what the user typed>"`. One `match:` is confirmed in the plan; several candidates or none are a gap (pick one, or install a build from a file) |
| Ticket | a key or URL in the request: read it with Jira tools when available (summary, description, acceptance criteria); otherwise the user's paste |
| Mode | explore by default; repro for a bug ticket; test-case for a test-case file; retest when they mention a new build with fixes; memory for leaks or slowness over time; ui-review for layout or accessibility |
| Charter | the ticket, or what they asked for; for explore without either, the first entries of `about.main_flows`. `about.not_in_scope` is always out |
| Device | the only ready one, else a saved test device; a personal phone only when it's the only choice or they asked for it |
| Build | installed when a matching version is; a file path in the request means installing it |
| Login, start state | the profile's `login` and `reset.strategy` |
| Time box | from the request, else the config's default |
| Extra checks | what they asked for, plus the mode guide's usual ones (explore: offline, the app killed in the background, a permission taken away; ui-review: font size, dark mode, landscape, RTL) |
| Telemetry | on when they asked for numbers or it's a benchmark run, else the config's default (off) |

A missing `about.description` in the profile is a gap: ask the first onboarding question ("What is your app about?") and save the answer.
Gaps go into one round of at most four questions, before the plan.

## 2. The plan

Show it as a short block, values inferred rather than given marked with "(assumed)":

- **App and build:** name, package, version, installed or from a file.
- **Device:** name, test device or personal phone, emulator or simulator.
- **Mode, charter, time box.**
- **Start state and login:** reset strategy, login method.
- **Evidence:** screen recording, the app log, crash watch, performance (Android), "Show taps" on a test device or emulator.
- **Extra checks:** offline, background kill, permissions, config stress, links.
- **Never done:** the standard list in [autopilot.md](autopilot.md) plus the profile's `forbidden`; reaching one is skipped and noted in the report.
- **Allowed this session:** the profile's `grants`, and any new ones from the request.
- **Needs your yes (personal phone only):** every system change the plan would make (offline, font size, dark mode, "Show taps", clearing app data, installing a build). On a test device or emulator this line is left out: nothing there needs a yes.
- **Questions:** asked only if testing can't go on without the answer; everything else is collected and asked at the end.
- **Telemetry:** on or off. **Files:** the `.gitignore` lines, on the first session.

Then one question with four options:
1. **Go:** the plan, its approvals and grants count as the user's yes for this session. Start.
2. **Add notes:** free text that changes the plan (focus, things to skip, extra checks, grants). Update the plan, show it again with the same four options.
3. **Cancel:** stop here. Touch neither the device nor the run folder.
4. **Restart:** drop the plan and ask "What should I test this time?" again (on the first session: the three onboarding questions).

With autopilot off, every later decision asks as before; the plan still comes first.

## 3. After Go

Start the session and write the plan into the run, so the report shows what was agreed:
- `dt report set RUN charter|ticket|time_box_min|install_source VALUE`
- `dt report add RUN forbidden "<action>" ...`, `dt report add RUN grants "<action>" ...`, and on a personal phone `dt report add RUN approvals "<system change>" ...`
- Add the `.gitignore` lines when the plan listed them.

Pass approvals to the tools as `--approval "session plan: <what was approved>"`; they count only for this session.
