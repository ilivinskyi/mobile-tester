# Autopilot

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Autopilot is this skill's setting, not your agent's permission mode (such as Claude Code's "auto mode", which approves tool calls).
Autopilot only skips the skill's own routine questions; whether the agent may write files or run commands is still decided by the agent's permissions.
When a tool call is blocked by those permissions, say so plainly and don't call it an autopilot problem.

With `autopilot.enabled: true` in `.mobile-tester/config.yaml`, the skill applies the defaults below instead of stopping to ask.
Record every decision taken automatically with `dt report decision RUN KEY VALUE --why "<what made it come up>"`.
It goes to `session.json` (listed under "Decided by autopilot" in the report's session details) and to the session's `logs/decisions.md`, so the report shows what was decided without the user.
With autopilot off, the skill asks at each of these points.

## Decision catalog

| Key | Comes up when | Default | Options |
|---|---|---|---|
| `keyboard_fallback` | `adt type` can't find a key (other keyboard, language, emoji). Android only: on iOS a missing key always asks | `keyevents` | `ask`, `keyevents` (one key event per character, noted in the finding), `bulk` |
| `app_permission_prompts` | The app under test asks for notifications, location, camera... | `deny` | `deny`, `allow`, `ask`. Testing the denied path is the stricter test |
| `consent_banners` | Cookie or tracking consent in the app | `reject_non_essential` | `reject_non_essential`, `ask`. Accepting consent is never automatic |
| `login` | The app offers login | `secrets_then_guest` | `secrets_then_guest`, `guest`, `ask` |
| `install_build` | A build file has to be installed | `install_if_verified` | `install_if_verified`, `ask`. A failed check always stops |
| `unconfirmed_repro` | A bug reproduces only through automation | `queue_manual_request` | `queue_manual_request` (ask at wrap-up), `ask_now`, `mark_only` |
| `crash_found` | The app crashes or shows an ANR | `capture_restart_continue` | `capture_restart_continue`, `ask` |
| `ambiguous_target` | Several elements match the step's target | `pick_and_log` | `pick_and_log` (most plausible visible one, logged), `ask` |
| `state_reset` | Before the session and each rerun (repro attempt, test case, retested issue) | `profile_strategy` | `profile_strategy` (the profile's `reset.strategy`), `restart`, `ask`. Clearing app data on a personal device still asks, once per session |
| `time_box_end` | The time box runs out | `wrap_up` | `wrap_up`, `ask` (offer to extend) |
| `show_taps_emulator` | Recording on an Android emulator | `ask` | `ask`, `on`. On physical devices "Show taps" always asks; iOS simulators have no such setting |
| `report_build` | End of session | `build_and_open` | `build_and_open`, `ask` |

## Never automatic

These always stop the session and wait for the user, whatever the config says:
- Purchases, payments, subscriptions.
- Sending messages, posts, reviews, invites, feedback.
- Account deletion, logout, password or email changes.
- Accepting terms, consent, or permissions on behalf of the user's accounts (OAuth, SSO).
- System-setting changes and clearing app data on a personal device.
- Installing a build that fails the authenticity checks.
- Creating or changing Jira issues.
- Deleting evidence or earlier reports.

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
    show_taps_emulator: ask
    report_build: build_and_open
```

A key missing from the config falls back to `ask`.
Older configs call this block `auto_mode:`: read it the same way, and rename it to `autopilot:` the next time you write the config.
Older configs may say `state_reset: run_reset_hook`: treat it as `profile_strategy` (a profile with a reset hook has `reset.strategy: hook`).
