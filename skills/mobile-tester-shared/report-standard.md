# Report standard

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS. The report is the same on both platforms; only the device facts differ.

Every session produces one run folder.
`dt report check RUN` enforces the rules marked *(checked)*; `dt report build RUN` renders:
- `index.html`: the finding list, grouped by severity (then observations, findings outside the scope, and retracted ones), one row per finding (priority, status, short summary), with search and filters.
- `bugs/<id>.html`: one page per finding with Copy for Jira (the description in Markdown), Copy title and Copy wiki markup (Jira Server and Data Center) at the top, all fields, and phone-framed evidence with a viewer.
- `bugs/<id>.md`: Jira-ready drafts for bugs and accessibility findings that aren't retracted, including those outside the scope.
- `findings.csv`: the same findings for Jira's CSV import (Summary, Description in wiki markup, Issue Type, Priority, Labels).
Validation and the build live in `scripts/mobiletester/core/report.py`, the pages in `report_html.py`, the text formats in `report_text.py`; keep this file and them in sync.

```
RUN/
  session.json      session facts (dt session start writes the device and app parts)
  findings.json     {"findings": [...]}
  index.html        the finding list
  bugs/<id>.html    one page per finding
  bugs/<id>.md      one Jira-ready file per bug and accessibility finding
  findings.csv      Jira CSV import of the same findings
  screenshots/  videos/  logs/ (actions.jsonl, logcat.txt or app.log, decisions.md)
```

## session.json

| Field | Content |
|---|---|
| `title` *(checked)* | "<App name> <platform> - <mode>", e.g. "<App name> iOS - exploratory test"; `dt session start` sets it when missing |
| `platform` | `Android` or `iOS`; `dt session start` writes it (run folders without it are Android) |
| `subtitle` | version, device, date and duration in one line |
| `mode` *(checked)*, `charter` *(checked)* | from the interview |
| `ticket` | `{"key", "url", "summary"}` or a string |
| `tester` | from the config; `dt session start` sets it when missing |
| `started`, `ended`, `time_box_min` | `dt session start/end` write the times |
| `device` *(checked)* | written by `dt session start`: `model`, `os` ("Android 15 (API 35)", "iOS 27.0"), `kind` (physical, emulator, simulator), `screen`, `navigation`, `keyboard`, `locale`, plus the platform's raw facts |
| `app` *(checked)* | `package` (bundle id on iOS), `versionName` and `versionCode` (on iOS the marketing version and the build number), plus `install_source` ("Play Store", "file Foo.xapk, signer verified", "simulator build of ...") |
| `input` | how input was driven; `dt session start` writes "adt human mode" or "idt human mode (XCUITest touches)" |
| `setup_steps_fast` | steps run with `--fast`, e.g. `["install", "clear data"]`; `dt app reset` adds itself, the rest via `dt report add RUN setup_steps_fast` |
| `decisions` | autopilot decisions, written by `dt report decision`: `[{"time", "key", "value", "why"}]`; shown in the session details |
| `summary` | 3-5 sentences: overall state, the most serious problems, what needs attention |
| `test_results` | test-case mode: `[{"case", "step", "result": pass/fail/blocked/skipped, "finding", "note"}]`; fail/blocked need a finding or note *(checked)*. Retest mode adds `"issue": "K-n"`; the report then reads pass as Fixed, fail as Still reproduces, blocked as Can't verify |
| `performance` | Android: written by `adt perf`: `startup` (cold start median and samples), `frames` (janky %, percentiles), `memory` (PSS, RSS, live Activities, Views and other objects), `memory_trend` (a sample every 10 actions), `leak_samples` and `leaks` (memory mode: verdict per flow) |
| `log_summary` | Android: written by `adt logcat summary`: the app's errors and warnings in the session log, grouped (kind, tag, text, count, first time); shown as "App log" |
| `worked_well`, `coverage`, `not_covered` | lists of short sentences; `not_covered` is required reading for the reader, always fill it |
| `technical` | written by `dt report telemetry`: `agent` (name, version, models, effort, output style), `minutes` (total, onboarding, session, wrap_up), `tokens` and `tokens_by_model` / `tokens_by_phase` (requests, input, output, thinking, cache_read, cache_write_5m, cache_write_1h), `peak_context`, `cost_usd` (API list prices, by model and phase), `tool_calls`, `tool_errors`, `user_turns`, `device_actions`, `autopilot_decisions`, `findings`, `artifacts`; shown last as "Technical data", and one row per run goes to `<reports dir>/telemetry.csv` |
| `evidence` | `{"session_video": "videos/session.mp4", "logcat": "logs/logcat.txt" (or `"app_log": "logs/app.log"` on iOS), "action_log": "logs/actions.jsonl"}` |

