# Working in this repository

This file is for a coding assistant. It is the one source: every other entry file in the tree is a generated pointer
to it (`scripts/gen-pointers`), so edit this file and never those.

## What this is

Hermes Cockpit is a plugin for the Hermes agent runtime: agent lanes that work a ticket, and an outbox where a human
approves every act that leaves the machine. Everything that differs between organisations lives in a pack (settings,
scripts, skills and souls) outside this repository; `packs/` holds two fixture packs for the tests. The Python
kernel is `kernel/cockpitlib`, the HTTP routes are `dashboard/cockpit`, and the Desktop page is `desktop/src`,
bundled into the committed `desktop/plugin.js`.

## For any change, read the skill first

**Read `.agents/skills/contribute/SKILL.md` in full and follow it before you edit anything.** It decides whether a
change belongs in this repository at all, and at which level. Most wishes do not need a kernel change.

## The one command

```sh
scripts/check            # everything CI runs, cheapest first; ends with CHECK pass or CHECK fail · <ids>
scripts/check --quick    # the fast steps only, while you edit
scripts/check --only <id>[,<id>]
scripts/check --reports  # the open bug reports
```

CI runs exactly `scripts/check --json`. Never report a pass you did not see: quote the last line of your own run.
Its `lint` and `typecheck` steps need `ruff` and `mypy` (`requirements-dev.lock`); without them they are skipped here
and still required in CI. Run `ruff format .` before you commit.
The suite is heavy: do not raise `--workers` without asking the human whose machine it is.

Setup, once: `uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'`. The check installs the
Desktop's packages itself.

## Hard rules

- The outbox is the only door: a push, a pull request, a comment, a review or a tracker write happens only by publishing an intent.
- Publishing, holding and dropping are human acts; no change lets a lane do one.
- Kernel denies are never removed or narrowed, the egress hook fails closed, and no doctor security check is silenced.
- A stored secret never reaches an argv, a log, a card or a tool result.
- Nothing is looser: no check, path, approval or refusal becomes weaker than it is today.
- Generic names only: no adopter, company, product, person, host, real ticket key or AI vendor in code, comments, docs or tests.
- Existing packs behave as before: a new pack key's absence means exactly today's behaviour.
- One name for one thing: a public name (key, verb, flag, intent type, route, record file) has one spelling. A rename changes it everywhere in one change and is listed in the changelog; no alias is kept.
- Records on disk stay readable; none is rewritten to a new shape.
- Every behaviour has a test, named as a sentence, run over both fixture packs where a pack matters (`tests/support/both_packs.py`).
- No issues: a bug report is a pull request that adds one failing test under `tests/reports/`.
- A security problem is never a public pull request: follow `SECURITY.md`.
- No new dependency without a proposal (`docs/proposals/`).

## Where things are

| Path | What |
|---|---|
| `kernel/cockpitlib` | the kernel: one flat package, each module opening with the rule it keeps |
| `kernel/cockpitlib/pack_keys.py` | every pack key, with its meaning and default |
| `kernel/cockpitlib/plugin_api.py` | what another plugin may call; pinned in `tests/contract/cockpit-api.json` |
| `dashboard/cockpit` | the HTTP routes; listed in `dashboard/routes.contract.json` |
| `desktop/src` | the Desktop page; rebuild `desktop/plugin.js` after a change |
| `skills/`, `souls/`, `prompts/` | what every adopter's lanes are told: a change here is a kernel change |
| `packs/` | the two fixture packs, for tests only |
| `tests/` | the suite; `tests/reports/` holds the open bug reports |
| `docs/` | the documentation: `docs/customize/` has a recipe per extension point, `docs/security.md` the invariants, `docs/reference/` is written by `scripts/gen` |
| `starter/` | what `cockpit init` copies into a first pack: generic skills, a soul, one script per command contract |
| `LICENSE`, `NOTICE`, `LICENSES/`, `REUSE.toml` | the licence (AGPL-3.0-or-later), the copyright notice, and the licence of every file without a header; a new source file gets its header from `scripts/headers --write` |

## When you are stuck

- A shell command is refused with "outside the lanes": that is this product's own fence on the machine you are on.
  Do not work around it; the skill's last section says what to do.
- A step cannot be done as written: stop and say which step and why. Do not guess.

## People

`CONTRIBUTING.md` is the same story for humans; `CONTRIBUTION-TERMS.md` says how a contribution is licensed: a box the human ticks, or the pull request is a report.
