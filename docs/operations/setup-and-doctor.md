# Setup and doctor

What `cockpit setup` creates, where things live afterwards, and how doctor decides.

## Binding a workspace

`~/.hermes/cockpit.yaml` binds the installation to a workspace and its pack. `cockpit init --write` writes it, last,
once the pack it wrote loads ([quickstart.md](../quickstart.md)); or point it by hand at a pack you already checked.
Then run setup by its path, from any directory:

```sh
~/.hermes/plugins/cockpit/bin/cockpit setup
```

`COCKPIT_WORKSPACE` and `COCKPIT_PACK` in the environment override the binding for one command.

## What setup does

`setup` creates every seat, the board, and the gateway. It registers each watcher as a Hermes cron job
(`hermes cron list`), records the egress hook on the shell-hook allowlist, and restarts the gateway when that service is
already running so the gateway loads both. It also links the program to `~/.hermes/bin/cockpit`. It still does not change
`PATH`; add that directory yourself when you want the short name:

```sh
export PATH="$HOME/.hermes/bin:$PATH"
```

Put that line in your shell startup file if you want it in new terminals. Run setup again after a seat change. It does
not remove a profile. `cockpit apply` is the same command.

`cockpit setup --rerender` writes every seat's files again from the pack (after a kernel update, or a change to
`seat_config`); `--rerender --seat <lane>` does one seat. See [customize/seats-and-souls.md](../customize/seats-and-souls.md).

Every seat loads the plugin, so it reaches cockpit's own skills by Hermes's plugin names (`cockpit:outbox`,
`cockpit:platform-map`, …); a pack's `skills.yaml` names them that way, and a bare name is always the pack's own skill.

## The agent home and the skill router

`setup` points each coding tool at `agent.home` and passes `agent.args`. The ticket checkout is named on the card and
stays beside that home, so the lane edits the ticket and still loads the skills, rules and MCP config that live in the
home. `skills.yaml` `router` is a file in that home. The card tells the lane to follow it and names only the skills for
this kickoff mode. The router picks the one extra skill the task needs.

A pack with no router and no `agent` block behaves as before those keys existed: the kickoff list is the whole procedure,
and the coding tool starts in whatever directory the seat process uses.

## Where things live

