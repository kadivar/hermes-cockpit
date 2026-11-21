---
name: open-pr
description: Ask for a push and a pull request by writing intents. The title and the body come from the commits. Read back what was made.
---

# Open a pull request

You do not push and you do not call the forge. You write two intents, the gatekeeper checks them, and the human
publishes them. Your part is to make them correct and easy to approve.

## 1. Before you ask

1. The gates ran green on the head you want pushed, or the report says exactly what is red and why.
2. Your own review is done (skill `self-review`).
3. `git status` is clean and `git log <base>..HEAD` shows only this ticket's commits.

Do not ask for a push of work in progress. Do not ask for a branch that holds someone else's commits without saying
so in the summary.

## 2. Title and body, from the commits

Read `git log --reverse <base>..HEAD` and `git diff --stat <base>...HEAD`. Write from them, not from memory.

- **Title:** the ticket key, a colon, and what the change does, in the present tense: `TASK-100: reject an empty
  export name`. Under seventy characters. No "fix", "update" or "changes" on their own.
- **Body,** in a file, in this order:
  1. **What and why.** Two or three sentences. Link the ticket.
  2. **How.** One bullet per commit or per area, each saying what changed.
  3. **Tested.** The gate's result, and each manual check with what you saw.
  4. **Not verified.** What you could not check, plainly.
  5. **Notes for the reviewer.** Where to look first, and any deviation from the plan.

Every statement in the body must be true of the pushed head. A body written before the last commit is rewritten.

Do not paste the diff into the body. Do not promise follow-up work without a ticket for it.

## 3. The intents

The push first, then the pull request for the same branch:

```sh
cockpit outbox new TASK-100 push-branch --card <card id> --summary "push the export name check" --repo api --branch work/TASK-100
cockpit outbox new TASK-100 open-pr --card <card id> --summary "open the pull request for the export name check" --repo api --branch work/TASK-100 --title "TASK-100: reject an empty export name" --body-file pr.md
```

- `--card` is your card's id. `--summary` says what the intent does and why, for the human who will approve it.
- `--base` names another target branch than the repo's own. `--labels a,b` sets labels. `--ready` opens it ready for
  review instead of as a draft.
- The body file is copied beside the intent. When you change the draft, amend:
  `cockpit outbox amend <intent id> --body-file pr.md`.
- The pull request is chained to the push it needs, so the two publish together, in order.

A missing or misshapen flag exits 2 and prints an example of the right form. Read it; do not retry blindly.

Do not write the intent's files by hand. Do not open a second intent for the same branch: amend the first.

## 4. Read back

1. `cockpit outbox show <intent id>` prints what was recorded. Compare the branch, the title and the body with what
   you meant.
2. `cockpit outbox verify <intent id>` runs the checks the gatekeeper will run. Fix what it names and amend.
3. Put both intent ids in your finishing report, with the head commit they carry.
4. After the human publishes, the pull request's address is on the intent. Read the pull request once: the title, the
   body as rendered, the target branch, the checks that started.

A push records the branch's tip when you write it. When you commit again, amend the push intent, or it will publish
the older head.

Do not report a pull request as open before it is published. Do not answer review comments on the forge yourself:
replies are intents too.
