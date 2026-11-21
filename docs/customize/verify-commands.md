# Verify commands

## Goal

A check that runs on exactly the commits a push intent would send (a linter on the changed files, a commit-message
check), before the gatekeeper may endorse it. A failing check is a reason the intent does not verify.

## The pack lines

In `repos.yaml`:

```yaml
repos:
  - name: api
    path: repos/api
    verify:
      - ["{pack}/bin/lint", "{files}"]
      - ["{pack}/bin/commit-check", "{base}", "{sha}"]
```

`verify` is a list of commands, each a list of words. Anything else is refused at load.

## The script contract

Implemented in `kernel/cockpitlib/outbox.py` (`verify`).

- **When:** for the push types (`push-branch`, `pr-patch-apply`) that name a repo and a commit: when the gatekeeper
  endorses, and on `cockpit outbox verify <id>`.
- **Arguments:** `{base}`, `{sha}`, `{worktree}` (the folder the check runs in) and `{pack}` (the pack's folder) are
  filled into each word. `{files}` must be a word by itself: it becomes one argument per changed file that still exists.
  - A file named like an option is passed as a path: `--fix` becomes `./--fix`.
  - A command with `{files}` is skipped when no changed file is left.
  - The first word is run as written, so name a pack script as `{pack}/bin/...`.
- **Working directory:** the ticket's checkout of the repo. When its head is not the intent's commit, the check runs in
  a throwaway detached checkout of that commit, removed afterwards.
- **Environment and standard input:** the caller's.
- **Standard output and error:** read only on failure: the last line is reported as
  `verify <program> failed on the pushed range: <line>`.
- **Exit codes:** 0 passes; anything else is a problem. There is no time limit.

## A copy-paste example

`repos.yaml`:

```yaml
repos:
  - name: api
    path: repos/api
    verify:
      - ["{pack}/bin/no-tabs", "{files}"]
```

`bin/no-tabs` in the pack folder (make it executable; the starter pack has another example of this contract,
`starter/bin/verify`):

```sh
#!/bin/sh
# refuses a changed file that holds a tab character
status=0
for file in "$@"; do
  if grep -q "$(printf '\t')" -- "$file"; then
    echo "$file: tab character"
    status=1
  fi
done
exit $status
```

## How to test it

Run the script by hand in a checkout first: `path/to/pack/bin/no-tabs src/app.py`. Then, with a push intent in the
outbox:

```sh
cockpit outbox verify TASK-100/001-push-branch
# ok                                   (exit 0)
# verify no-tabs failed on the pushed range: src/app.py: tab character     (exit 1)
```
