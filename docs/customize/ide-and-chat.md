# IDE and chat commands

## Goal

The **Open IDE** button opens your editor on a ticket's checkout or on one file, and the **Chat** button opens a
terminal running your coding tool on the ticket, resuming its session where there is one.

## The pack lines

In `pack.yaml`:

```yaml
providers:
  coding:
    command: [codetool, --print]             # required: the coding tool the lanes' workers start
  chat:
    command: [codetool, --session-id, "{session}"]                                     # a new session; cockpit names it
    resume:  [codetool, --resume, "{session}"]                                         # the session whose transcript exists
    fork:    [codetool, --resume, "{source}", --fork-session, --session-id, "{session}"]   # started from a lane's run
    session_glob: "{root}/chats/*/{session}.jsonl"                                     # where the tool keeps a transcript
    cwd: "{wt}"
    env: {EDITOR: vi}
ide:
  command: [bin/ide, open, "{ticket}"]
  file_command: [bin/ide, file, "{path}"]
```

`codetool` stands for your own coding tool's command. `providers.chat` takes `command`, `resume`, `fork`,
`session_glob` (which must name `{session}`), `display_name`, `cwd` and `env`; `ide` takes `command` and
`file_command`. Each command is a list of words.

## The script contract

Open IDE is implemented in `kernel/cockpitlib/ops.py` (`ide_open`, `ide_argv`, `ide_launch`), the chat in
`kernel/cockpitlib/chat.py`.

**Open IDE**

- **What runs:** `ide.file_command` for a file with no ticket, `ide.command` otherwise (a file together with a ticket
  still runs `ide.command`). Without the key, the request is only recorded.
- **Arguments:** `{ticket}`, `{path}`, `{workspace}` and `{root}` are filled in. A relative first word with a `/` is a
  file in the pack folder; a bare word such as `code` is found on `PATH`.
- **How:** started detached in the workspace folder, with no input and its output discarded. Its exit code is not read;
  a command that cannot start is reported (`ide.command did not start: ...`).
- **Record:** `<records>/platform/ide-<ticket>.json` (the ticket, its repos and worktrees, the file).

**Chat**

- **Which command:** `COCKPIT_CHAT_ARGV` in the environment wins, split on spaces. Otherwise `resume` when the
  session's transcript exists under `session_glob`, else `fork` when the chat starts from a lane's run, else `command`.
- **Without `providers.chat`:** a ticket chat runs `providers.coding.command` with its print-mode flags removed (`-p`,
  `--print`, and `--max-turns`, `--output-format`, `--input-format` with their values); the personal chat is your
  shell.
- **Arguments:** `{session}` and `{source}` in `command`, `resume` and `fork`; `{root}` and `{session}` in
  `session_glob`; `{ticket}`, `{wt}`, `{workspace}` and `{root}` in `cwd` and `env`; `{PATH}` in `env` is the current
  `PATH`.
- **Working directory:** `cwd` when that folder exists, else the pack's `agent.home`, else the ticket's worktree
  folder; the personal chat starts in the workspace.
- **Environment:** the Desktop's, plus `TERM=xterm-256color`, the pack's `env`, and `COCKPIT_FORK_FROM` (a lane's
  transcript) when forking.
- **How:** in a terminal the Desktop shows; the chat keeps one session per ticket until the flow ends.

## A copy-paste example

`bin/ide` in the pack folder (make it executable):

```sh
#!/bin/sh
# usage: ide open <ticket>   |   ide file <path>
editor="${VISUAL:-${EDITOR:-vi}}"
case "$1" in
  open) echo "$(date '+%H:%M') open $2" >> "${HOME}/cockpit-ide.log" ;;
  file) echo "$(date '+%H:%M') file $2" >> "${HOME}/cockpit-ide.log" ;;
  *) echo "usage: ide open <ticket> | ide file <path>" >&2; exit 1 ;;
esac
# replace the two lines above with your editor's own command, for example: exec "$editor" "$2"
```

## How to test it

```sh
cockpit pack check
cockpit ide open TASK-100
cockpit ide file hermes/qa/TASK-100/plan.md
tail -2 ~/cockpit-ide.log
```

Each prints the command line it started, or the record's path when the pack names no command. For the chat, set
`COCKPIT_CHAT_ARGV="sh -i"` in the Desktop's environment once to confirm the pane works before you wire your tool.
