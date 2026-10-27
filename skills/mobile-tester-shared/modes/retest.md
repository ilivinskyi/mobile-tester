# Retest mode: check known issues on a new build

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Goal: for each open known issue of the app, a clear verdict on the new build: Fixed, Still reproduces, or Can't verify.

## Choose what to retest

1. `dt issues list --package PKG` lists the open known issues, with their regression test case files.
2. Default scope: every open issue that has a test case. The user may narrow it (one ticket, only Major and up, only issues fixed in this release).
3. Issues without a test case: offer to write one now from the issue's original finding (its run folder is in `seen`), or skip them as "Can't verify".

## Before running

- Read each test case. They start as drafts generated from the bug's steps: fix missing preconditions, exact labels and test data before running, and save the improvements.
- Check the build under test is the one the user expects (`dt app info PKG`), and note it in `session.json`.

## Run each case

Run the case like test-case mode, in human mode: reset to the start state as in "Start state" in the entry skill (`android-native-tester` or `ios-native-tester`) before each run, then set up its preconditions.
The case **passes when the bug no longer happens**: the expected result is shown and the "Bug behaviour" doesn't appear.
- Run at least twice. A bug that reproduced only sometimes needs as many runs as it originally took to show up (see its reproducibility).
- Record the result with the issue key, once all runs of the case are done:
  `dt report result RUN --case "K-3 <title>" --issue K-3 --result pass|fail|blocked --note "<N of M runs passed>"`.
  A fail needs `--finding` (write the finding first, below); recording the case again replaces the result.
  The report shows pass as **Fixed**, fail as **Still reproduces**, blocked as **Can't verify**.
- Still reproduces: write a finding for this session with `"known_issue": "K-3"` (steps from the case, evidence, a clip). It shows as "seen again".
- Something new and different broke on the way: write a normal new finding.

## Update the registry

After the user has seen the results (in autopilot right away):
- Fixed: `dt issues set K-3 --package PKG --status fixed --build "<version (code)>" --run <run folder name> --note "<N of M runs passed>"`.
- Still reproduces: leave it open; `dt issues sync RUN --package PKG` records the sighting.
- A fixed issue that comes back in a later session is reopened automatically by `dt issues sync`.

## Report

- The "Retest results" table drives the summary: how many fixed, still reproducing, not verifiable.
- `summary` names the issues that are still open and anything new that broke.
