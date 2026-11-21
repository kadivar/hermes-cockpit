# Repo gates

## Goal

One command runs each repo's own tests, in the ticket's checkout, and picks the failing tests out of the log. Lanes run
it before they hand work over, and doctor warns when no repo has a gate.

## The pack lines

In `repos.yaml`:

```yaml
repos:
  - name: api
    path: repos/api
    gates:
      - make test
      - make lint
    failures:
      - '^FAIL (\S+)'
```

`gates` is a list of shell lines. `failures` is a list of regular expressions; each must compile, or the pack is refused
(`repos.yaml api failures: ...`).

## The script contract

Implemented in `kernel/cockpitlib/repo_gates.py`.

- **Command:** each gate runs as `bash -o pipefail -c "<line>"`. No placeholder is filled in.
- **Working directory:** the ticket's checkout of the repo, `wt/<ticket>/<repo>`, when there is one; otherwise the
  workspace. The ticket is `COCKPIT_TICKET` when it is set, else the ticket of the card the caller runs on. Write a
  gate for the repo's own folder: that is where a lane runs it.
- **Which repos:** with no repo named, the repos the ticket has a checkout of; when it has none, every repo.
- **Environment:** the caller's, plus `COCKPIT_TICKET` when a ticket is known.
- **Standard input:** the caller's. Under `--background` there is none.
- **Standard output and error:** merged into the run's log. Each `failures` pattern is applied line by line; the name of
  a failing test is the pattern's first group, or the whole match when it has none.
- **Exit codes:** 0 is green. The run's code is the first gate's code that is not 0. There is no time limit on a gate.
- **Records:** `<records>/qa/<ticket>/gates/<run id>.json` and `.log` (`qa/workspace/gates/` with no ticket). A baseline
  run (`--baseline`) is kept as `gates/baseline.json`, so a later failure can be told from one that was already there.

## A copy-paste example

`repos.yaml`:

```yaml
repos:
  - name: shop
    path: repos/shop
    gates:
      - ./bin/check
    failures:
      - '^FAIL (\S+)'
```

`repos/shop/bin/check` (make it executable):

```sh
#!/bin/sh
# prints one "FAIL <name>" line per failing check and exits 1 when there is any
status=0
for file in tests/*.sh; do
  [ -e "$file" ] || continue
  sh "$file" || { echo "FAIL $file"; status=1; }
done
exit $status
```

## How to test it

```sh
cockpit pack check
cockpit worktree add TASK-100 shop                    # the ticket's checkout, where the gate will run
COCKPIT_TICKET=TASK-100 cockpit gate --repo shop      # runs the gates now and prints a line per gate
COCKPIT_TICKET=TASK-100 cockpit gate --background     # prints a run id and returns
cockpit gate --wait <run id>                          # waits for that run and exits with its code
```

Break a test on purpose and confirm the run exits 1 and names it. Then read the log under
`<records>/qa/TASK-100/gates/`. Without a ticket the same gate runs in the workspace folder, where a path relative to
the repo does not exist.
