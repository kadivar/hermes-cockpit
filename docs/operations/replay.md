# Replay

Before a new kernel is accepted on an installation, `scripts/replay` proves on that machine that the new kernel reads the installation's real records exactly as the kernel running now does. Records stay on the machine. Only a receipt of hashes and counts leaves it.

| Word | Meaning |
|---|---|
| **Baseline** | The kernel checkout running now. |
| **Candidate** | The kernel checkout to accept. |
| **Snapshot** | A copy of what a replay reads: the records folder, the pack, the board. Cut by reading only. It holds private records. |
| **Capture** | What one kernel answers over a fresh copy of the snapshot: one JSON file per view, and a manifest of their hashes. It holds private records too. |
| **Receipt** | Hashes, counts and verdicts. No record, no pack content, no ticket key, no path. The only file that may leave. |

## What it proves

Both kernels are run over the same snapshot, at the same frozen moment, with no way out. Their answers must be the same, byte for byte:

- the Outbox list as the Desktop gets it, and every intent as its pane reads it (files, renderings, Brief, required skills);
- the Inbox (`/needs-you`, the PR rows, the plugin rows, the tracker notes), the stored standup and a standup drafted at the frozen moment;
- the Board and every card's detail; the Tickets page and every ticket; the QA index and every ticket's runs;
- every PR record and CI record as the pages read them;
- the skills each intent type and each card kind requires, and what each intent's lane is missing;
- the loaded pack, and `cockpit pack effective` when the kernel has it;
- the numbered digest, the morning digest, and one read of every watched PR against a quiet forge: the record each kernel writes;
- every file each kernel wrote in the sandbox while doing so, and every command and address it tried to reach;
- the fence's decision for about a hundred shell commands (`scripts/replay_support/commands.txt`), for each seat: no lane, worker, tester, reviewer, intake, analyst, gatekeeper, and an editor session outside the lanes.

## What it does not prove

- Nothing about writes that leave. No intent is published, no card is made, no tracker is written. The forge stand-in refuses every write and counts the attempts; the count must be zero.
- Nothing that needs the live runtime, the forge's real answers, git checkouts, the vault or a live session. The sandbox has the records, the pack and the board, and nothing else. Views that read more are left out, and the manifest names each one with the reason (`skipped`).
- The forge is a quiet one, made from the PR records themselves: each pull request as its record last saw it, with no new comment, review or thread. A change in how a kernel reads a new comment is the kernel suite's job.
- A fence decision that depends on a stored secret or a running card. The sandbox has neither.
- The Desktop bundle. Only the Python side is replayed.
- A view that raises is compared too: both kernels must raise the same. The receipt counts them. A count above zero is worth a look even when the replay is identical.

A file larger than 16 MB that is not a record (a video, an archive) is copied as an empty file of the same size and time. The views list such files; they do not read them. A pack may name absolute folders (its skills folder); those are read where they are.

The pack folder is copied whole, so a `pack.local.yaml` in it is in the snapshot. It holds one person's values (a login, an address, folders under their home): one more reason a snapshot never leaves the machine. In the sandbox `{home}` is the sandbox's own home folder, the same for both kernels. A kernel from before [personal values](../customize/personal-values.md) reads the two tokens as plain text, so on a pack that uses them its answers differ from a newer kernel's.

## The commands

