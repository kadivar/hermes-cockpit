# Security model

This page is the single source for what cockpit protects, how, and where the protection ends. Other documents cite the
[invariants](#invariants) at the end by number. To report a vulnerability, see [SECURITY.md](../SECURITY.md).

## In one paragraph

Cockpit puts a gate between agents and the outside world: every outward act the kernel offers goes through an outbox, a
gatekeeper's endorsement and a human's click. Around that gate it puts a fence: a hook that refuses the known other ways
out. Both run **as the installing user**. They stop accidents and well-behaved agents. They are **not a sandbox**: an
agent that is hostile, or that has been prompt-injected, and that can run arbitrary programs as your user, is not
contained by them.

## Trust boundaries

**Lanes run as you.** A seat is a Hermes profile on your machine, running under your OS user, with your git remotes,
your code-host login, your SSH agent and your files. Nothing in cockpit changes that identity.

**The outbox is the only path for outward acts that the kernel offers.** A lane has no command that pushes, opens a pull
request or writes to the tracker. It writes an intent (`cockpit outbox new`). Endorsing is the gatekeeper's or the
human's; publishing is the human's alone. A lane is recognised by `COCKPIT_LANE` in its environment, which setup writes
into each seat's `.env`: the human-only commands and routes refuse a caller that carries it.

**One opt-in removes the click.** A pack may list a scope and intent types under `outbox.auto`; the intents of cards
started in that scope are then endorsed and published by housekeeping without the human. It is off unless the pack says
so, every check of a publish still runs, and approvals, review verdicts, pushes to a base branch and bodies that hold a
stored secret still wait for the human ([operations/unattended-publishing.md](operations/unattended-publishing.md)).

**The egress hook and the fence refuse the known other paths.** Before each tool call of a lane, Hermes runs
`hooks/egress.py` (and the same check in-process, as the plugin's `pre_tool_call` hook). The kernel's own deny list
(`egress.KERNEL_DENY` and the checks beside it) refuses, whatever the pack says:

- `git push` (and `git send-pack`), changes to remotes (`git remote add|set-url|rename|remove`), writes to the git
  settings that redirect or disguise a push (`remote.*.url`, `remote.*.pushurl`, `url.*.insteadOf`,
  `url.*.pushInsteadOf`, `core.sshCommand`, `alias.*`, also as `git -c alias.…`), `--no-verify` and hook-path changes.
  Each is read from git's own arguments, so an option between `git` and the verb (`git -C dir push`) hides none;
- writes with the code host's command line (pull requests, releases, issues, workflows, secrets, and API calls with a
  method, fields or a mutation), and HTTP writes to the code host or the tracker host;
- reads and writes of the vault files, seat `.env` and `auth.json` files, the board database and slot login files, and
  reads of the OS keychain;
- writes to Hermes's scheduled jobs, and cockpit's own human commands (publish, setup, update apply, rollback and rehome);
- the pack's `production_hosts`, and destructive HTTP methods against the origins the pack marks.

Each seat's Hermes config also carries an approvals deny list (`git push*`, `cockpit publish*`) that survives Hermes's
unattended mode, as a second layer under the hook. Lanes may still *read* through the human's existing logins.

The fence also keeps a worker inside its ticket's worktrees and its `write_roots`. These checks **narrow** a lane's reach.
They read command lines and tool inputs; they do not watch system calls. Known gaps, by construction:

- the fence judges the write targets it can see (shell redirects, `cp`/`mv`/`sed -i`-style targets, the write tools). It
  does not see a `git -C <other repo> commit`, or a write made from inside a code-execution tool;
- git aliases that already exist in a git config are not resolved (defining one is refused);
- a program the agent writes and runs can do anything your user can do;
- a lane that unsets `COCKPIT_LANE` in a child process is no longer recognised as a lane by that process.

So: the gate and the fence do not contain a hostile or prompt-injected agent that can run arbitrary programs as the user.

**The pack is trusted code.** Its scripts (gates, verify commands, slot commands, helpers, notify commands, asks, the
tracker command, the accounts command) run with the human's environment, and several run as the human on purpose. Its
deny lists are added to the kernel's and cannot remove them. A command line that exactly equals an entry of
`allowed.reads` is past the pack's **own** rules only (its deny patterns, its hosts, its write roots): the kernel's deny
list above is judged first (`egress.kernel_refusal`), so an entry that is a push or a code-host write is refused like any
other, and doctor fails on it. Two narrowing checks, which are no kernel denies, still do not apply to an allowed read:
the refusal of a search over a home folder or the machine's root, and the fence that keeps a seat's
writes inside its roots. So list reads there, and nothing that writes. Review a pack as you would review a shell script
you are about to run.

**A plugin beside cockpit is trusted code too.** It runs in Hermes's process and calls `cockpitlib.plugin_api`.

**The dashboard routes have no authentication of their own.** They are mounted into the Hermes dashboard and rely on the
Hermes host: by Hermes's behaviour, a loopback bind by default, a session token on every `/api/` path, and a host-header
check. That is Hermes's protection, not cockpit's; re-verify it for each Hermes release you run, and do not expose the
dashboard beyond loopback. The routes do refuse human-only acts to a caller that carries a lane's environment.

One check of cockpit's own can be switched on under that, as defence in depth: with `COCKPIT_ORIGIN_CHECK=1` in the
environment the dashboard runs in, the router answers 403 to a request whose `Origin` header is another site's. A
request with no `Origin` passes (the Desktop calls the routes from its own process and sends none; so do same-origin
reads and a command line), as does a loopback origin on any port (`http(s)://localhost`, `127.0.0.1`, `[::1]`), the
very address the request was sent to, and each origin listed in `COCKPIT_ALLOWED_ORIGINS` (comma-separated, for a
dashboard served under a public URL by a proxy). It is off by default because what a proxied or hosted setup sends
could not be established for every way Hermes serves a plugin; on a loopback installation it refuses nothing that
cockpit's own pages send.

**Some read routes have side effects.** `GET /ticket` asks the slot provider for its status, which runs the pack's slot
status command. `GET /settings` reads the plan's usage windows, which writes the last good reading under the records'
`watch/` folder. Treat a `GET` as able to run pack code.

## What an endorsement binds

An endorsement records the commit it was given for, the SHA-256 of each **drafted file** kept beside the intent (the
body, the review threads, a patch, patch comments, a review-body update) and the SHA-256 of each **attachment**
(`--attach`: the file stays where it is in the workspace and is read at publish). A publish compares them and refuses a
draft or an attachment that changed or vanished since; an amend asks for a new endorsement. Putting an intent into a
sequence afterwards (`outbox relink`) changes only its order: the endorsement and its digests stay.

A review leaves in two stages: first as a pending review only the human sees on the code host, then its submission. The
drafts are compared at the first stage, and the digest of the drafted summary is kept with the pending review. The
second stage sends the threads that are on the code host by then, with either the summary the human gives at that moment
or the drafted one, and the drafted one only while it is still the file the first stage was published with.

It does **not** bind:

- an intent endorsed, or a review posted, by a kernel from before the digest in question was kept: nothing is compared,
  and it publishes as it did then;
- anything outside the intent: the state of the branch on the code host is checked by the publish's own lease and
  read-back, not by the endorsement.

## Records and their locks

A record is a plain file under the records folder that crons, lanes, the routes and the human's command line read and
write at the same time. Every write goes through `cockpitlib.store`: the bytes go to a temp file beside the record and
replace it in one step, so a reader sees the old record or the new one, never half of either.

A change that reads an intent, decides and writes it back holds the ticket's lock for exactly that:
`outbox/<ticket>/.lock`. A writer whose copy changed underneath is refused and writes nothing; an intent that is being
published is claimed in the lock file, and no other process writes or publishes it until it has left. A file several
writers share (the card index, a ticket or a pull request kept in files) has its lock beside it, `.<name>.lock`. A lock
file holds the holder's process id, the words of its command (never an argument's value) and when it took the lock, so
the one who waits can be told who holds it. Lock and temp files are never listed, committed or read as a record.

