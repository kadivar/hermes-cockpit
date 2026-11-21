# Publishing without a click (opt-in)

By default nothing leaves without the gatekeeper's endorsement and the human's publish. A pack may let one scope go
without the click:

```yaml
outbox:
  auto:
    - scope: release
      types: [push-branch, open-pr, pr-edit, pr-comment, tracker-transition]
```

A card started with `policy="release"` (a plugin's `cockpitlib.plugin_api.start_card`) records the scope, and so do the rework,
test and review cards that follow it. The housekeeping step `auto-publish` endorses and publishes the intents those
cards' lanes write, if their type is listed.

Every check a publish makes still runs: verify, the lease and the read-back, the rebase-only proof, the local-reference
scan.

Some things still wait for the human, with the reason on the intent:

- an approval or a review's verdict;
- a push to a base branch;
- a body that holds a stored secret.

`ticket-done` and `infra-note` are never published. The step never runs inside a lane.

This key widens what leaves without you. It is marked `security` in [reference/pack-keys.md](../reference/pack-keys.md),
and it belongs in a pack only for a scope whose cards you start deliberately. See [security.md](../security.md).