## findings.json

```json
{"findings": [{
  "id": "B1",
  "title": "<Screen> stays blank after closing the sign-in page",
  "type": "bug",
  "status": "Confirmed",
  "severity": "Major",
  "priority": "P2",
  "area": "<Screen> / sign-in",
  "preconditions": ["Not signed in", "Chrome installed and set up"],
  "steps": ["Open \"<screen>\"", "Tap \"<control that needs sign-in>\"", "Close the sign-in page with X",
            "Go back to \"<screen>\""],
  "expected": "<Screen> shows its content again.",
  "actual": "Only the header and tab bar are shown; switching tabs doesn't help; restarting the app does.",
  "reproducibility": {"automated": "2/2", "manual": "1/1"},
  "evidence": [
    {"type": "screenshot", "path": "screenshots/b1-blank.png", "caption": "Blank Start tab"},
    {"type": "video", "path": "videos/b1.mp4", "caption": "Reproduction"}
  ],
  "notes": "",
  "jira": {"key": "", "url": ""}
}]}
```

| Field | Rule |
|---|---|
| `id` *(checked, unique)* | B1.. bugs, A1.. accessibility, O1.. observations, in the order found |
| `type` *(checked)* | `bug`, `accessibility`, `observation` |
| `status` *(checked)* | `Confirmed`, `Unconfirmed` (reproduced only by automation, or not reproducible on demand), `Retracted` (turned out wrong; `notes` says why *(checked)*) |
| `severity` *(checked for bug and accessibility)* | scale below |
| `priority` *(checked for bug)* | suggestion only, P1-P4; the team decides |
| `steps`, `expected`, `actual` *(checked for bug)* | `expected` and `actual` also for accessibility; observations need `actual` |
| `reproducibility` *(checked for bug)* | `automated` and/or `manual` as "N/M" or "not tried"; Unconfirmed must state `manual` *(checked)*; a Blocker/Critical/Major confirmed only by automation is rejected *(checked)* |
| `evidence` *(checked: files exist)* | `screenshot`, `video`, `log`, `xml`, `other`, paths relative to RUN |
| `scope` | `in` (default) or `outside`: noticed outside the charter. Outside findings need only `title`, `type`, `status` and `actual` (plus evidence), are listed separately, and don't count as bugs |
| `summary` | one line for the bug list; defaults to the start of `actual` |
| `known_issue` *(checked: K-n)* | key in the app's known-issues registry: set it yourself when a finding matches an open known issue (shown as "seen again"); `dt issues sync` sets it, plus `new_issue: true`, for newly registered ones |
| `history` *(checked: time, action)* | written by `dt report confirm` (manual checks) and retests: who, when, result, tries, build, device, status change, note; shown as a timeline |

## Severity

| Severity | Use when |
|---|---|
| Blocker | The app or a core journey can't be used at all: crash on launch, data loss, payment or privacy breach, testing can't continue. |
| Critical | One of the app's main flows (from the app profile's `about.main_flows`) is broken with no workaround, data is wrong in a way users rely on, or the app crashes in a main flow. |
| Major | An important function is broken or misleading but has a workaround (restart, other path); a screen reader user can't complete a flow. |
| Minor | Limited impact or easy workaround: layout overlaps, localisation errors, small accessibility issues such as undersized targets. |
| Trivial | Cosmetic: typos, alignment, colour nits. |

Priority suggestion: P1 fix before release, P2 next release, P3 planned, P4 backlog.
Base it on severity and how many users hit it (main journey vs. rare edge case).

## Writing findings

- Title: what goes wrong, where, and when, in one sentence. Not "X doesn't work". Example: "Entering 999 in a number field leaves it stuck at 0 with no message".
- Steps start from the preconditions, one action per step, exact labels in quotes, test data spelled out.
- Expected and actual are observable facts, not opinions.
- Reproducibility always says how it was driven: automated (`dt` human mode) and/or manual (a person).
- Evidence: the screenshot at the moment it goes wrong, the clip from the action log, and the log lines or crash report for crashes.
- Retract instead of deleting: a reader should see what was checked and why it was dropped.
- Never put credentials, personal data or tokens into findings; crop or mention it instead.
