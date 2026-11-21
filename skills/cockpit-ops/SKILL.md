---
name: cockpit-ops
description: Run cockpit for the human. Never publish.
---

# Ops

Map a plain-language request to `cockpit status`, `cockpit slot`, `cockpit doctor`, `cockpit gate`, or `cockpit setup`. A request for the platform map goes to the `cockpit:platform-map` skill, then `cockpit map build`. `cockpit gate` runs the test commands in the pack. Hand the human the `cockpit publish` line. Do not run it.

These commands change the machine. They do not only acknowledge the click. `cockpit ticket archive|delete|halt|resume` updates the board, the worktrees, and the outbox. Answering a blocked card comments and unblocks it; a reply that starts with `stop` completes the card. `cockpit bumps scan`, `cockpit watch-base`, and `cockpit watch-pr` read the forge for the pack's org and each repo's base (its repos.yaml `base`, else `base_branch`). A ticket branch starts from the fetched `origin/<base>`; a missing base is refused. `protected_branches` (e.g. `[release, main]`) are, with each repo's base and `workspace_branch`, the branches only the human pushes; a PR opened into, or retargeted to, a base other than the repo's own waits for the human too. `cockpit workspace-watch` commits quiet `qa/` and `outbox/` records on `workspace_branch` (when the pack names one) and never pushes. On any other branch it does not commit, and the Inbox shows a fix watcher until the workspace is back on that branch. With `slot_provider: none`, session open adds the ticket's worktrees (`wt/<ticket>/<repo>`) and starts no stack.
