# Perf and export

## Goal

Two scheduled jobs that hand the records to your own scripts: a daily sync of what the pipeline did (for a dashboard or
a spreadsheet of your own), and a weekly export after the vault backup (an archive, an off-machine copy).

## The pack lines

In `pack.yaml`:

```yaml
perf:
  command: [bin/perf, "{record}"]
export:
  keep: 4
  commands:
    - [bin/archive, "{records}"]
```

`perf` takes `command`. `export` takes `commands` (a list of commands) and `keep` (a whole number of backups, 1 or
more). Without the blocks the two jobs still run: perf writes its record, export backs up the vault.

## The script contract

Implemented in `kernel/cockpitlib/ops.py` (`perf_sync`, `export_keep`).

- **Arguments:** `{records}` is the records folder. For perf, `{record}` is the file the kernel has just written,
  `<records>/platform/perf.json`: a JSON object with `name` and three lists of at most 20 rows, `tracker` (tracker
  intents: `ticket`, `type`), `pull_requests` (`ticket`, `repo`, `number`) and `approvals`. For an export
  command `{record}` is empty. A relative first word with a `/` is a file beside `pack.yaml`.
- **Environment and standard input:** the caller's (a Hermes cron job: a bare `PATH`, completed by cockpit with the
  usual folders).
- **Standard output and error:** read only on failure (the last line is reported).
- **Exit codes:** 0 is success. Anything else is a failed watcher: a red row in the Inbox for `perf-sync` or `export`.
- **Time limit:** 600 seconds a command.
- **Export order:** the vault backup runs first, keeping `keep` backups. When it fails, or the vault key is not sealed,
  the commands are skipped. Then each command runs in order, and every failure is collected.
- **Schedule:** `perf-sync` on working days and `export` on Fridays, as Hermes cron jobs that run `cockpit perf` and
  `cockpit export --keep 4`. The option wins: `export.keep` is what a plain `cockpit export` keeps.
- **Records:** `<records>/platform/perf.json` and `platform/export.json`; health in `<records>/watch/`.

## A copy-paste example

`bin/perf` in the pack folder (make it executable):

```sh
#!/bin/sh
# usage: perf <record file>   (appends one line a day to a CSV of your own)
record=$1
[ -f "$record" ] || { echo "no record $record" >&2; exit 1; }
python3 - "$record" >> "${HOME}/cockpit-perf.csv" <<'EOF'
import datetime, json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(",".join(str(item) for item in (datetime.date.today(), data["name"], len(data["pull_requests"]),
                                      len(data["approvals"]))))
EOF
```

`bin/archive`:

```sh
#!/bin/sh
# usage: archive <records folder>
tar -czf "${HOME}/cockpit-records-$(date +%Y%m%d).tgz" -C "$(dirname "$1")" "$(basename "$1")"
```

## How to test it

```sh
cockpit pack check
cockpit perf                 # writes perf.json, then runs your command
cockpit export --keep 4      # backs up the vault, then runs your commands
```

Each prints its outcome and leaves a health record; make a script exit 1 once to see the red row in the Inbox.
