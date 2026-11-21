---
name: pr-review
description: Review a pull request against its plan. Every finding has a severity, a file:line, and proof that it happens. The review is an intent the human submits.
---

# Review a pull request

You review; you never approve from a lane, and you never post to the forge. You write the threads and the summary to
files and file one intent. The human reads it as a pending review and submits it.

## 1. Get the shape

1. Read the pull request's description and the ticket's plan: `cockpit plan show TASK-100`.
2. Note the head commit you are reviewing. Every finding is about that commit, and the intent names it.
3. Read `git diff --stat <base>...<head>`, then the whole `git diff <base>...<head>`.
4. Read the threads that are already there. A point someone else made is not made again; a point the author answered
   is checked against the code, not against the answer.

Do not review a head you did not check out. Do not start from the description's claims: start from the diff.

## 2. What to look for

Read the diff once for each of these, in this order. Stop a pass early only when the file cannot be affected.

1. **Does it do what the plan says?** Each part of the plan's After has code. Nothing unplanned came along.
2. **Correctness.** Wrong conditions, off-by-one, a missing case, an error swallowed, a value used before it is
   checked, a race between two callers.
3. **Callers and contracts.** For every changed function, default, return shape and message: read its callers. A
   change that is right where it stands and wrong for a caller is the most common real defect.
4. **Data and access.** A read or write that is not scoped to its owner. A secret or a personal detail in a log or
   an error. A stored format that old data does not match.
5. **Tests.** Each behaviour of the plan has a test that would fail without the change. A test that only runs the
   code proves nothing.
6. **Readability.** Only where it will cost the next reader: a name that lies, a comment that contradicts the code,
   a function that does two things.

Do not comment on style a formatter owns. Do not ask for a refactor the ticket did not ask for.

## 3. Severity

Every finding carries one of four levels. Say the level first.

| Level | Meaning | What it asks |
|---|---|---|
| `blocker` | Wrong result, lost or exposed data, a broken contract, or the plan not met | Must change before merge |
| `major` | A defect on a path users reach, or a missing test for planned behaviour | Should change before merge |
| `minor` | A real but small problem: an edge case with a workaround, a misleading name | Change or answer |
| `question` | You could not tell. Ask one precise question | An answer |

Use the pack's own finding tags when it has them (its `finding_labels`); they mark a comment as a request for work.
A compliment, a preference or a "consider" is not a finding: leave it out, or put one line in the summary.

Do not inflate a level to be heard. Do not mark something a blocker that you have not reproduced.

## 4. A finding must manifest

Before a finding goes into the file:

1. Read the cited lines yourself, in the checked-out head. A summary of the code is not the code.
2. Name the condition under which it goes wrong, and find the caller or the input that produces that condition.
3. Make it happen where you can: a test, a command, a request on your slot. Keep the output for the thread.
4. If a guard elsewhere makes the condition impossible, there is no finding. If you could not decide, it is a
   `question`, and it says what you tried.

A finding is written so the author can act without asking back:

```
major: an export with no rows writes a file with no header.
`export/writer.py:88` returns before the header is written when `rows` is empty; `api/exports.py:41` calls it with
the result of an empty filter. Reproduced: `pytest tests/test_export.py -k empty` on this head fails with the
attached output. Expected: a file with the header row.
```

Do not write "this might break". Do not cite a line you did not open.

## 5. The threads file

The threads are a JSON list. One row per finding, each placed on a line of the diff:

```json
[
  {"path": "export/writer.py", "line": 88, "body": "major: an export with no rows writes a file with no header. ..."},
  {"path": "api/exports.py", "line": 41, "start_line": 37, "side": "RIGHT", "body": "question: ..."}
]
```

- `path` is the file's path in the repo. `line` is the line the thread ends on. `body` is the finding.
- `side` is `RIGHT` for the new version of the file (the default) and `LEFT` for a removed line.
- `start_line` (with an optional `start_side`) begins a thread that spans several lines.
- A line must be part of the diff. A finding about code the pull request did not touch goes in the summary, with
  its `file:line` in the text.

The summary is a second file: the verdict in one sentence, the count of findings per level, what you checked and
found sound, and what you did not check.

## 6. The intent

```sh
cockpit outbox new TASK-100 pr-review-submit --card <card id> --summary "review of the export change at <reviewed head>" --repo api --number 12 --sha <reviewed head> --threads-file review.json --body-file summary.md --event COMMENT
```

- `--sha` is the head you reviewed. If the pull request moves before the human submits, the review is refused and
  you review the new head.
- `--event` is `REQUEST_CHANGES` when there is a blocker or a major finding, and `COMMENT` otherwise. A lane never
  files `APPROVE`.
- Both files are copied beside the intent. Change a draft, then `cockpit outbox amend <intent id> --threads-file review.json`.
- Read it back with `cockpit outbox show <intent id>` and check it with `cockpit outbox verify <intent id>`.

Finish your card with the intent id, the reviewed head, and the findings per level.

Do not submit, approve or comment on the forge yourself. Do not file a review with no threads and no summary. Do not
repeat a finding in both a thread and the summary.
