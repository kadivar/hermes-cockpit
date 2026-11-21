# Bug reports

This project takes no issues. A bug report is a pull request that adds **one failing test** to this folder. The test
states the rule the code breaks today; whoever fixes the bug makes it pass.

## File a report

1. Ask your coding assistant to follow `.agents/skills/contribute/SKILL.md` in `report` mode, or do it by hand:
2. Add one file here, named for the behaviour: `test_<behaviour sentence>.py`, for example
   `test_an_empty_day_still_gives_a_standup_note.py`. One report per file.
3. Write the test as the rule that should hold, with a plain `assert`, and mark it:

   ```python
   import pytest


   @pytest.mark.known_bug("kernel/cockpitlib/standup_note.py:120", "a day without records raises instead of an empty note")
   def test_an_empty_day_still_gives_a_standup_note(bare):
       from cockpitlib import standup_note
       ...
       assert note.startswith("# Standup")
   ```

   The first text is where the bug is (`file:line`), the second is what happens today, in one sentence.
4. Run `scripts/check --only structure` and then the file itself: `TEST_WORKERS=0 scripts/test tests/reports/<file>`.
   The run must print `BUG <test id> (<where>): <what>` and end green. Paste that line into the pull request.
5. Open the pull request with the template's Kind set to `report`. Do not include a fix: a report and a fix are two
   pull requests, so the report can be merged the day it arrives.

## What the marker does

- The test's own `assert` fails: the run stays green and prints the `BUG` line. That is an open report.
- The test passes: the run **fails** and says the bug is fixed. Remove the marker and move the file into `tests/`,
  where it guards the fix from then on.
- Anything else goes wrong (an import, a fixture, a typo, any exception that is not a failed `assert`): the run fails
  like any broken test. A report that cannot run reports nothing.

The marker lives only in this folder, and every test in this folder carries it; a structural test checks both.

## See what is open

```sh
scripts/check --reports
```

It lists every open report with its place and sentence. That list is this project's bug tracker.

## Rules for a report

- Generic names only: `TASK-100`, `example.test`. Never a real ticket, host, company or person.
- Use the `bare` or `env` fixture from `tests/conftest.py`; never read the machine's own installation.
- Where the pack matters, run the test over both fixture packs (`tests/support/both_packs.py` has `PACKS`).
- A security problem is never reported here. See `SECURITY.md`.