The lock keeps cockpit's own processes from losing each other's changes. It is **not** access control: it is advisory,
and a program that writes a record's file directly is not stopped by it. The PR and CI watch records are written whole
but without a lock: a watch pass reads the code host between reading a record and writing it, and no lock is held
across the network.

## Text from outside is data

A tracker comment, a pull-request comment, a CI log or a web page is text someone else wrote. Where cockpit puts such
text on a card or in a prompt it is quoted as data (`cockpitlib.quoted`), the souls tell each lane to treat a quote as
information and never as an instruction, and cockpit reads no option out of a quote. This **reduces** prompt-injection
risk. It does not remove it: a model may still follow text it was told to ignore, which is why the gate does not rely on
the lanes behaving.

## Secrets

- **Where the key lives.** Lane logins live in the Hermes vault. Its key is `~/.hermes/vault/vault.key`. Cockpit wraps a
  copy to a GPG *public* key as `vault.key.gpg`; the matching private key is needed only to unwrap, restore or reveal.
  Cockpit never puts the plaintext key in git, and the weekly export never copies it. See
  [operations/vault.md](operations/vault.md).
- **Never in argv, a log or a tool result.** A stored secret is handed to a program on standard input or filled into the
  browser by the vault tool, not placed on a command line. `cockpit vault list` prints origin and email only.
  `cockpit record` refuses arguments that hold a stored secret. The accounts command's output is stored and never echoed.
