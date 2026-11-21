# Changelog

What changed, for someone who runs cockpit. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Before 1.0, a pack key may change; each change is listed here with what to write instead.

## [Unreleased]

### Added

- **Personal values.** In any value of a pack's YAML files `{home}` is the reader's home folder and `{local.<name>}`
  is the value an optional `pack.local.yaml` beside `pack.yaml` gives that name, so one pack is shared unchanged and
  each person keeps their login, branch prefix and folders in a file of their own; a soul takes `{{HOME}}`.
  `cockpit init` writes `pack.local.example.yaml` and a `.gitignore` for the real file. A pack that uses neither token
  and has no such file behaves as before. See `docs/customize/personal-values.md`.
- **`cockpit demo gate`** plays one ticket through the outbox gate in a sandbox under the temp folder, with no Hermes,
  no code-host account and no tracker: a lane's own `git push` is refused, then intent, verify, endorse and the human's
  send. See `docs/demo.md`.
- **A tracker protocol.** `tracker.kind: local` keeps tickets as files; `tracker.browse_url` is a ticket's page as a
  template; a tracker command may answer reads (`tracker.reads: [comments, me, status]`), which turns the comment watch
  on for it. A pack that sets none of these behaves as before.
- **GitHub Issues as the tracker.** `tracker.kind: github-issues` makes the issues of one repo the tickets: `GH-12` is
  issue 12, read and written through the code host the pack already publishes to (with `forge.kind: local`, through
  files). `tracker.status_labels` and `tracker.closed_statuses` carry more statuses than Open and Closed as labels.
  `cockpit init --tracker github-issues` writes it. See `docs/customize/tracker-github-issues.md`.
- **A key registry.** Every key a pack may set is listed as data, with its shape, its default and one sentence on what
  it does. It is held against the validators, both fixture packs and the code that reads each key.
- **`cockpit pack effective`** prints every setting of the bound pack with the value in force and where it came from;
  **`cockpit pack explain <key>`** prints one key with its meaning.
- **`cockpit describe --json`**: the kernel's commands, intent types, kickoff modes and card kinds as data, for a tool
  that would otherwise read the source.
- **`cockpit update apply --to <commit>`** stops an update at a named commit, and **`cockpit update rollback`** moves
  the installation back, never below a release's floor.
- **`cockpit update rehome <url>`** moves an installation to another repository that holds the installed tree, without
  changing a working file; `--dry-run` compares and reports, and `--undo` takes the move back.
- **Release automation**, as files that take effect in a public repository: weekly dependency updates, static
  analysis, the OpenSSF Scorecard, and a release from a signed tag with SBOMs and build provenance.
- **The Chat pane's terminal widget is part of the bundle.** It was fetched from a content network each time the pane
  opened; now the page loads nothing at run time. `THIRD-PARTY-NOTICES.md` names what the bundle carries.
- **Hashed lock files** (`requirements.lock`, `requirements-test.lock`, written by `scripts/lock`): CI, a release and
  the self-update install from them, every file checked against its recorded hash. `jsonschema` and `httpx` moved to
  the `test` extra: no run-time code imports them.
- **Updates can require a signed tag** (opt-in): with signers named in a tracked `UPDATE-SIGNERS` file or in
  `COCKPIT_UPDATE_SIGNERS`, only a tag one of them signed is offered and applied. Without them nothing changes.
- **An update pre-flight.** The incoming commit is run against the live pack before the checkout moves, and an update
  that would change a setting's value without declaring it is refused.
- **`scripts/replay`** proves that a new kernel reads an installation's real records exactly as the running one does.
- **Generated references**, written from the code by `scripts/gen`: pack keys, commands, intents, notify events,
  doctor's lines, the plugin API, and JSON schemas of the pack files for editor completion.
- **Documentation**: a short README, concepts, a quickstart, the security model, operations pages, and one recipe per
  extension point.
