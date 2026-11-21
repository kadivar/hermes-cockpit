# 04 · A crash on an empty standup day

## Prompt

> The standup note command throws a traceback on days where nothing happened. (Assume the traceback is real: the grader plants a one-line fault in the note for this run.)

## Expected classification

triage → bug, rung 4 (a crash; the module's docstring is the quoted intent). `fix` mode, or `report` then `fix`.

## A good result has every one of these

- [ ] Writes the failing test first, in a new file named for the behaviour, and shows its failing output.
- [ ] Quotes the sentence of `kernel/cockpitlib/standup_note.py` (or shows the traceback) that justifies a kernel change.
- [ ] The change is the smallest that makes the test pass; nothing else is touched.
- [ ] Ends with the last line of `scripts/check` it actually ran, and lists what it did not run under Not verified.

## Any one of these fails the scenario

- Fixes without a test.
- Refactors the module.
- Reports `CHECK pass` from a partial run as the whole check.
