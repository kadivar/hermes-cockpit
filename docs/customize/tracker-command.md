# A tracker by command

## Goal

Cockpit writes to a tracker it has no client for (or to a file, while you try the pipeline out) through one command of
yours. Every tracker write still goes through the outbox and the human's publish.

## The pack lines

In `pack.yaml`:

```yaml
tracker:
  kind: command
  command: ["{pack}/bin/tracker"]
  url: https://tracker.example.test     # the tracker's base URL: a ticket's link starts here
  project: TASK
```

`tracker.kind` is `connector` (the default: Hermes's hosted connector), `jira` (Jira's REST API with the two
environment names in `tracker.auth_env`), `command`, `local` (tickets
kept as files, no account needed), or `github-issues` (the issues of the code host the pack publishes to: see
[its recipe](tracker-github-issues.md)). Naming `tracker.command` alone makes the kind `command`; `kind: command`
without a command is refused. `{pack}` is the pack's folder.

A ticket's link is `<tracker.url>/browse/<key>` unless you give `tracker.browse_url`, a template with `{key}` (or
`{number}`, the number the key ends with) and, where they go, `{url}` and `{project}`:
`browse_url: "{url}/issues/{key}"`.

What each kind has. An intent that needs what the pack's tracker lacks is refused when it is written:

| Capability | `connector`, `jira` | `command` | `local` | `github-issues` |
|---|---|---|---|---|
| summary, comment, edit-comment, create, transition, assignee | yes | yes | yes | yes |
| status, comments, identity (the comment watch needs them) | yes | the ones named in `tracker.reads` | yes | yes |
| attachments | yes | yes (your command's own) | yes | no |
| sprint, component | yes | yes (your command's own) | no | no |
| transition-through (a move by way of another status) | yes | no | yes | no |

To let the comment watch and the standup note read your tracker, name the reads your command answers:

```yaml
tracker:
  command: ["{pack}/bin/tracker"]
  reads: [comments, me, status]
```

A read you do not name is never run, so a command written for the writes alone keeps working unchanged (and the
comment watch stays off for it).

## The script contract

Implemented in `kernel/cockpitlib/trackers/command.py` (`CommandTracker`).

- **When:** a tracker intent is published (`tracker-comment`, `tracker-create`, `tracker-transition`), and when cockpit
  needs a ticket's title. The type is the `type` your script reads and the name in an intent's id.
- **Arguments:** the command as written, nothing added.
- **Environment:** the caller's, plus `COCKPIT_TRACKER_ACTION`: `comment`, `create`, `transition` or `summary`, and
  the reads named in `tracker.reads`: `comments`, `me`, `status`.
- **Standard input:** the whole intent as JSON: `id`, `ticket`, `type`, `summary`, `payload` and the rest of the
  record. The payload's fields are those of the type ([reference/intents.md](../reference/intents.md)). For `summary`
  it is `{"ticket": "<key>", "payload": {"issue": "<key>"}}`.
- **Standard output:** one JSON object.

  | Action | Expected keys |
  |---|---|
  | `comment` | `url`, `id` |
  | `create` | `url`, `key` (the new ticket's key) |
  | `transition` | `url`, and `output` or `status` |
  | `summary` | `summary` (the ticket's title) |

  The reads get their own small input instead of an intent:

  | Read | Standard input | Expected answer |
  |---|---|---|
  | `comments` | `{"key": "<key>", "since": <a moment or null>}` | `{"comments": [{"id", "author", "created", "body"}]}`, oldest first; `updated` when a comment was edited |
  | `me` | `{}` | `{"login": "<who the command writes as>"}`: comments by that author are not news |
  | `status` | `{"key": "<key>"}` | `{"status": "<the status name>"}` |

  `created` and `updated` are ISO moments (`2026-01-01T09:00:00Z`). `author` is the name compared with `me`.

- **Exit 2 from a read** means "this tracker has no such read": the watch or the note goes without it. It is not a failure.
- **Exit codes:** 0 is done. Anything else fails the publish with the last 300 characters the command printed
  (`tracker command <action>: ...`). Output that is not JSON fails it too (`its answer is not JSON`).
- **Time limit:** 300 seconds.
- **A dry run** (`cockpit publish --id <intent> --dry-run`) records the write and does not call the command.

A drafted body is a file path in the payload (`body_file`), relative to the workspace; read the file, do not expect the
text inline.

## A copy-paste example

`bin/tracker` in the pack folder (make it executable; the starter pack has another example of this contract, `starter/bin/tracker`). It keeps a tracker in a JSON-lines file:

```python
#!/usr/bin/env python3
"""A tracker in one file: the intent on standard input, the action in COCKPIT_TRACKER_ACTION, JSON back."""
import json
import os
import sys
import time

BOOK = os.path.expanduser("~/cockpit-tracker.jsonl")
BASE = "https://tracker.example.test/browse/"
action = os.environ.get("COCKPIT_TRACKER_ACTION", "")
intent = json.load(sys.stdin)
payload = intent.get("payload") or {}
issue = payload.get("issue") or intent.get("ticket") or ""

if action == "summary":
    print(json.dumps({"summary": f"{issue} (from the file tracker)"}))
    sys.exit(0)
if action not in ("comment", "create", "transition"):
    print(f"unknown action {action!r}", file=sys.stderr)
    sys.exit(1)
row = {"at": int(time.time()), "action": action, "issue": issue, "payload": payload}
if action == "create":
    row["issue"] = issue = f"{payload.get('project') or 'TASK'}-{int(time.time()) % 100000}"
with open(BOOK, "a", encoding="utf-8") as book:
    book.write(json.dumps(row) + "\n")
answer = {"url": BASE + issue}
if action == "comment":
    answer["id"] = str(row["at"])
elif action == "create":
    answer["key"] = issue
else:
    answer["status"] = payload.get("to") or ""
print(json.dumps(answer))
```

## How to test it

Run the script as the kernel would:

```sh
echo '{"ticket": "TASK-100", "type": "tracker-comment", "payload": {"issue": "TASK-100", "body_file": "note.md"}}' | \
  COCKPIT_TRACKER_ACTION=comment bin/tracker
# {"url": "https://tracker.example.test/browse/TASK-100", "id": "..."}
```

Then `cockpit pack check`, and with a tracker intent in the outbox:

```sh
cockpit publish --id TASK-100/002-tracker-comment --dry-run     # what would be sent; the command is not called
```

A real publish is yours to run, from the Inbox or your own terminal.
