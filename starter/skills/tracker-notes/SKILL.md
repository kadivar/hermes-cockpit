---
name: tracker-notes
description: Write a tracker comment that can be read cold, with its evidence attached, and send it as an intent the human publishes.
---

# Tracker notes

A comment on a ticket is read later, by someone who was not there. It must stand on its own. You write it to a file
and file an intent; you do not write to the tracker yourself.

## 1. The shape of a comment

1. **The verdict first,** in one line: what is true now. "Failed: 3 of 4 rows pass; the empty export has
   no header."
2. **What was done,** in a short list or a table: the rows run, the commits pushed, the question answered.
3. **What it means for the reader:** the one thing they should do next, or that nothing is needed.
4. **Evidence:** each file by name, next to the statement it supports.
5. **What was not checked,** plainly.

Keep it under a screen. Use the tracker's plain formatting: short paragraphs, a list, one table at most. Refer to
rows and files by the names the reader will see.

Do not paste logs or diffs: attach them. Do not write for yourself ("as discussed", "see above"). Do not report a
guess as a result.

## 2. Attachments

- Attach what proves a statement: a screenshot of a failed row, the recording of a failure, the exported file.
- Attach failures. A passed row's screenshot stays in the run folder unless the reader asked for it.
- An attachment lives under the workspace (a run folder, usually) and is named for what it shows:
  `3-no-rows.png`, not `screenshot-2.png`.
- Look at each file before you attach it. A secret, a personal detail or another customer's data in a screenshot is
  a reason to retake it.

Do not attach a file you have not opened. Do not attach from outside the workspace.

## 3. The intent

```sh
cockpit outbox new TASK-100 tracker-comment --card <card id> --summary "post the test results of run 1" --issue TASK-100 --body-file note.md --attach evidence/3-no-rows.png
```

- `--body-file` is the comment. `--issue` names the ticket when it is not the card's own.
- `--attach` is repeatable, one file each.
- The body is copied beside the intent. Change the draft, then `cockpit outbox amend <intent id> --body-file note.md`.
- Check it before you finish: `cockpit outbox show <intent id>`, then `cockpit outbox verify <intent id>`.

Put the intent id in your finishing report. After the human publishes, the comment's address is on the intent.

Do not file a second comment to correct the first while the first is unpublished: amend it. Do not move the ticket
to another status as a side effect; that is an intent of its own.
