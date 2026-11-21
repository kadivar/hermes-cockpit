# Seats and souls

## Goal

Each kind of seat gets what your team wants it to have: a role prompt (its *soul*) with your house rules, a starting
memory, its own skills, MCP servers, environment and Hermes settings.

## The pack lines

In `pack.yaml`:

```yaml
seat_config:
  _common:                       # every seat
    soul: souls/common.md
    env: {REGION: eu-1}
  reviewer:
    soul: souls/reviewer.md
    skills:
      - {name: house-style, path: seat-skills/house-style}
    mcp: [docs]
    hermes:
      agent: {max_turns: 120}
  root:                          # the default profile: a soul only
    soul: souls/root.md
mcp_servers:
  docs:
    command: [example-mcp, --stdio]
    env_keys: [DOCS_TOKEN]
```

A kind is `_common`, `root`, or one of `intake`, `reviewer`, `analyst`, `worker`, `tester`, `gatekeeper`, `advisor`. A
seat takes `hermes`, `soul`, `memory_seed`, `skills`, `mcp`, `env` and `env_files`; `root` takes `soul` only.

- `soul` and `memory_seed` are files that exist, absolute or beside `pack.yaml`.
- `skills` are `{name, path}`; each folder holds a `SKILL.md`.
- `mcp` names servers from `mcp_servers`. A server has a `command` or a `url`, not both.
- `env` is plain values. A name that reads like a secret (`TOKEN`, `SECRET`, `PASSWORD`, ...) is refused: put it in a
  file named under `env_files`, an absolute path that only you can read and that is outside every git tree.
- `hermes` is laid over the seat's Hermes config. The settings cockpit owns may not be set
  (`seat_config <kind>.hermes: <path> is set by cockpit`): the model and its provider, hook auto-accept, the board's
  auto-decompose and review dispatch, the unattended approval modes, the delegation limits and `mcp_servers`.

## The script contract

There is no script here: the contract is how setup assembles a seat (`kernel/cockpitlib/setup.py`, checked in
`pack.py`).

- **The soul** is these parts, in this order, joined with a line break:
  1. the kernel's text for the role, `souls/<kind>.md` in the plugin;
  2. the pack's `_common` soul;
  3. the pack's soul for the kind;
  4. the kernel's `souls/_common.md`, the rules every lane keeps.
- **Placeholders** filled in the assembled text: `{{LANE}}` (the seat's name, such as `reviewer` or `worker-1`), `{{SLOT}}` (the
  slot number of a worker or tester seat), `{{RECORDS}}` (the records folder's name), `{{EVIDENCE}}` (the folder of a
  test run its screenshots and videos go in, the pack's `testflow.evidence_dir`), `{{HOME}}` (the home folder of whoever
  runs setup, see [personal-values.md](personal-values.md)) and `{{prompt:name}}` (a named prompt, see
  [prompt-overrides.md](prompt-overrides.md)).
- **The root soul** is written between two marker lines in `~/.hermes/SOUL.md`; the rest of that file is yours.
- **The memory** starts from the kind's `memory_seed`, else `_common`'s, else the kernel's. A memory the lane has
  edited is kept.
- **Lists that merge:** the seat's approval denies, enabled plugins and tool hooks are the kernel's plus the pack's.
  The kernel's own settings are applied last and win.
- **A pack's soul adds; it does not remove.** The kernel's role text and common rules are always in the seat's soul.
  They are also not what keeps a lane from publishing: the gate and the hook are
  ([security.md](../security.md)).

## A copy-paste example

`souls/common.md` in the pack folder:

```markdown
## House rules

- You are {{LANE}}. Your records are under `{{RECORDS}}/`.
- Commit messages are one present-tense sentence.
- Never change a file under `vendor/`.
```

```yaml
seat_config:
  _common:
    soul: souls/common.md
```

## How to test it

```sh
cockpit pack check
cockpit setup --rerender --seat reviewer       # one seat; without --seat, every seat
cockpit doctor                                 # "seat drift <lane> ..." when a seat's files no longer match the pack
```

Then read the result: `~/.hermes/profiles/reviewer/SOUL.md`. A rerender first copies the seat's config, soul,
environment and memory to `~/.hermes/backups/profiles/<stamp>/<lane>`.