Records for the workspace live in one directory, `hermes/` (or the pack's `records_dir`), so the workspace root stays the
pack and the project files:

| Directory | What it holds |
|---|---|
| `hermes/qa/<ticket>/` | plan, human notes, session, halt, pull-request notes |
| `hermes/watch/` | watcher heartbeats the Inbox reads |
| `hermes/platform/` | map, merged-PR census, bumps, CI and PR summaries, standup |
| `hermes/chat/` | lane chat transcripts |
| `hermes/outbox/` | intents |

`~/.hermes` is the installation (seats, crons, the vault).

## What the plugin touches

The plugin runs `git`, the code host's command line, and the pack's slot provider. It reads and writes the bound
workspace's records. It does not phone home. Tracker credentials stay in Hermes's secret scope (or in the environment
names the pack gives). Code-host writes happen only when the human publishes. The full list of what leaves the machine is
in [security.md](../security.md#outbound-network-destinations).

## The pack files doctor reads

- `staging.yaml` lists the app, api and auth origins the lanes open.
- `egress.yaml` `production_hosts` are regexes the tool hook blocks; the local and staging domains stay off that list.
  `role_deny.<kind>` are regexes refused to one seat kind; `git_deny.<kind>` lists the git verbs that kind may not run
  (`commit`, `push`, `checkout -b`), judged on the command's argv: options before the verb are skipped, `merge-base` is
  not `merge`, and `tag`/`branch` alone mean their moving forms; git aliases are not resolved.
- `repos.yaml` `gates` are the test commands for each repo, run by `cockpit gate`.

A repo with `watched: false` in `repos.yaml` stays a repo a ticket can check out, but the base-branch change scan and the
bump scan leave it out (a personal tool, a repo whose home is not the pack's organisation). `shipped: false` keeps a repo
out of the advisories only.

## Doctor

`cockpit doctor` checks the bound workspace and this machine's installation. Every finding belongs to one registered
check, and a check's tier is fixed in the kernel: no flag, environment variable or pack key changes it.

| Tier | Printed as | Verdict |
|---|---|---|
| error | the line, first | fails doctor (exit 1) and `cockpit setup` |
| warning | `warning: <line>`, after the errors | does not fail doctor or setup; fails doctor under `--strict` |
| note | `note: <line>`, after the verdict | never changes it |

Under each error and warning doctor prints `  fix: <what resolves it>`. With no error the last line is `doctor: OK`,
or `doctor: OK (2 warnings)`.

```sh
cockpit doctor            # errors, warnings, the verdict, notes
cockpit doctor --strict   # a warning fails too; no flag makes an error pass
cockpit doctor --online   # adds the checks that need the network: whether the code host's command line is signed in
cockpit doctor --json     # {ok, errors, warnings, pack, hermes, findings: [{id, severity, security, subject, message, fix}]}
```

An error is what stops work or opens a boundary: the agent home or the skill router file is missing, the production
hosts are not answered, a seat is not applied or has drifted from its pack, a seat's secrets file is readable by
others. A warning is what you should look at and can work without for now: no `staging.yaml` or no origin in it, no
repo with a gate, a helper's program or the program of `providers.coding.command` that is not installed, a notify key
no kernel code sends, `ffmpeg` missing for failure videos. A check that guards a boundary is marked **security**: each
is an error, the list of them is pinned in `tests/contract/doctor-security.json`, and none is ever downgraded
([security.md](../security.md#invariants)). Every check, its tier, its lines and its fix:
[reference/doctor.md](../reference/doctor.md).

### A newer Hermes

Cockpit rides on Hermes's hooks, and it was checked against named Hermes minors (`doctor.HERMES_VERIFIED`). A Hermes older
than those, another major, or one whose version cannot be read is an error.

A newer minor is asked instead of refused: doctor runs a small read-only helper inside Hermes's own interpreter (30
seconds at most) and compares what it offers with the shapes recorded in `tests/contract/hermes-hooks.json`: the three
hooks cockpit registers still exist, the payload schema is the same, a tool call is still dispatched to `pre_tool_call`
with every recorded keyword, a block with a message is still honoured, and a shell hook's block is still read.

- All of it matches: doctor stays green and prints one `note:` line saying the version was accepted on a live probe, and
  that the board, delegation and config shapes were not probed.
- Anything differs, or the probe cannot run (no contract file in the install, no answer from Hermes): the version is an
  error (a security one: the fence itself is in doubt), with a `note:` line saying why.

## Reading the pack as it is in force

`cockpit pack check --all` reports every problem of the pack, one a line, where `cockpit pack check` (like every load)
stops at the first; a check that reads what a failed one would have settled is not run and says which it waits for.

`cockpit pack effective [--json] [--sources]` prints every setting of the bound pack with the value in force (with
`--sources`, whether the pack set it, a default filled it in, or a Settings save overlaid it); the same pack prints the
same text on any machine, so two kernel versions can be compared. `cockpit pack explain <key> [--json]` gives one key's
value, source and meaning.

## The kernel as data

A tool beside cockpit (a pack's own tests, a plugin, a script) should not read cockpit's source to learn what it offers.
`cockpit describe --json` prints it: `api_version` and `api_min_supported`, `version`, every verb with its `flags`,
`zero_args`, `self_parsed` and one `example`, the intent types, the kickoff modes, the card kinds, the `marks` a lane is told to write (the privileged-login block, the 2FA block, the
tester's review request, the block that closes a run without a failure video), the roles and the seat kinds.

Every value comes from the table the kernel runs on. It reads no workspace and no pack, so it answers on a machine that
has neither, and it shows cockpit's own modes and kinds, not what a pack or a plugin adds. The top-level shape is pinned
in `tests/contract/describe.json`: keys are added, never removed or retyped.

## The platform map

The Platform page reads `platform/map.yaml` next to the pack. That file is what a person can do, grouped into areas and
features, with code anchors that may span several repositories. The `platform-map` skill (`cockpit:platform-map`) writes
it. Then `cockpit map build` compiles it and `cockpit map check` reports anchors that match nothing.