- **`cockpit init`** writes a first pack for a workspace: it detects the repos, their base branches and the test
  commands their files suggest, prints the files it would write, and writes nothing without `--write`. It never
  replaces a file, never guesses what production is (`--production-host` or `--no-production`), and binds the
  workspace last, once the pack loads.
- **A starter pack** under `starter/`: seven generic skills, a common soul and one working script for each of five
  command contracts (notify, tracker, verify, helper, slot). `cockpit init` copies it into the new pack.
- **Neutral names.** A pack names its forge and its tracker as `forge.org`, `tracker.url` and `tracker.project`; a
  tracker intent is typed `tracker-comment`, `tracker-create` or `tracker-transition`; the tracker kind for Jira's
  REST API is `jira`; and a diff against the base branch is asked as `base`. Each has that one name.
- **Doctor checks for a first installation**, each a warning: the coding tool's program, the programs a failure video
  needs, the code host's command line (and, with `--online`, its sign-in), a notify key no kernel code sends, an
  unset tracker credential variable, a repo folder that is not there, and a Python without PyYAML.
- **`scripts/check`** runs everything CI runs as one command, cheapest first, and ends with `CHECK pass` or
  `CHECK fail` and the failed steps. CI runs exactly that.
- **A linter, a formatter and a type checker**, as steps of `scripts/check` that CI requires: `ruff` holds the rules
  and the layout (`[tool.ruff]` in `pyproject.toml`), and `mypy` runs as a ratchet: a file may have as many type errors
  as `tests/contract/type-errors.json` counts for it and no more. The whole Python tree was formatted once, with no
  change in meaning.
- **A complexity ratchet.** No function may grow past 15 decisions or 80 lines; the ones already over are listed in
  `tests/contract/complexity.json` and the list only shrinks. `scripts/baselines` writes both baselines.
- **Doctor names three more things**: an entry of `terminal_deny` or `production_hosts` that is no regular expression
  (a security error), a list of `egress.yaml` or a repo's `gates` written as one text (a warning), and a Hermes patch
  release older than the one `plugin.yaml` asks for (an error).
- **The Desktop pages can be used from the keyboard.** A clickable row, tile or card takes Tab and answers Enter and
  Space, and a button that shows only a sign has a name.
- **`cockpit pack pin`** prints the lines a pack adds so that a default which is going to change no longer decides
  anything for it (`--all`: any default). It never writes. The defaults listed for change are in
  `kernel/cockpitlib/pending_defaults.json` (none today), and `cockpit pack effective --sources` marks the values
  that come from one. See `docs/operations/pinning.md`.
- **A pack words its test reports and names its run files**: `testflow.title`, `testflow.banners` (`ok`, `not_ok`,
  `in_progress`), `testflow.evidence_dir`, `testflow.plan_file` and `testflow.results_file`. Each has a
  plain default, and a report is read back by the same words it is written with.
- **A pack words its standup note**: `standup.sections` (a heading per section; an empty one hides it),
  `standup.order` and `standup.chat_file`. A pack without the block gets the kernel's plain headings.
- **The comment ids of an earlier pipeline's watch records are read by the pack's mapping**: `migrate.yaml`
  `records.watch_id_prefixes`; a pack that names none has none. A `migrate.yaml` that cannot be
  read stops the PR watch's pass with a health line instead of announcing old comments as new.
- **The pages' help texts that name a team's skills are the pack's**: `desktop.hints` (`review`, `bumps`, `bumps_tab`,
  `rereview`, `bumps_start`), each defaulting to words that name no skill.
- **The Live page lists a pack's own seats in order.** The job stream sends the seats in force by kind and number, so
  a fourth worker or a second reviewer is listed beside its kind and no longer after everything else.
- **`cockpit pack check --all`** reports every problem of a pack, where a load stops at the first; a check that waits
  for a failed one says which. The plain `pack check` prints what it always did.
- **An origin check for the dashboard routes**, off unless `COCKPIT_ORIGIN_CHECK` is set: the router then answers 403
  to a request whose `Origin` is another site's. No `Origin`, a loopback origin, the address the request was sent to and
  each origin in `COCKPIT_ALLOWED_ORIGINS` pass. See `docs/security.md`.
