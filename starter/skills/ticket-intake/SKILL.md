---
name: ticket-intake
description: Read a ticket end to end, separate what it claims from what you can show, reproduce it, write the plan, and stop for go.
---

# Ticket intake

A ticket is a report, not a specification. Its author saw a symptom and guessed a cause. Your job is to find out what
is true, say what will change, and wait. You do not edit product files and you do not publish.

## 1. Read everything

1. Read the description, every comment, every attachment, and every linked ticket. Read them in order: a later comment
   often withdraws an earlier one.
2. Open each link the ticket gives. A link you cannot open is a fact for the plan ("the trace it links is gone"), not
   a reason to guess what it said.
3. Note who said what and when. A claim by the reporter, a claim by a developer and a claim by a log are three
   different kinds of evidence.

Do not start reading code before you have read the whole ticket. Do not skip a long comment thread.

## 2. Separate claims from evidence

Write a table before you form a view. One row per claim the ticket makes.

| # | Claim | Who | Evidence in the ticket | Verdict | How you checked |
|---|---|---|---|---|---|
| 1 | Saving an empty form returns a 500 | reporter | screenshot | confirmed | reproduced on the slot, step 3 below |
| 2 | "It is the validator added last month" | developer | none | not confirmed | the validator is not on this path: `forms/save.py:41` |

Verdicts are `confirmed`, `not confirmed`, `false`, or `could not check` with the reason. A technical explanation in a
ticket is a hypothesis until you have checked it. "Could not check" is an honest verdict; a guess is not.

Do not copy the ticket's diagnosis into the plan as fact. Do not mark a claim confirmed because it sounds right.

## 3. Reproduce

1. Reproduce the symptom on your slot or in the ticket's worktree, with the smallest input that shows it.
2. Write the exact steps, the result you expected, and the result you got. Keep the command output or the screenshot.
3. Trace the symptom to the code: the entry point, the path through it, and the line where the behaviour goes wrong.
   Cite every step as `file:line`.
4. Change one thing to prove the cause: an input that avoids the line, or a temporary test that fails for the reason
   you name. Remove what you added.

A defect you cannot reproduce is not planned as if you had. Say what you tried, what you saw instead, and what you
would need (data, an account, a build) to try again. That is a complete intake.

Do not reproduce against production. Do not leave a temporary test or a debug line in the worktree.

## 4. Write the plan

The plan has six parts, in this order: brief, impacted areas, before, after, files, plan gate.

- **Brief.** Two or three sentences: the real defect or the real request, in your words, with the claims table's
  outcome ("the ticket blames the validator; the cause is the missing default in `forms/save.py:41`").
- **Impacted areas.** What a user or another system sees change, and what must not change.
- **Before.** What happens today, with the reproduction steps.
- **After.** What will happen, as checks someone else can run.
- **Files.** Each file you expect to touch, and why. Name the repo of each.
- **Plan gate.** `auto` when the change is small, local and covered by a test; `human` when it touches data, access,
  money, a public contract, or more than you could verify.

Write the plan to a file and record it:

```sh
cockpit plan init TASK-100 --file plan.md
cockpit plan show TASK-100
```

Add a part later with `cockpit plan append TASK-100 Reviewed "what the review changed"`. List the parts a plan
already has with `cockpit plan sections TASK-100`.

Keep the plan short. A reader should be able to decide on it in two minutes. Put the claims table and the
reproduction under Before, not in a separate document.

Do not plan a refactor the ticket did not ask for. Do not write "investigate further" as a step: investigate now, or
say what blocks you.

## 5. Stop for go

1. Block your card with the question you need answered: go, go with changes, or stop.
2. Wait. Do not start the work while you wait, and do not ask a second question in the same block.
3. After go, write the breakdown, one row per repo the plan touches, and hand it over:
   `cockpit flow decompose TASK-100 breakdown.json`.
4. Complete your card with the plan's path and the verdict of each claim.

Do not treat silence as go. Do not change the plan after go without saying what changed and asking again.
