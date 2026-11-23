# Architecture

Where things are, and the exact steps for the four changes people make most. For the rules a change must keep, read
[security.md](../security.md#invariants) first.

## The repository

| Path | What it is |
|---|---|
| `__init__.py`, `plugin.yaml` | The Hermes plugin entry: it registers cockpit's skills and the three hooks (`pre_tool_call`, `transform_tool_result`, `transform_terminal_output`). |
| `bin/cockpit` | The launcher. It puts `kernel/` on the path, moves to the plugin's own `.venv` when the host's Python has no PyYAML, completes a bare `PATH`, and calls `cockpitlib.cli.main`. |
| `kernel/cockpitlib/` | The kernel: about a hundred flat modules, grouped below. It knows no team, repo or product. |
| `kernel/schema/` | JSON schemas of the pack files, generated, for editor completion. |
| `hooks/` | The shell hooks Hermes runs: `egress.py` (the fail-closed check before a lane's tool call), `cursor.py` (the editor fence), `resume-context.sh`. |
| `hermes_bridge/` | Small helpers that run inside Hermes's own interpreter (board writes, usage readers, the vault store, the hook probe). They import Hermes's modules and never `cockpitlib`. |
| `cron/` | One script per scheduled job; each runs `cockpit <verb>` through `cron/run`. |
| `dashboard/` | The HTTP routes (`dashboard/cockpit/router.py`, `routes/pages.py`, `routes/vault.py`, and the page payload `payload.py`), the list of them a test calls one by one (`routes.contract.json`), and the web dashboard's tab. |
| `desktop/` | The Desktop pages: sources in `desktop/src`, bundled into the committed `desktop/plugin.js`; JS tests in `desktop/test`. |
| `souls/` | The kernel's role prompt for each kind of seat, and the rules common to all. |
| `prompts/` | Named prompts a soul includes (`{{prompt:name}}`); a pack may replace one. |
| `skills/` | Cockpit's own skills, which every seat reaches as `cockpit:<name>`. |
| `packs/` | Two fixture packs for the tests. They are not examples to copy. |
| `scripts/` | `check` (everything CI runs, as one command), `test` (the suite), `gen` (the generated references and schemas), `gen-pointers` (the entry files other coding assistants read), `replay` (two kernels on the same records), `lock` (the hashed lock files), `baselines` (the type and complexity baselines), `bump` (the version), `headers` (the copyright lines). |
| `starter/` | The starter pack: the skills, the soul and the scripts `cockpit init` copies into a new pack. |
| `AGENTS.md`, `.agents/` | The guide a coding assistant reads and the contribute skill; the other entry files are generated pointers to them. |
| `evals/` | The scenarios the contribute skill is graded on. |
| `.github/` | CI (it runs `scripts/check`), the comment that reports each check on a pull request, and the pull-request template. |
| `tests/` | The suite. A test name is a behaviour sentence; `tests/contract/` pins the shapes other code depends on; `tests/reports/` holds the open bug reports. |
| `docs/` | This documentation. `docs/reference/` is generated. |

## The kernel, by area

Each module's first docstring line says what it is. Grouped:

| Area | Modules | What it holds |
|---|---|---|
| **The pack** | `pack`, `pack_keys`, `pack_local`, `pack_effective`, `pack_pin`, `settings`, `environments`, `prompts`, `registry` | Loading and checking a pack; the key registry; the one reader of a pack's YAML files, which fills `{home}` and `{local.<name>}`; the values in force; the lines that pin a default; what the Settings page overlays; card kinds and kickoff modes. |
| **The outbox and the gate** | `intents`, `outbox`, `gate`, `sequence`, `publish`, `git_push`, `patch_apply`, `infra_note`, `local_refs`, `refusals`, `intent_view`, `diffs` | Intent types and statuses; creating, verifying, endorsing and holding; the gatekeeper's sweep; publishing with read-back; what a push would send. |
| **The fence** | `egress`, `fence`, `scrub`, `quoted`, `browser_card`, `plan_gate` | The command and tool check; the editor guard; secret masking; marking outside text as data; which browser a card may drive. |
| **Code host and tracker** | `forge`, `forges/`, `gh_cli`, `tracker`, `trackers/`, `connector`, `pr_watch`, `ci_watch`, `tracker_watch`, `owners` | The code host behind one protocol (`forges/`: GitHub through its command line, and a forge kept in files); the tracker behind one protocol (`trackers/`: Jira over REST or the connector, the pack's command, tickets kept in files, and the issues of the pack's code host); the pull-request, CI and tracker watches. |
| **The board and cards** | `kanban`, `kickoff`, `decompose`, `capacity`, `lanes`, `halt`, `resume`, `answers`, `asks`, `lend`, `advise` | Reading and writing the board; starting a card; the breakdown after go; seats and capacity; questions, approvals, loans, the advisor. |
| **Seats and setup** | `scaffold`, `sandbox`, `demo`, `setup`, `doctor`, `hook_probe`, `hermes_runtime`, `migrate`, `pack_migration` | Writing a first pack (`cockpit init`); a workspace that is nobody's, for the tests and for `cockpit demo gate`; creating seats, the board and crons; the health check and its registry of checks; the live probe of a newer Hermes; running helpers inside Hermes; migrations. |
| **Slots and worktrees** | `slots`, `worktree`, `cleanup`, `repo_gates`, `helpers` | Slot ownership and the pack's runtime commands; a ticket's checkouts; the stale-worktree pass; repo gates; helpers. |
| **Testing** | `test_flow`, `record`, `cdp_ws`, `qa_view` | When a test run may leave the machine; failure videos; the DevTools client; QA evidence as the page reads it. |
| **The vault** | `vault`, `vault_key`, `vault_book`, `lane_vault`, `accounts` | The wrapped key; the private key's state; the human's vault book; a seat's own store; declared accounts. |
| **Housekeeping and watchers** | `housekeeping`, `scheduled`, `ops`, `health`, `record_write`, `state_commit`, `notify`, `standup_note`, `window`, `advisories/` | The minute pass; what the crons run; watcher health; committing records; notifications; the standup note; the advisory watch. |
| **What the pages read** | `acts`, `board_view`, `lane_feed`, `lane_transcripts`, `activity`, `inbox`, `own_rows`, `map_build`, `render`, `chat`, `live_cli`, `skill_log` | What the page buttons change; the board, Live, activity and Inbox as the pages read them; markdown to safe HTML; the chat terminal. |
| **Usage and budget** | `usage`, `quota`, `pace`, `plan`, `plan_windows` | Token totals; provider quotas the budget gate respects; plan pace; the plan file; a subscription's own usage windows, asked of the coding tool's endpoint when Hermes's reader cannot answer. |
| **Itself** | `cli`, `plugin_api`, `describe`, `self_update`, `rehome`, `after_update`, `errors`, `paths`, `store`, `time_util` | The command line; the functions a plugin may call; the kernel as data; the self-update and the move to another repository; errors, paths, atomic records. |

House rules that explain the shape of the code:

- **Imports are relative, and often inside a function.** That is how a hundred flat modules avoid import cycles.
- **A docstring is one declarative sentence** stating the behaviour or the invariant.
- **Errors** are `CockpitError` (exit 1), `PackError` (2), `UsageError` (2; its message carries an example of the right
  form) and `Conflict`, all in `errors.py`.
- **A path built from a ticket key or a name** goes through `paths.qa_of`, `paths.outbox_of` or `paths.worktree_of`
  (one segment, nothing leaves the root), or `intents.ticket_folder` where the key must also fit the pack's
  `ticket_pattern` (a write or a removal). No file but `paths.py` joins `qa()`, `outbox()` or `wt()` with a name it was
  given: `tests/test_every_ticket_path_is_built_in_one_checked_place.py` reads the source and fails when one does.
- **Text from outside** (a tracker, a pull request, a log) goes through `quoted` before it reaches a card or a prompt.
- **A public name has one spelling.** A pack key, an intent type, a verb, an environment variable, a route or a
  record's file name is renamed everywhere in one change (code, fixture packs, starter, docs, generated references),
  listed under "Removed" in `CHANGELOG.md` and, for a pack key, declared in `UPDATE-CHANGES.json`. No alias is kept.

## Adding a pack key

1. Add the key to `KNOWN` in `pack.py` (or to the key set of its block: `SLOT_KEYS`, `TRACKER_KEYS`, `FORGE_KEYS`, ...).
2. Write a `_key(data)` validator whose `PackError` states the valid shape, and call it from `_load`.
3. Add its entry to `pack_keys.py`: path, type, one-sentence doc, example, and the default with the place that reads it.
4. A default applied where the key is read (`.get("key") or DEFAULT`) goes on the reviewed list
   `tests/contract/pack-defaults.json`.
5. **An absent key is exactly today's behaviour.** Test that, on both fixture packs.
6. Run `scripts/gen`, and the tests `tests/test_the_key_registry_matches_the_validators.py`,
   `tests/test_no_default_hides_from_the_registry.py`, `tests/test_generated_docs_are_current.py` and
   `tests/test_both_fixture_packs_fit_the_editor_schemas.py`.

## Adding a command

1. Write `cmd_<verb>(argv) -> int` in `cli.py`, with a docstring that starts with its usage.
2. Add an example to `EXAMPLES`, and its options to `FLAGS` (or the verb to `SELF_PARSED` when it checks its own, or to
   `ZERO_ARGS` when it takes none).
3. Register it in `COMMANDS`.
4. An existing test asserts that every example parses and that every command refuses an unknown option with exit 2.
   Keep that true. A human-only command calls `outbox.human_gate`.
5. Run `scripts/gen`: `docs/reference/cli.md` and `cockpit describe --json` both follow the tables.

## Adding an HTTP route

1. Add a nested `@router.get(...)` or `@router.post(...)` function inside `mount()` in `dashboard/cockpit/routes/pages.py`.
   Start it with `pack = _guard()`, check a ticket key with `_ticket(pack, ...)`, and wrap an act in `_act(...)`.
2. A human-only act calls `human_gate` there too: the route has no authentication of its own
   ([security.md](../security.md#trust-boundaries)).
3. List the route in `dashboard/routes.contract.json`. `tests/test_routes.py` calls every listed route.
4. A `GET` should read. If it must run pack code or write a file, say so in `docs/security.md`.

## Adding a Desktop view

1. Add `desktop/src/views/<name>.js` and import it in `desktop/src/app.js`.
2. Styles go through `desktop/src/lib/sdk.js`; text the page prints names no AI vendor or product
   (`tests/guards/grep_tokens.py` scans the bundle). Make every element with `h(...)` from that file: an element with a
   click handler that is no button or link then gets a role, a tab stop and Enter/Space from
   `desktop/src/lib/a11y.js`. An element that only catches a click (a dialog's body) says `role: 'presentation'`, and
   a button that shows only a sign needs a `title` or an `aria-label`. A rule in `desktop/test/rules.mjs` holds both.
3. Add its rules to `desktop/test/rules.mjs` and run `npm test` in `desktop/`.
4. Rebuild and commit the bundle: `cd desktop && npm ci && npm run build`, then commit `desktop/plugin.js`. A test
   rebuilds the bundle and compares, so a source change without its bundle fails.

## Writing a record

Records (`outbox/`, `qa/`, `watch/`, `platform/` under the workspace's records folder, and the state cockpit keeps in
the Hermes home) are plain files that crons, lanes, the routes and the human's command line write and read at the
same time. `kernel/cockpitlib/store.py` is the one place they are written.

- **Write through `store`.** `store.write_json` (the kernel's own form), `store.dump_json` (what `json.dump` would
  write, same parameters), `store.write_text`, `store.write_bytes`, `store.append_line` (a log line). Each puts the
  bytes in a temp file beside the target and replaces the target in one step, so a reader sees the old file or the new
  one. Never `open(path, "w")` on a record: `tests/test_a_record_write_goes_through_the_store.py` finds it, and
  `tests/contract/record-writes.json` lists only the writes that are not records, each with its reason.
- **Read without a lock.** A read is always safe; the Outbox list is read thousands of times while a page is built.
- **Read-modify-write takes the lock.** `store.locked(ticket)` for a ticket's intents, `store.locked_file(path)` for
  one shared file such as `watch/cards.json`. Inside the block: read again, check that what you decided on is still
  true, write. An intent goes through `intents.load` and `intents.save`, which do exactly that: a `save` of an intent
  whose file changed since it was loaded raises `Conflict` and writes nothing.
- **Never hold the lock across the network, a subprocess or a gate run.** Do the slow work first, on your copy, and
  take the lock only to write the answer. A new intent takes its number first (`intents.reserve_seq`), probes, then
  writes. A publish, which is slow, holds a claim instead (`intents.claimed`): other writers of that intent are
  refused while it runs, and its receipt is written with `intents.settle`.
- **A lock file is no record.** `.lock` in a ticket's outbox folder, `.<name>.lock` beside a shared file and store's
  temp files (`.<name>.<…>.tmp`) are `store.scratch` names: not intents, not committed by `workspace-watch`, not
  copied or compared by `scripts/replay`. A listing of a records folder leaves them out.
- **Hermes's databases are read through `store.read_db`**: read-only, with a busy timeout. A board write goes
  through Hermes's own functions (`kanban.BoardWrites`).

## Tests

- One behaviour sentence per test name: `test_a_missing_ticket_is_not_invented`.
- Where a pack matters, parametrize over **both** fixture packs and derive identifiers from the pack's own values.
- The `env` fixture gives a workspace with the fixture repos; `bare` gives one without. No test reads the machine's own
  installation.
- Restore what a test patched with another `monkeypatch.setattr`, not with `monkeypatch.undo()`: undo also drops the
  test's workspace. `tests/conftest.py` gives the whole run an empty Hermes home, so even then no real one is found.
- The coverage gate counts lines and branches together. Its figure is `fail_under` in `pyproject.toml`, the one place
  it is written: it is what the suite measures, rounded down, so it holds the level the code has. Assert behaviour,
  not that lines ran: a new decision needs a test for each side.
- Run a file with `scripts/test -q tests/<file>.py`; `scripts/test` alone runs the suite on several workers.
- `scripts/check` runs everything CI runs, cheapest first, and ends with `CHECK pass` or `CHECK fail · <ids>`;
  `scripts/check --quick` runs the steps before the suite. [AGENTS.md](../../AGENTS.md) and
  [CONTRIBUTING.md](../../CONTRIBUTING.md) say how a change is proposed.

Two parsers read text someone else wrote, and a seeded generator holds them to it
(`tests/test_hostile_input_never_crashes_the_shell_reader_or_the_pack_loader.py`): the fence's shell reader never raises,
ends within a bound and never allows a line a kernel deny matches; the pack loader answers a damaged pack with a pack or
a `PackError`. A failure names its seed and case. `FUZZ_CASES` and `FUZZ_SEED` in the environment run a longer hunt.

## Lint, types and the ratchets

`scripts/check` holds the code to four more things than its tests. Each is a step or a structure test, each fails on
the change that makes it worse, and none asks for a clean-up of what is already there.

| What | Where it runs | Its settings and its baseline |
|---|---|---|
| The linter's rules and the formatter's layout (`ruff check`, `ruff format --check`) | the `lint` step | `[tool.ruff]` in `pyproject.toml`. A rule that is off has its reason on its line. |
| The type checker (`mypy`), as a count of errors per file | the `typecheck` step | `[tool.mypy]` in `pyproject.toml`; `tests/contract/type-errors.json` |
| No function over 15 decisions or 80 lines | `tests/test_no_function_grows_past_the_ratchet.py` | `tests/contract/complexity.json` |
| No line of a page's source past 400 characters | `tests/test_no_source_line_of_the_pages_runs_past_four_hundred_characters.py` | none |

- **Lint.** Write `ruff format .` before you commit; `ruff check --fix .` sorts imports and applies the safe fixes. A
  line that must keep a finding says why on that line: `# noqa: BLE001 - one source failing is its own status line`.
  A `noqa` without a rule and a reason is not accepted in review. Markdown is not formatted, and a table of names with
  a column of comments stands between `# fmt: off` and `# fmt: on`.
- **Types.** The code is checked as it is, with untyped functions left unchecked, and what is installed beside it is
  read as untyped so the count does not move with a dependency's release. A file may have as many errors as
  `type-errors.json` counts for it and no more; a file that is not listed may have none. Fix an error rather than
  silence it: no `# type: ignore` is added to reach a count.
- **Complexity.** A function's decisions are its `if` and `elif`, `for`, `while`, `except`, `with`, each further
  operand of `and`/`or`, each `if` of a comprehension and each `case`; a nested function is measured as itself. The
  functions that are over a limit today are listed with their numbers. A listed function may not grow, a new one may
  not be over, and one that got under both limits must leave the list, so the list only shrinks. The linter has no
  complexity rule of its own for that reason: it knows one limit for every function and no baseline.
- **Writing a baseline again.** `scripts/baselines` measures and writes both files; `scripts/baselines complexity` or
  `scripts/baselines types` writes one. `scripts/baselines --check` compares and exits 1 on what got worse. Write a
  baseline again only to record an improvement: a count that rose is a finding to fix, not a number to raise.
- **The tools.** `ruff` and `mypy` are the `dev` extra of `pyproject.toml`, pinned, with a lock of their own
  (`requirements-dev.lock`, written by `scripts/lock --dev`): they are run on the code and never shipped. Without
  them the `lint` and `typecheck` steps are skipped and print the line that installs them; CI sets
  `CHECK_LINT=required` and `CHECK_TYPES=required`.

## The token guard

`tests/guards/grep_tokens.py` (`scripts/check --only tokens`) keeps the tree free of the places it was used in. It reads the
files git knows (tracked, or new and not ignored), so a file is checked before its first commit and a scratch file git
ignores never fails it. It has two
layers:

- **Word lists**, over the product folders: the fixture packs' names (`tests/guards/forbidden-tokens.txt`, allowed only under
  `packs/` and the test data) and AI vendor names (`tests/guards/ui-vendor-names.txt`, in any letter case).
- **Shape rules**, over every tracked file and its name:

  | Rule | What it refuses |
  |---|---|
  | `ticket-key` | a tracker key with four or more digits outside the fixture prefixes (`TASK-`, `ACME-`, `NORTH-`, `DEMO-`) and public advisory ids |
  | `fixture-key` | a fixture key with five or more digits: fixtures use `TASK-101` |
  | `pr-number` | `<repo>#<three or more digits>`, or `(#<four digits>`: fixtures use numbers under 100 |
  | `card-id` | a board card id (`t_` and eight hex digits) other than `t_00000001`…`t_00000009` |
  | `home-path` | a path under a person's home folder |
  | `host-filename` | a file named after a machine |
  | `dated-note` | an ISO date in a comment or a docstring of code: a comment states the rule, not the day it was learned |
  | `process-word` | a word of one team's product or stack, listed in `tests/guards/process-words.txt` |

An exception is one exact line of one file in `tests/guards/token-allow.txt`, under a `reason:` line. An entry without a
reason fails the guard, and so does an entry whose line is gone. Fix a failure by rewording; add an exception only for
an identifier the code must match against the machine (a program name on `PATH`, a provider id, a file name), kept in
one named table.

The real names of adopters are never committed. Locally, `COCKPIT_EXTRA_TOKENS=<file>` names a file of them, one per
line, and the guard reads it over the tests too; a hit prints the name's place in the list, never the name. In CI the
text comes from the repository secret `EXTRA_TOKENS`: `scripts/check` writes it to a file of that run and names it to
the guard. A push to the default branch fails when the secret is empty; a pull request from a fork has no secrets and
runs with the committed lists and the shape rules.

## Generated files

`scripts/gen` writes `docs/reference/*.md` and `kernel/schema/*.schema.json` from the code, and `scripts/gen --check`
fails when a committed one is stale. Never edit them by hand: change the table they come from. `scripts/gen-pointers`
does the same for the entry files that point a coding assistant at `AGENTS.md`. The `generated` step of `scripts/check`
runs both checks.

## The version

`plugin.yaml` states the version (it is what Hermes reads). `pyproject.toml`, `kernel/cockpitlib/__init__.py` and
`dashboard/manifest.json` must state it literally for their own tools, and a structure test holds them equal
(`scripts/bump --check`). `scripts/bump 1.2.3` writes all of them and moves the changelog's Unreleased entries under a
heading for that version with today's date. Nothing else states a version.

## Dependencies

`pyproject.toml` declares what the code imports at run time (`dependencies`), what only the tests need (the `test`
extra) and the tools that read the code (the `dev` extra, locked apart in `requirements-dev.lock` by
`scripts/lock --dev`); a structure test reads the imports and holds the first two lists to them. `scripts/lock` resolves both for every
supported Python and system and writes `requirements.lock` and `requirements-test.lock` with the hash of every release
file; `scripts/lock --check` reads them offline. After a change to a dependency, run `scripts/lock` and commit both
files. CI, the release and the self-update install from the lock:
`pip install --require-hashes -r requirements-test.lock && pip install --no-deps -e .`

Every dependency's licence must be one the project can be distributed with: [dependencies.md](dependencies.md) lists
each locked package with its licence, and a structure test fails on one outside the list.

## Copyright and licence of a file

The project is under AGPL-3.0-or-later (`LICENSE`, `NOTICE`). A source file states the copyright holder and the licence
in two comment lines at its top, after a shebang; `scripts/headers --write` adds them by file type and
`scripts/headers --check` names a file without them. Files that cannot carry a comment or must not (Markdown, JSON,
line-oriented data, lock files, generated and built files, the starter that becomes a user's own pack) are covered by
`REUSE.toml`. A structure test holds that every tracked file is covered one way or the other.

Two entries of `REUSE.toml` name another licence than the project's, and a structure test allows exactly these two:
the Desktop bundle (`AGPL-3.0-or-later AND MIT`, for the terminal widget it carries) and the starter pack under
`starter/` (`0BSD`), so that the files `cockpit init` copies into a user's pack are the user's own.

## A release

A release is a signed tag `v<version>` pushed to the repository; `.github/workflows/release.yml` does the rest. It
verifies the tag's signature against the signers held in the repository variable `RELEASE_SIGNERS` (ssh allowed
signers) or `RELEASE_GPG_KEYS`, runs `scripts/check`, writes the Python and npm dependency sets as CycloneDX SBOMs, and
publishes a release whose notes are the changelog's section for that version (`scripts/bump --notes <version>`), with
the source archive, the SBOMs and a signed build provenance for each file. Only its last job can write, and that job
runs no code of the repository.

The other workflows: `ci.yml` (the one command, on every push and pull request), `respond.yml` (the comment on a pull
request), `codeql.yml` (static analysis) and `scorecard.yml` (the OpenSSF Scorecard). Every action is pinned to a commit
with its version beside it, every workflow states its permissions, and a structure test holds both
(`tests/test_every_workflow_is_pinned_and_holds_the_least_it_needs.py`): a new workflow is listed there with the jobs
that may write.

## Adding a doctor check

1. Register it in `CHECKS` in `doctor.py`: an id, its tier, whether it guards a boundary, and the fix line.
2. Add its line in `doctor._collect` with `add("<id>", <message>)`.
3. A security check is an error and goes on `tests/contract/doctor-security.json`; a check never leaves that list
   without the owner.
4. Run `scripts/gen`: `docs/reference/doctor.md` follows the registry and the messages.
