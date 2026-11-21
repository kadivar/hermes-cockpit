# The Desktop pages

What each page shows and what it reads. The pages have no data of their own: each one reads the records, the board or the
code host through the kernel.

## The bundle

The Desktop loads `desktop/plugin.js`, a bundle of `desktop/src` built with `npm run build` in `desktop/` and committed; a
change under `desktop/src` reaches the Desktop only through that bundle (a test rebuilds it and compares). The Desktop
copies the bundle when `plugin.js` is newer than its copy and loads the copy at start; `cockpit setup` bumps the file when
a source beside it is newer, and `cockpit doctor` names a stale copy.

The web dashboard is a separate surface: `hermes dashboard`, the **Cockpit** tab. That tab comes from
`dashboard/manifest.json`, not from the Desktop switch.

## Inbox and Outbox

An intent's pane is its list row plus what leaves (the drafted files, markdown and tracker documents rendered), its
receipt log lines and a Brief in four fields: what leaves, why, what was checked, what it touches (a push counts its
commits and files from the checkout when the intent did not record them).

The pane's diff reads the checkout: the push against the base branch, against origin (what a force push drops, marked
replaced, rewritten or lost), the pair's real change after a rebase step, or the rebase itself.

The Inbox also lists every blocked card and every card Hermes moved to triage, with its block reason; an answer releases
either. A plugin's rows and a pack's own approvals appear there too ([plugins.md](plugins.md),
[customize/asks.md](customize/asks.md)).

## Board

The Board shows every open card and the done ones of the last two days (`/board?include_done_days=`). A card's Brief is
the newest comment's `Brief` heading, else the card's, else the ticket plan's (a `## Brief` section, or a `### Brief`
nested under a heading that names the ticket).

## Tickets and the demo card

A ticket's page shows its plan, its activity, its intents and its slot. The demo card's staging login reads cockpit's
vault when this machine can open it, else the seat store that holds the login.

## QA

The QA page reads `qa/<ticket>/run-<n>/test-results.md` (a Summary table with a verdict column) and the `evidence/`
folder. The run folder, the results file, the evidence folder and the plan file are named by the pack's
`testflow.run_dir`, `testflow.results_file`, `testflow.evidence_dir` and `testflow.plan_file`; those are their defaults.

## Platform

The Platform page's node badges count the changes of the chosen window (`/platform?days=`) that touch each node and how
many are unread; an area carries its features' numbers. It reads `platform/map.yaml`
([operations/setup-and-doctor.md](operations/setup-and-doctor.md#the-platform-map)).

## Standup

The standup draft lists, per ticket: testings, developments (opened PRs, merged), PR reviews, dependency bumps, tickets
created, closed, and what waits on colleagues; the channel gets its own format. The note is on by default;
`standup_enabled: false` in the pack turns it off: setup removes its cron job, the draft command refuses, and the Inbox
shows no standup row.

## Usage and pace

The Usage page reads every seat's `state.db` and the coding tool's transcripts named by
`providers.coding.transcript_glob`, booked per day; `{ticket}` in that glob is how a transcript is tied to its ticket.

The budget gate reads each lane provider's plan windows through Hermes's usage readers. For a subscription provider whose
Hermes reader cannot answer (the coding tool skips its usage fetch while its telemetry is off), cockpit reads the plan's
own windows itself: the coding tool's local login file, read-only, never refreshed, never logged; an expired token is an
error and the gate keeps its last good reading. A provider Hermes answers for is read as before. What that call sends is
in [security.md](security.md#outbound-network-destinations).

The Usage page's Pace panel and
`cockpit pace --json [--days 0,1,2,3,4] [--start HH:MM] [--end HH:MM] [--peak] [--fresh]` show, per window, the ideal %
by now (the quota ceiling `budget.plan_window_max_pct` spread over the window's active hours), the verdict (ahead / on /
behind, ±3 points), the % projected at the reset, the budget per remaining active hour and the binding window, plus this
week's efficiency (tokens per card run, failed or retried runs, the share of the largest model, cache-read share). With
`--peak`, weekday 05:00-11:00 America/Los_Angeles is left out of the spendable hours. Insight only: pace never gates a
card. A new kind of plan is one `PlanPaceSource` subclass registered in `cockpitlib.pace`.

## Chat and Open IDE

The Chat button opens a terminal on the ticket (or a personal one in the workspace); Open IDE opens the human's editor on
a ticket or a file. Both run commands the pack names: [customize/ide-and-chat.md](customize/ide-and-chat.md).

## Vault, Settings, Helpers

- **Vault**: the human's credential manager ([operations/vault.md](operations/vault.md)).
- **Settings**: seat counts, the budget, the browser-loan hours and the stale-worktree pass (each overlays the pack's
  value), and the update buttons ([operations/update.md](operations/update.md)).
- **Helpers**: the dev stack, tunnels and local services of the pack ([customize/helpers.md](customize/helpers.md)).
