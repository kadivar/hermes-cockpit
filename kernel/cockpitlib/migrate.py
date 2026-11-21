# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Draft a pack without publishing, pushing, or deleting workspace records."""

import os
import re
import shutil

import yaml

from .errors import CockpitError
from .paths import hermes_home

SECRET = re.compile(r"AKIA[0-9A-Z]{8}|-----BEGIN |password\s*=\s*\S+|api[_-]?key\s*[:=]\s*\S+", re.I)


def secrets_scan(text: str) -> str:
    match = SECRET.search(text or "")
    return match.group(0)[:12] if match else ""


def discover(workspace: str, skill_dirs=None) -> dict:
    """Read-only. skill_dirs are absolute paths the human named, plus SKILL.md trees inside the workspace."""
    dirs = []
    for folder in skill_dirs or []:
        if os.path.isabs(folder) and os.path.isdir(folder):
            dirs.append(os.path.realpath(folder))
    for dirpath, _dirnames, filenames in os.walk(workspace):
        if "SKILL.md" in filenames:
            parent = os.path.dirname(dirpath)
            if os.path.basename(os.path.dirname(parent)) in ("skills",) or os.path.basename(parent) == "skills":
                # SKILL.md lives at <skills>/<name>/SKILL.md
                skills_root = os.path.dirname(dirpath)
                if skills_root not in dirs:
                    dirs.append(os.path.realpath(skills_root))
    from .scaffold import ROUTER_FILES, find_repos

    # each repo's path starts where the kernel resolves it (the workspace's parent), with its own base branch
    repos = [
        {"name": repo["name"], "path": repo["path"], "base": repo["base"], "gates": [], "suggested": repo["suggested"]}
        for repo in find_repos(workspace)
    ]
    router = ""
    for name in ROUTER_FILES:
        if os.path.isfile(os.path.join(workspace, name)):
            router = name
            break
    cursor_skills = os.path.join(workspace, ".cursor", "skills")
    if os.path.isdir(cursor_skills) and os.path.realpath(cursor_skills) not in dirs:
        dirs.insert(0, os.path.realpath(cursor_skills))
    mcp = os.path.isfile(os.path.join(workspace, ".cursor", "mcp.json"))
    parent = os.path.dirname(os.path.realpath(workspace))
    add_dirs = [parent] if parent and parent != os.path.realpath(workspace) else []
    return {
        "skills_dir": dirs,
        "repos": repos,
        "name": os.path.basename(workspace) or "workspace",
        "router": router,
        "agent": {
            "home": os.path.realpath(workspace),
            "add_dirs": add_dirs,
            "args": ["--approve-mcps"] if mcp else [],
        },
    }


def draft(discovery, dest: str) -> list:
    """Write a pack under dest from a discovery, through the writer `cockpit init` uses: no file is replaced, a secret stops the
    call before its first write, the provider and model come from the Hermes home, and a worker and a tester seat exist.
    It is a draft: the human completes it before it loads (production is left unanswered, so doctor stays red until it
    is), and the migration writes the binding."""
    from . import scaffold
    from .paths import workspace

    if secrets_scan(yaml.safe_dump(discovery)):
        raise CockpitError("secret in draft")
    found = scaffold.detect(workspace(), pack_dir=dest, starter=False, as_is=True)
    supplied = discovery.get("skills") if isinstance(discovery.get("skills"), dict) else {}
    found.update(
        {
            "name": discovery.get("name") or found["name"],
            "repos": [dict(repo) for repo in discovery.get("repos") or []],
            "org": str(discovery.get("org") or "example"),
            "tracker_url": str(discovery.get("tracker_url") or "https://jira.example.test"),
            "project": str(discovery.get("project") or "PROJECT"),
            "tracker": "jira",
            "skills_dir": list(discovery.get("skills_dir") or []) or found["skills_dir"],
            "agent": discovery.get("agent") or {"home": "", "add_dirs": [], "args": []},
            "kickoff": supplied.get("kickoff") if isinstance(supplied.get("kickoff"), dict) else {},
            "intent": supplied.get("intent") if isinstance(supplied.get("intent"), dict) else {},
            "router": discovery.get("router")
            or (supplied.get("router") if isinstance(supplied.get("router"), str) else ""),
        }
    )
    return scaffold.write(scaffold.plan(found, bind=False), check=False)["written"]


def journal(workspace: str) -> str:
    path = os.path.join(workspace, "cockpit-pack", "_migrate")
    os.makedirs(path, exist_ok=True)
    return path


def rollback(snapshot: str, home: str = "") -> list:
    """Restore config.yaml, profiles, and the board export from a snapshot. Refuses to guess."""
    home = home or hermes_home()
    if not snapshot or not os.path.isdir(snapshot):
        raise CockpitError("snapshot missing; refusing to guess")
    restored = []
    config = os.path.join(snapshot, "config.yaml")
    if os.path.isfile(config):
        target = os.path.join(home, "config.yaml")
        os.makedirs(home, exist_ok=True)
        shutil.copy(config, target)
        restored.append(target)
    profiles = os.path.join(snapshot, "profiles")
    if os.path.isdir(profiles):
        dest = os.path.join(home, "profiles")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(profiles, dest)
        restored.append(dest)
    kanban = os.path.join(snapshot, "kanban")
    if os.path.isdir(kanban):
        dest = os.path.join(home, "kanban")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(kanban, dest)
        restored.append(dest)
    binding_src = os.path.join(snapshot, "cockpit.yaml")
    binding = os.path.join(home, "cockpit.yaml")
    if os.path.isfile(binding_src):
        os.makedirs(home, exist_ok=True)
        shutil.copy(binding_src, binding)
        restored.append(binding)
    elif os.path.isfile(binding):
        os.remove(binding)
        restored.append("binding-removed")
    return restored
