# Autopilot

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Autopilot is this skill's setting, not your agent's permission mode (such as Claude Code's "auto mode", which approves tool calls).
Autopilot only skips the skill's own routine questions; whether the agent may write files or run commands is still decided by the agent's permissions.
When a tool call is blocked by those permissions, say so plainly and don't call it an autopilot problem.

With `autopilot.enabled: true` in `.mobile-tester/config.yaml` (the default), the session plan's **Go** is the last question until the wrap-up.
Everything after it follows the plan and the defaults below:
- **Decisions** in the catalog take their configured value. Record each with `dt report decision RUN KEY VALUE --why "<what made it come up>"`: it goes to `session.json` (under "Decided by autopilot" in the report) and to `logs/decisions.md`.
- **Never done** (below): skipped, never asked about. Note it with `dt report add RUN not_covered "<what was skipped and where>"` and a `never_done` decision, then test something else.
- **Grants** from the plan (`dt report add RUN grants ...`) lift a never-done item for this session only.
- **Approvals** from the plan cover system changes on a personal phone for this session; a change that wasn't approved is skipped and noted like a never-done item. Test devices and emulators need none.
- **Questions** are asked mid-run only when testing can't go on at all: the device disconnected, the app won't install or start, a login only the user can do. Everything else is collected with `dt report add RUN open_questions "<question>"` and asked once at the wrap-up: unclear expected behaviour (also written as an observation), manual reproductions, Jira.

With autopilot off, the skill asks at each decision point, and a never-done item stops and asks instead of being skipped.

## Decision catalog

| Key | Comes up when | Default | Options |
|---|---|---|---|
| `keyboard_fallback` | `adt type` can't find a key (other keyboard, language, emoji). Android only: on iOS a missing key always asks | `keyevents` | `ask`, `keyevents` (one key event per character, noted in the finding), `bulk` |
| `app_permission_prompts` | The app under test asks for notifications, location, camera... | `deny` | `deny`, `allow`, `ask`. Testing the denied path is the stricter test |
| `consent_banners` | Cookie or tracking consent in the app | `reject_non_essential` | `reject_non_essential`, `ask`. Accepting consent is never done |
| `login` | The app offers login | `secrets_then_guest` | `secrets_then_guest`, `guest`, `ask` |
| `install_build` | A build file has to be installed | `install_if_verified` | `install_if_verified`, `ask`. A failed check is never installed |
| `unconfirmed_repro` | A bug reproduces only through automation | `queue_manual_request` | `queue_manual_request` (ask at wrap-up), `mark_only` |
| `crash_found` | The app crashes or shows an ANR | `capture_restart_continue` | `capture_restart_continue`, `ask` |
| `ambiguous_target` | Several elements match the step's target | `pick_and_log` | `pick_and_log` (most plausible visible one, logged), `ask` |
| `state_reset` | Before the session and each rerun (repro attempt, test case, retested issue) | `profile_strategy` | `profile_strategy` (the profile's `reset.strategy`), `restart`. Clearing data on a personal phone needs the plan's approval |
| `time_box_end` | The time box runs out | `wrap_up` | `wrap_up`, `ask` (offer to extend) |
| `show_taps` | Recording starts | `test_devices` | `test_devices` (on for test devices and emulators; on a personal phone only when the plan approved it), `off`. iOS has no such setting |
| `report_build` | End of session | `build_and_open` | `build_and_open`, `ask` |

## Never done

Whatever the config says, these are never done by autopilot; with autopilot off they stop and ask:
- Purchases, payments, subscriptions, placing orders.
- Sending messages, posts, reviews, invites, feedback.
- Account deletion, logout, password or email changes.
- Accepting terms, consent, or permissions on behalf of the user's accounts (OAuth, SSO).
- System-setting changes and clearing app data on a personal phone, unless the plan approved them.
- Installing a build that fails the authenticity checks.
- Creating or changing Jira issues.
- Deleting evidence or earlier reports.
- Anything in the app profile's `forbidden` list.

A grant in the plan can lift one of the first four items, or one of the profile's own, for that session (for example "logging out and back in is fine").
It never lifts the others: personal-phone changes need an approval, failing builds are never installed, Jira issues are created only with a yes per issue, evidence is never deleted.

## Config shape

```yaml
autopilot:
  enabled: true
  decisions:
    keyboard_fallback: keyevents
    app_permission_prompts: deny
    consent_banners: reject_non_essential
    login: secrets_then_guest
    install_build: install_if_verified
    unconfirmed_repro: queue_manual_request
    crash_found: capture_restart_continue
    ambiguous_target: pick_and_log
    state_reset: profile_strategy
    time_box_end: wrap_up
    show_taps: test_devices
    report_build: build_and_open
```

A key missing from the config takes the default above.
Older configs call this block `auto_mode:`: read it the same way, and rename it to `autopilot:` the next time you write the config.
Older configs may say `state_reset: run_reset_hook` (read it as `profile_strategy`; a profile with a reset hook has `reset.strategy: hook`) and `show_taps_emulator` (read `ask` as `test_devices`).
