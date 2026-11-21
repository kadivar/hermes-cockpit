# Notifications

## Goal

A message where you will see it (a chat channel, a desktop notification, an email) when something waits for you: a
ticket ready for review, new comments on your pull request, CI turning red, a new advisory.

## The pack lines

In `pack.yaml`, one command per event:

```yaml
notify:
  ready_for_review: [bin/notify, "{event}", "{ticket}"]
  ci_failed:        [bin/notify, "{event}", "{ticket}"]
  standup:          [bin/notify, "{event}"]
```

An event name is lowercase words (`^[a-z][a-z0-9_-]*$`), and a command is a list of words. An event the pack does not
name is not sent. The events the kernel sends, with the fields and the body of each, are generated from the code:
[reference/events.md](../reference/events.md).

## The script contract

Implemented in `kernel/cockpitlib/notify.py`.

- **Arguments:** `{event}`, `{key}` and the event's own fields (`{ticket}`, and `{sha}` for the CI events) are filled
  into each word. A relative first word with a `/` is a file beside `pack.yaml`.
- **Environment:** the caller's, plus `COCKPIT_EVENT` and `COCKPIT_EVENT_KEY`, so one command can serve every event.
- **Standard input:** the message body, as plain text.
- **Standard output and error:** read only on failure (the last line is reported).
- **Exit codes:** 0 is sent. Anything else is a failure: a red `notify-<event>` row in the Inbox until that event next
  goes out, and the same key is tried again on the next pass.
- **Time limit:** 120 seconds.
- **Once per key:** each event goes out once for its key (a ticket and a commit, a pull request and its head, a day).
  The ledger is `<records>/watch/notify-sent.json`. The standup is the exception: it is sent when you confirm it, and a
  failure is shown to you at once.

## A copy-paste example

`bin/notify` in the pack folder (make it executable; the starter pack has another example of this contract, `starter/bin/notify`). It appends to a file, so you can see the
contract before you wire a real channel:

```sh
#!/bin/sh
# usage: notify <event> [ticket]   (the message body arrives on standard input)
out="${HOME}/cockpit-notifications.log"
{
  echo "--- $(date '+%Y-%m-%d %H:%M') $COCKPIT_EVENT key=$COCKPIT_EVENT_KEY ticket=${2:-}"
  cat
} >> "$out"
```

To send to a chat channel instead, replace the body with your channel's own command, reading the message from standard
input. Hermes's own sender works the same way: `[hermes, send, --to, <target>, --file, "-"]`.

## How to test it

Run the script as the kernel would:

```sh
echo "TASK-100: CI is failed on 0123abcd" | \
  COCKPIT_EVENT=ci_failed COCKPIT_EVENT_KEY=TASK-100@0123abcd bin/notify ci_failed TASK-100; echo "exit $?"
tail -3 ~/cockpit-notifications.log
```

Then `cockpit pack check`, and make the script exit 1 once to see the red `notify-<event>` row in the Inbox the next time
that event is sent.
