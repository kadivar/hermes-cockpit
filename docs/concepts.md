# Concepts

The words cockpit uses, in an order where each is defined before it is used.

## The flow

```
 ticket
   │
   ▼
 intake ──▶ worker ──▶ tester ──▶ reviewer        agent lanes, each in the ticket's own worktree
   │           │          │           │
   └───────────┴────┬─────┴───────────┘           each writes intents (push, pull request, comment, ...)
                    ▼
                 outbox ──▶ gatekeeper endorses ──▶ the human publishes ──▶ code host / tracker

 egress hook: a push, a code-host write or a production host that does not go through the outbox is refused
```

## Hermes, and what cockpit adds to it

| Word | Meaning |
|---|---|
| **Hermes** | The agent runtime cockpit is a plugin for. It runs profiles, gives them tools, keeps a kanban board and runs scheduled jobs. |
| **Hermes profile** | One configured agent in Hermes: its own folder under `~/.hermes/profiles/` with a config, a role prompt, a memory and an environment file. |
| **Kernel** | Cockpit's own code (`kernel/cockpitlib`). It knows no team, repo or product: everything specific comes from the pack. |
| **Pack** | The files in a workspace that name the repos, skills, providers and slots: `pack.yaml` and its companions (`repos.yaml`, `skills.yaml`, `egress.yaml`, `staging.yaml`, and optionally `helpers.yaml`, an accounts manifest and `migrate.yaml`), plus the pack's own scripts and prompt files. Each person's own values sit beside it in `pack.local.yaml` ([personal values](customize/personal-values.md)). The plugin never contains them. |
| **Workspace** | The directory the pack and the records live in. `~/.hermes/cockpit.yaml` binds the installation to it. |
| **Records** | What cockpit writes in the workspace, under one folder (`hermes/` unless the pack's `records_dir` names another): `outbox/` (intents), `qa/<ticket>/` (plan, notes, test runs), `watch/` (watcher state), `platform/` (map, summaries, standup), `chat/`. |
| **Setup** | One idempotent command, `cockpit setup`, that creates every seat, the board, the crons and the gateway. |
| **Doctor** | `cockpit doctor`: the health check of the bound workspace and the installation. It sorts what it finds into errors, warnings and notes; an error fails doctor and setup. |

## Who does the work

| Word | Meaning |
|---|---|
| **Role** | The job a lane does: intake, worker, tester, reviewer, analyst, gatekeeper, advisor. The pack assigns each role a provider. |
| **Provider** | A model endpoint Hermes already knows, plus a model id. Opaque strings to cockpit. The pages never print a vendor name. |
| **Lane** | One Hermes profile with a role. A lane does one kind of work and cannot publish. |
| **Seat** | One running copy of a lane. Three reviewer seats are three profiles (`reviewer`, `reviewer-2`, `reviewer-3`); worker and tester seats are numbered by slot (`worker-1`, `tester-1`). The least loaded seat gets the next card. |
| **Soul** | The role prompt of a seat (`SOUL.md` in its profile): the kernel's text for the role, then the pack's additions. |
| **Concierge** | The default Hermes profile. It runs `cockpit` for the human and never publishes. |
| **Coding tool** | The process a worker starts inside a worktree to edit files. The pack configures it as an argv. It is not a lane and is not assumed to be any one product. |
| **Skill** | A `SKILL.md` the human already has, anywhere on the machine. The pack names it; the plugin does not copy it. Cockpit's own skills are reached as `cockpit:<name>`. |
| **Advisor** | An optional seat a worker asks at named checkpoints (`cockpit advise`). Its answer is recorded with the plan. |

## What the work is

| Word | Meaning |
|---|---|
| **Ticket** | The human's unit of work, a key such as `TASK-100`. One plan file, one set of worktrees, at most one slot. |
| **Board** | The Hermes kanban board the pack names. Every assignment is a card on it. |
| **Card** | One lane's assignment on the board, inside a ticket. |
| **Kickoff** | How a ticket enters: the human starts intake, a test, a review, a question, a rework or a dependency batch. Intake always waits for `go`. |
| **Workflow** | The path a ticket is on: intake, test, review, rework, dependency batch, pull-request watch or CI watch. |
| **Plan** | `qa/<ticket>/plan.md`. Intake writes it at `go`; every later lane appends a section. |
| **Worktree** | The ticket's own checkout of a repo, `wt/<ticket>/<repo>`, on the branch `<branch_prefix>/<ticket>`. The repo's own checkout is never switched. Lanes cannot push from it. |
| **Slot** | An isolated runtime for one ticket (a dev stack, a database, ports). Its owner is `free`, `human` or `lane:<profile>`. A pack may have zero slots. |
| **Bump** | A dependency-update pull request. The bump scan gathers the open ones into a batch under one ticket; `grooming` and `bump_sequence` in the pack say what each needs before it leaves. |

## How anything leaves the machine

| Word | Meaning |
|---|---|
| **Code host** | Where the repositories and pull requests live. The code and the pack keys call it the *forge*. Cockpit reaches it through its command line, signed in as the human. |
| **Tracker** | Where tickets live. Cockpit writes to it only by publishing an intent. |
| **Intent** | A file that describes one outward act: a push, a pull request, a comment, a tracker write. A lane writes it. Nothing happens until it is endorsed and published. |
| **Outbox** | The folder of intents. Also the page that shows them. |
| **Gatekeeper** | The lane that reads each pending intent and endorses or holds it. It cannot publish either. |
| **Endorse** | The gatekeeper's pass (or the human's). It records who gave it and the digest of each drafted file. It is not publish. |
| **Digest** | Two things. The *draft digest* is the SHA-256 of a file kept beside an intent, recorded at endorsement and compared at publish. The *outbox digest* (`cockpit outbox digest`) is the numbered list of waiting intents the human answers by number; the *morning digest* (`cockpit digest`) is the scheduled one-screen summary: open intents, blocked cards and the review column. |
| **Hold** | The gatekeeper's or the human's stop on an intent, with a reason: it waits for the human, or for its lane. |
| **Publish** | The human's click. `cockpit publish` runs as the human, performs the act and reads the result back. |
| **Gate** | The rule that an intent leaves only after an endorsement and the human's publish. (*Repo gates* are something else: a repo's test commands, run by `cockpit gate`.) |
| **Egress hook** | The check Hermes runs before every tool call of a lane (`hooks/egress.py`). It refuses pushes, code-host writes, production hosts, vault files and whatever the pack adds, and it fails closed. |
| **Fence** | The rules that keep a lane inside its own area: a worker writes only in its ticket's worktrees and its `write_roots`. The same word names the guard for the human's own editor sessions (`cockpit guard`), which keeps slots, vaults and publishing out of an assistant's reach. |
| **Halt** | A marker on a ticket that stops every card being made for it until the human resumes it. |

