# The code host's issues as the tracker

## Goal

A project whose tickets are GitHub issues needs no second tracker and no second sign-in: cockpit reads and writes the
issues through the code host the pack already publishes to. Every tracker write still goes through the outbox and the
human's publish.

## The pack lines

In `pack.yaml`:

```yaml
tracker:
  kind: github-issues
  project: GH          # the prefix of a ticket key: GH-12 is issue 12
  repo: api            # the repo of repos.yaml whose issues are the tickets; the first repo when unset
```

No `tracker.url` is needed: a ticket's link is the issue's own page on the code host. A ticket key keeps the shape
every other tracker has, `<project>-<n>`; the number is the issue's. A key of another project, or one whose number is
not a plain positive number (`GH-0`, `GH-012`), is refused.

The issues are reached through the pack's forge (`forge.kind`, `forge.org`, `forge.host`): with `forge.kind: github`
that is the `gh` command line signed in as you, and with `forge.kind: local` the issues are files beside the local
forge's pull requests, so `tracker.kind: github-issues` with `forge.kind: local` works with no network and no account.

A ticket's status is `Open` or `Closed`. To have more, carry them as labels:

```yaml
tracker:
  kind: github-issues
  project: GH
  status_labels:               # status name: the label that carries it, in the order they are looked for
    In Progress: in progress
    In Review: in review
    Done: done
  closed_statuses: [Done]      # the labelled statuses of a closed issue; the others are of an open one
```

A ticket has the first status whose label it carries, when the issue is open for an open status and closed for a
closed one; otherwise it is `Open` or `Closed`. So an issue someone closes on the code host reads `Closed` even while it
still carries `in review`. `Open` and `Closed` take no label.

To give a ticket's link another shape, set `tracker.browse_url`, a template with `{number}` (the issue's number) or
`{key}`, and `{url}` and `{project}` where they go.

## The script contract

There is no script: the kind is implemented in `kernel/cockpitlib/trackers/github_issues.py` (`GitHubIssuesTracker`)
over the forge's issue operations (`kernel/cockpitlib/forges/base.py`).

| Intent | What happens on the issue |
|---|---|
| `tracker-comment` | a comment, its Markdown as written; with `--comment-id`, that comment is edited in place |
| `tracker-create` | a new issue: the summary is its title, with the body, the labels and the assignee; its key is `<project>-<number>`, which a later intent may use (`--issue-from`, `{key}`) |
| `tracker-transition` | to `Open` or `Closed`: the issue is opened or closed and every status label taken off; to a labelled status: its label is set, the other status labels are taken off, and the issue is opened or closed as the status says |

Every write is read back, and the receipt says so. A move to a name that is not a status is refused with the statuses
the pack has.

| Capability | `github-issues` |
|---|---|
| summary, status, comments, identity | yes |
| comment, edit-comment, create, transition, assignee | yes |
| attachments | no: the code host's API has no upload for a file on an issue |
| sprint, component, transition-through | no |

An intent that needs a capability this tracker lacks is refused when it is written, not when it is published: a
comment with `--attach` is refused with `the pack's tracker (github-issues) has no attachments`. Put the evidence in
the pull request or link to it from the comment.

The comment watch works as for any tracker: a comment someone else writes on a ticket whose "done, confirm?" row waits
becomes an Inbox row; a comment written as you (the forge's login) is not news. The first hundred comments of an issue
are read.

## A copy-paste example

A solo project, one repo, three statuses:

```yaml
forge:
  org: example-org
tracker:
  kind: github-issues
  project: GH
  status_labels:
    In Progress: in progress
    In Review: in review
```

`cockpit init --tracker github-issues` writes the first three tracker lines for you (`--project` names the prefix; `GH`
when you give none).

## How to test it

```sh
cockpit pack check                         # the pack loads: tracker.repo names a repo of repos.yaml
cockpit outbox new GH-12 tracker-comment --card t_1 --summary "say it is tested" --issue GH-12 --body "Tested: it works."
cockpit publish --id GH-12/001-tracker-comment --dry-run     # what would be sent; the issue is read, nothing is written
```

A real publish is yours to run, from the Inbox or your own terminal. To try it with no account at all, set
`forge.kind: local` as well: the issues and their comments are then files under `forge.local.root`.
