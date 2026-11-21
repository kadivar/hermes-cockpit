---
name: contribute
description: Change this repository the way its maintainers will accept. Modes - triage (classify a wish on the genericity ladder, no edits), report (a bug as one failing known_bug test, no fix), fix (a bug with its test), feature (a pack key, a verb, a route or a page, at the lowest rung that works), check (run scripts/check and read its result), pr (open or update the pull request, then read it back from the forge).
---

# Contribute

This project takes **no issues**. A bug, an idea or a question arrives as a pull request, however rough: the
maintainers finish it. Your job is to make that pull request small, generic and proven.

Two rules outrank everything below:

- **Never report a pass you did not see.** A check counts only when you ran it in this session and read its last line.
  What you did not run goes under "Not verified", in words.
- **Stop and say so instead of guessing.** When a step cannot be done as written (a file is missing, a command is
  refused, the wish fits no rung), stop, say which step and why, and ask. Do not improvise around a rule.

## Modes

| Mode | Invocation | Edits | Ends with |
|---|---|---|---|
| `triage` | `contribute triage <the wish, in the user's words>` | nothing | the rung, the reason, and the next mode |
| `report` | `contribute report <what goes wrong>` | one new file under `tests/reports/` | the `BUG` line of a green run |
| `fix` | `contribute fix <the bug or the report file>` | the code, its test | `CHECK pass`, the failing output from before |
| `feature` | `contribute feature <the wish>` | what the rung allows, its tests, its docs line | `CHECK pass`, the rung and why not the one below |
| `check` | `contribute check` | nothing | the last line of `scripts/check` and each failure read |
| `pr` | `contribute pr` | the pull request only | the pull request's address, read back from the forge |

`report`, `fix` and `feature` each start with `triage`. No mode skips it.

## The genericity ladder

Every wish is placed on this ladder **from rung 1, stopping at the first yes**. The lower the rung, the fewer people
your change can break. A rung is skipped only with a written reason why it cannot work.

1. **PACK RECIPE: can a pack already do this?** A pack is an organisation's own settings, scripts, skills and souls.
   Look before you answer: `cockpit pack explain <key>` for any key that sounds close, `cockpit describe --json` for
   the verbs and intent types, `docs/reference/pack-keys.md` for every key with its meaning, `docs/customize/` for
   the recipe of each extension point, `starter/` for a working script per command contract, and the two fixture
   packs under `packs/` for a working example. If yes: answer with the pack lines and the script.
   **No pull request**, or a docs pull request when the recipe was written nowhere.
2. **PLUGIN: can another Hermes plugin do it?** Through `cockpitlib.plugin_api` (its functions and signatures are in
   `tests/contract/cockpit-api.json`), a card kind, a kickoff mode, a page of its own, or its own `plugins.<name>`
   block in the pack. If yes: it lives **outside this repository**. A pull request here only when the API lacks one
   function, and then it adds that function and nothing else.
3. **PACK KEY: is it a name, a policy or a command that differs between organisations?** Then it is a new key whose
   absence means **exactly today's behaviour**: a registry entry, a validator, a test with the key absent on both
   fixture packs and a test with it set on a copy of each.
4. **KERNEL: does the kernel contradict its own documented intent, or crash?** Quote the sentence it contradicts: a
   docstring, a `README.md` or `docs/` sentence, a refusal message. **No quote, no kernel change.** A crash needs no
   quote, but it needs the traceback.

**None fits:** do not write code. Add `docs/proposals/<slug>.md` (the wish, who else would want it, the rungs you
tried and why each failed, the smallest shape you can think of) and open that as a proposal pull request.

### Signs you are a rung too high

Go back down the ladder when your patch contains any of these:

