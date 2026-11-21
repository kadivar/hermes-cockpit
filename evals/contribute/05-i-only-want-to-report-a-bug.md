# 05 · I only want to report a bug

## Prompt

> I found a bug but I have no time to fix it: `cockpit pack explain` on a key that does not exist prints a traceback instead of a message. Just report it for me. (The grader plants this fault.)

## Expected classification

triage → bug; mode `report`: one file under `tests/reports/` with one `known_bug` test. No fix.

## A good result has every one of these

- [ ] Exactly one new file, `tests/reports/test_<behaviour sentence>.py`, with one test and the marker's two texts (where, what).
- [ ] Ran the file and quotes the `BUG …` line of a green run.
- [ ] No change outside `tests/reports/`.
- [ ] Does not try to open an issue; the pull request's Kind is report.

## Any one of these fails the scenario

- Includes the fix.
- Uses a skip or a plain expected-failure mark instead of `known_bug`.
- Puts the test in `tests/`.
- The test errors (import, fixture) instead of failing its assertion.
