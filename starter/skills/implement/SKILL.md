---
name: implement
description: Make the smallest change that satisfies the approved plan, ask the advisor at its checkpoints, and run the gates before handover.
---

# Implement

You work in the ticket's worktree, on the ticket's branch. The plan was approved; you carry it out. You publish
nothing yourself: a push and a pull request are intents (skill `open-pr`, and cockpit's own outbox skill).

## 1. Before the first edit

1. Read the plan: `cockpit plan show TASK-100`. Read the `Plan gate:` line on your card.
2. Read the code the plan names, and its callers. Find the existing test that covers it, or note that there is none.
3. Write your outline in a few lines: which files, in which order, and the test that will prove it.
4. Ask the advisor at checkpoint C0: `cockpit advise C0 "the outline"`.
5. With `Plan gate: human`, or when the advisor's answer holds the work, block your card for "plan ok" and wait.

Do not edit before C0 is answered. Do not widen the plan because the code nearby looks wrong: note it in your report.

## 2. The change

1. Write the failing test first when the code has tests. It must fail for the reason the plan names.
2. Make the smallest change that turns it green. Touch only the files the plan lists; a file outside the list needs
   a line in your report saying why.
3. Follow the code around you: its names, its error handling, its layout. A reviewer should not be able to tell which
   lines are yours by their style.
4. Commit in steps a reviewer can read, each with a message that says what changed and why. Sign nothing off that
   you did not run.

Do not reformat a file you did not need to change. Do not add a dependency, a configuration key or a migration the
plan did not name. Do not leave commented-out code, debug output or a skipped test.

## 3. The gates

The pack names each repo's test commands as its gates. Run them before handover, once, on the finished change.

```sh
cockpit gate --background
cockpit gate --wait <run id>
```

`--background` answers a run id at once; `--wait` ends with the gate's own exit code and lists the failures that are
new. When the base already fails before your change, record that first with `cockpit gate --baseline`, so later runs
name only what you broke. One repo of several: `cockpit gate --repo api`.

A red gate is yours to fix or to explain. A test that fails for a reason unrelated to your change goes in the report
with the evidence (it fails on the base too), never silently.

Do not start a second gate run while one is going. Do not hand over on a gate you did not see finish.

## 4. Before handover

1. Review your own diff with skill `self-review`. Fix what it finds.
2. Ask the advisor at checkpoint C2: `cockpit advise C2 "what changed, what was tested, what is left"`.
3. Something the plan did not foresee (a second cause, a file you may not touch, a decision only the human can make)
   is a block with one question, not a guess.
4. Finish with a report: the commits, the gate's result, each deviation from the plan, and what you did not verify.

Do not say "tested" for a path you only read. Do not complete the card while a checkpoint is unanswered.
