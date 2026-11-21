# Plugins beside cockpit

Another Hermes plugin can start and follow cards through cockpit's own rules. It does not write the board or the records
itself. The functions it may call, with their pinned signatures, are in
[reference/plugin-api.md](reference/plugin-api.md); the recipe for adding a card kind or a kickoff mode is
[customize/plugin-card-kinds.md](customize/plugin-card-kinds.md).

## Its pack block

`plugins.<name>` in `pack.yaml` is that plugin's settings. Cockpit hands the block to the plugin's `cockpit_pack.py`
`validate(block, pack_dir)`, which returns the block it will use or raises with the reason. A plugin that is not installed
loads unchecked, and `doctor` says so.

Three keys in the block are cockpit's, and the validator never sees them:

- `card_kinds: {kind: {title, flow, role}}`
- `kickoff_modes: {mode: {lane_kind, capacity_bucket, title_kind, preflight, text, label}}`
- `page: {label, path}`, a link to the plugin's own page.

## Its lane

`kickoff.lanes: {mode: seat kind}` picks the seat a mode starts on, for cockpit's modes and a plugin's. An unknown mode is
refused. It never falls back to intake.

## Its calls

`cockpitlib.plugin_api` (`API_VERSION`, signatures pinned in `tests/contract/cockpit-api.json`). A plugin calls `api.require(N)`
first with the version it was built for: every version from `API_MIN_SUPPORTED` to `API_VERSION` is served, so a plugin
built for an older API keeps working on a newer kernel; a newer one is refused and told to update cockpit.

`start_card` runs the Kick off page's checks: halt, twin, capacity, the lane, a slot, the browser loan.

- `policy="release"` records the go on the plan instead of asking for it, and says so on the card.
- An `idempotency_key` gives one card however often it is sent.
- `repos` (default none) are recorded on that one card: its own PRs read them. Each is a `repos.yaml` `name`, a repo's
  optional `label` (its short name), or the one name it prefixes with a dot (`core` for `core.shop.example.test`). A
  name that matches none or several is refused with a `CockpitError` naming it (`<x> is not a repo of this pack`,
  `<x> is ambiguous (…)`) and no card starts. Given repos, the result carries the resolved names as `repos`. Recording
  them also adds each repo's `repos.yaml` `skills` to the card and limits the card's PR pane to those repos. They never
  fan the card out: a rework still starts one card, with its `max_runtime_seconds`.

`board_cards`, `runs` (with each run's metadata), `comment`, `answer`, `block`, `unblock`, `outbox_create`, and
`halt.write` and `halt.clear` act through Hermes's board functions and the outbox.

## Its cards

Housekeeping does not settle, return or unstrand a card of a plugin's kind. It touches `<records>/wake/<plugin>` with the
card id instead.

## Its Inbox rows

A file at `<records>/inbox/<plugin>/<id>.json`, `{id, icon, what, action_label, href, tone}`, is a row on the human's
Inbox that links to the plugin's page. `api.inbox_row` writes one.

## Linking a plugin into the seats

`extra_plugins` in `pack.yaml` names plugins cockpit links beside itself: each `{name, path, where}`, where `where` is
`root`, `seats` or a list of seat kinds.

## Trust

A plugin runs in Hermes's process with the human's environment. It is trusted code, like the pack
([security.md](security.md#trust-boundaries)).