Run them on the installation's machine, with an interpreter that has the kernel's dependencies (a kernel's own `.venv` is used when it has one; `--python` names another). Write the snapshot and the captures outside the workspace and outside `~/.hermes`; the tool refuses otherwise.

```sh
cd <candidate checkout>

# 1. one snapshot, cut by reading only
scripts/replay snapshot --kernel ~/.hermes/plugins/cockpit \
  --workspace <workspace> --pack <workspace>/<pack folder>/pack.yaml --out /tmp/replay/snapshot

# 2. each kernel over that same snapshot
scripts/replay capture --kernel ~/.hermes/plugins/cockpit --snapshot /tmp/replay/snapshot --out /tmp/replay/baseline
scripts/replay capture --kernel <candidate checkout>      --snapshot /tmp/replay/snapshot --out /tmp/replay/candidate

# 3. what differs
scripts/replay compare /tmp/replay/baseline /tmp/replay/candidate

# 4. the receipt, with the pack's own tests run against the candidate
scripts/replay receipt --baseline /tmp/replay/baseline --candidate /tmp/replay/candidate \
  --pack-tests "<the pack's test command>" --out /tmp/replay/receipt.json

# 5. the snapshot and the captures hold private records: remove them
rm -rf /tmp/replay/snapshot /tmp/replay/baseline /tmp/replay/candidate
```

`compare` exits 0 when every answer is identical, 1 when one differs, 2 when the two captures are not of the same snapshot, clock and pack. `receipt` exits 0 only on `accept`: replay identical (or every difference allowed), effective settings not different, pack tests passed. The pack's test command gets `COCKPIT_PLUGIN_DIR=<candidate checkout>`.

Send `receipt.json`. Nothing else.

## Reading a difference

```
views/outbox/list.json: 2 difference(s)
  $.result.rows[3].skills.required.length: 1 -> 2
  $.result.rows[3].skills.required[1]: only in B: "open-pr"
```

The file is the view (`views/outbox/list.json` is the Outbox list; `views/outbox/intent/<ticket>/<intent>.json` one intent; `views/fence/worker.json` the worker's fence). The path is where in that answer, as a JSON path. `A` is the first capture, `B` the second. The first five differences of a file are shown. Open the two files side by side for the rest; they are sorted and indented the same way, so a plain `diff` works.

Where to look first:

- `views/pack/loaded.json` or `views/pack/effective.json` differ: the candidate reads the pack differently. Most other differences follow from this one.
- `views/effects/written.json` differs: a kernel wrote a file the other did not, or wrote it differently. The path names the file, as `{WORKSPACE}/…`.
- `views/effects/outward.json` differs: a kernel tried a command or an address the other did not.
- `views/fence/<seat>.json` differs: a command is decided differently for that seat. `key` is the command's line in the corpus. A decision that got looser is never acceptable.
- A file is `only in A` or `only in B`: one kernel has a route the other lacks, or one raised where the other answered.

## Allowing a difference

A difference that is meant (a new field, a new route) goes on a reviewed list, with the reason. The list is a JSON file:

```json
[
  {"file": "views/outbox/intent/*.json", "path": "$.result.brief", "reason": "the Brief gained a line for the base branch"},
  {"file": "views/settings/new-page.json", "path": "$", "reason": "a new route"}
]
```

`*` is any run of characters, in both globs; nothing else is special. Pass the file to `compare` and `receipt` with `--allow`. The receipt then says `allowed`, how many differences were excused, and the hash of the list. The list itself is reviewed with the candidate, not sent with the receipt.

## How it keeps the installation safe

- The workspace, the pack and the runtime's home are opened for reading only. The board's database is copied as files and settled in the copy; it is never opened where it lives. `config.yaml` is not copied: only the provider it names is.
- Each capture runs over its own copy of the snapshot, in a temp folder that is removed afterwards.
- The kernel runs in a process of its own with an environment made from nothing: no lane, no credentials, a home, a temp folder and a keyring of the sandbox. Its sockets refuse to connect and no name is looked up. `gh`, the runtime's CLI, `curl`, `ssh`, `docker` and the like are stand-ins first on its `PATH`.
- The clock is frozen at the moment the snapshot was cut (`--clock` names another). A sleep moves the clock on and takes no time.
- Folders are listed in name order, hash seeds are fixed, the zone is UTC, and every path of the sandbox or of a kernel's checkout is written as `{WORKSPACE}`, `{HERMES_HOME}`, `{ROOT}`, `{PACK}`, `{KERNEL}`.
