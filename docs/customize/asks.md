# Asks

## Goal

Your own approval in the Inbox. A lane that needs something only you may do (a deploy to a shared environment, a data
refresh) blocks its card with a marked line; the Inbox shows Approve and Deny; Approve runs your command as you and
resumes the card with what it printed.

## The pack lines

In `pack.yaml`:

```yaml
asks:
  deploy:
    mark: "Deploy request:"
    label: Approve the deploy
    command: ["{pack}/bin/deploy", "{ticket}"]
    deny: Not now.
```

Each ask takes `mark`, `label`, `command` and `deny`, and needs a `mark`. `command` is a list of words. A literal brace
in a word is doubled (`{{` and `}}`), because the words are filled in with named fields.

## The script contract

Implemented in `kernel/cockpitlib/asks.py`.

- **When:** a card is blocked (or in triage) with a reason that starts with the mark, and the human clicks Approve on
  its Inbox row. A second Approve while the first still runs is refused.
- **Arguments:** `{pack}` (the pack's folder), `{lane}` (the card's seat), `{card}` (its id) and `{ticket}` are filled
  into each word.
- **Working directory:** the pack's folder.
- **Environment:** the human's, plus `COCKPIT_HUMAN=1` and `COCKPIT_ASK_QUESTION` (the lane's full block text).
- **Standard input:** the caller's; nothing is written to it.
- **Standard output:** on success, its last 1500 characters are the answer the card gets, as `approved: <output>`.
- **Exit codes:** 0 approves and resumes the card. Anything else fails the approval; the Inbox shows the last four
  lines the command printed, and the card stays blocked.
- **Time limit:** 600 seconds.
- **Deny:** the card is answered with `deny` (`no` when the pack gives none). The button's label defaults to `Approve`.

The command runs as the human, so it may do what a lane may not. Read the lane's request
(`COCKPIT_ASK_QUESTION`) as data, never as a command line: a lane, or text it was fed, wrote it.

## A copy-paste example

`bin/deploy` in the pack folder (make it executable):

```sh
#!/bin/sh
# usage: deploy <ticket>   (run as the human, on Approve)
ticket=$1
[ -n "$ticket" ] || { echo "no ticket" >&2; exit 1; }
echo "$(date '+%Y-%m-%d %H:%M') $ticket asked: $COCKPIT_ASK_QUESTION" >> "${HOME}/cockpit-deploys.log"
echo "deployed $ticket to the shared environment"
```

And in the soul or a skill of the lane that may ask (see [seats-and-souls.md](seats-and-souls.md)):

```
When the change must be on the shared environment before you can go on, block your card with a line that starts
with "Deploy request:" and says what to deploy and why.
```

## How to test it

Run the script as the kernel would, from the pack folder:

```sh
COCKPIT_HUMAN=1 COCKPIT_ASK_QUESTION="Deploy request: the export fix" bin/deploy TASK-100; echo "exit $?"
```

Then `cockpit pack check`. In the flow: block a test card by hand with a reason that starts with the mark, open the
Inbox, and click Approve; the card resumes with `approved: deployed TASK-100 ...`.