- **Two doctor lines for a pack's own egress rules**: an error when the pack's denies refuse a plain `git status`,
  `git diff` or `git log` to a worker (`egress.pack-refuses-read`), and a warning that names a key of `egress.yaml` no
  rule reads, with the closest known key (`egress.unknown-key`).
- **A bug report is a pull request** that adds one failing test under `tests/reports/`; there is no issue tracker.
  `CONTRIBUTING.md` and `CLA.md` say how a change is proposed and under what agreement.
- **A contribute skill** and `AGENTS.md` for a coding assistant: every wish is placed on a ladder (a pack recipe, a
  plugin, a pack key, a kernel change) before any code is written, with an evaluation set of ten scenarios.

### Changed

- **The tracker intent types are `tracker-comment`, `tracker-create` and `tracker-transition`**, in the command line,
  an intent's id and file name, and every pack key that names an intent type. `skills.yaml` refuses a key under
  `intent` that is no intent type.
- **The licence is AGPL-3.0-or-later.** The project is open source under the GNU Affero General Public License,
  version 3 or any later version, in place of the noncommercial licence it carried before publication; a commercial
  licence is available on request (`COMMERCIAL.md`). `LICENSE` is the licence's own text, `NOTICE` names the copyright
  holder, every source file states both in its first lines, and `REUSE.toml` covers the files that cannot.
- **The token guard reads every tracked file for text shaped like one team's data**: a ticket key, a pull-request
  number, a board card id, a home path, a date in a code comment, a word of a product. Vendor names are matched in any
  letter case. Each exception is one listed line with its reason (`tests/token-allow.txt`). CI takes the private names
  from the secret `EXTRA_TOKENS`; a push to the default branch fails without it.
- **A tracker note in the Inbox says "Tracker comment"** unless the pack's tracker is Jira. The `/repos` route sends
  `tracker_kind`.
- **Doctor probes a newer Hermes instead of refusing it.** A newer minor is accepted, with a note, when its hooks
  answer the recorded shapes in a live probe.
- **The starter pack is under 0BSD.** The files `cockpit init` copies into a new pack ask nothing of the copy, so a
  pack made from them is yours. Everything else stays under AGPL-3.0-or-later.
- **The coverage gate counts branches too**, and its figure is written once, as `fail_under` in `pyproject.toml`.
- **Doctor sorts what it finds into errors, warnings and notes.** Only an error fails doctor and setup; `--strict`
  makes a warning fail too, `--json` prints every finding as data, and each error and warning comes with the line
  that resolves it. A line that failed doctor before and is now a warning: a missing or empty `staging.yaml`, no repo
  gate, a helper's missing program, a full seat memory file, provider drift, a stale Desktop copy, a cron the pack
  turned off or rescheduled, a provider dependency that could not be asked, a plugin block that is not checked, an
  unsealed key with nothing stored.
- **A plugin built for an older API version keeps working** on a newer kernel.
- A default applied where a pack key is read must be on a reviewed list, so a new one cannot appear unseen.
- **A record is written whole or not at all.** Every record write goes through one path (`store`): the bytes go to a
  temp file beside the record and replace it in one step, so a reader sees the old file or the new one and never half
  of either. A write outside it must be on a reviewed list that only shrinks. The bytes of every record are unchanged.
- **An intent is written under its ticket's lock** (`outbox/<ticket>/.lock`), and a writer whose copy changed
  underneath is refused instead of overwriting the newer record; an intent being published is not written by anyone
  else until it has left. The card index, the tickets and the pull requests kept in files take a lock the same way. A
  lock or a temp file is never listed, committed or read as a record.
- Hermes's databases are opened through one read-only helper.
- The test suite passes on any machine: no test reads the installation, a time zone or a git author. The large
  regression file is split by area.

### Removed

A pack that still writes a removed key does not load (`unknown key <name>`); an update that would change what a pack
means is refused or announced by its pre-flight (`docs/operations/update.md`).