## What runs by itself

| Word | Meaning |
|---|---|
| **Gateway** | Hermes's background service that dispatches cards to profiles and runs the crons. `cockpit up`, `down` and `status` drive it. |
| **Cron** | A scheduled Hermes job. Setup registers cockpit's: `ci-watch` (every minute), `pr-watch` (5 minutes), `workspace-watch` (10 minutes), `advisories` (30 minutes), `slot-gc` (hourly), `base-watch` (2 hours), and the daily `standup`, `bumps`, `morning-digest`, `perf-sync` and weekly `export`. |
| **Watcher** | A cron with no model: it reads the code host, the tracker or the workspace and writes a record. A failure is an Inbox row. |
| **Housekeeping** | The pass that runs with the minute watch. It settles finished reviews, hands back cards whose worker is gone, returns lent logins, starts the gatekeeper's sweep, makes queued rework cards, assigns slots, checks for updates and more. |
| **Lend** | A loan to one card for a limited time: the privileged login (asked for with a marked block, approved by the human, 30 minutes) or the human's browser (a test kickoff's option, for `shared_chrome_hours`). Housekeeping takes a loan back. |
| **Advisories** | The stack watch: what the pack's shipped repos build and run, held against public advisory feeds. A match becomes an Inbox row and an analyst card. Off unless the pack has an `advisories` block. |
| **Pace** | How fast a subscription's usage windows are being spent against the pack's ceiling (`cockpit pace`). Insight only: pace never holds a card. The budget gate is what holds new cards. |
| **Inbox** | The page of everything that waits for the human: endorsed intents, blocked cards, watcher failures, plugin rows. |

See also: [security.md](security.md) for what these protections do and do not stop, and
[reference/pack-keys.md](reference/pack-keys.md) for every key a pack may set.
