# Egress rules

## Goal

Your production hosts, dangerous commands and protected paths refused to every lane, on top of what the kernel always
refuses, and a way to prove a rule does what you meant before an agent meets it.

## The pack lines

In `egress.yaml`:

```yaml
production_hosts:                # regular expressions; an empty list is a doctor error
  - 'app\.example\.test'
  - '\.prod\.example\.test\b'
terminal_deny:                   # command patterns no lane may run
  - '\bledgerctl\s+purge\b'
sacred:                          # path patterns no lane may write
  - '/release/'
infra_paths:                     # infrastructure a lane may not write
  - '/deploy/'
destructive_http:                # origins where a destructive HTTP method is refused
  - 'staging\.example\.test'
local_domains:                   # hosts that are this machine's own
  - '\.example\.internal\b'
deny_tools: [browser_cdp]        # tool names no lane may call
mcp_allow:                       # the only MCP tools that may write
  - mcp__ledger__create_note
role_deny:
  reviewer: ['\bmake\s+deploy\b']
git_deny:
  reviewer: [commit, push, "checkout -b"]
write_roots:
  tester: ["{workspace}/evidence"]
host_probes:
  refused: ["curl https://app.example.test/login"]
  allowed: ["git status", "ls repos/app.example.test"]
```

In `pack.yaml`: `refused.hosts` and `refused.commands` (literal texts, added to the deny lists), `allowed.reads`
(exact command lines a lane may run though one of the pack's own rules would refuse them), and `protected_branches`
(branches only the human writes).

## The script contract

There is no script: the contract is what the hook does with these lists (`kernel/cockpitlib/egress.py`; the pack side
is checked in `pack.py` `_egress`).

- **The kernel's own denies come first and cannot be removed.** Pushes, code-host writes, vault and secret files, the
  board database, Hermes's scheduled jobs and cockpit's human commands are refused whatever the pack says. The pack's
  lists are **appended** ([security.md](../security.md#invariants), invariant 2).
- **Patterns are regular expressions**, searched in the command line or the URL. `refused.hosts` and
  `refused.commands` are literal texts instead.
- **`git_deny.<kind>`** lists git verbs with the flags that make them a move (`commit`, `push`, `checkout -b`), judged
  on the command's own arguments: options before the verb are skipped, `merge-base` is not `merge`, and `tag` or
  `branch` alone mean their moving forms. Git aliases are not resolved.
- **`write_roots.<kind>`** entries are absolute or start with `{workspace}` or `{root}`.
- **`mcp_allow`** entries start with `mcp__`.
- **`allowed.reads`** is matched exactly: a command line counts when every part of it (split at `&&`, `||`, `;` and
  `|`) equals an entry. Such a line is past the pack's own rules (`terminal_deny`, `refused.commands`,
  `production_hosts`, `refused.hosts`, `sacred`, `infra_paths`, `role_deny`, `git_deny` and the write roots): the use is
  a read your own pattern catches by accident, such as `ls repos/app.example.test`. It is **not** past the kernel: the
  kernel's denies are judged first, so an entry that is a push, a changed remote, a code-host write, a commit that skips
  its hooks or a read of a secret file is still refused, and `cockpit doctor` fails on it
  (`allowed.reads lists a command the kernel refuses: <entry>`).
  An allowed read is also past two narrowing checks that are not kernel denies: the refusal of a
  search over a home folder or the machine's root, and the write fence. List reads, and nothing that writes.
- **Known limit: a read of a remote is judged by where its words stand.** `git remote -v`, `git remote show`,
  `git remote get-url` and `git config --get remote.origin.pushurl` are refused when the words stand together (the
  older rule refuses every such line, reads included), and pass behind an option (`git -C <dir> remote -v`,
  `git -C <dir> config --get remote.origin.url`), where git's own arguments are read and only a change is refused. A
  change is refused in both forms. The two forms were not made alike because that would allow lines that are refused
  today; a lane that needs a remote's address uses the `-C` form.
- **The hook fails closed:** a tool call it cannot read is blocked, and when the bound pack does not load, every tool
  that can reach the network or change anything is refused until `cockpit pack check` passes.
- **What it is not:** a sandbox. It reads command lines and tool inputs
  ([security.md](../security.md#trust-boundaries)).

## A copy-paste example

The smallest useful `egress.yaml` for a project with one production site:

```yaml
terminal_deny: []
production_hosts:
  - 'shop\.example\.test'
sacred: []
infra_paths: []
destructive_http: []
host_probes:
  refused:
    - "curl https://shop.example.test/admin"
    - "curl -X POST https://shop.example.test/api/orders"
  allowed:
    - "git status"
    - "cat repos/shop.example.test/README.md"
```

The second `allowed` probe is the reason probes exist: a folder named like the host must not be refused.

## How to test it

```sh
cockpit pack check
cockpit doctor
#   production host NOT blocked: <command>                       a refused probe got through
#   production_hosts refuses a command it must allow: <command>  an allowed probe was refused
#   allowed.reads lists a command the kernel refuses: <entry>     the entry never runs: take it out
#   the pack's own rules refuse git status to a worker (<rule>): its lanes cannot work
#   warning: egress.yaml: unknown key production_host (did you mean production_hosts?): no kernel code reads it
```

For the write fence, ask for one path as a card's lane would get it:

```sh
cockpit fence-check --card <card id> --path repos/api/src/app.py --lane worker-1
# ALLOWED  /abs/path          or          BLOCKED  /abs/path  (<why>)
# then the card, its ticket, its repos and its worktrees; exit 0 allowed, 1 blocked
```

It reads only. The kernel's own rules are exercised by `tests/test_fence_rules.py`.
