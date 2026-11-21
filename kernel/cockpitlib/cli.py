# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One command line. Every subcommand calls the kernel and prints a line."""

import json
import os
import sys

from .doctor import report as doctor_report
from .errors import CockpitError, NeedMigrate
from .pack import check_repos, load
from .paths import pack_path, qa_of, workspace
from .setup import gateway_down, gateway_status, gateway_up
from .setup import setup as do_setup

EXAMPLES = {
    "pack": (
        "cockpit pack check [--all] | cockpit pack effective [--json] [--sources] | cockpit pack explain forge.bump_batch [--json] | "
        "cockpit pack pin [--all] [--json]"
    ),
    "describe": "cockpit describe --json",
    "demo": "cockpit demo gate [--yes] [--keep]",
    "init": "cockpit init --no-production | cockpit init ~/work/shop --production-host 'app\\.example\\.test' --write",
    "setup": "cockpit setup",
    "update": (
        "cockpit update check | cockpit update apply [--to <commit>] [--no-restart] | cockpit update rollback [--to <commit>] [--no-restart]"
        " | cockpit update rehome https://example.test/team/cockpit.git [--branch main] [--dry-run] | cockpit update rehome --undo"
    ),
    "apply": "cockpit apply",
    "doctor": "cockpit doctor [--strict] [--json] [--online]",
    "up": "cockpit up",
    "down": "cockpit down",
    "status": "cockpit status",
    "outbox": "cockpit outbox new TASK-100 push-branch --card t_1 --summary 'push the export' --repo api --branch work/TASK-100",
    "guard": "cockpit guard < hook-input.json",
    "publish": "cockpit publish --id TASK-100/001-push-branch --dry-run",
    "plan": "cockpit plan show TASK-100",
    "migrate": "cockpit migrate discover",
    "slot": "cockpit slot status",
    "live": "cockpit live TASK-123 --no-tools",
    "board": "cockpit board --watch",
    "advise": "cockpit advise C0 note",
    "ticket": "cockpit ticket list",
    "watch-pr": "cockpit watch-pr",
    "watch-ci": "cockpit watch-ci",
    "watch-base": "cockpit watch-base",
    "bumps": "cockpit bumps scan",
    "advisories": "cockpit advisories scan | list | ack <id> [--note <text>] | unack <id>",
    "standup": "cockpit standup draft",
    "vault": "cockpit vault init --key <fingerprint>",
    "session": "cockpit session open 1 TASK-100",
    "worktree": "cockpit worktree add TASK-100 | cockpit worktree gc [--days 14] [--dry-run]",
    "ide": "cockpit ide open TASK-100 | cockpit ide open TASK-100 --file hermes/qa/TASK-100/plan.md | cockpit ide file hermes/qa/TASK-100/plan.md",
    "map": "cockpit map build",
    "gate": "cockpit gate",
    "workspace-watch": "cockpit workspace-watch",
    "export": "cockpit export --keep 4",
    "resume-context": "cockpit resume-context",
    "digest": "cockpit digest",
    "perf": "cockpit perf",
    "helper": "cockpit helper run web start",
    "reply": "cockpit reply 'publish 1-3'",
    "ci": "cockpit ci flaky TASK-100 <sha> --run-id 42",
    "flow": "cockpit flow decompose TASK-100 breakdown.json | flow reopen TASK-100 'what changed'",
    "test": "cockpit test plan TASK-100 plan.md | test fail TASK-100 3 'what broke' | test run-dir TASK-100",
    "pace": "cockpit pace --json [--days 0,1,2,3,4] [--start HH:MM] [--end HH:MM] [--peak] [--fresh]",
    "record": (
        "cockpit record start --session tester-1-TASK-100 --out hermes/qa/TASK-100/run-1/evidence/videos/"
        "s3-save-button-repro.mp4 --record-id 'order 4711' --on-screen 'the saved order, form open' "
        "[--max-seconds 180] [--url-contains /orders] | record stop --session tester-1-TASK-100 | record status"
    ),
}
FLAGS = {
    "pack": {"--json", "--sources", "--all"},
    "publish": {"--dry-run", "--approve", "--id", "--all"},
    "advisories": {"--note"},
    "export": {"--keep"},
    "vault": {"--key", "--fix", "--lane", "--force"},
    "ticket": {"--force"},
    "setup": {"--rerender", "--seat"},
    "update": {"--no-restart", "--to", "--branch", "--dry-run", "--undo"},
    "describe": {"--json"},
    "demo": {"--yes", "--keep"},
    "doctor": {"--strict", "--json", "--online"},
    "init": {
        "--write",
        "--yes",
        "--json",
        "--pack",
        "--slots",
        "--production-host",
        "--no-production",
        "--tracker",
        "--accept-gates",
        "--no-starter",
        "--no-bind",
        "--rebind",
        "--staging-origin",
        "--tracker-url",
        "--project",
    },
    "slot": {"--json"},
    "live": {"--lane", "--minutes", "--no-tools", "--once", "--json"},
    "board": {"--status", "--lane", "--all", "--watch", "--json"},
    "worktree": {"--from", "--days", "--dry-run"},
    "ide": {"--file"},
    "plan": {"--file", "--decision"},
    "watch-base": {"--file"},
    "gate": {"--repo", "--wait", "--run-id", "--baseline", "--background"},
    "helper": {"--choice", "--run-id", "--background", "--group", "--json"},
    "pace": {"--json", "--days", "--start", "--end", "--peak", "--fresh"},
}
# Commands that check their own flags (their payload flags come from the intent schema).
SELF_PARSED = {"outbox", "ci", "test", "advise", "flow", "record", "fence-check"}
ZERO_ARGS = {
    "up",
    "down",
    "status",
    "apply",
    "watch-pr",
    "watch-ci",
    "watch-base",
    "workspace-watch",
    "digest",
    "perf",
    "resume-context",
}


def parse_command(argv) -> str:
    """The command name only. Examples are parsed and not run."""
    if not argv or argv[0] not in COMMANDS:
        raise CockpitError(f"unknown {argv[0] if argv else ''}")
    return argv[0]


def _unknown_flag(name, argv) -> str:
    allowed = FLAGS.get(name, set())
    for token in argv:
        if token == "--":
            return ""
        if token.startswith("-") and token not in allowed:
            return token
    return ""


