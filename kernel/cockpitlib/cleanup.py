# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stale worktrees: the ticket folders under wt/ that nothing has touched for a fortnight. `cockpit worktree gc` lists and
removes them; the Settings page turns a daily pass on (worktree_gc, off by default). A folder goes only when every gate
passes, and each gate names itself as the reason to keep: nothing under it was touched for the period (node_modules,
vendor and .git aside), no commit that recent, no slot holds the ticket, no open card names it, no process runs inside
it, every checkout is clean and its commits are on a remote. Branches stay, as the rest of the kernel keeps them."""

import json
import os
import subprocess
import time

from .errors import CockpitError
from .kanban import OPEN, board_cards
from .paths import watch_dir, worktree_of, wt
from .store import dump_json
from .worktree import list_worktrees, repo_source

DEFAULT_DAYS = 14
DAYS_RANGE = (1, 365)
PASS_EVERY = 86400  # the automatic pass runs once a day
SKIP = ("node_modules", "vendor", ".git")


def _record_path() -> str:
    return os.path.join(watch_dir(), "worktree-gc.json")


def last_pass() -> dict:
    try:
        data = json.load(open(_record_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _git(folder: str, *args, timeout: int = 20) -> tuple:
    try:
        done = subprocess.run(
            ["git", "-C", folder, *args], check=False, capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout if done.returncode == 0 else (done.stderr or done.stdout)).strip()


def _touched(folder: str, cutoff: float) -> str:
    """The first path under the folder newer than the cutoff (the folder itself counts), or ""."""
    for current, dirs, files in os.walk(folder):
        dirs[:] = [name for name in dirs if name not in SKIP]
        for name in [""] + files:
            path = os.path.join(current, name) if name else current
            try:
                if os.lstat(path).st_mtime >= cutoff:
                    return os.path.relpath(path, folder) if path != folder else os.path.basename(folder)
            except OSError:
                continue
    return ""


def _size_kb(folder: str) -> int:
    total = 0
    for current, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.lstat(os.path.join(current, name)).st_size
            except OSError:
                continue
    return total // 1024


def human(kb: int) -> str:
    if kb >= 1048576:
        return f"{kb / 1048576:.1f} GB"
    if kb >= 1024:
        return f"{kb // 1024} MB"
    return f"{kb} KB"


def _held(pack) -> set:
    """The tickets the slots are bound to, whoever owns them."""
    from .slots import read_ticket

    count = max(1, int((pack.get("seats") or {}).get("slots") or 1))
    return {read_ticket(number) for number in range(1, count + 1)} - {""}


def _carded(pack) -> dict:
    """{ticket: the title of an open card}."""
    found = {}
    for card in board_cards(pack["board"]):
        if card["status"] in OPEN and card["ticket"] not in found:
            found[card["ticket"]] = card["title"]
    return found


def _cwds() -> list:
    """The working directory of every process lsof can see; empty when it cannot run."""
    try:
        done = subprocess.run(
            ["lsof", "-a", "-d", "cwd", "-Fn"], check=False, capture_output=True, text=True, timeout=15
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    return [line[1:] for line in done.stdout.splitlines() if line.startswith("n")]


def keep_reason(pack, ticket: str, days: int, held: set, carded: dict, cwds: list, now: float) -> str:
    folder = worktree_of(ticket)
    cutoff = now - days * 86400
    recent = _touched(folder, cutoff)
    if recent:
        return f"touched within {days} days ({recent})"
    checkouts = [path for path in list_worktrees(ticket) if os.path.exists(os.path.join(path, ".git"))]
    for path in checkouts:
        repo = os.path.basename(path)
        try:
            repo_source(pack, repo)
        except CockpitError:
            return f"{repo} is not a repo of the pack (remove by hand)"
        code, stamp = _git(path, "log", "-1", "--format=%ct", "HEAD")
        if code != 0:
            return f"{repo} is not a git checkout (remove by hand)"
        if stamp.isdigit() and int(stamp) >= cutoff:
            return f"{repo} has a commit within {days} days"
    if ticket in held:
        return "a slot holds it"
    if ticket in carded:
        return f"open card: {carded[ticket][:60]}"
    for cwd in cwds:
        if cwd == folder or cwd.startswith(folder + os.sep):
            return "a process runs inside it"
    for path in checkouts:
        repo = os.path.basename(path)
        code, changed = _git(path, "status", "--porcelain")
        if code != 0 or changed:
            return f"{repo} has uncommitted changes"
        code, ahead = _git(path, "rev-list", "--count", "HEAD", "--not", "--remotes")
        if code != 0 or ahead != "0":
            return f"{repo} has commits not on a remote"
    return ""


def inventory(pack, days: int = 0, now=None) -> list:
    """Every ticket folder under wt/: {ticket, repos, keep} — keep is the reason it stays, "" when it can go."""
    days = int(days or DEFAULT_DAYS)
    moment = time.time() if now is None else now
    base = wt()
    if not os.path.isdir(base):
        return []
    held, carded, cwds = _held(pack), _carded(pack), _cwds()
    found = []
    for name in sorted(os.listdir(base)):
        folder = worktree_of(name)
        if not os.path.isdir(folder):
            continue
        repos = [os.path.basename(path) for path in list_worktrees(name) if os.path.exists(os.path.join(path, ".git"))]
        found.append(
            {"ticket": name, "repos": repos, "keep": keep_reason(pack, name, days, held, carded, cwds, moment)}
        )
    return found


def remove(pack, ticket: str) -> list:
    """The ticket folder: each checkout through git (its branch stays), then the folder's own files. The repos' stale
    worktree records go with it."""
    from .acts import remove_worktrees

    removed = remove_worktrees(pack, ticket)
    sources = set()
    for repo in pack["repos"]["repos"]:
        try:
            sources.add(repo_source(pack, repo["name"]))
        except CockpitError:
            continue
    for source in sources:
        if os.path.isdir(source):
            _git(source, "worktree", "prune")
    return removed


def gc(pack, days: int = 0, dry_run: bool = False, now=None) -> dict:
    """One pass: {days, dry_run, removed: [{ticket, repos, kb}], kept: [{ticket, why}], freed_kb, lines}."""
    days = int(days or DEFAULT_DAYS)
    if not DAYS_RANGE[0] <= days <= DAYS_RANGE[1]:
        raise CockpitError(f"days is a whole number from {DAYS_RANGE[0]} to {DAYS_RANGE[1]}")
    removed, kept, lines = [], [], []
    for row in inventory(pack, days, now):
        if row["keep"]:
            kept.append({"ticket": row["ticket"], "why": row["keep"]})
            lines.append(f"keep {row['ticket']}: {row['keep']}")
            continue
        folder = worktree_of(row["ticket"])
        kb = _size_kb(folder)
        if not dry_run:
            try:
                remove(pack, row["ticket"])
            except (CockpitError, OSError) as exc:
                kept.append({"ticket": row["ticket"], "why": f"removal failed: {exc}"})
                lines.append(f"keep {row['ticket']}: removal failed: {exc}")
                continue
        removed.append({"ticket": row["ticket"], "repos": row["repos"], "kb": kb})
        lines.append(
            f"{'would remove' if dry_run else 'removed'} {row['ticket']} (up to {human(kb)}; {' '.join(row['repos']) or 'no checkouts'})"
        )
    freed = sum(item["kb"] for item in removed)
    lines.append(
        f"{'would free' if dry_run else 'freed'} up to {human(freed)}: {len(removed)} removed, {len(kept)} kept (untouched for {days} days)"
    )
    return {"days": days, "dry_run": dry_run, "removed": removed, "kept": kept, "freed_kb": freed, "lines": lines}


def settings_of(pack) -> dict:
    from .settings import load

    return dict(load(pack).get("worktree_gc") or {"enabled": False, "days": DEFAULT_DAYS})


def _write_record(record: dict) -> None:
    os.makedirs(watch_dir(), exist_ok=True)
    dump_json(_record_path(), record)


def run_if_due(pack, now=None) -> str:
    """The housekeeping step: nothing while the setting is off; one pass a day while it is on. A line, never a failure
    for a folder that would not go (its reason is in the record the Settings page shows)."""
    moment = time.time() if now is None else now
    setting = settings_of(pack)
    if not setting.get("enabled"):
        return "off"
    last = last_pass()
    if last.get("ran_at") and moment - float(last["ran_at"]) < PASS_EVERY:
        return f"{last.get('summary') or 'ran'} ({int((moment - float(last['ran_at'])) / 3600)}h ago)"
    result = gc(pack, int(setting.get("days") or DEFAULT_DAYS), now=moment)
    summary = f"removed {len(result['removed'])}, kept {len(result['kept'])}, freed up to {human(result['freed_kb'])}"
    _write_record(
        {
            "ran_at": moment,
            "days": result["days"],
            "summary": summary,
            "removed": [item["ticket"] for item in result["removed"]],
            "kept": result["kept"],
            "freed_kb": result["freed_kb"],
        }
    )
    return summary
