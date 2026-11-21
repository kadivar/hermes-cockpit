# See the gate work in a minute

`cockpit demo gate` shows the one rule cockpit is built on, on your machine, before you connect anything: an agent
lane cannot send anything out by itself. What it wants sent goes into the outbox, a reviewer endorses it, and a human
sends it.

```sh
cockpit demo gate          # waits for Enter before the human's step
cockpit demo gate --yes    # does not wait
cockpit demo gate --keep   # leaves the sandbox so you can look at every file it made
```

It needs no Hermes, no account on a code host and no tracker, and it works on a machine where no workspace is bound.
It takes well under a minute.

## What it does

It builds a sandbox in the temp folder: a workspace, one git repository with a bare repository as its remote, the
starter pack written by `cockpit init`, and a forge and a tracker that are plain files (`forge.kind: local`,
`tracker.kind: local`). Then it runs the real commands, as child processes, and prints each one with what came of it:

1. A lane (`COCKPIT_LANE=worker-1`) commits a change on a ticket branch in its own worktree.
2. The lane runs `git push`. The egress hook, the same one Hermes calls before every tool call of a lane, refuses, and
   the refusal is printed. The remote still does not have the branch.
3. The lane writes a `push-branch` intent instead: `cockpit outbox new ...`.
4. `cockpit outbox verify` checks the intent against the rules.
5. `cockpit outbox endorse`: you stand in for the gatekeeper, the reviewing seat of a real board.
6. `cockpit publish --dry-run` shows what would be sent and sends nothing.
7. It waits for Enter. That is the human's step: on a real board it is your click in the Inbox.
8. `cockpit publish` sends it.
9. The remote now has the branch, at the lane's commit.
10. A pull request (`open-pr`) and a tracker comment (`tracker-comment`) go through the same gate, to the local forge
    and the local tracker, and each is read back.

One rule of the starter pack is left out of the sandbox's pack: an intent is held when the lane that wrote it did not
load the skill for it, and no lane session runs in the demo to load one. The demo says so when it gets there.

## What it does not touch

Every path the child commands use (`COCKPIT_WORKSPACE`, `COCKPIT_ROOT`, `COCKPIT_HERMES_HOME`, `COCKPIT_PACK`,
`COCKPIT_WT`, `COCKPIT_CURSOR_HOOKS`, `COCKPIT_VOLUMES`, `GNUPGHOME`) points into the sandbox, and the demo refuses to
run a command when one of them would not. Your bound workspace, your Hermes home and your real remotes are never read
or written. Without `--keep`, the sandbox is removed when the demo ends, whether it passed or stopped.

## Next

The demo's forge and tracker are the same ones a pack can use for real while you try the pipeline out: see
[quickstart.md](quickstart.md) for a first pack of your own, and [customize/tracker-command.md](customize/tracker-command.md)
for the tracker kinds ([customize/tracker-github-issues.md](customize/tracker-github-issues.md) when your tickets are
GitHub issues).
