# Card text and titles

## Goal

Cards worded your way: which skills each kind of card loads, what its title and body say, and which chain of cards a
ticket is broken into after `go`.

## The pack lines

In `skills.yaml`:

```yaml
router: router.md                # optional: the skill router file the coding tool is pointed at
kickoff:                         # required: the skills a kickoff of each mode loads
  intake: [cockpit:outbox]
  test: [cockpit:outbox]
intent:                          # required: the skills an intent of each type must have been written with
  open-pr: [cockpit:outbox]
  pr-review-submit: [[review-short, review-full]]   # a list inside the list: any one of them
cards:
  skills:
    review: [house-review]
  titles:
    review: "{ticket}: review of {repo}"
  body: cards/body.md
  decompose: [work, tester, review]
  analyst:
    ci: "Read {url} and say why {repo} is red for {ticket}."
```

`cards` takes `skills`, `titles`, `body`, `decompose` and `analyst`. Every skill named must exist: a bare name is the
pack's own skill, `cockpit:<name>` is one of the plugin's.

## The script contract

There is no script: the contract is the fields each template may use (`pack.py` `_cards`, `kanban.py`,
`decompose.py`).

- **`cards.titles.<kind>`**: the kind is a card kind (`intake`, `rework`, `test`, `tester`, `review`, `analyst`,
  `bumps`, `ci`, `base`, `advisory`, `work`, ...). Fields: `{ticket}`, `{repo}`, `{sha}`, `{change}`. The title must
  start with `{ticket}`: flows and twin detection read the kind cockpit recorded, never the words, but a title is how
  a person finds the ticket.
- **`cards.skills.<kind>`**: added after the kickoff mode's skills and before each repo's own `skills`
  (`repos.yaml`), without duplicates.
- **`cards.body`**: a file. Fields: `{ticket}`, `{role}`, `{repo}`, `{plan}`, `{slot}`, `{prs}`, `{plan_gate}`,
  `{note}`. The kernel's own body is five lines: the ticket, role and repo, then the plan, the slot, the PRs and the
  plan gate.
- **`cards.analyst.<kind>`** (`base`, `ci`, `advisory`): the body text of that analyst card. Fields: `{ticket}`,
  `{repo}`, `{change}`, `{sha}`, `{id}`, `{url}`, `{files}`. A `{{prompt:name}}` is not resolved here.
- **`cards.decompose`**: the chain of kinds each repo of a ticket gets, each card the child of the one before. It
  starts with `work` or `rework`; the kinds are `work`, `rework`, `test`, `tester` and `review`. The default is
  `work`, `tester`, `review`.
- **`intent.<type>`**: an intent written by a lane that has not loaded these skills is held (or sent back, by
  `outbox.missing_skill`).

The breakdown intake hands to `cockpit flow decompose` is a YAML or JSON file:

```yaml
repos:
  - repo: api
    plan_gate: human             # auto or human
    note: "the export endpoint"
  - repo: web
    after: api                   # this repo's chain starts when that one's ends
```

Each row takes `repo`, `slot`, `prs`, `plan_gate`, `model`, `note` and `after`.

## A copy-paste example

`cards/body.md` in the pack folder:

```markdown
{ticket}: {role} on {repo}.

Plan: {plan}
Slot: {slot}
PRs: {prs}
Plan gate: {plan_gate}

House rule: one commit per logical change. {note}
```

```yaml
cards:
  body: cards/body.md
  titles:
    work: "{ticket}: build it in {repo}"
```

## How to test it

```sh
cockpit pack check                               # refuses a title that does not start with {ticket}, an unknown field
cockpit pack explain skills.yaml:cards.decompose
cockpit flow decompose TASK-100 breakdown.yaml   # for a ticket that has its go; prints the cards as JSON
cockpit board --all                              # the new cards, with your titles
```
