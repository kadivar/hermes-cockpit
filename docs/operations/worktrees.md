# Worktrees

## One checkout per repo per ticket

`cockpit worktree add <ticket> [repo] [--from <ref>]` makes the ticket's checkout of a repo, `wt/<ticket>/<repo>`, on the
branch `<branch_prefix>/<ticket>`. The repo's own checkout is never switched.

`runtime` in `pack.yaml` is `worktree` or absent, which means the same; any other value is refused.

What a new worktree gets from `repos.yaml`: the paths listed under `copy`, the files under `worktree_files`, the hooks
folder under `hooks_path`, and then each command under `after_add`. See
[reference/pack-keys.md](../reference/pack-keys.md#repos).

## Where a worker may write

A worker edits its ticket's worktrees, `wt/<ticket>/<repo>`, and its `write_roots`; a repo's own checkout is never a
worker's to edit, whatever branch it is on. A plugin card started through `cockpitlib.plugin_api.start_card` records the `repos`
the plugin passes; without them it records none.

The fence judges the write targets it can see: shell redirects, `cp`/`mv`/`sed -i`-style targets, and the write tools
(`write_file`, `patch`, …). It does not see a `git -C <other repo> commit`, or a write made from inside `execute_code`, so
it narrows a worker's reach rather than sealing it. `cockpit fence-check --card <card> --path <path>` says whether one
path is inside a card's area and why ([customize/egress-rules.md](../customize/egress-rules.md)).

## Stale worktrees

Every ticket keeps its checkouts under `wt/<ticket>/<repo>` until something removes them, and they pile up
and take disk. `cockpit worktree gc [--days 14] [--dry-run]` is one pass over them. A ticket folder goes only
when every gate passes, and each gate names itself as the reason the folder stays:

- nothing under it was touched for the period (`node_modules`, `vendor` and `.git` aside);
- no commit that recent;
- no slot holds the ticket;
- no open card names it;
- no process runs inside it;
- every checkout is clean and its commits are on a remote.

Branches stay.

The Settings page has the same pass as a switch, **Remove stale worktrees** (`worktree_gc: {enabled, days}`, off by
default; a pack may set the start state): on, housekeeping runs it once a day and the page shows the last pass. Preview
and Run now on that page, and the command, run it by hand whatever the switch says.
