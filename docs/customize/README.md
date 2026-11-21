# Customising cockpit

Everything specific to a team lives in its pack: YAML files, scripts and prompt files in the workspace. The kernel knows
no repo, product or host. This folder has one recipe per extension point, each with the same five headings:

1. **Goal**: what you get.
2. **The pack lines**: the keys to add.
3. **The script contract**: arguments, environment, standard input, standard output and exit codes, as the named module
   implements them.
4. **A copy-paste example**: minimal and runnable.
5. **How to test it**: without waiting for an agent to reach it.

Three things hold for every recipe:

- **A pack script is trusted code.** It runs with your environment, and several run as you on purpose. See
  [security.md](../security.md#trust-boundaries).
- **Check the pack after every edit:** `cockpit pack check` names the key and the shape it takes;
  `cockpit pack explain <key>` prints one key's meaning and the value in force. Every key is in
  [reference/pack-keys.md](../reference/pack-keys.md), and the schemas under `kernel/schema/` give an editor completion.
- **An absent key is exactly the behaviour before the key existed.** Add only what you need.
- **A default that will change is announced first.** `cockpit pack pin` prints the lines that write out each value
  your pack takes from such a default; see [operations/pinning.md](../operations/pinning.md).

The [starter pack](../../starter/README.md) under `starter/` holds generic skills, a common soul and one working
script for five of these contracts (`bin/notify`, `bin/tracker`, `bin/verify`, `bin/helper`, `bin/slot`).
`cockpit init` copies it into a new pack; the recipes of those five say so.

## Commands the pack provides

| Recipe | You want | Module |
|---|---|---|
| [Repo gates](repo-gates.md) | each repo's tests run by one command, with the failures picked out | `gates.py` |
| [Verify commands](verify-commands.md) | a lint or check run on exactly the commits about to be pushed | `outbox.py` |
| [Slot runtime](slot-runtime.md) | an isolated dev stack per ticket | `slots.py` |
| [Helpers](helpers.md) | the dev stack, tunnels and services started from one place | `helpers.py` |
| [Notifications](notifications.md) | a message in your channel when something waits for you | `notify.py` |
| [Asks](asks.md) | your own approval button in the Inbox | `asks.py` |
| [Perf and export](perf-and-export.md) | a scheduled sync or archive of the records | `ops.py` |
| [The advisor](advisor.md) | a second opinion at checkpoints of a worker's run | `advise.py` |
| [IDE and chat commands](ide-and-chat.md) | Open IDE and Chat wired to your tools | `ops.py`, `chat.py` |
| [A tracker by command](tracker-command.md) | a tracker cockpit has no client for | `trackers/command.py` |
| [The code host's issues as the tracker](tracker-github-issues.md) | tickets that are GitHub issues, with no second sign-in | `trackers/github_issues.py` |
| [The accounts command](accounts-command.md) | test accounts made and renewed for the lanes | `accounts.py` |

## Text and behaviour the pack shapes

| Recipe | You want | Module |
|---|---|---|
| [Seats and souls](seats-and-souls.md) | each role's prompt, skills, MCP servers and settings | `pack.py`, `setup.py` |
| [Prompt overrides](prompt-overrides.md) | your own text for a named kernel prompt | `prompts.py` |
| [Card text and titles](card-text-and-titles.md) | cards worded and chained your way | `pack.py`, `decompose.py` |
| [Kickoff preflight and lanes](kickoff-preflight-and-lanes.md) | a mode started on another seat, or with other checks | `registry.py` |
| [Plugin card kinds and kickoff modes](plugin-card-kinds.md) | a plugin's own cards and modes | `registry.py`, `api.py` |
| [Egress rules](egress-rules.md) | your production hosts and paths refused to every lane | `egress.py` |
| [Personal values](personal-values.md) | one pack shared unchanged, with each person's home folder, login and addresses in a file of their own | `pack_local.py` |

## The shared exit-code convention

Slot commands and helpers answer the same way:

| Exit code | Meaning |
|---|---|
| 0 | ok |
| 1 | failed |
| 2 | still working |
| 3 | a dependency is down |

Any other code is read as failed. Every other pack command is simpler: 0 is success and anything else is a failure whose
last output line is reported.
