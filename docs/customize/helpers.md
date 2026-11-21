# Helpers

## Goal

The dev stack, tunnels and local services you start and stop all day, on one page and under one command, with their
state shown. A helper can depend on another, stand for several, and be opened to the lanes.

## The pack lines

In `pack.yaml`:

```yaml
helpers: helpers.yaml            # a file beside pack.yaml
```

In `helpers.yaml`:

```yaml
groups:
  stack:
    label: Stack
    status: {argv: ["{pack}/bin/helper", status], parse: lines}
helpers:
  queue:
    label: Message queue
    group: stack
    argv: ["{pack}/bin/helper", "{verb}", queue]
  web:
    label: Web server
    group: stack
    argv: ["{pack}/bin/helper", "{verb}", web]
    verbs: [start, stop, restart]
    depends_on: [queue]
  everything:
    composite: [queue, web]
```

A helper has an `argv` or a `composite`, not both. Its keys: `label`, `group`, `argv`, `verbs` (default `start`,
`stop`), `depends_on`, `composite`, `options`, `who` (`human` by default, `lane` or `both`), `warn`, `self`,
`status_names`. A group has `label` and `status`. A dependency loop, an unknown key or an unknown placeholder is refused
at load.

## The script contract

Implemented in `kernel/cockpitlib/helpers.py`.

- **Arguments:** `{pack}`, `{workspace}`, `{root}`, `{records}`, `{verb}`, `{choice}` and `{helper}` are filled in. A
  word with `{choice}` needs `options`: a list of choices, or a command that prints them (one a line, or a JSON list).
  The first word is run as written: name a pack script as `{pack}/bin/...`.
- **Environment:** the caller's, plus `COCKPIT_HELPER_RUN=1` for a run (not for status or options).
- **Standard input:** the caller's.
- **Standard output of a run:** JSON when it starts with `{` or `[`, otherwise text; its tail is kept with the run.
- **Standard output of a group's status:** with `parse: lines`, one line per helper, `name: state (detail)`, where the
  state is `running`, `stopped`, `skipped`, `failed` or `working`. With `parse: json`, a list (or `{"rows": [...]}`) of
  `{name, state, detail}`. A row is matched to a helper by its name, or by the names in `status_names`.
- **Exit codes:** 0 ok, 1 failed, 2 still working, 3 a dependency is down; any other code is read as 1. When a
  dependency fails, the helpers that need it are skipped with 3. A status command that exits with anything but 0 or 2
  marks its group as in error.
- **Time limits:** 3600 seconds for a run, 60 for status and options.
- **Who:** a helper marked `human` is refused to a lane, and one marked `lane` to the human. A run still going is not
  started twice.
- **Records:** `<records>/helpers/<name>.json` and `<name>.log`.

Doctor fails when a helper's program is not on `PATH` or not an executable file.

## A copy-paste example

`bin/helper` in the pack folder (make it executable; the starter pack has another example of this contract, `starter/bin/helper`):

```sh
#!/bin/sh
# usage: helper start|stop|restart <name>   |   helper status
state="${TMPDIR:-/tmp}/example-helpers"; mkdir -p "$state"
case "$1" in
  start)   touch "$state/$2" ;;
  stop)    rm -f "$state/$2" ;;
  restart) rm -f "$state/$2"; touch "$state/$2" ;;
  status)
    for name in queue web; do
      if [ -e "$state/$name" ]; then echo "$name: running (marker file)"; else echo "$name: stopped"; fi
    done ;;
  *) echo "unknown verb $1" >&2; exit 1 ;;
esac
```

## How to test it

```sh
cockpit pack check
cockpit helper list
cockpit helper run web start      # starts queue first; exits with the helper's code
cockpit helper status --json
cockpit helper run everything stop
```

`cockpit doctor` names a helper whose program is missing.
