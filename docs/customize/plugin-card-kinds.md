# Plugin card kinds and kickoff modes

## Goal

Another Hermes plugin starts its own kind of card through cockpit's rules (halt, twin, capacity, the lane, a slot)
instead of writing the board itself, and has its own kickoff mode and its own page link.

## The pack lines

In `pack.yaml`:

```yaml
extra_plugins:
  - {name: ledger, path: plugins/ledger, where: root}      # links the plugin into the homes that need it
plugins:
  ledger:
    card_kinds:
      audit: {title: "{ticket}: audit", flow: card, role: analyst}
    kickoff_modes:
      audit: {lane_kind: analyst, capacity_bucket: question, title_kind: audit, preflight: [], label: "Audit → analyst",
              text: "The analyst audits the ticket's ledger entries."}
    page: {label: Ledger, path: /ledger}
    retention_days: 30                                     # the plugin's own setting
```

`plugins.<name>`: the name is lowercase (`[a-z0-9][a-z0-9_-]*`) and not `cockpit`. `card_kinds`, `kickoff_modes` and
`page` are cockpit's; everything else in the block is the plugin's. An `extra_plugins` entry is exactly
`{name, path, where}`: `path` holds a `plugin.yaml`, and `where` is `root`, `seats` or a list of seat kinds.

## The script contract

Implemented in `kernel/cockpitlib/pack.py` (`_plugin_blocks`), `registry.py` and `api.py`.

**The validator.** Cockpit looks for the plugin's folder (the `extra_plugins` path, else `~/.hermes/plugins/<name>/`,
else a folder of that name beside cockpit's own) and, in it, `cockpit_pack.py` with:

```python
def validate(block: dict, pack_dir: str) -> dict:
    """The block the plugin will use. Raise with the reason to refuse the pack."""
```

It receives the block without cockpit's three keys and returns the block to keep. Any exception refuses the pack as
`plugins.<name>: <reason>`. A plugin that is not installed loads unchecked, and doctor says so.

**A card kind** is `{title, flow, role}`: the title names `{ticket}`; the role is the seat kind. A plugin cannot
redefine one of cockpit's own kinds or modes (`card kind <name> is cockpit's own`).

**A kickoff mode** is `{lane_kind, capacity_bucket, title_kind, preflight, text, label}`: the bucket is `dev`, `test`,
`review` or `question`; the preflight steps are the kernel's
([kickoff-preflight-and-lanes.md](kickoff-preflight-and-lanes.md)).

**The calls** (`cockpitlib.plugin_api`, signatures in [reference/plugin-api.md](../reference/plugin-api.md)):

- `api.require(1)` first: a version above the kernel's is refused ("update cockpit"), one below the oldest served is
  refused ("update the plugin").
- `api.start_card(mode, ticket, body="", policy="kickoff", ...)` runs the Kick off page's checks and returns the card.
  `policy` is `kickoff` or `release`; `release` records the go instead of asking for it.
- `api.register_card_kind` and `api.register_kickoff_mode` do at run time what the pack block does at load.
- `api.inbox_row(plugin, row)` writes `<records>/inbox/<plugin>/<id>.json`. A row needs `id` and `what`, and may carry
  `icon`, `action_label`, `href`, `tone` (`info`, `warn`, `danger`, `ok`), `ticket` and `detail`.
- `api.wake_marker(plugin)` is the file housekeeping appends `<time> <card id>` lines to when one of the plugin's cards
  needs it. Housekeeping does not settle, return or unstrand a plugin's cards itself.

## A copy-paste example

`plugins/ledger/cockpit_pack.py`:

```python
def validate(block, pack_dir):
    days = block.get("retention_days", 30)
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("retention_days is a whole number of days, 1 or more")
    return {**block, "retention_days": days}
```

And, in the plugin's own code:

```python
from cockpitlib import api

api.require(1)
card = api.start_card("audit", "TASK-100", body="Audit the ledger entries of this ticket.", idempotency_key="audit-TASK-100")
api.inbox_row("ledger", {"id": "audit-TASK-100", "what": "TASK-100: the audit started", "href": "/ledger", "tone": "info"})
```

## How to test it

```sh
cockpit pack check                      # runs your validate(); a refusal reads plugins.ledger: <reason>
cockpit pack explain plugins.ledger
cockpit doctor                          # says when the plugin is not installed, so its block went unchecked
```

Set `retention_days: 0` once to see the refusal. The kernel's own tests for this surface are
`tests/test_plugin_api.py` and `tests/test_a_plugin_built_for_an_older_api_still_loads.py`.
