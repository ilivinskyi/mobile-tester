---
name: mobile-tester-shared
description: Shared reference files of the android-native-tester and ios-native-tester skills (onboarding, session interview, test modes, autopilot, report standard, templates). Not used on its own - when the user wants an app tested, load android-native-tester (Android) or ios-native-tester (iOS) instead.
---

# mobile-tester shared files

The two entry skills, `android-native-tester` and `ios-native-tester`, run test sessions and link here for everything that is the same on both platforms.
Don't start a session from this skill: load the entry skill for the platform, which reads the project config and drives the session.

In these files, `dt` stands for the platform's device tool: `adt` on Android, `idt` on iOS.
Both take the same command names and options where the platform has the concept; the entry skill and its device skill list the differences.
"Package" means the Android package name or the iOS bundle id.

| File | Content |
|---|---|
| [onboarding.md](onboarding.md) | First use in a project: tester, devices, app profiles, start state, autopilot |
| [session-interview.md](session-interview.md) | The questions at the start of every session |
| [autopilot.md](autopilot.md) | Decisions autopilot takes, and what is never automatic |
| [report-standard.md](report-standard.md) | Run folder, `session.json`, `findings.json`, severity, writing findings |
| [modes/](modes/) | explore, test-case, repro, ui-review, retest, memory |
| [templates/](templates/) | config, app profile, notes, test case, hook and check examples |

Project files live in `.mobile-tester/` in the project folder: `config.yaml`, `apps/<package>/` (profile, notes, known issues, hooks, checks, tests), and `state/` (device state, not committed).