- **Pack keys with one name each.** `github_org`, `jira_url` and `jira_project` are gone: write `forge.org`,
  `tracker.url` and `tracker.project`. `standup_hour` is gone: write `hours.standup`. `tracker.kind: rest` is gone:
  write `jira`.
- **Defaults that were one team's habits are neutral.** A pack that wants the earlier value writes it:
  `finding_labels` is empty (was `[B, CS, Q, PP, NTH]`; with no tags only a suggestion block asks for work);
  `testflow.title` is `Test run` (was `Test Run`), `testflow.banners.ok` and `.not_ok` are `Passed` and `Failed`
  (were `Tested and Ok`, `Tested and Not Ok`), `testflow.evidence_dir` is `evidence` (was `evidences`),
  `testflow.plan_file` is `test-plan.md` (was `test-scenarios.md`), `testflow.review_mark` is `ready for review`
  (was `ready for your review`); `standup.chat_file` is `standup.chat` (was `standup.slack`) and the headings
  `standup.sections.testings`, `developments`, `opened`, `reviews`, `created` and `waiting` are `Tested:`,
  `Developed:`, `Opened:`, `Reviewed:`, `Created:` and `Waiting on others:` (were `Testings:`, `Developments:`,
  `Opened PRs:`, `PR reviews:`, `Tickets created:`, `Waiting on colleagues:`); `desktop.diff_held_suffix` is empty
  (was `-wt`); the `desktop.hints` texts and `forge.rereview_job` name no skill of a pack; and
  `records.watch_id_prefixes` in `migrate.yaml` is empty (was `rc`, `ic`, `rv` for `inline:`, `issue:`, `review:`).
- **Names with one spelling.** The verbs `watch-rc` and `state-commit` (use `watch-base` and `workspace-watch`), the
  kickoff modes `worker`, `tester` and `reviewer` (use `rework`, `test` and `review`), the diff mode `rc` and the
  field `commits_rc` (use `base` and `commits_base`), and the watcher names `weekly-export` and `perf` (use `export`
  and `perf-sync`). `cockpit describe --json` no longer lists `verb_aliases` and `kickoff_mode_aliases`.
- **Readers of earlier installations.** A `test_run_<n>` folder is shown only when the pack's `testflow.run_dir`
  names it; setup no longer removes the cron jobs and scripts `rc-watch` and `state-commit`; and the doctor check
  `pack.spelling-conflict` is gone with the second spelling it compared.


### Updating an installation from before this release

- **Convert the records first.** An intent stored as `jira-comment`, `jira-create` or `jira-transition` is not listed
  until it is renamed to its `tracker-*` name, in the file, its name and every record that quotes its id.
- **The update ends with a traceback, once.** The kernel that applies the update was started before the modules were
  renamed, and its last step looks up a module by the earlier name (`No module named 'cockpitlib.afterupdate'`). The
  checkout, the dependencies and the gateway restart are done by then. Run `cockpit setup --rerender` and
  `cockpit doctor` yourself, and restart the Desktop.

### Fixed

- **The standup note knows a pack's own bump batch.** A batch ticket was recognised only by the prefix `BUMPS-`, so a
  pack on any other `forge.bump_batch` template, the kernel's default `{project}-BUMPS` included, had its batch listed
  as ordinary work. The note now asks the same matcher the outbox does, and still reads the old prefix.
- **The diff pane finds the remote branch of a repo with its own held-branch suffix.** Only `-wt` came off a branch
  name; now the repo's `branch_suffix_when_held` does. A repo that names none loses the pack's
  `desktop.diff_held_suffix`, which is empty unless the pack names one.

- **`cockpit publish --all` no longer stops at a move that already left.** A move the tracker reaches only through
  an earlier move sends that earlier one first; the batch now reads each intent again before its turn, so the earlier
  one is not sent twice and is not refused as changed.
- A tracker or forge key written with no value (`tracker: {url: }`) is read as an absent key; it stood as the text
  `None`.
