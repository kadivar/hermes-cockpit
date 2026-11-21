# The advisor

## Goal

A second opinion at named checkpoints of a worker's run: before it starts on a plan, before it hands over. The answer is
one of the words you allow, recorded with the plan, and a blocking answer stops the card for the human.

## The pack lines

In `pack.yaml`:

```yaml
roles:
  advisor: judgment              # the provider the advisor seat runs on
advisor:
  prompt: prompts/advisor.md
  max_calls: 3
  checkpoints:
    C0: {answers: [APPROVED, DEVIATES], block_on: [DEVIATES]}
    C1: {answers: [DONE, INCOMPLETE]}
  report_line: '^Advisor: \w+'
  report_on: [work]
```

`advisor` takes `command`, `prompt`, `max_calls`, `checkpoints`, `report_line`, `in_tool` and `report_on`.
`checkpoints` is required: each has `answers`, words in capitals, and optionally `block_on`, a subset of them.
`max_calls` is a whole number, 1 or more. `in_tool: true` needs `report_line`.

## The script contract

Implemented in `kernel/cockpitlib/advise.py`.

- **Default command:** `hermes --profile {profile} chat -Q --query-file {query_file}`: the advisor seat answers. Name
  `advisor.command` only to put something else in its place.
- **Arguments:** `{profile}` (the advisor seat), `{query_file}`, `{checkpoint}`, `{ticket}` and `{report_file}` are
  filled in. A relative first word with a `/` is a file beside `pack.yaml`.
- **The query file:** the pack's prompt (with `{{prompt:name}}` resolved), the checkpoint and the answers it may give,
  the ticket's plan, and the worker's note.
- **Environment:** the caller's without Hermes's board variables, plus `HERMES_QUIET_TURN_REPORT_FILE` (the report
  file's path).
- **Standard output:** the reply, unless the report file holds a JSON `reply`. The verdict is the first line that,
  after leading `#`, `*`, `>`, `-` and spaces, starts with one of the checkpoint's answers.
- **Exit codes:** 0 with a verdict is an answer. A non-zero exit, or a reply with no verdict, blocks the card for the
  human.
- **Time limit:** 900 seconds.
- **Limit:** past `max_calls` for a ticket the call is refused (`advisor limit: ...`). Every call counts, failed ones
  too.
- **Records:** `<records>/qa/<ticket>/advisor/calls.jsonl` and one file per call; a line in the plan; a comment on the
  card.
- **The report line:** with `report_line`, a worker's finishing report on the card kinds in `report_on` must carry a
  line that matches, or completing the card is refused.

`in_tool: true` is for an advisor that runs inside the coding tool: the worker passes the line it was given with
`--said`, and that line is what is recorded.

## A copy-paste example

A stand-in advisor, to see the contract before you give the seat a model. `bin/advise` in the pack folder (make it
executable):

```sh
#!/bin/sh
# usage: advise <query file> <checkpoint>   (approves a plan that names a test, questions one that does not)
if grep -qi "test" "$1"; then
  echo "APPROVED: the plan says how it will be tested"
else
  echo "DEVIATES: the plan names no test"
fi
```

```yaml
advisor:
  command: [bin/advise, "{query_file}", "{checkpoint}"]
  checkpoints:
    C0: {answers: [APPROVED, DEVIATES], block_on: [DEVIATES]}
```

## How to test it

```sh
cockpit pack check
cockpit advise C0 "starting on the export" --ticket TASK-100
# prints the call as JSON; exit 0 with a verdict, 1 without one
```

Then read `<records>/qa/TASK-100/advisor/calls.jsonl`. `cockpit advise` is a lane's command: run it for a ticket that
has a plan.
