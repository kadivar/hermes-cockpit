---
name: self-review
description: Review your own diff against the plan before anyone else reads it. A finding counts only when you have shown it happens.
---

# Self-review

Read your change as a stranger would, before you ask for a push. The reviewer's time is for what you could not see,
not for what a checklist would have caught.

## 1. Get the whole diff

1. Find the base the pull request will target (the repo's base branch in the pack).
2. Read `git diff --stat <base>...HEAD`, then the full `git diff <base>...HEAD`. Read every hunk, including the ones
   you think you remember.
3. Read the plan again: `cockpit plan show TASK-100`.

Do not review from memory. Do not review only the last commit.

## 2. The checklist

Go through the diff once per question. Write down each thing you notice with its `file:line`.

**The plan**
- Does every part of the plan's After have code and a test? Name the line for each.
- Is there a change the plan did not ask for? Remove it, or justify it in the report.

**Behaviour**
- What happens with no input, an empty list, a missing key, a zero, a very long text, two calls at once?
- Does an error reach the caller with a message that says what to do, or is it swallowed?
- Is anything read from outside (a request, a file, an environment variable) used without a check?
- Did a default, a limit or an order change for callers you did not touch? Search for each one.

**Data and access**
- Does the change read or write data of another user, tenant or project? Show the line that scopes it.
- Does a secret, a token or a personal detail reach a log, an error message or a test fixture?
- Is a schema or stored format changed? Then old data, and a rollback, need an answer.

**Tests**
- Does each new test fail without the change? Revert the fix locally and watch it fail, then put the fix back.
- Does a test assert the behaviour, or only that the code ran?
- Did you delete or loosen a test? Say why in the report.

**Leftovers**
- Debug output, commented-out code, a TODO without an owner, a skipped test, a file you did not mean to add.
- Names that describe the old behaviour. Comments and documentation that now lie.

## 3. A finding must manifest

A line that looks wrong is a suspicion. It becomes a finding when you have shown what goes wrong.

1. State the condition: the input, the state and the caller under which the line misbehaves.
2. Check that the condition can happen: find a caller that passes that input, or a path that reaches that state.
   A guard two frames up that makes it impossible ends the suspicion; note the guard's `file:line`.
3. Make it happen: a test, a command, or a request against your slot. Keep the output.
4. Only then write it down as a finding, with the reproduction.

A suspicion you could not make happen is reported as exactly that, in one line, with what you tried. It is not fixed
"to be safe": a defensive change for a case that cannot occur is noise the next reader must understand.

Do not report a mechanism ("this could be null") without the path that makes it so. Do not fix a finding you have
not reproduced.

## 4. Act on what you found

1. Fix each finding in its own commit, with a test where the code has tests.
2. Run the gates again when you changed code: `cockpit gate --background`, then `cockpit gate --wait <run id>`.
3. Record the outcome in the plan: `cockpit plan append TASK-100 Reviewed "what you found and fixed, what stands"`.
4. List in your report: the findings fixed, the suspicions that did not manifest, and the checklist questions you
   could not answer.

Do not hand over with a known finding left unreported. Do not write "reviewed, clean" without the list of what you
checked.
