# Quickstart

Day 0, from nothing to a first ticket. Budget about 30 minutes, most of it answering questions about your own project.

Before you start you need what the [README](../README.md#requirements) lists: Hermes, Python 3.11+, git, the code host's
command line signed in as you, a tracker, GPG with a public key, and ffmpeg.

## 1. Install the plugin (2 minutes)

```sh
hermes plugins install https://github.com/kadivar/hermes-cockpit
export PATH="$HOME/.hermes/bin:$PATH"
```

Expected: Hermes reports the plugin installed. `cockpit` is not on your `PATH` yet (setup creates the link in step 4);
until then the program is `~/.hermes/plugins/cockpit/bin/cockpit`.

If `python3` on this machine has no PyYAML, give the plugin its own interpreter:

```sh
cd ~/.hermes/plugins/cockpit && python3 -m venv .venv && .venv/bin/pip install -e .
```

## 2. Enable it in Hermes (1 minute)

Add `cockpit` to `plugins.enabled` in the Hermes config, or in the Desktop: Capabilities → Plugins → Rescan → switch
Cockpit on.

Expected: the Desktop shows the Cockpit pages. The web dashboard is a separate surface: refresh `hermes dashboard` and
open the **Cockpit** tab.

## 3. Write the pack (10 minutes)

From your workspace folder (the one that holds, or sits beside, your repositories), look first:

```sh
~/.hermes/plugins/cockpit/bin/cockpit init --no-production
```

`init` asks nothing. It prints what it detected (the workspace, each repo with its base branch and the test commands
its files suggest, the provider and model of your Hermes home, a coding tool on your `PATH`), then the files it would
write and the command that writes them. Without `--write` it writes nothing. A folder that is itself a git repository
is taken as a repo of the workspace, and the workspace becomes its sibling `<folder>-workspace`.

It never guesses what production is, so that answer is always yours: `--no-production` when the project has none, or
one `--production-host REGEX` per production hostname (`--production-host 'app\.example\.test'`). The other answers
are options too:

| Option | What it answers |
|---|---|
| `--staging-origin URL` | the origin the lanes test on; `staging.yaml` is written only with it |
| `--tracker-url URL`, `--project KEY` | the tracker's base URL and project key (`tracker.url`, `tracker.project`) |
| `--tracker command`, `--tracker jira` or `--tracker github-issues` | `command` (the choice when the starter is copied) wires the starter's `bin/tracker`, a tracker kept in a file, so the pipeline works before a real one is connected; `jira` leaves the tracker to Hermes's connector; `github-issues` makes the issues of the first repo the tickets (`GH-12` is issue 12; `--project` names another prefix), with no tracker URL: see [customize/tracker-github-issues.md](customize/tracker-github-issues.md) |
| `--accept-gates` | the suggested test commands are written as each repo's `gates` |
| `--slots N` | `seats.slots`, 0 to 8 (default 1) |
| `--pack DIR`, `--no-starter`, `--no-bind`, `--rebind` | another place for the pack; no starter files; no binding; replace a binding to another workspace (a copy of it is kept) |

Then write it:

```sh
~/.hermes/plugins/cockpit/bin/cockpit init --no-production --staging-origin https://staging.example.test --write
```

It writes `<workspace>/cockpit-pack/`: `pack.yaml`, `repos.yaml`, `skills.yaml`, `egress.yaml`, `staging.yaml` when you
named an origin, and the `skills/`, `souls/` and `bin/` of the [starter pack](../starter/README.md). Every key is
written under its one-sentence meaning. Beside them it writes `pack.local.example.yaml` and a `.gitignore` naming
`pack.local.yaml`: the file for what differs between two people who share the pack
([personal values](customize/personal-values.md)). The pack is built beside its place, loaded and checked there, and moved in;
only then is the workspace bound in `~/.hermes/cockpit.yaml`. It never replaces a file: a `cockpit-pack/` that is there
and not empty is refused, and so is a Hermes home that names no provider. Writing is a human's act: a lane's call is
refused.

Expected: `wrote:` with the files, then `next: cockpit setup, then cockpit doctor`, and this passes:

```sh
~/.hermes/plugins/cockpit/bin/cockpit pack check
# pack ok <your pack's name>
```

A refusal names the key and the shape it takes. `cockpit pack explain <key>` prints one key's meaning and the value in
force; [reference/pack-keys.md](reference/pack-keys.md) lists them all. A workspace that already ran an earlier
pipeline starts from [operations/migrating.md](operations/migrating.md) instead.

## 4. Create the seats (5 minutes)

```sh
~/.hermes/plugins/cockpit/bin/cockpit setup
```

It creates every seat as a Hermes profile, the board, the scheduled jobs and the gateway, records the egress hook on each
home's allowlist, and links the program as `~/.hermes/bin/cockpit`. It is safe to run again, and you run it again after a
seat change.

Expected: a line about the vault (`vault init pending` when this machine has no GPG public key to seal with), then
`setup ok`. Setup ends with doctor's checks: an error is printed and setup exits 1; a warning is printed and setup goes on.

## 5. Read doctor (5 minutes)

```sh
cockpit doctor
```

Expected: `doctor: OK`, with the count of warnings when there are some. Doctor sorts what it finds into three tiers:

- an **error** is printed first, and fails doctor (exit 1) and setup;
- a **warning** is printed as `warning: …` and does not fail it (`cockpit doctor --strict` makes a warning fail too);
- a **note** is printed as `note: …` after the verdict and never changes it.

Under each error and warning is a `fix:` line that says what resolves it. `cockpit doctor --json` prints the same as
data, and `--online` adds the checks that need the network (whether the code host's command line is signed in).
[reference/doctor.md](reference/doctor.md) lists every check with its tier. The ones a new pack usually meets:

| Line | Tier | Do this |
|---|---|---|
| `egress production_hosts is empty` | error | A pack written by hand: list your production host patterns in `egress.yaml`, or say `no_production_hosts: true`. |
| `staging.yaml missing`, `staging origins empty` | warning | Name the origins the lanes may open in `staging.yaml`. |
| `no repo gates` | warning | Give a repo its test commands under `gates` in `repos.yaml`. |
| `vault key not sealed` | warning while nothing is stored, error once a key or a login is | `cockpit vault init --key <fingerprint>` ([operations/vault.md](operations/vault.md)). |

## 6. Start a ticket (5 minutes)

Open the Desktop's **Kick off** page, enter a ticket key, and start intake. Intake reads the ticket, writes a plan and
waits for your `go`. After that the worker, the tester and the reviewer take their cards in turn, and what each wants to
send appears in the **Inbox** once the gatekeeper has endorsed it.

Expected: nothing reaches the code host or the tracker until you click Publish on an Inbox row. `cockpit board --watch`
and `cockpit live <ticket>` show the same from a terminal.

## Next

- [concepts.md](concepts.md) for the vocabulary.
- [security.md](security.md) for what the gate and the fence do and do not stop.
- [customize/](customize/README.md) to plug in your own test commands, dev stack, notifications and tracker.