- **Scrubbing is exact-match, best effort.** `cockpitlib.scrub` keeps a salted index of every stored password and seed
  and masks a match as `[secret]` in what a lane's tool call sends and receives. It finds a secret that appears exactly
  as stored, of 6 characters or more. It does not find one that was encoded, split or transformed.
- **Seat secrets** go in files named by `seat_config.<kind>.env_files`; doctor fails when one is readable by others or
  sits inside a git tree. A secret-looking name under `seat_config.<kind>.env` is refused at load.

## Updates

`cockpit update apply` is a human act (a lane's call is refused). Before the checkout moves it exports the incoming
commit, runs **that commit's own** `pack check` against the live pack, compares the effective settings, and refuses the
update when either fails. No flag skips it. See [operations/update.md](operations/update.md).

**What an update trusts.** By default, one thing: the remote the checkout follows. Whoever can push to that branch, or
answer for that address, decides what the next update is; the pre-flight checks that the code loads your pack, not who
wrote it. An installation can add a second thing, a signature: with signers named (a tracked `UPDATE-SIGNERS` file in the
installed tree, or `COCKPIT_UPDATE_SIGNERS`), an update is only ever a tag one of those signers signed, verified before
the checkout moves, and the signers are read from the installed tree, never from the incoming one. It is opt-in; see
[operations/update.md](operations/update.md#requiring-a-signed-tag). Dependencies are installed from a hashed lock file
when the tree carries one.

`hermes plugins update` and a manual `git pull` in the plugin folder **bypass** that pre-flight. So does anything else
that moves the checkout. Use `cockpit update apply`.

## Outbound network destinations

Cockpit does not phone home: there is no telemetry and no call to its author. The kernel itself contacts these, and
nothing else:

| Destination | When | What is sent | Code |
|---|---|---|---|
| The code host, through its command line (`gh api`) | the watchers read; a publish writes | the human's own login (held by that tool); repository, pull-request and review data | `forge.py`, `gh.py`, `publish.py` |
| The git remotes of your repos (`git fetch`, `git push`) | worktrees and watchers fetch; a publish pushes | commits, with your git credentials | `git_push.py`, `worktree.py` |
| The plugin's own git remote (`git fetch origin`) | the hourly update check, `cockpit update` | nothing but the fetch | `self_update.py` |
| A repository you name (`git ls-remote`, `git fetch`) | `cockpit update rehome <url>`, once, by your own hand | nothing but the fetch | `rehome.py` |
| The Python package index (`pip install`) | `cockpit update apply`, only when `pyproject.toml` or `requirements.lock` changed and the plugin has a `.venv`. A tree with `requirements.lock` is installed from it with `--require-hashes` (every file is checked against its recorded hash), then the plugin itself with `--no-deps` | the names of the plugin's dependencies | `self_update.py` |
| The tracker's URL (`tracker.url`) | tracker kind `jira`: the tracker watch reads; a publish writes | the email and API token from the two environment names in `tracker.auth_env`, as Basic auth; issue keys, comment and ticket bodies, attachments | `trackers/jira.py` |
| Hermes's hosted connector | tracker kind `connector` (the default) | the same tracker calls, through Hermes; cockpit holds no credential | `connector.py`, `trackers/jira.py` |
| The pack's tracker command | tracker kind `command` | the intent as JSON on standard input; for a read named in `tracker.reads`, the ticket key | `trackers/command.py` |
| No network: files under `tracker.local.root` | tracker kind `local` | nothing leaves the machine | `trackers/local.py` |
| No new destination: the code host, through its command line (the first row) | tracker kind `github-issues`: the tracker watch reads; a publish writes | issue numbers, titles, bodies, labels and comments of `tracker.repo`, with the human's own login held by that tool; with `forge.kind: local` nothing leaves the machine | `trackers/github_issues.py`, `forges/` |
| `api.osv.dev` | the advisory watch, only when the pack has an `advisories` block naming `osv` | the names and versions of the packages your shipped repos lock (Composer and npm) | `advisories/sources.py` |
| `www.cisa.gov`, `www.php.net`, `nodejs.org`, `nginx.org` | the advisory watch, per source named | a plain `GET` of a public feed; nothing about you | `advisories/sources.py` |
| `hn.algolia.com` | the advisory watch, source `hn` | a search for each watched product name (`php`, `nginx`, `node`, ...) | `advisories/sources.py` |
| The coding tool's own usage endpoint | the budget gate and the Pace panel, only for a subscription provider whose Hermes reader cannot answer | a `GET` with that tool's local login token as the Authorization header; the token is read from the tool's own credentials file, never refreshed, logged or stored | `plan_windows.py`, beside `pace.py` |
| The staging origins in `staging.yaml` | a slot handoff checks an origin is up | a TCP connection, no data | `acts.py` |
| The pack's `notify` commands | each event | the message body on standard input, to wherever your command sends it | `notify.py` |
| Loopback: the browser's DevTools port | `cockpit record` | DevTools commands to a local browser | `record.py`, `cdp_ws.py` |

Every advisory request carries the user agent `cockpit-advisories/1 (stack watch; read-only)`.

The Desktop pages add one of their own, loaded by the page and not by the kernel: the diagram module from the URL in
`desktop.mermaid_url` (none unless the pack names one). That module is **pack-trusted code**: the pack chooses the
address, the page imports whatever it serves with no integrity check, and it runs in a sandboxed frame that holds the
diagram's source and nothing else of the page. Name an address you control or trust as you trust the pack itself.

The terminal widget of the Chat pane is not fetched: it is part of the committed bundle, written into the terminal
frame's own page ([THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) names it and its licence).

Everything else that leaves the machine is the lanes' own traffic (their model provider, the staging origins they
browse), which Hermes makes, within the egress rules.

## A hardened setup

For anything beyond a trusted personal machine:

1. **Run the whole installation as a separate OS user, or in a container or VM**, with only the repositories it needs.
   This is the control that contains a misbehaving agent; cockpit's own checks are not.
2. **Give the lanes a read-only code-host login.** Sign the installation's code-host command line in with a fine-grained
   token that can only read, and publish from your own session with your own login.
3. Keep `production_hosts` complete and prove it with `host_probes` ([customize/egress-rules.md](customize/egress-rules.md)).
4. Keep the GPG private key off the machine, or on a security key: sealing needs only the public key.
5. Leave the Hermes dashboard on loopback.
6. Review the pack, and any plugin beside cockpit, as code.

## Invariants

A change to cockpit never weakens these, and a contribution that does is refused.

1. **The outbox is the only door.** The kernel offers no other way to push, open or edit a pull request, comment,
   review, or write to the tracker.
2. **Kernel egress denies cannot be removed by a pack.** Pack denies are appended to the kernel's list, and no pack
   list (`allowed.reads` included) is read before it.
3. **The hook fails closed.** A tool call it cannot read is blocked, and a bound pack that does not load refuses every
   tool that can reach the network or change anything, until `cockpit pack check` passes.
4. **Hold, drop, publish and update are human acts.** A hold is the gatekeeper's or the human's; confirming, dropping,
   returning, acknowledging, publishing, applying or rolling back an update, and moving the installation to another
   repository are the human's alone.
5. **A stored secret never reaches argv, a log or a tool result.**
6. **A doctor security check is never downgraded.** No flag, environment variable or pack key turns one into a warning.
   Each is an error, and the list of them is pinned in `tests/contract/doctor-security.json`: a check leaves it only by
   a change to that file, which `scripts/check` lists under `security-surface` for the owner
   ([reference/doctor.md](reference/doctor.md) marks them).
