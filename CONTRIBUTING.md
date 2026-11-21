# Contributing

## There are no issues here

This project does not take issues. Whatever you have (a bug, an idea, a question), it arrives as a **pull request**.
It may be rough: maintainers adjust pull requests rather than send them back.

- **A bug** is a pull request that adds one failing test under `tests/reports/`. See `tests/reports/README.md`.
  `scripts/check --reports` lists the open ones; that list is the bug tracker.
- **An idea** is a pull request with the change, or, when it is large or you are unsure, one that adds
  `docs/proposals/<slug>.md`.
- **A question** whose answer is written nowhere is a pull request against the docs, even if all it adds is the
  question under a heading.
- **A security problem** is the one exception: it is reported privately. See `SECURITY.md`. Do not open a pull
  request for it.

## Let your coding assistant do it

The repository is prepared for that. Point your coding assistant at `AGENTS.md` and say what you want. It will read
`.agents/skills/contribute/SKILL.md`, which first decides **where** the change belongs:

1. Can a pack already do it? Then you get the recipe and no pull request is needed.
2. Can another plugin do it through the plugin API? Then it lives outside this repository.
3. Is it something that differs between organisations? Then it is a new pack key whose absence changes nothing.
4. Only when the kernel contradicts what it documents, or crashes, does the kernel change.

Most wishes stop at 1 or 3. That is what keeps one organisation's needs from breaking another's installation.

## The one command

```sh
uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'    # once
uv pip install --python .venv/bin/python --require-hashes -r requirements-dev.lock    # once: the linter, the type checker
scripts/check
```

It runs everything CI runs, cheapest first, and ends with `CHECK pass` or `CHECK fail · <ids>`. CI runs the same
command. `scripts/check --quick` runs the fast steps while you work. The whole suite is heavy on a laptop.

Among its steps are the linter and the formatter (`ruff`), the type checker (`mypy`) and two ratchets: a file may not
gain a type error, and a function may not grow past 15 decisions or 80 lines. Without the two tools those steps are
skipped with the line that installs them; CI requires them. `ruff format .` writes the layout the check asks for.
[docs/contributing/architecture.md](docs/contributing/architecture.md) ("Lint, types and the ratchets") has the rest.

After you open the pull request, a comment appears with the result of every check; your coding assistant can read
it and push a correction.

## What a pull request needs

The template asks for it: a title that states the behaviour, the kind, the rung and why not the one below, the
evidence, a sentence on compatibility, the last line of `scripts/check`, and what you did not verify. Please keep
"allow edits by maintainers" on.

## How your contribution is licensed

The project is published under AGPL-3.0-or-later (`LICENSE`) and is also offered under commercial licences
(`COMMERCIAL.md`). A change can be part of both only when the maintainer may license it both ways, so the pull request
template has one box (`CONTRIBUTION-TERMS.md`):

- **Ticked:** you license the contribution to the maintainer under 0BSD. You keep the copyright. It can be merged, and
  it may be published under AGPL-3.0-or-later and under other terms, a commercial licence included.
- **Not ticked:** the pull request is a report. It is closed with thanks and not merged; the maintainer may write a
  change of their own for the same problem.

There is nothing to sign. A merged contribution gives no claim to payment or to a share of a licence fee.

A new source file opens with the project's two header lines (copyright and licence): `scripts/headers --write` adds
them, and `scripts/check` fails without them. A file that cannot carry a comment is covered by `REUSE.toml`. A new
dependency must be under a licence on the list in `docs/contributing/dependencies.md`.

## What will not be merged

- Anything that lets an act leave the machine without the human's approval, or that weakens a check, a refusal or
  an approval. `AGENTS.md` lists these rules.
- A change that makes an existing pack behave differently.
- The name of a company, a product, a person or a host in code, tests or docs.
