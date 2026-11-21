# Migrating

Two different things carry this name: drafting a first pack from a workspace, and cutting an installation over from an
earlier pipeline.

## Drafting a pack from a workspace

From the workspace:

```sh
cockpit migrate discover     # read-only: prints what it found as JSON
cockpit migrate draft        # writes cockpit-pack/ in the workspace
```

`discover` lists the folders that hold skills (`SKILL.md` trees inside the workspace, and `.cursor/skills`), every
directory of the workspace that is a git repository, and the router file when `AGENTS.md` or another assistant
instruction file is present.

`draft` writes `pack.yaml`, `repos.yaml`, `skills.yaml` and `egress.yaml` under `cockpit-pack/`, through the writer
[`cockpit init`](../quickstart.md#3-write-the-pack-10-minutes) uses. It sets `agent.home` to the workspace,
`agent.add_dirs` to the parent that holds sibling repositories, `skills_dir` to the skill folders it found, and
`skills.router` when it found a router file. When `.cursor/mcp.json` exists it adds `--approve-mcps` to `agent.args`,
because the Cursor CLI leaves a workspace's MCP servers unapproved in a headless run without that flag. The provider and model come from
the Hermes home.

What it shares with `init`:

- it never replaces a file: a `cockpit-pack/` that is there and not empty is refused, and so is a Hermes home that names
  no provider;
- when what it found reads like a secret, it stops with `secret in draft` before its first write.

What differs: `draft` copies no starter files, does not check that the pack loads, and writes no binding (the
migration below does). A new workspace with no earlier pipeline starts from `cockpit init` instead.

The draft is a starting point, and doctor reports an error until production is answered. Fill `egress.yaml`
(`production_hosts`, or `no_production_hosts: true`) and its terminal denies, write `staging.yaml` with its origins, give
`repos.yaml` its gates, correct `forge.org`, `tracker.url` and `tracker.project` in `pack.yaml`, then run setup and
doctor ([setup-and-doctor.md](setup-and-doctor.md)).

## Moving off an earlier pipeline

A pack that replaces another pipeline carries `migrate.yaml` beside `pack.yaml`: the legacy profiles, plugins, crons,
shell hooks, root soul blocks, `.env` and config keys to retire, the record folders to move (and convert), the board cards
to rewrite or map to a flow, the slot bindings to carry over, and the adopter's exporters (logins as neutral JSON lines on
a pipe). The engine knows none of those names. Its keys are in
[reference/pack-keys.md](../reference/pack-keys.md#migrateyaml).

```sh
cockpit migrate plan       # what would change, with counts; exporters only count, no secret is read
cockpit migrate apply      # refused while this home's Hermes gateway runs or a card runs; snapshot first, then a journal
cockpit migrate verify     # the cutover gate: one line per check, with its evidence; exit 1 on any FAIL
cockpit migrate rollback <stamp>   # the snapshot back; record moves reversed (git mv inside one repository)
```

`cockpit migrate rollback <snapshot>` restores the Hermes snapshot and does not delete the records folder.

`cockpit vault import` reads the same JSON lines on standard input and keeps a login the seat store already holds.

### What happens to intents

Intents move with their folder and are converted in place: cockpit's fields stay, an earlier pipeline's names for the
summary and the risk are mapped, and anything else waits under `legacy`. A file beside an intent that is not one (a kept
comment body) is left alone. An intent of a type cockpit lacks becomes an `infra-note` under its own number: open, it is
held for the human with the reason; published or dropped, it keeps its status as history.

### Replacing an older cockpit

Replacing an older cockpit is the same call. Keep the workspace. Do not copy the old plugin's scripts or product hosts
into this one. Records from an older pipeline are moved in by the migration, not by setup.

`tests/live/run-all.sh` runs cockpit against the installed Hermes on fresh temporary homes for both fixture packs.
