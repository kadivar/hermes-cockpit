# Slot runtime

## Goal

An isolated runtime per ticket (a dev stack, a database, its own ports) that a tester can drive without touching your
own stack. The kernel owns who holds a slot; your commands own the stack.

## The pack lines

In `pack.yaml`:

```yaml
seats:
  slots: 1                       # each slot has a worker and a tester seat
slots:
  provider: command
  ports: {app: 8100}             # a slot's port is the base plus the slot number
  state_dir: "{root}/slots/{slot}"
  commands:
    up:     {argv: [bin/slot, up, "{slot}", "{port.app}"]}
    down:   {argv: [bin/slot, down, "{slot}"]}
    ready:  {argv: [bin/slot, ready, "{slot}", "{port.app}"]}
    status: {argv: [bin/slot, status, "{slot}", "{port.app}"]}
    exec:   {argv: [bin/slot, exec, "{slot}", "{args...}"], passthrough: true, who: lane}
```

`slots` takes only the keys in [the reference](../reference/pack-keys.md#slots). `state_dir` and `data_dir` must name
`{slot}`. A command is `{argv, who, passthrough}`: `who` is `human`, `lane` or `both` (the default, except `login`,
which is the human's); `{args...}` needs `passthrough: true`. `slots.provider: none` (or `seats.slots: 0`) is a pack
without slots.

## The script contract

Implemented in `kernel/cockpitlib/slots.py` (`CommandProvider`); the block is checked in `pack.py` (`_slots`).

- **Arguments:** filled into each word: `{slot}`, `{ticket}`, `{owner}`, `{repo}`, `{records}`, `{worktree}` (the
  ticket's `wt/<ticket>` folder), `{state_dir}`, `{data_dir}` and `{port.<name>}`. `{args...}` as a word by itself
  becomes the caller's own words. A relative first word with a `/` is a file in the pack folder.
- **Environment:** the caller's, plus `COCKPIT_SLOT`, `COCKPIT_TICKET`, `COCKPIT_OWNER` and `COCKPIT_LANE`.
- **Standard input:** the caller's.
- **Standard output:** when it starts with `{` or `[` it is read as JSON, otherwise kept as text.
  - `status`: the keys of a JSON object (other than `slot`, `owner`, `ticket`) are merged into the slot's status row.
  - `login`: JSON with `user` and `password`.
  - a store's `probe`: JSON with `present` and `have`; its `capacity`: a number.
- **Exit codes:** 0 ok, 1 failed, 2 still working, 3 a dependency is down; any other code is failed. `up`, `down`,
  `reset`, `exec` and `login` are an error unless the answer is ok or working.
- **Time limit:** 3600 seconds a command. After `up`, the kernel polls `ready` every 2 seconds for up to 30 minutes.
- **Bring-up order:** `warm` when the pack has it, else `up`; then the pack's `slot_browser` and `dev_servers` commands
  are started; then `ready` is polled.
- **Who:** a verb marked `human` is refused to a lane and one marked `lane` to the human. Toggles and releasing a slot
  are the human's. `exec` is refused for a line that matches `slots.exec_refuse`.
- **Records:** each run's output and exit code in the slot's own folder as `<verb>.log`.

## A copy-paste example

`bin/slot` in the pack folder (make it executable; the starter pack has another example of this contract, `starter/bin/slot`). It serves one folder per slot with Python's
built-in web server:

```sh
#!/bin/sh
# usage: slot <verb> <slot> [port] [args...]
verb=$1; slot=$2; port=$3
state="${TMPDIR:-/tmp}/example-slot-$slot"
case "$verb" in
  up)
    mkdir -p "$state/www"
    echo "slot $slot for ${COCKPIT_TICKET:-nobody}" > "$state/www/index.html"
    # every stream of the server goes to a file: a background process that kept the command's own output open
    # would keep the kernel waiting for it
    nohup python3 -m http.server --directory "$state/www" "$port" >"$state/server.log" 2>&1 </dev/null &
    echo $! >"$state/pid"
    exit 2 ;;                                   # still working: ready says when it is up
  ready|status)
    if curl -fs "http://127.0.0.1:$port/" >/dev/null 2>&1; then
      [ "$verb" = status ] && echo "{\"url\": \"http://127.0.0.1:$port/\"}"
      exit 0
    fi
    [ -f "$state/pid" ] && exit 2 || exit 1 ;;
  down)
    [ -f "$state/pid" ] && kill "$(cat "$state/pid")" 2>/dev/null
    rm -rf "$state"; exit 0 ;;
  exec)
    shift 2; exec "$@" ;;
  *) echo "unknown verb $verb" >&2; exit 1 ;;
esac
```

## How to test it

Run these in your own terminal (an editor assistant's session is refused slot commands by the editor fence):

```sh
cockpit pack check
cockpit slot status --json        # every slot with its owner and what status printed
cockpit slot up 1 TASK-100
cockpit slot ready 1              # exits 0, 1, 2 or 3 as your command did
cockpit slot run status 1         # any verb of the pack, by name
cockpit slot down 1
```

Then test the script alone, with the environment the kernel sets:
`COCKPIT_SLOT=1 COCKPIT_TICKET=TASK-100 bin/slot up 1 8101; echo $?`.
