---
name: outbox
description: Write an intent instead of pushing, opening a pull request, or posting. The human publishes.
---

# Outbox

Do not push, open pull requests, comment, review, or write to the tracker yourself. Write an intent. The gatekeeper
checks it, and the human publishes it.

```sh
cockpit outbox new <ticket> <type> --card <card id> --summary "<what and why>" [payload flags]
cockpit outbox amend <intent id> [--summary "<what changed>"] [payload flags]
cockpit outbox show <intent id>
cockpit outbox verify <intent id>
```

A missing or misshapen flag exits 2 and prints an example of the right form. Drafts you name with `--body-file`,
`--threads-file` or `--patch-comments` are copied beside the intent, so edit the draft and `amend` when it changes.
Attachments (`--attach`, repeatable) stay where they are and must live under the workspace.

| Type | Flags |
|---|---|
| `push-branch` | `--repo --branch` · `--rebase-only` for a pure rebase pushed on its own, then the content push `--after` it |
| `open-pr` | `--repo --branch --title --body-file` · `--base --labels a,b --ready` |
| `pr-edit` | `--repo --number` and any of `--base --title / --title-append --body-file --labels --add-labels --remove-labels --assignee me --ready` · `{key}` in a title takes the key of `--issue-from <the tracker-create intent>` at publish |
| `pr-patch-apply` | `--repo --number --branch --threads-file <manifest>`: the push, then one row per judged thread |
| `pr-comment` | `--repo --number --body-file` · a thread reply: `--in-reply-to <comment id> [--thread <node id> --resolve] [--react]` |
| `pr-review-submit` | `--repo --number --sha <reviewed head> --threads-file --body-file --event` · add to your pending review: `--review-id` |
| `tracker-comment` | `--body-file` (`.json` is a ready document) · `--issue --attach --probe-title --comment-id --comment-from` |
| `tracker-create` | `--summary` · `--body-file --labels --component --sprint active --assignee me --transition` |
| `tracker-transition` | `--to` · `--issue` or `--issue-from <the tracker-create intent>` · `--assignee me` |
| `ci-rerun` | `--repo --run-id <the failed run>` |

A push records its commits, files and the remote's tip (the lease) when you write it; amend after the branch moves.
A pull request, a reply that names a pushed commit or claims a fix, and a move of the same issue are chained to the
intent they need, so they publish together, in order. A push whose range holds someone else's commits waits for the
human. On your own open pull request, thread replies belong in its `pr-patch-apply`, with the push.

Steps that must reach the forge one at a time, each on its own click, are a **sequence**: file each stage with
`--waits-for <the stage before it>`. A stage is not offered and not published until the stage before it is out, and
an approval in a sequence also waits for green CI at the commit it reviewed. A stage is never chained with `--after`
(that pairs two intents into one publish). A stage you filed alone joins its sequence with
`cockpit outbox amend <id> --waits-for <id>`; the human or the gatekeeper moves any open intent with
`cockpit outbox relink <id> --waits-for <id>`, which keeps its endorsement.
