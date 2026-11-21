# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A first pack for a workspace: what `cockpit init` detects, the files it would write, and the writing itself.

Nothing is written until write() is called, and write() never replaces a file: the pack is built in a folder beside its
place, loaded and checked there, and only then moved in. The binding file is written last.
"""

import json
import os
import re
import shutil
import subprocess
import time

import yaml

from .errors import CockpitError, UsageError
from .paths import PLUGIN_ROOT, binding_file, hermes_home

GIT_TIMEOUT = 20
# The coding tools init looks for on PATH, in this order; the first one found starts the human's sessions. A pack names
# its own command in providers.coding.command, so this list only saves a first edit. Program names and the instruction
# files such tools read, matched against the machine and the workspace: never printed.
ROUTER_FILES = ("AGENTS.md", "CLAUDE.md")
CODING_TOOLS = ("cursor-agent", "claude", "codex", "gemini", "opencode", "aider")
STARTER = "starter"
STARTER_PARTS = ("skills", "souls", "bin")
OUTBOX = "cockpit:outbox"
# Which starter skills a kickoff of each mode loads, and which an intent type asks its lane to have loaded. A skill the
# starter does not hold is left out, so a pack written without the starter names cockpit's own outbox skill only.
KICKOFF_SKILLS = {
    "intake": ("ticket-intake",),
    "rework": ("implement", "self-review", "open-pr"),
    "worker": ("implement", "self-review", "open-pr"),
    "test": ("test-plan", "tracker-notes"),
    "tester": ("test-plan", "tracker-notes"),
    "review": ("pr-review",),
    "analyst": ("ticket-intake",),
    "bumps": (),
}
INTENT_SKILLS = {
    "open-pr": ("open-pr",),
    "pr-review-submit": ("pr-review",),
    "pr-comment": ("pr-review",),
    "tracker-comment": ("tracker-notes",),
}
PLACEHOLDER_MODEL = "set-a-model"
# Written beside the pack's own files: the example of a personal-values file, and the line that keeps the real one out
# of version control (pack_local).
PERSONAL_FILES = {
    "pack.local.example.yaml": (
        "# Personal values: what differs between two people who share this pack.\n"
        "# Copy this file to pack.local.yaml (.gitignore keeps that one out of version control) and set your own.\n"
        "# A pack file asks for a value as {local.<name>}; {home} is your home folder and needs no line here.\n"
        "# `cockpit pack check` names a value a pack file asks for and pack.local.yaml does not set.\n"
        "\n"
        "# forge_login: your-login\n"
        '# checkouts: "{home}/src"\n'
    ),
    ".gitignore": "pack.local.yaml\n",
}
REMOTE = re.compile(
    r"^(?:[a-z+]+://)?(?:[^@/]+@)?(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})(?::\d+)?[:/](?P<org>[^/:]+(?:/[^/]+)*)/(?P<name>[^/]+?)(?:\.git)?/?$"
)
FORGE_HOST = "github.com"
# fmt: off
ISSUES = "github-issues"                   # the tracker kind whose tickets are the issues of a repo on the pack's forge
ISSUES_PROJECT = "GH"                      # the prefix of its tickets when init is given no --project
TRACKERS = ("jira", "command", ISSUES)     # what init --tracker takes
# fmt: on


# ---------- detection ----------


def _git(folder: str, *argv) -> str:
    """One read-only git answer about a folder, or empty."""
    try:
        done = subprocess.run(
            ["git", "-C", folder, *argv], capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def repo_base(folder: str) -> str:
    """A repo's base branch: what its origin calls HEAD, else the branch it is on, else main."""
    head = _git(folder, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if "/" in head:
        return head.split("/", 1)[1]
    return _git(folder, "symbolic-ref", "--short", "HEAD") or "main"


def repo_remote(folder: str) -> dict:
    """{host, org} of a repo's origin, each empty when it has none or it is a folder on this machine."""
    match = REMOTE.match(_git(folder, "remote", "get-url", "origin"))
    return {"host": match.group("host").lower(), "org": match.group("org")} if match else {"host": "", "org": ""}


def _has(folder: str, name: str, pattern: str = "") -> bool:
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        return False
    if not pattern:
        return True
    try:
        return re.search(pattern, open(path, encoding="utf-8", errors="replace").read()) is not None
    except OSError:
        return False


def suggested_gates(folder: str) -> list:
    """The test commands a repo's own project files point at. A suggestion: the kernel does not invent a gate."""
    found = []
    try:
        scripts = (json.load(open(os.path.join(folder, "package.json"), encoding="utf-8")) or {}).get("scripts") or {}
    except (OSError, ValueError, AttributeError):
        scripts = {}
    if isinstance(scripts, dict) and scripts.get("test"):
        found.append("npm test")
    if (
        _has(folder, "pytest.ini")
        or _has(folder, "pyproject.toml", r"(?m)^\[tool\.pytest")
        or _has(folder, "tox.ini", r"(?m)^\[pytest\]")
        or _has(folder, "setup.cfg", r"(?m)^\[tool:pytest\]")
    ):
        found.append("python -m pytest -q")
    if _has(folder, "composer.json"):
        found.append(
            "composer test" if _has(folder, "composer.json", r'"scripts"\s*:\s*\{[^}]*"test"') else "vendor/bin/phpunit"
        )
    if _has(folder, "go.mod"):
        found.append("go test ./...")
    if _has(folder, "Cargo.toml"):
        found.append("cargo test")
    if _has(folder, "Makefile", r"(?m)^test\s*:"):
        found.append("make test")
    return found


def _is_repo(folder: str) -> bool:
    return os.path.isdir(folder) and os.path.exists(os.path.join(folder, ".git"))


def base_folder(workspace: str) -> str:
    """Where a repo's relative path starts: COCKPIT_ROOT, else the workspace's parent (paths.root, without a binding)."""
    return os.path.realpath(os.environ.get("COCKPIT_ROOT") or os.path.dirname(workspace))


def find_repos(workspace: str, skip=()) -> list:
    """The git repos that are children of the workspace or of its parent, each with a path check_repos resolves, its
    base branch, its origin and the gates its project files suggest. A child of the workspace wins a name."""
    workspace = os.path.realpath(workspace)
    start = base_folder(workspace)
    skipped = {os.path.realpath(path) for path in (workspace, *skip)}
    found, names = [], set()
    for parent in (workspace, os.path.dirname(workspace)):
        try:
            children = sorted(os.listdir(parent))
        except OSError:
            continue
        for name in children:
            folder = os.path.realpath(os.path.join(parent, name))
            if name.startswith(".") or name in names or folder in skipped or not _is_repo(folder):
                continue
            names.add(name)
            relative = os.path.relpath(folder, start)
            found.append(
                {
                    "name": name,
                    "path": folder if relative.startswith("..") else relative,
                    "base": repo_base(folder),
                    "gates": [],
                    "folder": folder,
                    "suggested": suggested_gates(folder),
                    **repo_remote(folder),
                }
            )
    return found


def hermes_model(home: str) -> dict:
    """{provider, model} a seat can run on, read from the Hermes home: config.yaml's model.provider and model.default,
    else the first name in known-providers. Each empty when the home does not say."""
    from .pack import _listed_providers

    listed = _listed_providers(home)
    try:
        config = yaml.safe_load(open(os.path.join(home, "config.yaml"), encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        config = {}
    model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
    provider = str(model.get("provider") or "")
    if provider in listed:
        return {"provider": provider, "model": str(model.get("default") or "")}
    try:
        names = [
            line.strip()
            for line in open(os.path.join(home, "known-providers"), encoding="utf-8")
            if line.strip() and not line.startswith("#")
        ]
    except OSError:
        names = []
    return {"provider": names[0] if names else "", "model": ""}


def coding_command() -> list:
    """The first known coding tool on PATH as a command, or empty."""
    for program in CODING_TOOLS:
        if shutil.which(program):
            return [program]
    return []


def starter_dir() -> str:
    return os.path.join(PLUGIN_ROOT, STARTER)


def starter_skills() -> list:
    folder = os.path.join(starter_dir(), "skills")
    if not os.path.isdir(folder):
        return []
    return sorted(name for name in os.listdir(folder) if os.path.isfile(os.path.join(folder, name, "SKILL.md")))


def place(directory: str = "", as_is: bool = False) -> dict:
    """{workspace, moved_from}: the workspace init proposes for a folder. A folder that is itself a git repo is a repo
    of the workspace, not the workspace: a sibling <name>-workspace is proposed, and moved_from names the repo. as_is
    keeps the folder (a workspace that is already bound stays where it is)."""
    folder = os.path.realpath(directory or os.getcwd())
    if _is_repo(folder) and not as_is:
        return {"workspace": folder + "-workspace", "moved_from": folder}
    return {"workspace": folder, "moved_from": ""}


# ---------- the files ----------


def _doc(file: str, path: str) -> str:
    from . import pack_keys

    entry = pack_keys.find(path if file == pack_keys.PACK else f"{file}:{path}")
    return entry["doc"] if entry else ""


def _leaf(key, value, indent: str) -> list:
    if isinstance(value, (list, dict)):  # a list or an empty mapping reads best on its key's line
        return [
            f"{indent}{key}: " + yaml.safe_dump(value, default_flow_style=True, width=1000, allow_unicode=True).strip()
        ]
    text = yaml.safe_dump({key: value}, default_flow_style=False, sort_keys=False, width=1000, allow_unicode=True)
    return [indent + line for line in text.splitlines()]


def _emit(file: str, data: dict, notes: dict, prefix: str = "", indent: str = "", docs: bool = True) -> list:
    """The lines of a mapping, each key under its one-sentence doc from the key registry, so a comment and the registry
    never disagree. notes adds lines under a key, by its dotted path. A list's keys are explained on its first item."""
    lines, said = [], ""
    for key, value in data.items():
        path = f"{prefix}{key}"
        doc = _doc(file, re.sub(r"\[\d+\]", "[]", path)) if docs else ""
        if not indent and lines:
            lines.append("")
        if doc and doc != said:  # keys that share one sentence (a pack's own names under one rule) get it once
            lines.append(f"{indent}# {doc}")
        said = doc
        lines += [f"{indent}# {note}" for note in notes.get(path) or []]
        if isinstance(value, dict) and value:
            lines.append(f"{indent}{key}:")
            lines += _emit(file, value, notes, path + ".", indent + "  ", docs)
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            lines.append(f"{indent}{key}:")
            for index, item in enumerate(value):
                rows = _emit(file, item, notes, f"{path}[{index}].", indent + "    ", docs and index == 0)
                first = next(number for number, row in enumerate(rows) if not row.lstrip().startswith("#"))
                rows[first] = indent + "  - " + rows[first].lstrip()
                lines += rows
        else:
            lines += _leaf(key, value, indent)
    return lines


def _text(file: str, data: dict, notes=None, head=()) -> str:
    return "\n".join([*(f"# {line}" for line in head), *([""] if head else []), *_emit(file, data, notes or {})]) + "\n"


def _tracker(found: dict) -> dict:
    """The pack's tracker block for the tracker chosen: the issues of the first repo need no URL, the others start a ticket's link at one."""
    if found["tracker"] == ISSUES:
        return {
            "kind": ISSUES,
            "project": found["project"],
            **({"repo": found["repos"][0]["name"]} if found["repos"] else {}),
        }
    return {
        **(
            {"kind": "command", "command": ["{pack}/bin/tracker"], "reads": ["comments", "me", "status"]}
            if found["tracker"] == "command"
            else {}
        ),
        "url": found["tracker_url"],
        "project": found["project"],
    }


def files_for(found: dict) -> dict:
    """{file name: text} of the pack for what was detected and answered."""
    from . import pack_keys

    name = found["name"]
    skills = found.get("starter_skills") or []
    provider = {"hermes_provider": found["provider"], "model": found["model"] or PLACEHOLDER_MODEL}
    pack = {
        "name": name,
        "board": name,
        "forge": {"org": found["org"]},
        "tracker": _tracker(found),
        "skills_dir": found["skills_dir"],
        "seats": {"slots": found["slots"], "intake": 1, "reviewer": 1, "analyst": 1},
        "slot_provider": "none",
        "providers": {"main": provider, "coding": {"command": found["coding"] or ["true"], "display_name": "Chat"}},
        "roles": {
            role: "main" for role in ("intake", "worker", "tester", "reviewer", "analyst", "gatekeeper", "advisor")
        },
        "agent": found["agent"],
    }
    notes = {
        "providers": ["One provider serves every role here; add a second entry and point a role at it to split them."],
        "slot_provider": ["none: the worker and tester seats work in a ticket's worktree, with no stack of their own."],
    }
    if not found["model"]:
        notes["providers.main.model"] = [
            f"The Hermes config names no model.default: replace {PLACEHOLDER_MODEL} before the first card."
        ]
    if not found["coding"]:
        notes["providers.coding.command"] = [
            "No known coding tool was found on PATH: `true` does nothing. Name yours here."
        ]
    if found.get("host") and found["host"] != FORGE_HOST:
        notes["forge.org"] = [f"Detected on {found['host']}: the kernel's forge commands speak to {FORGE_HOST} today."]
    if found.get("soul"):
        pack["seat_config"] = {"_common": {"soul": "souls/common.md"}}
    repos, repo_notes = [], {}
    for index, repo in enumerate(found["repos"]):
        gates = list(repo.get("gates") or [])
        suggested = [gate for gate in repo.get("suggested") or [] if gate not in gates]
        if found["accept_gates"]:
            gates, suggested = gates + suggested, []
        if suggested:
            repo_notes[f"repos[{index}].gates"] = [
                "suggested from this repo's files (cockpit init --accept-gates writes it): " + json.dumps(suggested)
            ]
        repos.append(
            {
                **{
                    key: value
                    for key, value in repo.items()
                    if key not in ("folder", "suggested", "host", "org", "gates")
                },
                "gates": gates,
            }
        )
    kickoff = found.get("kickoff")
    if kickoff is None:
        kickoff = {
            mode: [*(skill for skill in wanted if skill in skills), OUTBOX] for mode, wanted in KICKOFF_SKILLS.items()
        }
    intent = found.get("intent")
    if intent is None:
        intent = {kind: [skill for skill in wanted if skill in skills] for kind, wanted in INTENT_SKILLS.items()}
        intent = {kind: wanted for kind, wanted in intent.items() if wanted}
    skills_file = {"kickoff": kickoff, "intent": intent, **({"router": found["router"]} if found.get("router") else {})}
    egress = {
        "terminal_deny": [],
        "production_hosts": list(found["production_hosts"]),
        "sacred": [],
        "infra_paths": [],
        "destructive_http": [],
    }
    egress_notes = {}
    if found["no_production"]:
        egress = {
            "terminal_deny": [],
            "production_hosts": [],
            "no_production_hosts": True,
            "sacred": [],
            "infra_paths": [],
            "destructive_http": [],
        }
    elif not found["production_hosts"]:
        egress_notes["production_hosts"] = [
            "Not answered yet. Doctor stays red until this lists production, or no_production_hosts: true says there is none."
        ]
    files = {
        pack_keys.PACK: _text(
            pack_keys.PACK,
            pack,
            notes,
            head=(
                "The pack: what this workspace is, who works in it, and with what.",
                "Every key: cockpit pack explain <key>. The settings in force: cockpit pack effective.",
            ),
        ),
        pack_keys.REPOS: _text(
            pack_keys.REPOS,
            {"repos": repos},
            repo_notes,
            head=("The repositories a ticket may touch. A relative path starts at the workspace's parent.",),
        ),
        pack_keys.SKILLS: _text(
            pack_keys.SKILLS,
            skills_file,
            head=("Which skills a card loads. cockpit:<name> is one of cockpit's own; a bare name is in skills_dir.",),
        ),
        pack_keys.EGRESS: _text(
            pack_keys.EGRESS,
            egress,
            egress_notes,
            head=(
                "What no lane may reach. The kernel's own denies (a push, a forge write) are not listed here and cannot be removed.",
            ),
        ),
    }
    if found.get("staging_origin"):
        files[pack_keys.STAGING] = _text(
            pack_keys.STAGING,
            {"origins": {"app": found["staging_origin"]}},
            head=("Where the lanes test: never production.",),
        )
    return files


def detect(
    directory: str = "",
    pack_dir: str = "",
    slots: int = 1,
    production_hosts=(),
    no_production: bool = False,
    tracker: str = "",
    accept_gates: bool = False,
    starter: bool = True,
    staging_origin: str = "",
    tracker_url: str = "",
    project: str = "",
    as_is: bool = False,
) -> dict:
    """Everything init knows before it writes: the workspace, the pack's place, the repos, the provider, the coding
    tool, the answers given, and the notes a human should read. It reads and writes nothing else."""
    where = place(directory, as_is)
    workspace = where["workspace"]
    pack_dir = os.path.realpath(pack_dir) if pack_dir else os.path.join(workspace, "cockpit-pack")
    repos = find_repos(workspace, skip=(pack_dir,))
    home = hermes_home()
    model = hermes_model(home)
    have = starter_skills() if starter else []
    hosts = [(repo["host"], repo["org"]) for repo in repos if repo["host"]]
    host, org = max(hosts, key=hosts.count) if hosts else ("", "")
    notes = []
    if where["moved_from"]:
        notes.append(
            f"{where['moved_from']} is a git repository, so it is a repo of the workspace and not the workspace: "
            f"the workspace is its sibling {workspace}"
        )
    if not repos:
        notes.append(f"no git repository is a child of {workspace} or of its parent: list yours in repos.yaml")
    if host and host != FORGE_HOST:
        notes.append(
            f"the repos' origin is {host}, not {FORGE_HOST}: org {org} is written as detected, and the kernel's forge commands speak to {FORGE_HOST} today"
        )
    if not org:
        notes.append("no repo has an origin on a forge: forge.org is written as `example`; correct it in pack.yaml")
    if not model["provider"]:
        notes.append(
            f"no provider in {home}/config.yaml (model.provider) or {home}/known-providers: choose one in Hermes first (hermes model)"
        )
    elif not model["model"]:
        notes.append(
            f"{home}/config.yaml names no model.default: providers.main.model is written as {PLACEHOLDER_MODEL}; set it in pack.yaml"
        )
    coding = coding_command()
    if not coding:
        notes.append(
            "no known coding tool is on PATH: providers.coding.command is written as `true`; name yours in pack.yaml"
        )
    if starter and not have:
        notes.append(f"the starter pack is not in {starter_dir()}: the pack is written without starter skills")
    chosen = tracker or (
        "command" if starter and os.path.isfile(os.path.join(starter_dir(), "bin", "tracker")) else "jira"
    )
    if chosen == ISSUES and not repos:
        notes.append(
            "tracker github-issues: no repo was found to hold the issues; list yours in repos.yaml and name it as tracker.repo in pack.yaml"
        )
    router = next((name for name in ROUTER_FILES if os.path.isfile(os.path.join(workspace, name))), "")
    name = re.sub(r"[^a-z0-9-]+", "-", os.path.basename(workspace).lower()).strip("-") or "workspace"
    return {
        "workspace": workspace,
        "pack": pack_dir,
        "name": name,
        "moved_from": where["moved_from"],
        "repos": repos,
        "host": host,
        "org": org or "example",
        "provider": model["provider"],
        "model": model["model"],
        "coding": coding,
        "slots": slots,
        "production_hosts": list(production_hosts),
        "no_production": no_production,
        "tracker": chosen,
        "tracker_url": tracker_url or "https://tracker.example.test",
        "project": project or (ISSUES_PROJECT if chosen == ISSUES else "TASK"),
        "accept_gates": accept_gates,
        "starter": bool(starter and have),
        "starter_skills": have,
        "soul": bool(starter and os.path.isfile(os.path.join(starter_dir(), "souls", "common.md"))),
        "skills_dir": ["{pack}/skills"],
        "agent": {"home": ".", "add_dirs": [], "args": []},
        "router": router,
        "staging_origin": staging_origin,
        "notes": notes,
    }


def plan(found: dict, bind: bool = True, rebind: bool = False) -> dict:
    """What init would do with a detection: the files by name, the starter folders copied in, and the binding. A
    refusal is a reason in `refused`; nothing here touches the disk."""
    pack_dir = found["pack"]
    files = {**files_for(found), **PERSONAL_FILES}
    copies = [part for part in STARTER_PARTS if found["starter"] and os.path.isdir(os.path.join(starter_dir(), part))]
    listed = [os.path.join(pack_dir, name) for name in files]
    for part in copies:
        for base, _dirs, names in os.walk(os.path.join(starter_dir(), part)):
            listed += [
                os.path.join(pack_dir, os.path.relpath(os.path.join(base, name), starter_dir()))
                for name in sorted(names)
                if not name.endswith(".pyc")
            ]
    if "skills" not in copies:
        listed.append(os.path.join(pack_dir, "skills", ".gitkeep"))
    refused = ""
    if os.path.lexists(pack_dir) and (not os.path.isdir(pack_dir) or os.listdir(pack_dir)):
        refused = f"{pack_dir} is there and not empty: init never replaces a file (name another place with --pack DIR)"
    elif not found["provider"]:
        refused = found["notes"][
            [index for index, note in enumerate(found["notes"]) if note.startswith("no provider in ")][0]
        ]
    elif found["tracker"] == "command" and "bin" not in copies:
        refused = "--tracker command needs the starter's bin/tracker: leave --no-starter out, or choose --tracker jira"
    binding = None
    if bind:
        from .paths import load_binding

        wanted = {"workspace": found["workspace"], "pack": os.path.join(pack_dir, "pack.yaml")}
        current = load_binding()
        same = current and all(
            os.path.realpath(str(current.get(key) or "")) == os.path.realpath(wanted[key]) for key in wanted
        )
        binding = {"path": binding_file(), **wanted, "replaces": bool(current and not same), "kept": bool(same)}
        if current and not same and not rebind and not refused:
            refused = (
                f"{binding_file()} binds another workspace ({current.get('workspace')}): --rebind keeps a copy and binds this one, "
                "--no-bind writes the pack only"
            )
    return {
        "found": found,
        "files": files,
        "copies": copies,
        "listed": sorted(listed),
        "binding": binding,
        "refused": refused,
    }


# ---------- writing ----------


def _scan(texts) -> None:
    """A secret in anything about to be written stops the call before its first write."""
    from .migrate import secrets_scan

    for text in texts:
        if secrets_scan(text):
            raise CockpitError("secret in draft")


def _starter_texts(copies) -> list:
    texts = []
    for part in copies:
        for base, _dirs, names in os.walk(os.path.join(starter_dir(), part)):
            for name in names:
                try:
                    texts.append(open(os.path.join(base, name), encoding="utf-8").read())
                except (OSError, UnicodeError):
                    continue
    return texts


def _remove_made(made) -> None:
    """Take back what this call made, newest first: a file it wrote, a folder it created and that is empty again."""
    for path in reversed(made):
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                os.rmdir(path)
            else:
                os.remove(path)
        except OSError:
            continue


def _mkdir(path: str, made: list) -> None:
    missing = []
    while path and not os.path.isdir(path):
        missing.append(path)
        path = os.path.dirname(path)
    for folder in reversed(missing):
        os.mkdir(folder)
        made.append(folder)


def _write_new(path: str, text: str, made: list) -> None:
    with open(path, "x", encoding="utf-8") as handle:  # "x": a file that is there is never replaced
        handle.write(text)
    made.append(path)


def _check(pack_file: str, workspace: str) -> None:
    """The written pack loads, its repos are where it says, and Hermes knows its provider. The workspace is named for
    the length of the check only: nothing is bound yet."""
    from .pack import check_known_providers, check_repos, load

    before = os.environ.get("COCKPIT_WORKSPACE")
    os.environ["COCKPIT_WORKSPACE"] = workspace
    try:
        data = load(pack_file)
        check_repos(data, base_folder(workspace))
        check_known_providers(data, hermes_home())
    finally:
        if before is None:
            os.environ.pop("COCKPIT_WORKSPACE", None)
        else:
            os.environ["COCKPIT_WORKSPACE"] = before


def write(planned: dict, check: bool = True) -> dict:
    """Write a plan: the pack beside its place, checked there, moved in; then the binding. {written, binding, backup}.
    A refusal, a secret or a failed check leaves no file of this call behind, and no file that was there is touched.
    check=False is a draft a human completes before it loads (the migration's)."""
    if planned["refused"]:
        raise UsageError(planned["refused"])
    found, files, copies = planned["found"], planned["files"], planned["copies"]
    _scan([*files.values(), *_starter_texts(copies)])
    pack_dir = found["pack"]
    made = []
    temp = os.path.join(os.path.dirname(pack_dir), f".{os.path.basename(pack_dir)}.init-{os.getpid()}")
    try:
        _mkdir(found["workspace"], made)
        _mkdir(os.path.dirname(pack_dir), made)
        os.mkdir(temp)
        made.append(temp)
        for name, text in files.items():
            _write_new(os.path.join(temp, name), text, made)
        for part in copies:
            for base, dirs, names in os.walk(os.path.join(starter_dir(), part)):
                dirs[:] = sorted(name for name in dirs if name != "__pycache__")
                target = os.path.join(temp, os.path.relpath(base, starter_dir()))
                os.mkdir(target)
                made.append(target)
                for name in sorted(names):
                    if name.endswith(".pyc"):
                        continue
                    shutil.copy2(os.path.join(base, name), os.path.join(target, name))
                    made.append(os.path.join(target, name))
        if "skills" not in copies:
            os.mkdir(os.path.join(temp, "skills"))
            made.append(os.path.join(temp, "skills"))
            _write_new(os.path.join(temp, "skills", ".gitkeep"), "", made)
        if check:
            _check(os.path.join(temp, "pack.yaml"), found["workspace"])
        os.rename(temp, pack_dir)  # onto nothing, or onto the empty folder that was there
    except BaseException:
        _remove_made(made)
        raise
    binding, backup = planned["binding"], ""
    if binding and not binding["kept"]:
        path = binding["path"]
        if binding["replaces"]:
            backup = f"{path}.{time.strftime('%Y%m%dT%H%M%S')}"
            shutil.copy2(path, backup)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        scratch = f"{path}.init-{os.getpid()}"
        with open(scratch, "w", encoding="utf-8") as handle:
            handle.write(yaml.safe_dump({"workspace": binding["workspace"], "pack": binding["pack"]}, sort_keys=False))
        os.replace(scratch, path)
    return {
        "written": [
            path.replace(temp, pack_dir, 1)
            for path in made
            if path.startswith(temp + os.sep) and not os.path.isdir(path.replace(temp, pack_dir, 1))
        ],
        "binding": binding["path"] if binding else "",
        "backup": backup,
    }