- a product, vendor, host, label, team or tracker-status name, in code, a comment, a test or a doc;
- an `if` on a pack's name, or on anything that identifies one organisation;
- a new dependency in `pyproject.toml` or `desktop/package.json`;
- a default that changes what an existing pack does;
- a change in `kernel/` with no quoted sentence behind it;
- a new file under `skills/` or `souls/` (they are registered into every adopter's lanes: that is a kernel change).

### Worked examples

**A team wants its own tags on review comments to count as findings.** Rung 1: the key `finding_labels` already
lists the tags that mark a comment as a finding, and the key `forge.tagged_comments_only` decides whether an untagged
comment asks for work. Answer with those two pack lines. If the team needs a behaviour no key gives (say, one tag
that never asks for work), that is rung 3: a new key, absent meaning today's behaviour. **Never** a tag written into
the kernel.

**Someone wants another code host.** The kernel reaches the forge through one module
(`kernel/cockpitlib/forge.py`, reads in `kernel/cockpitlib/gh_cli.py`). Which host an organisation uses differs between
organisations, so this is rung 3, the way the key `tracker.kind` already chooses how the tracker is reached. But it
is large: **proposal first** (`docs/proposals/<slug>.md`), naming the functions the interface needs and how every
read-back stays a read-back. No host name appears outside the one adapter and its tests.

**The standup note crashes on a day without records.** Rung 1 to 3 cannot fix a crash. Rung 4, with the quote:
`kernel/cockpitlib/standup_note.py` says the note is "what the platform did since the window opened, read from the
records that already exist". A day with no records is still a day: the documented intent is an empty note, and the
code raises. First the failing test (mode `report` or step 3 of `fix`), then the smallest change that makes it pass.

## Mode: triage

MANDATORY steps, in order:

1. Restate the wish in one sentence that names no organisation: "a pack can …" or "the kernel … when …".
2. Classify it: `bug` (the code breaks a rule it states), `wish` (new behaviour), `question` (answer it; if the answer
   was written nowhere, that is a `docs` change), or `security` (stop: see step 6).
3. Walk the ladder from rung 1. For each rung write one line: yes or no, and the evidence (the key, the API function,
   the fixture pack line, the quoted sentence). Run the lookups; do not answer from memory.
4. Check `scripts/check --reports` and `docs/proposals/` for the same thing already filed.
5. Name the next mode: `report`, `fix`, `feature`, a docs change, a proposal, or "no pull request: here is the recipe".
6. A way to make something leave the machine without the human, to read a stored secret, or to loosen a check is a
   security report. It is never filed in public: follow `SECURITY.md` and stop.

Do not edit any file in this mode.
Do not classify a wish as rung 4 without the quoted sentence or the traceback.
Do not skip a rung because the higher one is quicker to write.

Required output: the one-sentence wish; the classification; one line per rung; the chosen rung and why not the rung
below; the next mode.

## Mode: report

A bug report is a pull request that adds one failing test. `tests/reports/README.md` is the reference.

1. Run `triage`. Continue only for a `bug`.
2. Reproduce it in a test, not in prose. Create `tests/reports/test_<behaviour sentence>.py` with one test function
   that states the rule that should hold, using a plain `assert`.
3. Mark it `@pytest.mark.known_bug("<file:line>", "<what happens today>")`: where the bug is, and one sentence.
4. Run it: `TEST_WORKERS=0 scripts/test tests/reports/<your file>`. It must end green and print
   `BUG <test id> (<where>): <what>`. An error instead means the test is broken, not the code: fix the test.
5. Run `scripts/check --quick`. Read the last line.

Do not fix the bug in the same pull request: the report merges first, on its own.
Do not use the marker outside `tests/reports/`, and do not put a plain test inside it.
Do not write a report for something the test cannot show failing. Say what you could not reproduce and stop.

Required output: the report file's path, the `BUG` line as printed, the last line of `scripts/check --quick`.

## Mode: fix

1. Run `triage`. Continue only for a `bug` on rung 4, or a bug in a test, a script or a doc.
2. Find the report under `tests/reports/` if there is one. If there is none, write the failing test first, in
   `tests/`, named for the behaviour (see "The test recipe"). **Run it and keep the failing output.**
3. Make the smallest change that makes it pass. Touch nothing the test does not need.
4. If a report existed: remove its `known_bug` marker and move the file from `tests/reports/` into `tests/`. The run
   tells you to when the bug is fixed.
5. Run the tests of the area (the repo map names them), then `scripts/check`. Read the last line.
6. Walk "Compatibility" and "The invariants" below and write one sentence for each in the pull request.

Do not change a test so that it passes. A test that was wrong is its own change, with the reason.
Do not refactor, rename or reformat beside the fix.
Do not widen the fix into a feature. A second wish is a second pull request.

Required output: the test's name, its failing output before the change, `CHECK pass` after it, what was not verified.

## Mode: feature

1. Run `triage`. Continue only on rung 3, on rung 2's "one additive API function", or with a maintainer's written
   yes on a proposal.
2. Follow the recipe of the rung:
   - **A pack key.** `KNOWN` and a `_<key>(data)` validator in `kernel/cockpitlib/pack.py` (its `PackError` states
     the valid shape), called from `_load`; an entry in `kernel/cockpitlib/pack_keys.py` (path, type, default, one
     sentence, an example); a default applied where the key is read goes on `tests/contract/pack-defaults.json`.
   - **A CLI verb.** `cmd_<verb>(argv) -> int` in `kernel/cockpitlib/cli.py`, an entry in `EXAMPLES` and in `FLAGS`
     (or `SELF_PARSED` / `ZERO_ARGS`), registration in `COMMANDS`. Every example must parse and every verb must
     refuse an unknown flag with exit 2; `tests/contract/describe.json` pins the list.
   - **A route.** A nested `@router.get/post` inside `mount()` in `dashboard/cockpit/routes/pages.py`, also listed in
     `dashboard/routes.contract.json`. An act goes through the same human gate as its verb.
   - **A plugin API function.** In `kernel/cockpitlib/plugin_api.py`, additive only, with `tests/contract/cockpit-api.json`
     updated in the same commit. A changed signature is not additive: stop and propose.
   - **A page change.** Under `desktop/src`; then rebuild (see "Regenerate").
3. Write the tests of "The test recipe". For a pack key: absent on both fixture packs (today's behaviour, asserted),
   and set on a copy of each.
4. Write the one place a user will look: the registry sentence for a key, the `EXAMPLES` line for a verb, a page under
   `docs/` for a recipe.
5. Regenerate (see "Regenerate"), then run `scripts/check`. Read the last line.
6. Walk "Compatibility" and "The invariants" and write one sentence for each in the pull request.

Do not add a key, a verb or a route "for later". Each one is kept forever.
Do not rename anything public unless the task is the rename; then change the name everywhere at once and keep no alias.
Do not add a dependency. If you believe one is needed, stop and propose.
Do not name an organisation's product, host, label or status in code, tests or docs.

Required output: the rung and why not the rung below; the new public names; the tests by name; `CHECK pass`; what
was not verified.

## Mode: check

1. Run `scripts/check` (or `scripts/check --quick` while you are still editing). It runs, cheapest first: `env`,
   `generated`, `tokens`, `lint`, `typecheck`, `structure`, `security-surface`, `tests`, `coverage`, `dashboard`,
   `desktop`. `lint` (`ruff`) and `typecheck` (`mypy`) are skipped with a note when the tool is not installed
   (`requirements-dev.lock` installs both); CI requires them, so install them before you report a pass.
2. Read the **last line**: `CHECK pass` or `CHECK fail · <ids>`. Nothing else is the verdict.
3. For each failed id, read its failures (add `--json` and read `check-result.json`: each has `test`, `file`, `line`,
   `message` and a `rerun` command). Fix the cause, then run that `rerun` command.
4. When every failed id passes alone, run the whole `scripts/check` once more.
5. On a laptop the suite takes minutes and every core you give it. `--workers N` sets how many; do not raise it
   above the default without asking the human.

Do not report `CHECK pass` from a run with `--only` or `--quick` as the result of the whole check. Name what you ran.
Do not use `CHECK_TEST_ARGS` for a result you report: it narrows the suite and is for trying the script.
Do not silence a failure: no skip, no marker, no lowered gate, no deleted test.

Required output: the command you ran, its last line verbatim, and for a failure the ids and what you changed.

## Mode: pr

Run this mode only when the human asked for a pull request. It needs `git` and the forge's command line (`gh`),
signed in as the human.

1. Run mode `check` in full. Continue on `CHECK pass`, or on a failure the pull request itself states under
   "Not verified" (a report pull request is green by construction).
2. Commit on a branch of your fork, never on the default branch. Subject: one present-tense behaviour sentence
   ("An empty day still gives a standup note"), not an imperative, no prefix. Body: what was wrong, the change as
   `module.function: rule` lines, a `Tests:` line with the commands you ran and their counts, a `Not verified:` line.
3. Fill `.github/pull_request_template.md` completely (see "The pull request standard"). Write the body to a file.
4. Push the branch and open the pull request with "allow edits by maintainers" on (`gh pr create --body-file <file>`),
   or update the open one (`gh pr edit <number> --body-file <file>`). When the forge cannot be reached, print the
   title and the body and say that nothing was opened.
5. **Read it back from the forge**: `gh pr view <number> --json url,title,body,headRefOid,maintainerCanModify`.
   Compare `headRefOid` with `git rev-parse HEAD`, the body with your file, and `maintainerCanModify` with true.
6. Wait for the first response: one comment that carries `<!-- cockpit-check v1 -->` followed by a JSON block
   (`verdict`, and under `cells` one entry per CI cell in the shape of `check-result.json`). Read it with
   `gh pr view <number> --json comments`. For a failure, go to mode `check`, push the correction and repeat from
   step 5.

Do not open a pull request for a security problem. Follow `SECURITY.md`.
Do not open an issue, on any repository, for this project.
Do not claim the pull request exists until step 5 has shown it to you.
Do not mark a tick box the human has not confirmed (the licence grant is theirs to give, see `CONTRIBUTION-TERMS.md`).

Required output: the address step 5 returned, the head commit it shows, the check result, and "Not verified".

## The repo map

| You are changing | Look in | Its tests |
|---|---|---|
| a pack key, how a pack loads | `kernel/cockpitlib/pack.py`, `kernel/cockpitlib/pack_keys.py`, `kernel/cockpitlib/pack_effective.py` | `tests/test_the_key_registry_matches_the_validators.py`, `tests/test_no_default_hides_from_the_registry.py`, `tests/test_a_pack_prints_its_effective_settings.py` |
| a CLI verb | `kernel/cockpitlib/cli.py`, `kernel/cockpitlib/describe.py` | `tests/test_both_packs.py`, `tests/test_the_kernel_describes_itself_as_data.py` |
| intents, the outbox, the gate | `kernel/cockpitlib/intents.py`, `kernel/cockpitlib/outbox.py`, `kernel/cockpitlib/gate.py` | `tests/test_outbox_rules.py`, `tests/test_gatekeeper.py` |
| publishing and its read-back | `kernel/cockpitlib/publish.py`, `kernel/cockpitlib/forge.py`, `kernel/cockpitlib/tracker.py` | `tests/test_publish_read_back.py`, `tests/test_what_was_endorsed_is_what_is_published.py` |
| what a lane may run | `kernel/cockpitlib/egress.py`, `kernel/cockpitlib/fence.py`, `hooks/egress.py` | `tests/test_fence_rules.py`, `tests/test_the_push_deny_reads_gits_own_options.py` |
| seats, setup, doctor | `kernel/cockpitlib/setup.py`, `kernel/cockpitlib/doctor.py`, `kernel/cockpitlib/lanes.py` | `tests/test_seat_setup.py`, `tests/test_seat_and_stack.py`, `tests/test_doctor_sorts_what_it_finds_into_errors_and_warnings.py` |
| a first pack (`cockpit init`), the starter pack | `kernel/cockpitlib/scaffold.py`, `starter/` | `tests/test_init_writes_a_pack_only_when_asked.py`, `tests/test_init_scaffold_loads.py`, `tests/test_starter_pack.py` |
| the documentation, the generated references | `docs/`, `scripts/gen` | `tests/test_every_link_in_the_docs_points_at_a_file.py`, `tests/test_generated_docs_are_current.py` |
| cards, kickoff, the board | `kernel/cockpitlib/kickoff.py`, `kernel/cockpitlib/registry.py`, `kernel/cockpitlib/kanban.py` | `tests/test_card_lifecycle.py`, `tests/test_lane_card.py` |
| watchers (CI, pull requests, tracker) | `kernel/cockpitlib/ci_watch.py`, `kernel/cockpitlib/pr_watch.py`, `kernel/cockpitlib/housekeeping.py` | `tests/test_watchers.py`, `tests/test_watch_rules.py` |
| notifications, the standup note | `kernel/cockpitlib/notify.py`, `kernel/cockpitlib/standup_note.py`, `kernel/cockpitlib/window.py` | `tests/test_effects.py`, `tests/test_panes.py` |
| the vault, logins, secrets | `kernel/cockpitlib/vault.py`, `kernel/cockpitlib/vault_book.py`, `kernel/cockpitlib/scrub.py` | `tests/test_vault.py`, `tests/test_vaultbook.py`, `tests/test_logins_and_lends.py` |
| slots and worktrees | `kernel/cockpitlib/slots.py`, `kernel/cockpitlib/worktree.py` | `tests/test_slot_runtime.py`, `tests/test_worktree_checkouts.py` |
| the plugin API | `kernel/cockpitlib/plugin_api.py`, `tests/contract/cockpit-api.json` | `tests/test_plugin_api.py`, `tests/test_a_plugin_built_for_an_older_api_still_loads.py` |
| an HTTP route | `dashboard/cockpit/routes/pages.py`, `dashboard/routes.contract.json` | `tests/test_routes.py`, `tests/test_views.py` |
| the Desktop page | `desktop/src`, the committed `desktop/plugin.js` | `desktop/test/rules.mjs`, `tests/test_bundle.py` |
| updating an installation | `kernel/cockpitlib/self_update.py` | `tests/test_selfupdate.py`, `tests/test_an_installation_can_be_rolled_back.py` |
| records on disk | `kernel/cockpitlib/store.py`, `kernel/cockpitlib/paths.py`, `scripts/replay` | `tests/test_a_replay_proves_two_kernels_read_the_same_records.py`, `tests/test_a_ticket_key_never_names_a_path.py` |
| what lanes are told | `skills/`, `souls/`, `prompts/` | `tests/test_foundations.py` |
| a fixture pack | `packs/` | every test that takes `PACKS` from `tests/support/both_packs.py` |
| a bug report | `tests/reports/` | `tests/test_a_bug_report_is_a_test_that_fails_as_declared.py` |
| this skill, the entry points | `.agents/skills/contribute/SKILL.md`, `AGENTS.md`, `scripts/gen-pointers` | `tests/test_contribute_skill.py`, `tests/test_ai_entry_points.py` |

Each module opens with a docstring that states its rule. Read it before you change the module: it is the "documented
intent" rung 4 asks you to quote.

## The test recipe

- **A new file named for the behaviour**: `tests/test_<behaviour sentence>.py`, such as
  `test_an_empty_day_still_gives_a_standup_note.py`. Do not append to a large existing file.
- **A test name is a full behaviour sentence**: `test_a_missing_ticket_is_not_invented`.
- **Take `env` or `bare`** from `tests/conftest.py`: `env` is a workspace with the fixture repositories, `bare` the
  same without them, for a test that never touches a checkout. No test reads the machine's own installation.
- **Where the pack matters, run over both fixture packs** and derive every identifier from the pack itself:

  ```python
  from tests.support.both_packs import PACKS

  @pytest.mark.parametrize("pack_file", PACKS)
  def test_a_pack_without_the_key_behaves_as_before(env, pack_file, monkeypatch):
      monkeypatch.setenv("COCKPIT_PACK", pack_file)
      pack = load(pack_file)
      ticket = f"{pack['tracker']['project']}-100"      # never a literal from one pack
  ```

- **Assert behaviour**, not that lines ran. The gate counts lines and branches of `cockpitlib` and
  `dashboard.cockpit`, and its figure is `fail_under` in `pyproject.toml`: every new decision needs a test for each
  side, one that would fail without it.
- **A function stays small**: at most 15 decisions and 80 lines. A function that is already over is listed in
  `tests/contract/complexity.json` and may not grow; do not add to that list, split the function.
- **A file gains no type error**: `tests/contract/type-errors.json` counts what each file has. Fix a new one; never
  add `# type: ignore` or raise a count. A line that must keep a lint finding says why: `# noqa: <rule> - <reason>`.
- **Generic data only**: `TASK-100`, `example.test`, `dev@example.test`.
- A test of the repository itself (a file exists, a list matches) carries `pytestmark = pytest.mark.structure`.

## Compatibility

Two rules: a pack that loads today loads tomorrow and does the same, and a record written today is read tomorrow.

- **One name for one thing.** A public name (pack key, intent type, CLI verb, flag, environment variable, route,
  record file name) has one spelling. A rename is a breaking change: it changes the name everywhere in one change,
  keeps no alias, is listed under "Removed" in `CHANGELOG.md` and, for a pack key, is declared in
  `UPDATE-CHANGES.json` so an update says which key a pack must rewrite.
- **A removed key is a refusal**, never a silent ignore: the pack does not load, and the error is the ordinary
  `unknown key <name>`.
- **The plugin API is additive.** A new function, or a new argument with a default that means "as before". Anything
  else raises `API_VERSION`, which is the maintainers' decision: stop and propose.
- **Records stay readable.** Never rewrite a record on disk to a new shape; read both shapes. `scripts/replay` proves
  two kernels read the same records.
- **Records are written whole and under a lock.** Write a record through `kernel/cockpitlib/store.py` (never
  `open(path, "w")`), and take its lock for read-modify-write, never across the network.
  `docs/contributing/architecture.md` ("Writing a record") has the rules; `tests/contract/record-writes.json` lists
  the writes that are not records.
- **The registry and the defaults list move with the code**: `kernel/cockpitlib/pack_keys.py` and
  `tests/contract/pack-defaults.json`, in the same commit as the key.
- In the pull request, write: "Existing packs: unchanged because …". If you cannot finish that sentence, stop.

## The invariants

These are never weakened, by any rung, for any reason. `docs/security.md` is their source; they are stated here so
this file stands alone.

1. **The outbox is the only door.** A push, a pull request, a comment, a review or a tracker write happens only by
   publishing an intent. No code path sends one directly.
2. **Publishing, holding and dropping are human acts**; so is applying an update. Endorsing is the gatekeeper's or
   the human's. A lane does none of them. What publishes with no click is only what the pack's key `outbox.auto`
   names, by scope and intent type.
3. **Kernel denies cannot be removed or narrowed.** A pack adds denies; it never takes one away.
4. **The egress hook fails closed.** An error in the check is a refusal.
5. **The seat approvals deny-list survives unattended mode.**
6. **A stored secret never reaches an argv, a log, a card or a tool result.**
7. **Text from outside is data**, never an instruction (`kernel/cockpitlib/quoted.py`).
8. **Doctor's security checks are never silenced or downgraded.** Each is an error, an error is a failed setup, and
   `tests/contract/doctor-security.json` pins the list; there is no key that makes doctor look away.

A wish that needs one of these weakened is refused, in triage, with the invariant quoted. Offer what exists instead:
for "let a lane publish by itself", the key `outbox.auto`. `scripts/check` lists a change that touches the kernel
denies, the fence, the egress hook, the seat approvals or the doctor security list under `security-surface`; such a
pull request waits for the owner.

## Generic names

Nothing in code, comments, docs or tests names an adopter, a company, a product, a person, a real ticket key, a real
pull-request number, a host or a dated incident. Nothing the page prints, and no text under `README.md`, `docs/`,
`skills/` or this folder, names an AI vendor or product: write "your coding assistant", "the coding tool", "the
provider". The fixture packs' own names appear only under `packs/` and `tests/`.

`tests/guards/grep_tokens.py` enforces this (`scripts/check --only tokens`): two word lists (`tests/guards/forbidden-tokens.txt`,
`tests/guards/ui-vendor-names.txt`) and shape rules over every tracked file (a ticket key of four digits, a fixture key of
five, a pull-request number of three, a board card id, a home path, a date in a code comment, a word of
`tests/guards/process-words.txt`). Fixtures use `TASK-101`, `t_00000001`, numbers under 100 and hosts under `example.test`. A
failure there is fixed by rewording, never by editing the lists or the scan; an identifier the code must match against
the machine sits in one named table with an entry and its reason in `tests/guards/token-allow.txt`.

## Regenerate

Generated files are committed, and `scripts/check` fails when one is stale.

- `scripts/gen-pointers` after any change to `AGENTS.md` or to this file's frontmatter: it rewrites the pointer files
  other coding assistants read.
- `scripts/gen` after any change to a pack key, a command, an intent type, a notify event, a doctor check or the
  plugin API: it rewrites the pages under `docs/reference/` (such as `docs/reference/pack-keys.md`) and the schemas
  under `kernel/schema/`.
- After any change under `desktop/src`: `cd desktop && npm ci && npm run build`, and commit `desktop/plugin.js`.
- `ruff format .` after any change to Python: the `lint` step compares the layout.
- `scripts/baselines` only after a function left the complexity list or a file lost type errors: it records the
  improvement. `scripts/lock --dev` after a change to the `dev` extra.

Never edit a generated file by hand.

## The pull request standard

The template is `.github/pull_request_template.md`. Every section is filled; "none" is an answer, a blank is not.

- **Title**: one present-tense behaviour sentence. "A pack can name its own finding tags", not "Add tags support".
- **Kind**: report, fix, feature, docs or proposal. One kind per pull request.
- **Rung**: the rung you stopped at, and why the rung below could not do it.
- **Evidence**: the tests by name; for a fix, the failing output from before the change.
- **Compatibility**: "Existing packs: unchanged because …" and "Nothing is looser: …".
- **Check**: the last line of `scripts/check`, verbatim, and the command if it was not the whole check.
- **Not verified**: everything you did not see with your own run. This section is never empty by default.
- Two tick boxes, both the human's: the contribution is licensed to the Maintainer (`CONTRIBUTION-TERMS.md`; left open, the pull request is a report and is not merged), and edits by maintainers are allowed.

`CONTRIBUTING.md` says the same for people.

## If your shell command is refused with "outside the lanes"

On a machine that runs this plugin, an editor fence refuses a coding assistant's shell commands that look like vault,
slot or publish use. It reads the command's text, so even a read of a file whose path matches is refused (the rule is
`kernel/cockpitlib/fence.py`). This is the product working, not a fault in your change.

- Do not set `COCKPIT_HUMAN` or `COCKPIT_LANE` in your shell, and do not look for another way around it.
- Read the file with your file-reading tool instead of the shell.
- Run tests through `scripts/check` or `scripts/test`: the tests run in a workspace of their own.
- If the work truly needs the refused command, stop and ask the human to run it.