- A pull-request link on any forge is written to a card as `repo#n`, not only a `github.com` one.
- **A review label with a space or a slash is taken off.** The label went into the code host's address as it was, and
  the removal was refused; a label, a branch and an id are now encoded there.
- **The pause after the code host refuses a burst twice is kept by every process.** It was never written (an import
  that named no module, caught in silence), so each process went on asking.
- **A ticket whose page cannot be built is named without a link** in the standup note and the review messages; a pack
  with no tracker address got a link to `/browse/<key>`.
- A pattern Python warns about (`[` inside a set) loads without printing that warning.
- The CI watch never reads a lock or a temp file in a ticket's `ci/` folder as a commit's record.
- Two tests that failed now and then on unchanged code fail only what they mean to (the CI watch's forgotten commit,
  the gate scan without `/proc`).
- A running card whose worker is gone is handed back, so it and the cards behind it move again.
- A pull request is not offered for publishing while the push of its own branch is still to go out.
- A pull request whose base branch left the remote goes back for its rebase by itself.
- A ticket's pull requests name each other whichever way the second one went out.
- A ticket's second pull request under review gets its own card.
- A lent login is not taken back by the housekeeping pass that runs beside its approval.
- A standup note sent the afternoon its window opened no longer swallows the next morning's.
- An infrastructure note that was applied is no longer an Inbox row.
- Pairing a staged intent in an amend is refused with the reason, instead of answered "amended".
- A lane's own command finds its card on the board when its shell was not told which card it runs.
- A ticket's cards sit on the stack the ticket holds, and a stack reserved in error has a way out.

### Security

- **What was endorsed is what is published.** An endorsement records the digest of each drafted file, and a publish
  refuses a draft that changed since.
- **Only the gatekeeper or the human endorses.** Any other lane is refused, and the endorsement names who gave it.
- **Applying an update is the human's act**, on the route, in the command and in the kernel's own denies.
- **A ticket key names one folder.** A path, a dot name or an empty key is refused by the routes and by the kernel.
- **Text from outside is quoted as data** on cards and in prompts, and cockpit reads no option out of a quote.
- The kernel's push deny reads git's own arguments, so an option between `git` and the verb does not carry a push past
  it.
- **A pack's `allowed.reads` is held to the kernel's denies.** An entry that was a push, a code-host write or a commit
  without hooks ran because the list was read first; the kernel's denies are judged first now, and doctor fails on
  such an entry (`egress.allowed-read-denied`, a security check). An allowed read is past the pack's own rules, as before.
- **A changed remote and a push setting are refused behind git's own options too**: `git -C dir remote set-url`, a
  write to `remote.*.url`, `remote.*.pushurl`, `url.*.insteadOf`, `core.sshCommand`, `core.hooksPath` or `alias.*`,
  `git config --edit`, an alias given as `git -c alias.…`, and `git send-pack`.
- **An endorsement binds the attachments too**, and a pending review is submitted with the summary it was posted with:
  an attachment or a drafted summary that changed after the approval is refused.
- **Every path from a ticket key is built in one checked place** (`paths.qa_of`, `outbox_of`, `worktree_of`), and a test
  reads the source to keep it so. A ticket folder that is a link out of the records is refused.
- A halt marker is written and removed for a named ticket only: `halt.write("")` made a marker at the records' own
  level and is refused now, as every other write with no ticket key already was. One left there is still read.
- A pack file that is not YAML, or a value whose shape no check expected, is refused as a pack error that names the
  file or the check; it raised a raw error before.
- A command holding a NUL byte is checked by the fence like any other; it raised an error out of the check before.
- A changed file named like an option reaches a pack's verify command as a path.
- A link's target in rendered markdown is never scanned again, so it cannot grow a second link or an attribute.
- The Desktop hands an address from a record to the system only when it is a web address.
- **Doctor's security checks are a pinned list.** Each is an error, no flag or pack key downgrades one, and a change to
  the list waits for the owner.
