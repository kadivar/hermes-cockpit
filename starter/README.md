# The starter pack

A pack is what makes cockpit yours: a folder of YAML, skills, souls and small scripts that says what your workspace
is, how your team works, and what no lane may reach. This folder is the material a first pack starts from.

`cockpit init` copies `skills/`, `souls/` and `bin/` into the new pack (leave them out with `--no-starter`). The
copies are yours: edit them, delete what you do not use, add your own. Nothing reads this folder after the copy, and
an update of cockpit never touches a pack.

`cockpit init` also writes `pack.local.example.yaml` beside the new pack's `pack.yaml`, and a `.gitignore` naming
`pack.local.yaml`. That file is where each person who shares the pack keeps what is theirs (a login, a folder under
their home): a pack file asks for a value as `{local.<name>}`, and `{home}` is the home folder. There is no such file in
this folder because it is not a pack; `docs/customize/personal-values.md` has the recipe.

That is also why no file here carries a copyright header: a header would put this project's name on a file that
becomes yours. And it is why this folder, alone in the repository, is under the 0BSD licence (`LICENSES/0BSD.txt`;
`REUSE.toml` at the root says so) and not under the project's own: 0BSD lets you use, change and pass on a copy
with no condition and no notice to keep, so a pack made from the starter is yours, under whatever terms you choose.

## What is here

| Path | What it is | Used through |
|---|---|---|
| `skills/ticket-intake` | Read a ticket, separate claims from evidence, reproduce, plan, stop for go | `skills.yaml` `kickoff.intake`, `kickoff.analyst` |
| `skills/implement` | The smallest change, the advisor checkpoints, the gates | `kickoff.rework` |
| `skills/self-review` | A checklist over your own diff; a finding must be shown to happen | `kickoff.rework` |
| `skills/open-pr` | A push and a pull request as intents, written from the commits | `kickoff.rework`, `intent.open-pr` |
| `skills/pr-review` | Severity, `file:line`, the threads file, one review intent | `kickoff.review`, `intent.pr-review-submit` |
| `skills/test-plan` | A happy/unhappy/edge table, the run folder, the results file | `kickoff.test` |
| `skills/tracker-notes` | A comment that reads cold, with evidence, as an intent | `kickoff.test`, `intent.tracker-comment` |
| `souls/common.md` | Working rules added to every seat's soul | `pack.yaml` `seat_config._common.soul` |
| `bin/notify` | Example: keeps each message in a file | `pack.yaml` `notify.<event>` |
| `bin/tracker` | Example: a tracker kept in one JSON file | `pack.yaml` `tracker: {kind: command}` |
| `bin/verify` | Example: refuses a file with a merge-conflict marker | `repos.yaml` `verify` |
| `bin/helper` | Example: a service to start, stop and probe | `helpers.yaml` |
| `bin/slot` | Example: the verbs of a slot's stack | `pack.yaml` `slots.commands` |

## Skills

A skill is `skills/<name>/SKILL.md`: a frontmatter with `name` (the folder's name) and `description`, then the
procedure. A card loads the skills `skills.yaml` lists for its kickoff mode; an intent type listed under `intent`
asks the lane that writes it to have loaded those skills first.

To change one, edit its file: the next card reads the new text. To add one, make a folder beside the others and name
it in `skills.yaml`; `cockpit pack check` fails on a name that has no folder. Cockpit's own skills are written
`cockpit:<name>` (the outbox skill is `cockpit:outbox`) and are not in your pack.

Write a skill as the kernel's own are written: short declarative sentences, numbered steps, and a "Do not" line for
each mistake you have seen. Every command it cites should be one you ran.

## Souls

A seat's soul is cockpit's text for that kind of seat, then your additions, then cockpit's common rules.
`seat_config._common.soul` names a file added to every seat; `seat_config.<kind>.soul` names one for a single kind
(`reviewer`, `tester`, ...). After you edit a soul, run `cockpit setup --rerender` so the seats are written again;
doctor reports a seat whose soul differs from its pack.

## Scripts

Each script in `bin/` is a small working example of one contract, with the contract at its top. They keep their
state in a `.cockpit-starter` folder beside the pack (or where `COCKPIT_STARTER_STATE` points), so you can run them
by hand and see what cockpit would get.

- **notify**: the message body on stdin, the event's name in `COCKPIT_EVENT`, its subject in `COCKPIT_EVENT_KEY`.
  Exit 0 means sent. Events: `cockpit pack explain notify`.
- **tracker**: the intent as JSON on stdin, the act in `COCKPIT_TRACKER_ACTION` (`comment`, `create`, `transition`,
  `summary`, and the reads `comments`, `me`, `status` when `tracker.reads` names them), one JSON object on stdout. `cockpit init --tracker command` wires it, so a new workspace can file and
  publish tracker intents before a real tracker is connected.
- **verify**: a repo's check on the files of a push; a non-zero exit holds the push and its output is the reason.
- **helper** and **slot**: a verb answers with its exit code: 0 ok, 1 failed, 2 still working, 3 a dependency is
  down. A slot's `status` prints JSON; a helper group's status prints one `name: state (detail)` line per service.

Replace the inside of a script with your own commands and keep its contract. Read credentials from the environment
inside the script; a secret never goes into a pack file.

## After a change

`cockpit pack check` loads the pack and names the first thing wrong. `cockpit doctor` lists what stops work (errors)
and what you should look at (warnings), each with the line that resolves it.
