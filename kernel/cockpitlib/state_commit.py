# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Commit cockpit records in the workspace. Local only. Never pushes."""

import os
import subprocess
import time

from .errors import CockpitError
from .kanban import board_cards
from .paths import records_name, workspace
from .store import scratch
from .time_util import quiet

RUNNING = ("in_progress", "running", "claimed")


def _git(root, args, check=True):
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Cockpit")
    env.setdefault("GIT_AUTHOR_EMAIL", "cockpit@localhost")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    env["GRAPHIFY_SKIP_HOOK"] = "1"
    result = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=env, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "git failed").strip()
        raise CockpitError(detail)
    return result


def _busy(root) -> str:
    git_dir = _git(root, ["rev-parse", "--git-dir"]).stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(root, git_dir)
    for name in (
        "index.lock",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
        "BISECT_LOG",
    ):
        if os.path.exists(os.path.join(git_dir, name)):
            return name
    return ""


def _changed(root) -> list:
    result = _git(root, ["status", "--porcelain", "--untracked-files=all", "--", records_name()])
    found = []
    for line in result.stdout.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path:
            found.append(path)
    return found


def _concern(path) -> str:
    prefix = records_name().rstrip("/") + "/"
    if not path.startswith(prefix):
        return ""
    parts = path[len(prefix) :].split("/")
    if len(parts) < 2 or scratch(parts[-1]):  # a lock or a temp file of store's is no record: never committed
        return ""
    kind = parts[0]
    if kind == "outbox" and parts[1].startswith("_"):
        return "receipts" if parts[1] == "_published.log" else ""
    if kind == "platform":
        return "platform"
    if kind in ("watch", "chat"):
        return ""
    if kind == "qa" and len(parts) == 2:
        return ""
    if kind in ("qa", "outbox") and len(parts) > 2:
        return "ticket:" + parts[1]
    return ""


def _newest(root, paths) -> float:
    newest = 0.0
    for path in paths:
        full = os.path.join(root, path)
        if os.path.exists(full):
            newest = max(newest, os.path.getmtime(full))
    return newest


def _last_commit(root, paths) -> int:
    result = _git(root, ["log", "-1", "--format=%ct", "--", *paths], check=False)
    text = result.stdout.strip()
    return int(text) if text.isdigit() else 0


def _running(pack, ticket) -> list:
    return [card["id"] for card in board_cards(pack["board"]) if card["ticket"] == ticket and card["status"] in RUNNING]


def _record_subject(concern: str, paths) -> str:
    """A platform commit names the records it includes."""
    if concern != "platform":
        return "pipeline: receipt log"
    names = ", ".join(os.path.basename(path) for path in sorted(paths))
    return f"platform: {names}"


def _commit(root, paths, subject) -> str:
    _git(root, ["add", "-A", "--", *paths])
    _git(root, ["commit", "--only", "-m", subject[:160], "--", *paths])
    return _git(root, ["log", "-1", "--format=%h %s"]).stdout.strip()


def _branch(root) -> str:
    result = _git(root, ["symbolic-ref", "--short", "HEAD"], check=False)
    if result.returncode != 0:
        return "detached"
    return result.stdout.strip() or "detached"


def workspace_branch(pack) -> str:
    """The branch the pack names. An empty pack does not imply one."""
    return str((pack or {}).get("workspace_branch") or "").strip()


def state_commit(pack, now=None, quiet_seconds=300) -> str:
    root = workspace()
    if not os.path.isdir(os.path.join(root, ".git")) and not os.path.isfile(os.path.join(root, ".git")):
        return "HOLD no git workspace"
    current = _branch(root)
    wanted = workspace_branch(pack)
    if not wanted:
        return "workspace-watch: records stay uncommitted (the pack names no workspace_branch)"
    if current != wanted:
        return f"HOLD workspace is on {current}; workspace-watch commits only on {wanted}"
    marker = _busy(root)
    if marker:
        return f"workspace-watch: git is busy ({marker})"
    groups = {}
    for path in _changed(root):
        concern = _concern(path)
        if concern:
            groups.setdefault(concern, []).append(path)
    if not groups:
        return "workspace-watch: nothing new"
    moment = time.time() if now is None else now
    lines = []

    def commit(paths, subject) -> str:
        try:
            return _commit(root, paths, subject)
        except (CockpitError, OSError) as exc:
            return "HOLD " + str(exc)

    for concern in sorted(groups, key=lambda name: (name == "receipts", name)):
        paths = groups[concern]
        if not quiet(_newest(root, paths), moment, quiet_seconds):
            lines.append(f"{concern}: still changing")
            continue
        if concern.startswith("ticket:"):
            ticket = concern.split(":", 1)[1]
            running = _running(pack, ticket)
            if running:
                lines.append(f"{ticket}: still running")
                continue
            made = commit(paths, f"{ticket}: pipeline records")
            if made.startswith("HOLD "):
                return made
            lines.append(made)
            continue
        if concern == "receipts" and moment - _last_commit(root, paths) < 3600:
            lines.append("receipts: committed within the hour")
            continue
        made = commit(paths, _record_subject(concern, paths))
        if made.startswith("HOLD "):
            return made
        lines.append(made)
    return "workspace-watch: " + "; ".join(lines)
