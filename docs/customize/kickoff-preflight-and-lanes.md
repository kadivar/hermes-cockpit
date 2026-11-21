# Kickoff preflight and lanes

## Goal

A kickoff mode started on another kind of seat, or with other checks before its card: a test that does not wait for a
slot, a review that does not wait for the tester.

## The pack lines

In `pack.yaml`:

```yaml
kickoff:
  lanes:
    bumps: analyst               # the seat kind a mode starts on
  preflight:
    test: [intake_go, decision]  # replaces the mode's own steps
```

`kickoff` takes `lanes`, `preflight` and `done_rows` (whose one value, `developed`, keeps the Inbox's done row for
tickets the human develops). A mode that does not exist, a step that does not exist, or a seat kind a kickoff cannot
start (`gatekeeper`) is refused at load.

## The script contract

There is no script: the contract is the kernel's table of modes (`kernel/cockpitlib/registry.py`), which
`cockpit describe --json` prints as `kickoff_modes`.

| Mode | Starts on | Its own preflight |
|---|---|---|
| `intake` | intake | `slot` |
| `rework` | worker | `intake_go`, `decision` |
| `test` | tester | `tester_slot`, `intake_go`, `decision`, `manual_plan` |
| `review` | reviewer | `intake_go`, `decision`, `reviewer_ready` |
| `bumps` | reviewer | `bumps` |
| `analyst` | analyst | (none) |

The steps, run in the order listed, before the card is made:

| Step | What it checks |
|---|---|
| `bumps` | a repo's bumps already started elsewhere refuse the kickoff |
| `tester_slot` | the ticket's slot is ready and not the human's session |
| `intake_go` | an intake card still waiting for go refuses the kickoff |
| `decision` | the ticket's plan has a recorded go |
| `reviewer_ready` | the tester's run is done; otherwise the card waits, blocked, for it |
| `manual_plan` | the cheap gate runs green before a test plan starts |
| `slot` | a free slot is warmed for the ticket (when the pack has slots) |

- `kickoff.preflight.<mode>` **replaces** the mode's list; it does not add to it. An empty list runs no step.
- `kickoff.lanes.<mode>` picks the seat kind: `intake`, `worker`, `tester`, `reviewer` or `analyst`. An unknown mode is
  refused; nothing falls back to intake.
- The checks every kickoff makes whatever the pack says stay: a halted ticket, a twin card, capacity.
- A plugin's modes take the same two keys ([plugin-card-kinds.md](plugin-card-kinds.md)).

Removing a step removes a safeguard. `decision` is what keeps work from starting before your go.

## A copy-paste example

A pack with no slots, whose tests run against staging and need no local stack:

```yaml
seats: {slots: 0, intake: 1, reviewer: 1, analyst: 1}
kickoff:
  preflight:
    intake: []
    test: [intake_go, decision]
```

## How to test it

```sh
cockpit pack check
cockpit pack explain kickoff.preflight
cockpit describe --json          # the kernel's own modes and steps, before any pack
```

Then start the mode from the Desktop's Kick off page and confirm the card lands on the seat you named.
