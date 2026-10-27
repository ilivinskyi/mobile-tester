# Test-case mode: run written test cases

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Goal: execute given test cases step by step and report pass/fail per step, with findings for every failure.

## Input

Markdown test cases, one or more per file (format: `templates/test-case.md`):
a title and ID, preconditions, numbered steps, and an expected result per step or per case.
When a case is ambiguous (which button, which data), look for the answer in the app profile's `about` (rules, glossary) first.
If it's still unclear, ask before running it, or in autopilot choose the most plausible reading and write it in the result's `note`.

## Run each case

1. Reset to the start state as in "Start state" in the entry skill (`android-native-tester` or `ios-native-tester`), then establish the case's preconditions with `--fast` setup steps, and verify them with a screenshot.
2. For each step:
   - Perform it in human mode.
   - Check its expected result: screenshot plus the hierarchy when text or state matters. Never assume a step passed because the command succeeded.
   - Record the result with `dt report result RUN --case "<case>" [--step N] --result pass|fail|blocked|skipped`: a fail needs `--finding B2` (write the finding first), a blocked one `--note "<why>"`.
     Recording the same case and step again replaces the earlier result, so a rerun gives the final word.
3. On a failure: capture evidence, write the finding (steps from the case, expected from the case, actual as observed), then decide with the user (or autopilot) whether to continue the case, skip to the next one, or stop.
4. A failure seen only once: reset, rerun the case from its preconditions before reporting it as a bug; record N of M.

## Report extras

- `test_results` drives the "Test results" table.
- `summary` states passed / failed / blocked counts and the cases that matter most.