def _print_help() -> None:
    print(
        "cockpit <init|demo|pack|describe|setup|update|apply|doctor|outbox|publish|plan|migrate|slot|live|board|advise|up|down|status|ticket|watch-pr|watch-ci|watch-base|bumps|standup|vault|session|worktree|ide|map|gate|workspace-watch|export|resume-context|digest|perf|helper|reply|ci|test|flow|pace|record>"
    )
    print(
        "A wrong argument prints the reason, the usage, and an example, and does not run. This help is the longer explanation."
    )
    for example in EXAMPLES.values():
        print(f"  {example}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        _print_help()
        return 2
    if argv[0] in ("-h", "--help", "help"):
        if argv[1:]:
            token = argv[1]
            reason = "unknown option " + token if token.startswith("-") else "stray argument"
            _header(reason, "cockpit help")
            return 2
        _print_help()
        return 0
    try:
        handler = COMMANDS.get(argv[0])
        if handler is None:
            _header("unknown command " + argv[0], "cockpit doctor")
            return 2
        flag = _unknown_flag(argv[0], argv[1:]) if argv[0] not in SELF_PARSED else ""
        if flag:
            _header("unknown option " + flag, EXAMPLES.get(argv[0], "cockpit " + argv[0]))
            return 2
        if argv[0] in ZERO_ARGS and argv[1:] and argv[:2] != ["watch-base", "verdict"]:
            _header("stray argument", EXAMPLES.get(argv[0], "cockpit " + argv[0]))
            return 2
        from .vault_key import at_terminal, human_present

        with human_present(
            at_terminal()
        ):  # a person at a terminal may be asked for the vault key; a cron or a lane never
            return handler(argv[1:])
    except NeedMigrate as exc:
        print(f"cockpit: {exc}", file=sys.stderr)
        return exc.exit_code
    except CockpitError as exc:
        print(f"cockpit: {exc}", file=sys.stderr)
        return exc.exit_code


def _pack():
    return load(pack_path())


def cmd_pack(argv) -> int:
    """cockpit pack check [--all] | effective [--json] [--sources] | explain <key> [--json] | pin [--all] [--json]: the
    bound pack, checked (with --all: every problem it has, not only the first); every setting with the value in force (and where it came from); one key with its meaning; the lines
    that write out each value the pack takes from a default that will change (with --all, from any default)."""
    if not argv:
        _header("missing argument", "cockpit pack check")
        return 2
    flags = [word for word in argv if word.startswith("--")]
    words = [word for word in argv if not word.startswith("--")]
    if words[:1] == ["pin"]:
        usage = "cockpit pack pin [--all] [--json]"
        if "--sources" in flags:
            _header("unknown option --sources", usage)
            return 2
        if _fits(words, 1, 1, usage):
            return 2
        from .pack_pin import render as render_pin

        text = render_pin(_pack(), every="--all" in flags, as_json="--json" in flags)
        if text:
            print(text)
        return 0
    if "--all" in flags and words[:1] != ["check"]:
        _header("unknown option --all", "cockpit pack pin [--all] [--json]")
        return 2
    if words[:1] == ["effective"]:
        if _fits(words, 1, 1, "cockpit pack effective [--json] [--sources]"):
            return 2
        from .pack_effective import render

        print(render(_pack(), sources="--sources" in flags, as_json="--json" in flags))
        return 0
    if words[:1] == ["explain"]:
        usage = "cockpit pack explain forge.bump_batch [--json]"
        if "--sources" in flags:
            _header("unknown option --sources", usage)
            return 2
        if _fits(words, 2, 2, usage):
            return 2
        from .pack_effective import explain, render_explain

        print(render_explain(explain(_pack(), words[1]), as_json="--json" in flags))
        return 0
    every = flags == ["--all"]
    if flags and not every:  # check takes --all and no other option
        _header("unknown option " + [flag for flag in flags if flag != "--all"][0], "cockpit pack check")
        return 2
    if words[:1] != ["check"]:
        _header("invalid value", "cockpit pack check")
        return 2
    if _fits(words, 1, 1, "cockpit pack check"):
        return 2
    if every:  # every problem of the pack, not only the first a load stops at
        from .pack import problems

        found = problems(pack_path())
        for line in found:
            print(f"cockpit: {line}", file=sys.stderr)
        if found:
            return 2
    data = _pack()
    if os.environ.get("COCKPIT_ROOT") or os.environ.get("COCKPIT_WORKSPACE"):
        from .paths import root

        check_repos(data, root())
    print(f"pack ok {data['name']}")
    return 0


INIT_VALUES = ("--pack", "--slots", "--production-host", "--tracker", "--staging-origin", "--tracker-url", "--project")
INIT_ANSWER = "cockpit init --production-host 'app\\.example\\.test' --write (one per production hostname), or cockpit init --no-production --write"


def _init_words(argv):
    """(folders, {flag: [values]}, switches) of an init command line, or None when a flag that takes a value has none."""
    words, values, switches, index = [], {}, set(), 0
    while index < len(argv):
        token = argv[index]
        if token in INIT_VALUES:
            if index + 1 >= len(argv) or not argv[index + 1] or argv[index + 1].startswith("--"):
                return None
            values.setdefault(token, []).append(argv[index + 1])
            index += 2
            continue
        (switches.add if token.startswith("--") else words.append)(token)
        index += 1
    return words, values, switches


def cmd_init(argv) -> int:
    """cockpit init [DIR]: a first pack for a workspace. It prints what it detected and the files it would write, and
    writes nothing without --write. It never replaces a file, and it never guesses what production is: that takes
    --production-host REGEX (repeatable) or --no-production. The binding file is written last, once the pack loads."""
    import re
    import shlex

    from . import scaffold

    usage = EXAMPLES["init"]
    parsed = _init_words(argv)
    if parsed is None:
        _header("missing argument", usage)
        return 2
    words, values, switches = parsed
    one = {flag: found[-1] for flag, found in values.items()}
    hosts = values.get("--production-host") or []
    try:
        count = int(one.get("--slots", "1"))
        for host in hosts:
            re.compile(host)
    except (ValueError, re.error):
        _header("invalid value", usage)
        return 2
    if (
        len(words) > 1
        or not 0 <= count <= 8
        or one.get("--tracker", "jira") not in scaffold.TRACKERS
        or (hosts and "--no-production" in switches)
        or any(len(found) > 1 for flag, found in values.items() if flag != "--production-host")
    ):
        _header("stray argument" if len(words) > 1 else "invalid value", usage)
        return 2
    writing = "--write" in switches
    if writing:
        from .outbox import human_gate

        human_gate("a new pack and the binding")  # a lane never binds the machine to another workspace
    found = scaffold.detect(
        words[0] if words else "",
        pack_dir=one.get("--pack", ""),
        slots=count,
        production_hosts=hosts,
        no_production="--no-production" in switches,
        tracker=one.get("--tracker", ""),
        accept_gates="--accept-gates" in switches,
        starter="--no-starter" not in switches,
        staging_origin=one.get("--staging-origin", ""),
        tracker_url=one.get("--tracker-url", ""),
        project=one.get("--project", ""),
    )
    planned = scaffold.plan(found, bind="--no-bind" not in switches, rebind="--rebind" in switches)
    answered = bool(hosts) or "--no-production" in switches
    done = None
    if writing and answered and not planned["refused"]:
        done = scaffold.write(planned)
    again = shlex.join(["cockpit", "init", *[word for word in argv if word != "--write"]])
    if "--json" in switches:
        print(
            json.dumps(
                {
                    "workspace": found["workspace"],
                    "pack": found["pack"],
                    "provider": found["provider"],
                    "model": found["model"],
                    "coding": found["coding"],
                    "tracker": found["tracker"],
                    "production": "none" if found["no_production"] else hosts,
                    "repos": [
                        {key: repo[key] for key in ("name", "path", "base", "gates", "suggested")}
                        for repo in found["repos"]
                    ],
                    "files": planned["listed"],
                    "binding": (planned["binding"] or {}).get("path", ""),
                    "written": done is not None,
                    "notes": found["notes"],
                    "refused": planned["refused"],
                },
                indent=2,
            )
        )
    else:
        print(f"workspace   {found['workspace']}")
        print(f"pack        {found['pack']}")
        print(
            f"provider    {found['provider'] or '(none found)'}"
            + (f", model {found['model']}" if found["model"] else "")
        )
        print(f"coding tool {' '.join(found['coding']) or '(none found)'}")
        print(f"tracker     {found['tracker']}")
        print(
            "production  "
            + ("none: no_production_hosts" if found["no_production"] else ", ".join(hosts) if hosts else "NOT ANSWERED")
        )
        for repo in found["repos"]:
            repo_gates = f", gates suggested: {'; '.join(repo['suggested'])}" if repo["suggested"] else ""
            print(f"repo        {repo['name']} at {repo['path']}, base {repo['base']}{repo_gates}")
        binding = planned["binding"]
        print(
            "binding     "
            + (
                "not written (--no-bind)"
                if not binding
                else f"{binding['path']} (already this workspace)"
                if binding["kept"]
                else binding["path"]
                + (" (replaces another workspace's; a copy is kept)" if binding["replaces"] else "")
            )
        )
        for note in found["notes"]:
            print(f"note: {note}")
        print("wrote:" if done else "would write:")
        for name in planned["listed"]:
            print(f"  {name}")
    if planned["refused"]:
        print(f"cockpit: {planned['refused']}", file=sys.stderr)
        return 2
    if not answered:
        print(f"production is not answered, and init never guesses it: {INIT_ANSWER}", file=sys.stderr)
        return 2 if writing or "--yes" in switches else 0
    if done is None:
        if "--json" not in switches:
            print(f"nothing was written. To write it: {again} --write")
        return 0
    if "--json" not in switches:
        if done["backup"]:
            print(f"the binding that was there is kept as {done['backup']}")
        print("next: cockpit setup, then cockpit doctor")
    return 0


def cmd_describe(argv) -> int:
    """cockpit describe --json: this kernel's verbs, intent types, kickoff modes, card kinds and marks, as data. It reads
    no workspace and no pack."""
    if [word for word in argv if word != "--json"]:
        _header("stray argument", EXAMPLES["describe"])
        return 2
    from .describe import describe

    print(json.dumps(describe(), indent=2))
    return 0


def cmd_demo(argv) -> int:
    """cockpit demo gate [--yes] [--keep]: the outbox gate shown working in a sandbox under the temp folder, with no Hermes,
    no forge account and no tracker. It needs no bound workspace and touches none. --yes does not wait for Enter before
    the publish; --keep leaves the sandbox to look at."""
    words = [word for word in argv if not word.startswith("-")]
    if words != ["gate"]:
        _header("missing argument" if not words else "stray argument", EXAMPLES["demo"])
        return 2
    from .demo import gate

    return gate(keep="--keep" in argv, yes="--yes" in argv)


def cmd_update(argv) -> int:
    """cockpit update check | status | apply [--to <commit>] [--no-restart] | rollback [--to <commit>] [--no-restart] |
    rehome <url> [--branch <name>] [--dry-run] | rehome --undo: the plugin against its own repository."""
    from .self_update import apply, check, rollback, status

    words, valued, index = [], {}, 0
    while index < len(argv):
        if argv[index] in ("--to", "--branch"):
            if argv[index] in valued or index + 1 >= len(argv) or not argv[index + 1].strip():
                _header("missing argument", EXAMPLES["update"])
                return 2
            valued[argv[index]] = argv[index + 1]
            index += 2
            continue
        if not argv[index].startswith("--"):
            words.append(argv[index])
        index += 1
    to = valued.get("--to")
    verb = words[0] if words else "status"
    moving = verb == "rehome"
    undo = moving and "--undo" in argv
    takes = {
        "apply": {"--to", "--no-restart"},
        "rollback": {"--to", "--no-restart"},
        "rehome": {"--undo"} if undo else {"--branch", "--dry-run"},
    }.get(verb, set())
    if (
        verb not in ("check", "status", "apply", "rollback", "rehome")
        or len(words) != (2 if moving and not undo else 1 if words else 0)
        or [
            flag
            for flag in argv
            if flag in FLAGS["update"] and flag not in takes and (moving or flag != "--no-restart")
        ]
    ):
        _header("invalid value", EXAMPLES["update"])
        return 2
    if moving:
        import sys

        from . import rehome
        from .outbox import human_gate

        human_gate("updates")  # which repository the code comes from is the human's to say
        done = (
            rehome.undo()
            if undo
            else rehome.rehome(words[1], branch=valued.get("--branch") or "", dry_run="--dry-run" in argv)
        )
        print(json.dumps(done, indent=2))
        line = (done.get("next") or {}).get("line") or ""
        if line:
            print(f"# after the move, run:\n{line}", file=sys.stderr)
        if done.get("undo"):
            print(
                f"# to take the move back, for as long as no update was applied since:\n{done['undo']}", file=sys.stderr
            )
        return 0
    if verb in ("apply", "rollback"):
        import sys

        from .outbox import human_gate

        human_gate("updates")  # the code every seat runs is replaced: a lane reads the state and leaves the act
        done = (apply if verb == "apply" else rollback)(restart="--no-restart" not in argv, to=to or "")
        print(json.dumps(done, indent=2))
        for note in (done.get("preflight") or {}).get("notes") or []:
            print(f"# {note}", file=sys.stderr)
        line = (done.get("next") or {}).get("line") or ""
        if line:  # what is left to the human, one line for this shell, on stderr so the JSON above stays whole
            print(f"# after the {'update' if verb == 'apply' else 'rollback'}, run:\n{line}", file=sys.stderr)
        return 0
    print(json.dumps(check() if verb == "check" else status(), indent=2))
    return 0


def cmd_setup(argv) -> int:
    rerender = False
    seat = ""
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--rerender" and not rerender:
            rerender = True
            index += 1
            continue
        if token == "--seat" and not seat:
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                _header("missing argument", "cockpit setup --rerender --seat worker-1")
                return 2
            seat = argv[index + 1]
            index += 2
            continue
        _header("stray argument", EXAMPLES["setup"])
        return 2
    if seat and not rerender:
        _header("--seat needs --rerender", "cockpit setup --rerender --seat worker-1")
        return 2
    data = _pack()
    do_setup(data, rerender=rerender, seat=seat)
    gateway_up()
    from .vault import init_vault

    sealed = init_vault()
    found = doctor_report(data)["findings"]
    errors = [item for item in found if item["severity"] == "error"]
    for line in _finding_lines(errors) + _finding_lines(
        [item for item in found if item["severity"] == "warning"], "warning: "
    ):
        print(line, file=sys.stderr)
    if errors:  # a warning is printed and never fails setup; an error does, as every doctor line did before the tiers
        return 1
    from .map_build import MISSING, map_yaml_path

    if not os.path.isfile(map_yaml_path(data)):
        print(MISSING)
    print(sealed)
    print("setup ok")
    return 0


def cmd_apply(argv) -> int:
    return cmd_setup(argv)


def _finding_lines(found, prefix: str = "") -> list:
    """Each finding's message, and under it the line that resolves it."""
    lines = []
    for item in found:
        lines.append(prefix + item["message"])
        if item.get("fix"):
            lines.append(f"  fix: {item['fix']}")
    return lines


def cmd_doctor(argv) -> int:
    """cockpit doctor [--strict] [--json] [--online]: the errors, then the warnings, each with the line that resolves it.
    Only an error fails it; --strict makes a warning fail too, and no flag makes an error pass. --online adds the probes
    that need the network. A note is printed after the verdict and never changes it."""
    if [word for word in argv if not word.startswith("--")]:
        _header("stray argument", EXAMPLES["doctor"])
        return 2
    data = _pack()
    told = doctor_report(data, online="--online" in argv, strict="--strict" in argv)
    if "--json" in argv:
        print(json.dumps(told, indent=2))
        return 0 if told["ok"] else 1
    found = told["findings"]
    warnings = [item for item in found if item["severity"] == "warning"]
    lines = _finding_lines([item for item in found if item["severity"] == "error"]) + _finding_lines(
        warnings, "warning: "
    )
    if told["ok"]:
        lines.append(
            "doctor: OK" + (f" ({len(warnings)} warning{'s' if len(warnings) > 1 else ''})" if warnings else "")
        )
    print("\n".join(lines))
    for item in found:  # what doctor accepted on a live check, or why one did not pass: printed, never the verdict
        if item["severity"] == "info":
            print(f"note: {item['message']}")
    return 0 if told["ok"] else 1


def cmd_up(_argv) -> int:
    print(gateway_up())
    return 0


def cmd_down(_argv) -> int:
    print(gateway_down())
    return 0


def cmd_status(_argv) -> int:
    print(gateway_status())
    return 0


OUTBOX_USAGE = (
    "cockpit outbox new <ticket> <type> --card <id> --summary <text> [payload flags] | amend <id> [--summary <text>] "
    "[--top-level] [payload flags] | list [<ticket>] | show <id> | endorse <id> <risk> [notes] | hold <id> --reason <text> "
    "[--waits lane] [--rework <text> [--chain]] [--ask <question> --option <answer>...] | return <id> --instruction <text> "
    "[--assignee <lane>] [--evidence <path>]... [--no-chain] | drop <id> [--note <text>] | verify <id> | reprobe <id> | ack <id> | "
    "digest | "
    "reconcile [<ticket>] | sweep | rework <ticket> --instruction <text> [--repo <repo>] [--evidence <path>]... | "
    "chain <ticket> <after-card> --instruction <text> [--repo <repo>] | relink <id> --waits-for <id>"
)
OUTBOX_VALUES = {
    "--card",
    "--summary",
    "--risk",
    "--evidence",
    "--reason",
    "--waits",
    "--rework",
    "--ask",
    "--option",
    "--instruction",
    "--assignee",
    "--note",
}
OUTBOX_REPEATS = {"--evidence", "--attach", "--option"}
OUTBOX_SWITCHES = {"--top-level", "--chain", "--no-chain"}
# flags each action takes besides the payload flags of new and amend
ACTION_FLAGS = {
    "hold": {"--reason", "--waits", "--rework", "--ask", "--option", "--chain"},
    "return": {"--instruction", "--assignee", "--evidence", "--no-chain"},
    "drop": {"--note"},
    "rework": {"--instruction", "--repo", "--evidence"},
    "chain": {"--instruction", "--repo"},
    "relink": {"--waits-for"},
    "ci-override": {"--reason"},
}


def _payload_flags():
    from .intents import FIELDS

    values = {"--" + name.replace("_", "-") for name, shape in FIELDS.items() if shape != "bool"}
    switches = {"--" + name.replace("_", "-") for name, shape in FIELDS.items() if shape == "bool"}
    return values, switches


def _split_flags(words, values, switches, repeats):
    """(positional words, {flag: value or [values] or True}); an unknown flag or a missing value raises."""
    positional, found = [], {}
    index = 0
    while index < len(words):
        word = words[index]
        if word in switches:
            found[word] = True
            index += 1
            continue
        if word in values:
            if index + 1 >= len(words) or str(words[index + 1]).startswith("--"):
                raise CockpitError(f"{word} needs a value")
            if word in repeats:
                found.setdefault(word, []).append(words[index + 1])
            else:
                found[word] = words[index + 1]
            index += 2
            continue
        if word.startswith("--"):
            raise CockpitError(f"unknown option {word}")
        positional.append(word)
        index += 1
    return positional, found


def _payload_of(found) -> dict:
    from .intents import FIELDS

    payload = {}
    for name in FIELDS:
        flag = "--" + name.replace("_", "-")
        if flag in found:
            payload[name] = found[flag]
    return payload


def cmd_outbox(argv) -> int:
    if not argv:
        _header("missing argument", OUTBOX_USAGE)
        return 2
    action = argv[0]
    if action.startswith("-"):
        _header(f"unknown option {action}", OUTBOX_USAGE)
        return 2
    values, switches = _payload_flags()
    try:
        words, found = _split_flags(argv[1:], values | OUTBOX_VALUES, switches | OUTBOX_SWITCHES, OUTBOX_REPEATS)
    except CockpitError as exc:
        _header(str(exc), OUTBOX_USAGE)
        return 2
    bounds = {
        "new": (2, 2),
        "amend": (1, 1),
        "list": (0, 1),
        "show": (1, 1),
        "endorse": (2, 3),
        "hold": (1, 2),
        "drop": (1, 2),
        "verify": (1, 1),
        "reprobe": (1, 1),
        "ack": (1, 1),
        "return": (1, 1),
        "digest": (0, 0),
        "reconcile": (0, 1),
        "sweep": (0, 0),
        "rework": (1, 1),
        "chain": (2, 2),
        "relink": (1, 1),
        "ci-override": (1, 1),
    }
    if action not in bounds:
        _header("invalid value", OUTBOX_USAGE)
        return 2
    low, high = bounds[action]
    allowed = ACTION_FLAGS.get(action, set())
    if len(words) > high or (found and action not in ("new", "amend") and not set(found) <= allowed):
        _header("stray argument", OUTBOX_USAGE)
        return 2
    if len(words) < low:
        _header("missing argument", OUTBOX_USAGE)
        return 2
    from .intents import load
    from .outbox import ack, amend, create, drop, endorse, hold, verify

    data = _pack()
    lane = os.environ.get("COCKPIT_LANE") or "human"
    if action in ("rework", "chain"):
        if "--instruction" not in found:
            _header(f"{action} needs --instruction", OUTBOX_USAGE)
            return 2
        _own_ticket(words[0])
        repo = found.get("--repo", "")
        if action == "rework":
            from .acts import continue_ticket

            print(
                json.dumps(
                    continue_ticket(
                        data,
                        words[0],
                        found["--instruction"],
                        found.get("--evidence") or [],
                        "rework",
                        repos=[repo] if repo else None,
                    )
                )
            )
            return 0
        from .gate import _chain

        print(
            json.dumps(
                {
                    "ok": True,
                    "chain": _chain(
                        data, {"ticket": words[0], "payload": {"repo": repo}}, words[1], found["--instruction"]
                    ),
                }
            )
        )
        return 0
    if action == "new":
        if "--card" not in found or "--summary" not in found:
            _header("new needs --card and --summary", OUTBOX_USAGE)
            return 2
        payload = _payload_of(found)
        payload.update({flag[2:].replace("-", "_"): True for flag in found if flag in switches})
        intent = create(
            data,
            words[0],
            words[1],
            found["--card"],
            found["--summary"],
            payload,
            created_by=lane,
            risk=found.get("--risk", ""),
            evidence=found.get("--evidence") or [],
        )
        from .intents import path_of

        print(intent["id"])
        print(path_of(intent["id"]))
        if intent.get("status") == "held":
            print(f"held: {intent['hold']['reason']}")
        return 0
    if action == "amend":
        payload = _payload_of(found)
        payload.update({flag[2:].replace("-", "_"): True for flag in found if flag in switches})
        from .outbox import staged_pair_refusal

        refusal = staged_pair_refusal(words[0], payload)
        if refusal:
            print(refusal)
            return 1
        intent = amend(
            words[0],
            summary=found.get("--summary", ""),
            payload=payload,
            created_by=lane,
            pack=data,
            top_level=bool(found.get("--top-level")),
        )
        print(f"amended {intent['id']} → {intent['status']}")
        return 0
    if action == "list":
        from .intents import all_intents

        print(json.dumps([item["id"] for item in all_intents(words[0] if words else None)]))
        return 0
    if action == "show":
        from .intents import FIELDS, load
        from .paths import workspace

        intent = load(words[0])
        print(json.dumps(intent, indent=2, sort_keys=True))
        for name, shape in FIELDS.items():
            value = (intent.get("payload") or {}).get(name)
            if value and shape == "file":
                path = os.path.join(workspace(), value)
                print(f"\n--- {name}: {value} ---")
                print(
                    open(path, encoding="utf-8", errors="replace").read()[:4000]
                    if os.path.isfile(path)
                    else "(missing)"
                )
        return 0
    if action == "endorse":
        seat = os.environ.get("COCKPIT_LANE") or ""  # the seat that runs this, read as it is: no seat is the human
        if seat not in ("", "gatekeeper"):
            raise CockpitError(
                "endorse is the gatekeeper's or the human's: a lane writes its intent and leaves the check to them"
            )
        # the record names who gave it: the gatekeeper with the model it ran on, or the human with none
        provider = data["providers"][data["roles"]["gatekeeper"]] if seat else {"hermes_provider": "", "model": ""}
        endorse(
            words[0],
            words[1],
            words[2] if len(words) > 2 else "",
            seat or "human",
            provider["hermes_provider"],
            provider["model"],
            pack=data,
        )
        print("endorsed")
        return 0
    if action == "hold":
        if lane not in ("human", "gatekeeper"):
            raise CockpitError("hold is the gatekeeper's or the human's")
        reason = found.get("--reason") or (words[1] if len(words) > 1 else "")
        if not reason:
            _header("hold needs --reason", OUTBOX_USAGE)
            return 2
        if found.get("--waits", "human") not in ("human", "lane"):
            _header("--waits is human or lane", OUTBOX_USAGE)
            return 2
        held = hold(
            words[0],
            reason,
            waits=found.get("--waits", "human"),
            rework=found.get("--rework", ""),
            ask=found.get("--ask", ""),
            options=found.get("--option") or [],
            chain=bool(found.get("--chain")),
            pack=data,
        )
        print(f"{held['status']} {held['id']}")
        return 0
    if action == "return":
        from .gate import return_intent
        from .outbox import human_gate

        human_gate()
        if not found.get("--instruction"):
            _header("return needs --instruction", OUTBOX_USAGE)
            return 2
        returned = return_intent(
            data,
            words[0],
            found["--instruction"],
            assignee=found.get("--assignee", ""),
            evidence=found.get("--evidence") or [],
            chain=not found.get("--no-chain"),
        )
        card = returned["returned"]["card"] or "no card yet: housekeeping makes it"
        print(f"returned {returned['id']} → {returned['returned']['lane']} ({card})")
        return 0
    if action == "ci-override":
        from .outbox import ci_override

        overridden = ci_override(data, words[0], found.get("--reason", ""))
        print(f"CI overridden for {overridden['id']} at {(overridden['payload'].get('sha') or '')[:12]}")
        return 0
    if action == "digest":
        from .gate import digest

        for row in digest(data):
            intent = load(row["id"])
            print(f"{row['number']:<3} {intent['ticket']:<12} {intent['type']:<17} {intent['status']:<9} {row['id']}")
        print("Reply: cockpit reply 'publish all' | 'publish 1-3' | 'hold 4: <why>' | 'drop 5' | 'open 2'")
        return 0
    if action == "reconcile":
        from .gate import reconcile

        print("\n".join(reconcile(data, words[0] if words else "")) or "nothing to reconcile")
        return 0
    if action == "sweep":
        from .gate import request_sweep

        request_sweep(lane)
        print("sweep requested: the next housekeeping run starts the gatekeeper")
        return 0
    if action == "relink":
        if "--waits-for" not in found:
            _header("relink needs --waits-for", OUTBOX_USAGE)
            return 2
        from .outbox import relink
        from .sequence import waits

        intent = relink(words[0], found["--waits-for"], pack=data)
        wait = waits(intent, data)
        print(
            f"{intent['id']} waits for {intent['payload']['waits_for']}: "
            + (f"offered once it is out ({wait['status']} now)" if wait else "that stage is out, so it is offered now")
        )
        return 0
    if action == "drop":
        from .outbox import human_gate

        human_gate()
        drop(words[0], found.get("--note") or (words[1] if len(words) > 1 else ""))
        print("dropped")
        return 0
    if action == "verify":
        problems = verify(words[0], pack=data)
        print("\n".join(problems) if problems else "ok")
        return 1 if problems else 0
    if action == "reprobe":
        from .outbox import human_gate, reprobe

        human_gate("re-probe")
        row = reprobe(words[0], pack=data)
        print(f"{row['id']} probed again: {row['status']}")
        return 0
    from .outbox import human_gate

    human_gate("ack")
    ack(words[0])
    print("acknowledged")
    return 0


def cmd_publish(argv) -> int:
    """cockpit publish --id <intent> [--dry-run] [--approve] | --all: every endorsed intent in digest order, stopping at
    the first refusal."""
    from .intents import load, save
    from .publish import execute, forge_for, publish_all

    dry = False
    approve = False
    every = False
    ident = ""
    seen = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("--dry-run", "--approve", "--all"):
            if token in seen:
                _header("stray argument", EXAMPLES["publish"])
                return 2
            seen.add(token)
            dry = dry or token == "--dry-run"
            approve = approve or token == "--approve"
            every = every or token == "--all"
            index += 1
            continue
        if token == "--id":
            if token in seen:
                _header("stray argument", EXAMPLES["publish"])
                return 2
            if index + 1 >= len(argv) or str(argv[index + 1]).startswith("-"):
                _header("missing argument", EXAMPLES["publish"])
                return 2
            seen.add(token)
            ident = argv[index + 1]
            index += 2
            continue
        _header("stray argument", EXAMPLES["publish"])
        return 2
    if bool(ident) == every:
        _header("missing argument" if not ident else "stray argument", EXAMPLES["publish"])
        return 2
    pack = _pack()
    if every:
        from .gate import digest

        rows = [load(row["id"]) for row in digest(pack)]
        rows = [row for row in rows if row["status"] == "endorsed" and row["type"] not in ("ticket-done", "infra-note")]
        receipts = publish_all(rows, forge_for(pack), {row["id"]: row["id"] for row in rows}, pack=pack)
        for row, receipt in zip(rows, receipts):
            print(
                f"{row['id']}: {receipt.get('url') if receipt.get('ok') else 'refused: ' + str(receipt.get('error'))}"
            )
        print(f"published {sum(1 for receipt in receipts if receipt.get('ok'))} of {len(rows)}")
        return 0 if all(receipt.get("ok") for receipt in receipts) else 1
    intent = load(ident)
    try:
        forge = forge_for(pack, dry)
        receipt = execute(intent, forge, dry_run=dry, explicit_approve=approve, pack=pack, confirm=ident)
    except CockpitError as exc:
        print(str(exc))
        return 1
    if not dry:
        from .publish import link_siblings

        save(intent)  # first, so the fill reads this PR as out
        link_siblings(forge, intent, receipt)
        save(intent)
    print(json.dumps(receipt))
    return 0 if receipt.get("ok") or receipt.get("dry_run") else 1


def cmd_ci(argv) -> int:
    """cockpit ci flaky|real <ticket> <sha> [--run-id N] [--repo R]: the analyst's verdict on a failed CI run."""
    usage = "cockpit ci flaky <ticket> <sha> --run-id <id> [--repo <repo>] | ci real <ticket> <sha> | ci rework <ticket> <sha> [--repo <repo>]"
    try:
        words, found = _split_flags(list(argv), {"--run-id", "--repo"}, set(), set())
    except CockpitError as exc:
        _header(str(exc), usage)
        return 2
    if len(words) != 3 or words[0] not in ("flaky", "real", "rework"):
        _header("ci takes a verdict, the ticket and the sha", usage)
        return 2
    _own_ticket(words[1])
    if words[0] == "rework":
        from .acts import continue_ticket

        repo = found.get("--repo", "")
        instruction = (
            f"CI failed at {words[2][:9]}" + (f" in {repo}" if repo else "") + ": fix what the analyst's card names."
        )
        from .acts import _diagnosis_of

        diagnosis = _diagnosis_of(_pack(), words[1], words[2])
        if diagnosis:
            instruction += f"\n\nThe analyst's diagnosis:\n{diagnosis}"
        pack = _pack()
        mechanical = (pack.get("outbox") or {}).get("ci_rework_chain")
        print(
            json.dumps(
                continue_ticket(
                    pack,
                    words[1],
                    instruction,
                    kind="rework",
                    repos=[repo] if repo else None,
                    chain=mechanical is not False,
                )
            )
        )
        return 0
    from .acts import mark_ci

    marked = mark_ci(_pack(), words[1], words[2], words[0], found.get("--repo", ""), found.get("--run-id", ""))
    print(json.dumps(marked))
    return 0


def cmd_flow(argv) -> int:
    """cockpit flow decompose <ticket> <file>: intake's breakdown after go becomes the linked cards. flow reopen <ticket>
    "<what changed>": a lane reopens its own ticket; intake proposes again."""
    flag = next((word for word in argv if word.startswith("--")), "")
    if flag:
        _header(f"unknown option {flag}", EXAMPLES["flow"])
        return 2
    if len(argv) != 3 or argv[0] not in ("decompose", "reopen"):
        _header("flow takes decompose or reopen, the ticket and one more word", EXAMPLES["flow"])
        return 2
    pack = _pack()
    _own_ticket(argv[1])
    if argv[0] == "decompose":
        import yaml

        from .decompose import decompose_or_queue

        if not os.path.isfile(argv[2]):
            _header(f"no breakdown file {argv[2]}", EXAMPLES["flow"])
            return 2
        print(json.dumps(decompose_or_queue(pack, argv[1], yaml.safe_load(open(argv[2], encoding="utf-8")))))
        return 0
    from .acts import continue_ticket

    print(json.dumps(continue_ticket(pack, argv[1], argv[2])))
    return 0


def _own_ticket(ticket: str) -> None:
    """A lane acts only on the ticket of the card it runs; the human (no lane) on any."""
    if not os.environ.get("COCKPIT_LANE"):
        return
    from .skill_log import current_ticket

    mine = current_ticket()
    if mine != ticket:
        raise CockpitError(f"{ticket} is not this card's ticket ({mine or 'no card'})")


def cmd_test(argv) -> int:
    """cockpit test plan <ticket> <file>: post the test plan and wait for go. test fail <ticket> <row> "<note>": the one
    recording of a failed row. test run-dir <ticket>: the folder the next run writes to."""
    shapes = {"plan": 3, "fail": 4, "run-dir": 2}
    flag = next((word for word in argv if word.startswith("--")), "")
    if flag:
        _header(f"unknown option {flag}", EXAMPLES["test"])
        return 2
    if not argv or argv[0] not in shapes or len(argv) != shapes[argv[0]] or any(word.startswith("--") for word in argv):
        _header("test takes plan, fail or run-dir", EXAMPLES["test"])
        return 2
    from .acts import post_test_plan, record_fail

    if argv[0] == "plan":
        if not os.path.isfile(argv[2]):
            _header(f"no plan file {argv[2]}", EXAMPLES["test"])
            return 2
        print(json.dumps(post_test_plan(_pack(), argv[1], open(argv[2], encoding="utf-8").read())))
        return 0
    if argv[0] == "fail":
        print(json.dumps(record_fail(argv[1], argv[2], argv[3])))
        return 0
    from .test_flow import next_run_dir

    folder = qa_of(argv[1])
    print(next_run_dir(_pack(), folder))
    return 0


def cmd_reply(argv) -> int:
    """cockpit reply "<publish all | publish 1-3,5 | hold 4: why | drop 5 | open 2>": the answer to the last digest."""
    if len(argv) != 1:
        _header("reply takes one quoted answer", "cockpit reply 'publish 1-3'")
        return 2
    from .gate import reply

    lines = reply(_pack(), argv[0])
    print("\n".join(lines))
    return 1 if any("stopped here" in line for line in lines) else 0


def _plan_words(argv):
    """`plan init|append` take the text as an argument, or `--file <path>` (`/dev/stdin` for a pipe) in its place, and the decision as
    `--decision <text>`: the forms a lane writing a long outline reaches for. None (usage printed) when a flag is wrong."""
    if argv[0] not in ("init", "append"):
        return argv
    words, taken = [argv[0]], {}
    rest = list(argv[1:])
    while rest:
        word = rest.pop(0)
        if word in ("--file", "--decision"):
            if not rest:
                _header("missing argument", EXAMPLES["plan"])
                return None
            taken[word] = rest.pop(0)
        else:
            words.append(word)
    if argv[0] == "append" and "--decision" in taken:
        _header("append takes no --decision", EXAMPLES["plan"])
        return None
    if "--file" in taken:
        # the text comes from the file: an inline text as well is ambiguous, never read as the decision
        if len(words) > (2 if argv[0] == "init" else 3):
            _header("pass the text or --file, not both", EXAMPLES["plan"])
            return None
        try:
            text = open(taken["--file"], encoding="utf-8").read()  # `--file /dev/stdin` reads a pipe
        except OSError as exc:
            _header(f"cannot read {taken['--file']}: {exc.strerror}", EXAMPLES["plan"])
            return None
        words.append(text)  # init: ticket, text; append: ticket, section, text
    if argv[0] == "init" and len(words) < 3:
        _header("init needs the plan text (an argument or --file)", EXAMPLES["plan"])
        return None
    if "--decision" in taken:
        if len(words) > 3:
            _header("pass the decision once (--decision or the last argument)", EXAMPLES["plan"])
            return None
        words.append(taken["--decision"])
    return words


def cmd_plan(argv) -> int:
    from .plan import append, init, sections, show

    allowed = {"init": (3, 4), "append": (4, 4), "show": (2, 2), "sections": (2, 2)}
    if not argv or argv[0] not in allowed:
        _header("missing argument" if not argv else "invalid value", EXAMPLES["plan"])
        return 2
    argv = _plan_words(argv)
    if argv is None:
        return 2
    low, high = allowed[argv[0]]
    if _fits(argv, low, high, EXAMPLES["plan"]):
        return 2
    if argv[0] == "init":
        print(init(argv[1], argv[2], argv[3] if len(argv) > 3 else "go", outline=True))
        return 0
    if argv[0] == "append":
        print(append(argv[1], argv[2], argv[3]))
        return 0
    if argv[0] == "show":
        print(show(argv[1]))
        return 0
    if argv[0] == "sections":
        print("\n".join(sections(argv[1])))
        return 0


def cmd_migrate(argv) -> int:
    from .migrate import discover, draft, rollback

    if not argv or argv[0] not in ("discover", "draft", "rollback", "plan", "apply", "verify"):
        _header("missing argument" if not argv else "invalid value", EXAMPLES["migrate"])
        return 2
    if argv[0] in ("plan", "apply", "verify"):
        if _fits(argv, 1, 1, EXAMPLES["migrate"]):
            return 2
        from . import pack_migration

        if argv[0] == "verify":
            lines = pack_migration.verify(_pack())
            for ok, line, evidence in lines:
                print(f"{'ok  ' if ok else 'FAIL'} {line}: {evidence}")
            return 0 if all(ok for ok, _line, _evidence in lines) else 1
        print(json.dumps(getattr(pack_migration, argv[0])(_pack()), indent=1))
        return 0
    if argv[0] == "rollback":
        if _fits(argv, 2, 2, EXAMPLES["migrate"]):
            return 2
        from .pack_migration import rollback as roll_back
        from .pack_migration import snapshots_dir

        if os.path.isdir(os.path.join(snapshots_dir(), argv[1])):
            print("\n".join(roll_back(_pack(), argv[1])))
            return 0
        print("\n".join(rollback(argv[1])))
        return 0
    if _fits(argv, 1, 1, EXAMPLES["migrate"]):
        return 2
    if argv[0] == "discover":
        print(json.dumps(discover(workspace())))
        return 0
    dest = os.path.join(workspace(), "cockpit-pack")
    written = draft(discover(workspace()), dest)
    print("\n".join(written))
    return 0


SLOT_USAGE = (
    "cockpit slot status [--json] | free | gc | up N TICKET | down N | release N | reset N | ready N | exec N -- ARGS | "
    "run VERB N [-- ARGS] | toggle NAME on|off|status N"
)


def _watching(run, example, argv) -> int:
    try:
        return run(_pack(), argv)
    except ValueError as exc:
        _header(str(exc), example)
        return 2


def cmd_live(argv) -> int:
    from .live_cli import run_live

    return _watching(run_live, EXAMPLES["live"], argv)


def cmd_board(argv) -> int:
    from .live_cli import run_board

    return _watching(run_board, EXAMPLES["board"], argv)


def cmd_slot(argv) -> int:
    if not argv:
        _header("missing argument", EXAMPLES["slot"])
        return 2
    words, passed = (argv[: argv.index("--")], argv[argv.index("--") + 1 :]) if "--" in argv else (argv, [])
    shapes = {
        "gc": 1,
        "free": 1,
        "status": (1, 2),
        "up": 3,
        "down": 2,
        "release": 2,
        "reset": 2,
        "ready": 2,
        "exec": 2,
        "run": 3,
        "toggle": 4,
        "bringup": 2,
    }
    verb = words[0]
    if verb not in shapes:
        _header("invalid value", SLOT_USAGE)
        return 2
    low, high = shapes[verb] if isinstance(shapes[verb], tuple) else (shapes[verb], shapes[verb])
    if (
        not low <= len(words) <= high
        or (verb == "status" and words[1:] not in ([], ["--json"]))
        or (passed and verb not in ("exec", "run"))
    ):
        _header("missing argument" if len(words) < low else "stray argument", SLOT_USAGE)
        return 2
    number = (
        words[-1]
        if verb in ("down", "release", "reset", "ready", "exec", "run", "toggle", "bringup")
        else (words[1] if verb == "up" else "")
    )
    if number and not str(number).isdigit():
        _header("invalid value", SLOT_USAGE)
        return 2
    from .ops import slot_gc
    from .slots import free_slots, provider_for

    data = _pack()
    provider = provider_for(data.get("slot_provider"), data)
    if verb == "gc":
        return _run_watched("slot-gc", lambda: slot_gc(data))
    if verb == "free":
        print(" ".join(str(slot) for slot in free_slots(data["seats"]["slots"])))
        return 0
    if verb == "status":
        print(json.dumps(provider.status(count=max(1, data["seats"]["slots"]))))
        return 0
    slot = int(number)
    if verb == "bringup":
        from .slots import bringup

        state = bringup(slot, data)
        print(state)
        return 0 if state == "ready" else 1
    if verb == "up":
        provider.up(slot, words[2])
        print("up")
        return 0
    if verb == "release":
        from .slots import release

        try:
            print(release(slot, data, provider))
        except CockpitError as exc:
            print(str(exc))
            return 1
        return 0
    if verb in ("down", "reset"):
        held = getattr(provider, verb)(slot)
        if verb == "down":
            from .slots import down_said

            print(down_said(slot, held))
            return 0
        print(verb)
        return 0
    if verb == "ready":
        result = provider.ready(slot) if hasattr(provider, "ready") else {"state": "ok", "tail": "ready"}
        print(result["state"] if result["state"] != "failed" else f"failed: {result['tail']}")
        return {"ok": 0, "failed": 1, "working": 2, "dependency down": 3}.get(result["state"], 1)
    if not hasattr(provider, "run"):
        raise CockpitError("this pack's slots run no commands (slots.provider: command)")
    if verb == "exec":
        result = provider.exec(slot, passed)
    elif verb == "run":
        result = provider.run(words[1], slot, args=passed)
    else:
        result = provider.toggle(words[1], words[2], slot)
    out = result["out"]
    print(json.dumps(out) if isinstance(out, (dict, list)) else out)
    return {"ok": 0, "failed": 1, "working": 2, "dependency down": 3}.get(result["state"], 1)


def _header(reason: str, usage: str) -> None:
    print(f"{reason}\n{usage}\nExamples:\n  {usage}", file=sys.stderr)


def _fits(argv, low, high, usage) -> bool:
    """True when the token count is refused. The caller returns 2 and does not run."""
    if low <= len(argv) <= high:
        return False
    _header("stray argument" if len(argv) > high else "missing argument", usage)
    return True


def cmd_ticket(argv) -> int:
    from .halt import halted
    from .intents import all_intents

    usage = "cockpit ticket <list|status|halt|resume>"
    if not argv:
        _header("missing argument", usage)
        return 2
    action = argv[0]
    if action not in ("list", "status", "halt", "resume", "archive", "delete"):
        _header("invalid value", usage)
        return 2
    if action == "list":
        if _fits(argv, 1, 1, EXAMPLES["ticket"]):
            return 2
        print(
            json.dumps(
                [
                    {"ticket": row.get("ticket"), "id": row.get("id"), "status": row.get("status")}
                    for row in all_intents()
                ]
            )
        )
        return 0
    ticket_usage = "cockpit ticket <status|halt|resume> <ticket>"
    if action == "halt":
        if len(argv) < 2:
            _header("missing argument", ticket_usage)
            return 2
    elif action == "delete":
        if len(argv) < 2:
            _header("missing argument", usage)
            return 2
        flags = argv[2:]
        if any(token != "--force" for token in flags) or flags.count("--force") > 1:
            _header("stray argument", usage)
            return 2
    elif _fits(argv, 2, 2, ticket_usage):
        return 2
    ticket = argv[1]
    if argv[0] == "halt":
        from .acts import halt_ticket

        print("\n".join(halt_ticket(_pack(), ticket, " ".join(argv[2:]))))
        return 0
    if argv[0] == "resume":
        from .acts import resume_ticket

        print(resume_ticket(ticket))
        return 0
    if argv[0] == "archive":
        from .acts import archive_ticket

        print(json.dumps(archive_ticket(_pack(), ticket)))
        return 0
    if argv[0] == "delete":
        from .acts import delete_ticket

        print(json.dumps(delete_ticket(_pack(), ticket, force="--force" in argv)))
        return 0
    rows = [row for row in all_intents() if row.get("ticket") == ticket]
    print(json.dumps({"ticket": ticket, "halted": bool(halted(ticket)), "intents": [row.get("id") for row in rows]}))
    return 0


def _run_watched(name, action) -> int:
    """Run a watcher. A crash is an Inbox row with the traceback behind a plain sentence."""
    from .ops import record_crash

    try:
        print(action())
    except Exception:
        record_crash(name)
        raise
    return 0


def cmd_watch_pr(_argv) -> int:
    from .ops import watch_pr

    return _run_watched("pr-watch", lambda: watch_pr(_pack()))


def cmd_watch_ci(_argv) -> int:
    from .ops import watch_ci

    return _run_watched("ci-watch", lambda: watch_ci(_pack()))


def cmd_watch_base(argv) -> int:
    """cockpit watch-base: one pass. cockpit watch-base verdict <repo> <number> (--file <path> | <text>): the analyst's verdict
    on one change of the base branch."""
    from .ops import watch_base

    if argv and argv[0] == "verdict":
        usage = "cockpit watch-base verdict <repo> <number> (--file <path> | <text>)"
        if len(argv) < 4 or not argv[2].isdigit():
            _header("verdict takes a repo, a number and the verdict", usage)
            return 2
        if argv[3] == "--file":
            if len(argv) != 5 or not os.path.isfile(argv[4]):
                _header("--file takes one existing file", usage)
                return 2
            text = open(argv[4], encoding="utf-8").read()
        else:
            text = " ".join(argv[3:])
        from .acts import write_verdict

        print(json.dumps(write_verdict(argv[1], int(argv[2]), text)))
        return 0
    return _run_watched("base-watch", lambda: watch_base(_pack()))


def cmd_bumps(argv) -> int:
    from .ops import bumps_scan

    if not argv or argv[0] != "scan":
        _header("missing argument" if not argv else "invalid value", EXAMPLES["bumps"])
        return 2
    if _fits(argv, 1, 1, EXAMPLES["bumps"]):
        return 2
    return _run_watched("bumps", lambda: bumps_scan(_pack()))


def cmd_advisories(argv) -> int:
    """The stack watch: scan (the cron's), list (alerts first), ack <id> [--note <text>], unack <id>. Ack and unack are
    the human's."""
    usage = EXAMPLES["advisories"]
    if not argv or argv[0] not in ("scan", "list", "ack", "unack"):
        _header("missing argument" if not argv else "invalid value", usage)
        return 2
    action, rest = argv[0], argv[1:]
    if action == "scan":
        from .ops import advisories_scan

        return 2 if _fits(argv, 1, 1, usage) else _run_watched("advisories", lambda: advisories_scan(_pack()))
    if action == "list":
        if _fits(argv, 1, 1, usage):
            return 2
        from .advisories.scan import state

        for row in state()["advisories"]:
            print(
                f"{'ALERT' if row.get('alert') else '     '} {row.get('severity') or 'unknown':<8} {row.get('status') or '':<15} {row['id']}  {row.get('summary') or ''}"
            )
        return 0
    note = ""
    if len(rest) == 3 and rest[1] == "--note" and action == "ack":
        note, rest = rest[2], rest[:1]
    if len(rest) != 1:
        _header("missing argument" if not rest else "stray argument", usage)
        return 2
    if os.environ.get("COCKPIT_LANE"):
        _header("acknowledging an advisory is the human's", usage)
        return 2
    from .advisories.scan import ack

    hit = ack(_pack(), rest[0], note, on=action == "ack")
    if not hit:
        _header(f"no advisory {rest[0]}", usage)
        return 1
    print(
        f"{hit['id']}: {'acknowledged' if action == 'ack' else 'back in the Inbox' if hit.get('alert') else 'unacknowledged'}"
    )
    return 0


def cmd_standup(argv) -> int:
    from .ops import standup_draft

    if not argv or argv[0] != "draft":
        _header("missing argument" if not argv else "invalid value", EXAMPLES["standup"])
        return 2
    if _fits(argv, 1, 1, EXAMPLES["standup"]):
        return 2
    return _run_watched("standup", lambda: standup_draft(_pack(), after_send="skip"))


def cmd_resume(_argv) -> int:
    """Print progress for a respawned card. Empty or unreadable stdin prints nothing."""
    import json

    from .resume import progress_note

    raw = sys.stdin.read()
    if not raw.strip():
        from .resume import latest_transcript, note_from_transcript, write_resume_log

        path = latest_transcript()
        if not path:
            return 0
        from .resume import mark_resume, shown_resume

        if shown_resume(path):
            return 0
        note = note_from_transcript(path)
        if not note:
            return 0
        mark_resume(path)
        write_resume_log(note)
        try:
            from .housekeeping import stamp_from_transcript

            stamp_from_transcript(_pack(), path)
        except Exception:  # noqa: BLE001, S110 - the stamp is a courtesy: the note is printed either way
            pass
        print(note)
        return 0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if isinstance(data, dict) and data.get("hook_event_name") == "pre_llm_call":
        from .resume import hook_context

        note = hook_context(data, _pack())
        if not note:
            return 0
        print(json.dumps({"context": note}))
        return 0
    if isinstance(data, dict) and data.get("transcript"):
        from .resume import mark_resume, note_from_transcript, shown_resume

        source = str(data.get("transcript"))
        if shown_resume(source):
            return 0
        note = note_from_transcript(source)
        if not note:
            return 0
        mark_resume(source)
        from .resume import write_resume_log

        write_resume_log(note)
        print(note)
        return 0
    events = data if isinstance(data, list) else (data.get("events") if isinstance(data, dict) else [])
    note = progress_note(events or [])
    if not note:
        return 0
    from .resume import mark_resume, shown_resume

    if shown_resume(raw):
        return 0
    mark_resume(raw)
    from .resume import write_resume_log

    write_resume_log(note)
    print(note)
    return 0


def cmd_vault(argv) -> int:
    from .ops import vault_put
    from .vault import init_vault, login_metadata

    if not argv:
        _header("missing argument", EXAMPLES["vault"])
        return 2
    if argv[0] == "import":
        if _fits(argv, 1, 1, EXAMPLES["vault"]):
            return 2
        from .vault import import_logins

        print(json.dumps(import_logins(sys.stdin.read(), _pack())))
        return 0
    if argv[0] == "restore":
        if _fits(argv, 1, 2, EXAMPLES["vault"]):
            return 2
        from .vault import restore_vault

        print(restore_vault(argv[1] if len(argv) > 1 else ""))
        return 0
    if argv[0] == "init":
        fingerprint = ""
        if len(argv) == 1:
            fingerprint = ""
        elif argv[1] == "--key" and len(argv) == 2:
            _header("missing argument", EXAMPLES["vault"])
            return 2
        elif argv[1] == "--key" and len(argv) == 3:
            fingerprint = argv[2]
        else:
            _header("stray argument", EXAMPLES["vault"])
            return 2
        message = init_vault(fingerprint)
        print(message)
        return 1 if message.startswith("vault init pending") else 0
    if argv[0] == "list":
        if _fits(argv, 1, 1, EXAMPLES["vault"]):
            return 2
        for item in login_metadata():
            print(f"{item['origin']} {item['email']}")
        return 0
    if argv[0] == "audit":
        if argv[1:] not in ([], ["--fix"]):
            _header("stray argument", "cockpit vault audit --fix")
            return 2
        from .lane_vault import audit

        findings = audit(_pack(), fix=argv[1:] == ["--fix"])
        print("\n".join(findings) if findings else "vault audit: clean")
        return 1 if findings else 0
    if argv[0] == "accounts":
        from . import accounts

        verbs = {"plan": accounts.plan, "apply": accounts.apply, "verify": accounts.verify, "list": None, "renew": None}
        if (
            len(argv) < 2
            or argv[1] not in verbs
            or (argv[1] != "renew" and len(argv) > 2)
            or argv[2:] not in ([], ["--force"])
        ):
            _header("invalid value", "cockpit vault accounts plan|apply|verify|renew [--force]|list")
            return 2
        data = _pack()
        if argv[1] == "list":
            for row in accounts.rows(data):
                print(
                    f"{row['identifier']} {row['origin']} -> {', '.join(row['expected'])}"
                    f" (placed on {', '.join(row['seats']) or 'none'}{', renewal due' if row['due'] else ''})"
                )
            return 0
        if argv[1] == "renew":
            print("\n".join(accounts.renew(data, force=argv[2:] == ["--force"])))
            return 0
        lines = verbs[argv[1]](data)
        print("\n".join(lines) if lines else "accounts: as declared")
        return 1 if argv[1] == "verify" and lines else 0
    if argv[0] == "human-add":
        if _fits(argv, 3, 3, "cockpit vault human-add <origin> <email>  (password, then an optional seed, on stdin)"):
            return 2
        from .vault import store_login

        given = sys.stdin.read().splitlines()
        if not given or not given[0]:
            _header("missing argument", "printf '%s\n' \"$PASSWORD\" | cockpit vault human-add <origin> <email>")
            return 2
        print(
            store_login(
                argv[1],
                argv[2],
                given[0],
                otp=(given[1] if len(given) > 1 and given[1] else None),
                privileged=True,
                pack=_pack(),
            )
        )
        return 0
    if argv[0] in ("status", "unlock", "lock"):
        if _fits(argv, 1, 1, f"cockpit vault {argv[0]}"):
            return 2
        from .vault_book import VaultBook

        book = VaultBook(pack=_pack())
        if argv[0] == "status":
            state = book.state()
            key = state["key"]
            print(
                f"sealed: {'yes' if state['sealed'] else 'no'} · key: {key['secret']}"
                f"{' (passphrase, ' + ('cached' if key['cached'] else 'locked') + ')' if key['protected'] else ''}"
                f" · values open now: {'yes' if not state['locked'] else 'no'}{' · ' + state['reason'] if state['reason'] else ''}"
            )
            return 0
        if argv[0] == "lock":
            print(book.lock())
            return 0
        if sys.stdin.isatty():  # gpg-agent's own pinentry asks: passphrase, PIN, touch
            from .fence import refuse_outside

            refuse_outside()
            print(book.sealer.key.unlock_here())
            return 0
        print(book.unlock(sys.stdin.readline().rstrip("\n")))
        return 0
    if argv[0] == "scopes":
        if _fits(argv, 1, 1, "cockpit vault scopes"):
            return 2
        from .vault_book import VaultBook

        for row in VaultBook(pack=_pack()).vaults():
            print(f"{row['name']} {row['count']}{' (built in)' if row['builtin'] else ''}")
        return 0
    if argv[0] == "rm":
        if _fits(argv, 3, 3, "cockpit vault rm <origin> <email>"):
            return 2
        from .vault_book import VaultBook

        print(VaultBook(pack=_pack()).remove_login(argv[1], argv[2]))
        return 0
    if argv[0] == "reindex":
        if _fits(argv, 1, 1, "cockpit vault reindex"):
            return 2
        from .vault_book import VaultBook

        print(VaultBook(pack=_pack()).reindex())
        return 0
    if argv[0] == "index":
        if _fits(argv, 1, 1, "cockpit vault index"):
            return 2
        from .scrub import rebuild

        index = rebuild()
        print(f"scrub index: {sum(len(source.get('entries') or []) for source in index['sources'])} secrets")
        return 0
    if argv[0] != "put":
        _header("invalid value", EXAMPLES["vault"])
        return 2
    words = list(argv[1:])
    lane = ""
    if "--lane" in words:
        at = words.index("--lane")
        if at + 1 >= len(words):
            _header("missing argument", "cockpit vault put <origin> <email> --lane tester-1")
            return 2
        lane = words[at + 1]
        del words[at : at + 2]
    if len(words) != 2:
        _header(
            "missing argument" if len(words) < 2 else "stray argument",
            "cockpit vault put <origin> <email> --lane tester-1",
        )
        return 2
    print(vault_put(_pack(), words[0], words[1], lane=lane))
    return 0


def cmd_guard(argv) -> int:
    """An editor agent's pre-tool hook: its JSON on stdin. Outside the lanes, a slot, vault, or publishing command, a
    vault or slot path, or a lane's account is refused (exit 2, the reason on stderr and in the block JSON both
    common editor hook formats read)."""
    if argv:
        _header("stray argument", EXAMPLES["guard"])
        return 2
    from .fence import guard_reason, outside

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        print("cockpit guard: unreadable hook input", file=sys.stderr)
        return 2
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    texts = [str(payload.get("command") or ""), str(tool_input.get("command") or "")]
    texts += [str(tool_input.get(key) or "") for key in ("file_path", "path", "notebook_path")]
    if not outside(cwd=payload.get("cwd") or None):
        return 0
    from .errors import PackError

    try:
        pack = _pack()
    except (PackError, NeedMigrate, FileNotFoundError):
        pack = {}
    reason = next((found for found in (guard_reason(text, pack) for text in texts) if found), "")
    if not reason:
        return 0
    print(
        json.dumps(
            {"decision": "block", "reason": reason, "permission": "deny", "userMessage": reason, "agentMessage": reason}
        )
    )
    print(reason, file=sys.stderr)
    return 2


def cmd_session(argv) -> int:
    from .acts import session_close, session_handoff, session_open

    if not argv:
        _header("missing argument", EXAMPLES["session"])
        return 2
    data = _pack()
    if argv[0] == "open":
        if _fits(argv, 3, 40, "cockpit session open <slot> <ticket> [repo...]"):
            return 2
        known = {repo["name"] for repo in data["repos"]["repos"]}
        if any(
            word not in known for word in argv[3:]
        ):  # a word after the ticket is a repo of the pack, else it is refused before anything runs
            _header("stray argument", "cockpit session open <slot> <ticket> [repo...]")
            return 2
        print(session_open(data, argv[1], argv[2], argv[3:]))
        return 0
    if argv[0] == "close":
        if _fits(argv, 2, 2, "cockpit session close <slot>"):
            return 2
        print(session_close(data, argv[1]))
        return 0
    if argv[0] == "handoff":
        if _fits(argv, 3, 3, "cockpit session handoff <slot> <lane>"):
            return 2
        print(session_handoff(data, argv[1], argv[2]))
        return 0
    _header("invalid value", EXAMPLES["session"])
    return 2


def cmd_worktree(argv) -> int:
    usage = "cockpit worktree add <ticket> [repo] [--from <ref>] | cockpit worktree gc [--days <1-365>] [--dry-run]"
    if not argv:
        _header("missing argument", usage)
        return 2
    if argv[0] == "gc":
        return _worktree_gc(argv[1:])
    if argv[0] != "add":
        _header("invalid value", EXAMPLES["worktree"])
        return 2
    words = list(argv)
    start = ""
    if "--from" in words:
        at = words.index("--from")
        if at + 1 >= len(words):
            _header("missing argument", usage)
            return 2
        start = words[at + 1]
        del words[at : at + 2]
    if _fits(words, 2, 3, usage):
        return 2
    from .ops import worktree_add

    repo = words[2] if len(words) > 2 else ""
    print("\n".join(worktree_add(_pack(), words[1], repo, branch_from=start)))
    return 0


def _worktree_gc(argv) -> int:
    """Stale ticket folders under wt/, each kept with its reason or removed: the manual pass (the daily one is the
    Settings page's worktree_gc)."""
    usage = "cockpit worktree gc [--days <1-365>] [--dry-run]"
    words = list(argv)
    days = 0
    dry = "--dry-run" in words
    if dry:
        words.remove("--dry-run")
    if "--days" in words:
        at = words.index("--days")
        if at + 1 >= len(words) or not words[at + 1].isdigit():
            _header("missing argument" if at + 1 >= len(words) else "invalid value", usage)
            return 2
        days = int(words[at + 1])
        del words[at : at + 2]
    if words:
        _header("stray argument", usage)
        return 2
    from .cleanup import gc

    result = gc(_pack(), days, dry_run=dry)
    print("\n".join(result["lines"]))
    return 0


def cmd_ide(argv) -> int:
    usage = "cockpit ide open <ticket> [--file <path>] | cockpit ide file <path>"
    if not argv:
        _header("missing argument", usage)
        return 2
    if argv[0] not in ("open", "file"):
        _header("invalid value", EXAMPLES["ide"])
        return 2
    from .ops import ide_open

    if argv[0] == "file":
        if _fits(argv, 2, 2, usage):
            return 2
        print(ide_open(_pack(), "", file=argv[1]))
        return 0
    if len(argv) == 4 and argv[2] == "--file":
        print(ide_open(_pack(), argv[1], file=argv[3]))
        return 0
    if _fits(argv, 2, 2, usage):
        return 2
    print(ide_open(_pack(), argv[1]))
    return 0


def cmd_map(argv) -> int:
    if not argv:
        _header("missing argument", EXAMPLES["map"])
        return 2
    if argv[0] not in ("build", "check", "nodes"):
        _header("invalid value", EXAMPLES["map"])
        return 2
    if _fits(argv, 1, 1, EXAMPLES["map"]):
        return 2
    from .map_build import map_check, map_nodes_text
    from .ops import map_build

    pack = _pack()
    if argv[0] == "build":
        print(map_build(pack))
        return 0
    if argv[0] == "check":
        misses = map_check(pack)
        if not misses:
            print("ok")
            return 0
        print("\n".join(misses))
        return 1
    print(map_nodes_text(pack))
    return 0


GATE_USAGE = "cockpit gate [REPO | --repo REPO] [--baseline] [--background] | cockpit gate --wait ID"


def cmd_gate(argv) -> int:
    words = list(argv)
    options = {}
    for flag in ("--repo", "--wait", "--run-id"):
        if flag in words:
            at = words.index(flag)
            if at + 1 >= len(words):
                _header("missing argument", GATE_USAGE)
                return 2
            options[flag] = words[at + 1]
            del words[at : at + 2]
    switches = {flag for flag in ("--baseline", "--background") if flag in words}
    words = [word for word in words if word not in switches]
    if len(words) > 1 or (words and "--repo" in options):
        _header("stray argument", GATE_USAGE)
        return 2
    repo = options.get("--repo") or (words[0] if words else "")
    from . import repo_gates

    if "--wait" in options:
        code, lines = repo_gates.wait(options["--wait"])
    elif "--background" in switches:
        started = repo_gates.start_background(_pack(), repo, "--baseline" in switches)
        if not started:
            print("gate already running")
            return 1
        print(started)
        return 0
    else:
        code, lines = repo_gates.run_gates(_pack(), repo, "--baseline" in switches, options.get("--run-id", ""))
    print("\n".join(lines))
    return code


HELPER_USAGE = (
    "cockpit helper list | status [--group G] [--json] | options NAME | run NAME VERB [--choice C] [--background]"
)


def cmd_helper(argv) -> int:
    """The pack's helpers (helpers.yaml): start, stop and see the dev stack and local services."""
    words = list(argv)
    options = {}
    for flag in ("--choice", "--run-id", "--group"):
        if flag in words:
            at = words.index(flag)
            if at + 1 >= len(words):
                _header("missing argument", HELPER_USAGE)
                return 2
            options[flag] = words[at + 1]
            del words[at : at + 2]
    switches = {flag for flag in ("--background", "--json") if flag in words}
    words = [word for word in words if word not in switches]
    from . import helpers

    verb = words[0] if words else ""
    if verb == "list" and len(words) == 1:
        for row in _helper_rows(helpers):
            print(row)
        return 0
    if verb == "status" and len(words) == 1:
        found = helpers.status(_pack(), options.get("--group", ""))
        if "--json" in switches:
            print(json.dumps(found))
            return 0
        for group in found["groups"]:
            print(f"{group['label']}:" + (f" {group['error']}" if group["error"] else ""))
            for row in group["rows"]:
                print(f"  {row['name']}: {row['state']}" + (f" ({row['detail']})" if row["detail"] else ""))
        return 0
    if verb == "options" and len(words) == 2:
        print("\n".join(helpers.options(_pack(), words[1])))
        return 0
    if verb == "run" and len(words) == 3:
        result = helpers.run(
            _pack(),
            words[1],
            words[2],
            options.get("--choice", ""),
            "--background" in switches,
            options.get("--run-id", ""),
        )
        if result.get("warn"):
            print(f"note: {result['warn']}")
        for step in result.get("steps") or []:
            print(
                f"{step['helper']}: {step['state']}"
                + (f" — {step['out']}" if step["out"] and step["state"] != "ok" else "")
            )
        if result.get("already"):
            print(f"{result['name']} already running ({result['run']})")
        elif result["code"] == 2:
            print(f"{result['name']} {result['verb']}: started ({result['run']})")
        return result["code"]
    _header("unknown helper command", HELPER_USAGE)
    return 2


def _helper_rows(helpers) -> list:
    rows = []
    for entry in helpers.status(_pack())["helpers"]:
        made = f" = {' + '.join(entry['composite'])}" if entry["composite"] else ""
        needs = f" (needs {', '.join(entry['depends_on'])})" if entry["depends_on"] else ""
        rows.append(f"{entry['name']}: {entry['label']}{made}{needs} — {' | '.join(entry['verbs'])}")
    return rows


def cmd_workspace_watch(_argv) -> int:
    from .ops import workspace_watch

    return _run_watched("workspace-watch", lambda: workspace_watch(_pack()))


def cmd_export(argv) -> int:
    from .ops import export_keep

    keep = None
    seen_keep = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token != "--keep" or seen_keep:
            _header("stray argument", EXAMPLES["export"])
            return 2
        seen_keep = True
        if index + 1 >= len(argv):
            _header("missing argument", EXAMPLES["export"])
            return 2
        raw = argv[index + 1]
        if not str(raw).isdigit():
            _header("invalid value", EXAMPLES["export"])
            return 2
        keep = int(raw)
        index += 2
    return _run_watched("export", lambda: export_keep(_pack(), keep))


def cmd_digest(_argv) -> int:
    """Records the digest, then prints its rows: the one screen the human asked for."""
    from .ops import morning_digest
    from .paths import platform_dir

    status = _run_watched("morning-digest", lambda: morning_digest(_pack()))
    path = os.path.join(platform_dir(), "digest.md")
    if os.path.isfile(path):
        print(open(path, encoding="utf-8").read().rstrip())
    return status


def cmd_perf(_argv) -> int:
    from .ops import perf_sync

    return _run_watched("perf-sync", lambda: perf_sync(_pack()))


def cmd_advise(argv) -> int:
    """cockpit advise <checkpoint> [note] [--ticket T] [--card C] [--said LINE]: ask the advisor, or with --said record the line an
    in-tool advisor gave the worker; exit 1 when there is no verdict."""
    try:
        words, found = _split_flags(list(argv), {"--ticket", "--card", "--said"}, set(), set())
    except CockpitError as exc:
        _header(str(exc), EXAMPLES["advise"])
        return 2
    if not 1 <= len(words) <= 2:
        _header("stray argument" if words else "missing argument", EXAMPLES["advise"])
        return 2
    from .advise import advise

    result = advise(
        _pack(),
        words[0],
        words[1] if len(words) > 1 else "",
        found.get("--ticket", ""),
        found.get("--card", ""),
        said=found.get("--said", ""),
    )
    print(json.dumps({key: value for key, value in result.items() if key != "reply"}))
    return 0 if result["ok"] else 1


RECORD_VALUES = {
    "start": {"--session", "--out", "--record-id", "--on-screen", "--max-seconds", "--url-contains"},
    "stop": {"--session"},
    "status": {"--session"},
}
RECORD_NEEDS = {
    "start": {"--session", "--out"},
    "stop": {"--session"},
    "status": set(),
}  # --record-id, --on-screen: recommended


def cmd_record(argv) -> int:
    """cockpit record start|stop|status: one reproduction video of a failed scenario on a test kickoff card
    (cockpitlib.record). Every value is a flag; a wrong shape prints the usage and does not run (exit 2); a refusal
    or a video that does not play exits 1 with the reason; success prints JSON."""
    usage = EXAMPLES["record"]
    if argv and argv[0].startswith("-"):
        _header(f"unknown option {argv[0]}", usage)
        return 2
    if not argv or argv[0] not in RECORD_VALUES:
        _header("record takes start, stop or status", usage)
        return 2
    verb, values, at = argv[0], {}, 1
    while at < len(argv):
        token = argv[at]
        if token not in RECORD_VALUES[verb]:
            _header(f"unknown option {token}" if token.startswith("-") else f"stray argument {token}", usage)
            return 2
        if at + 1 >= len(argv) or argv[at + 1].startswith("--"):
            _header(f"{token} takes a value", usage)
            return 2
        values[token] = argv[at + 1]
        at += 2
    missing = sorted(RECORD_NEEDS[verb] - set(values))
    if missing:
        _header(f"record {verb} needs {', '.join(missing)}", usage)
        return 2
    if "--max-seconds" in values and not values["--max-seconds"].isdigit():
        _header("--max-seconds takes whole seconds", usage)
        return 2
    from . import record

    if verb == "status":
        print(json.dumps(record.status(values.get("--session") or "")))
        return 0
    pack = _pack()
    if verb == "stop":
        print(json.dumps(record.stop(pack, values["--session"])))
        return 0
    print(
        json.dumps(
            record.start(
                pack,
                values["--session"],
                values["--out"],
                values.get("--record-id") or "",
                values.get("--on-screen") or "",
                int(values.get("--max-seconds") or record.MAX_SECONDS),
                values.get("--url-contains") or "",
            )
        )
    )
    return 0


def cmd_pace(argv) -> int:
    """`cockpit pace --json`: the plan pace for the supervisor (cockpitlib.pace). Exits 0 with a wrong flag value or an
    unreadable plan in `error`; an unknown flag is refused before it runs (exit 2), as for every command. Without --json the same answer as one line per window."""
    values, flags, problem = {}, set(), ""
    at = 0
    while at < len(argv):
        token = argv[at]
        if token in ("--days", "--start", "--end"):
            if at + 1 >= len(argv) or argv[at + 1].startswith("--"):
                problem = problem or f"{token} takes a value"
                at += 1
                continue
            values[token] = argv[at + 1]
            at += 2
            continue
        if token in ("--json", "--peak", "--fresh"):
            flags.add(token)
        else:
            problem = problem or f"stray argument {token}"
        at += 1
    from .pace import blank, pace

    try:
        pack = _pack()
    except Exception as exc:  # noqa: BLE001 - the contract: exit 0, the reason in error
        pack, problem = None, problem or f"pack: {exc}"
    if problem:
        result = blank(pack, problem)
    else:
        result = pace(
            pack,
            days=values.get("--days"),
            start=values.get("--start"),
            end=values.get("--end"),
            peak="--peak" in flags,
            fresh="--fresh" in flags,
        )
    if "--json" in flags:
        print(json.dumps(result))
        return 0
    if result["error"]:
        print(f"pace: {result['error']}")
    for window in result["windows"]:
        print(
            f"{window['name']}: {window['used']}% used, ideal {window['ideal']}%, {window['verdict']}, "
            f"{window['projected']}% at reset, {window['budget_per_hour']}%/h for {window['active_hours_left']} h"
        )
    return 0


def cmd_fence_check(argv) -> int:
    """The worker write fence's decision for one path as a card's lane would get it, and why. Reads only."""
    usage = "cockpit fence-check --card <card id> --path <path> [--lane <lane>]"
    found = {}
    words = list(argv)
    while words:
        flag = words.pop(0)
        if flag not in ("--card", "--path", "--lane") or not words:
            _header("missing argument" if flag in ("--card", "--path", "--lane") else f"unknown option {flag}", usage)
            return 2
        found[flag] = words.pop(0)
    if not found.get("--card") or not found.get("--path"):
        _header("missing argument", usage)
        return 2
    from .egress import fence_explain

    path = os.path.abspath(found["--path"])
    result = fence_explain(_pack(), found["--card"], path, found.get("--lane") or "worker-1")
    print(
        f"{'ALLOWED' if result['allowed'] else 'BLOCKED'}  {path}" + (f"  ({result['why']})" if result["why"] else "")
    )
    print("\n".join(result["lines"]))
    return 0 if result["allowed"] else 1


COMMANDS = {
    "fence-check": cmd_fence_check,
    "init": cmd_init,
    "pack": cmd_pack,
    "describe": cmd_describe,
    "demo": cmd_demo,
    "setup": cmd_setup,
    "update": cmd_update,
    "apply": cmd_apply,
    "doctor": cmd_doctor,
    "up": cmd_up,
    "down": cmd_down,
    "status": cmd_status,
    "outbox": cmd_outbox,
    "guard": cmd_guard,
    "publish": cmd_publish,
    "plan": cmd_plan,
    "migrate": cmd_migrate,
    "slot": cmd_slot,
    "live": cmd_live,
    "board": cmd_board,
    "advise": cmd_advise,
    "ticket": cmd_ticket,
    "watch-pr": cmd_watch_pr,
    "watch-ci": cmd_watch_ci,
    "watch-base": cmd_watch_base,
    "bumps": cmd_bumps,
    "advisories": cmd_advisories,
    "standup": cmd_standup,
    "vault": cmd_vault,
    "session": cmd_session,
    "worktree": cmd_worktree,
    "ide": cmd_ide,
    "map": cmd_map,
    "gate": cmd_gate,
    "workspace-watch": cmd_workspace_watch,
    "export": cmd_export,
    "resume-context": cmd_resume,
    "digest": cmd_digest,
    "perf": cmd_perf,
    "helper": cmd_helper,
    "reply": cmd_reply,
    "ci": cmd_ci,
    "test": cmd_test,
    "flow": cmd_flow,
    "pace": cmd_pace,
    "record": cmd_record,
}
