# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One checkout per repo per ticket. Lanes cannot push."""

import os
import subprocess

from .errors import CockpitError
from .paths import root, worktree_of, wt


def dest(ticket: str, repo: str) -> str:
    return worktree_of(ticket, repo)


def _run(argv) -> None:
    done = subprocess.run(argv, check=False, capture_output=True, text=True)
    if done.returncode == 0:
        return
    detail = (done.stderr or done.stdout or "git failed").strip()
    raise CockpitError(detail)


def _worktree_config(target: str) -> None:
    subprocess.run(
        ["git", "-C", target, "config", "extensions.worktreeConfig", "true"],
        check=False,
        capture_output=True,
        text=True,
    )


def _push(target: str, value: str) -> str:
    """The push URL lives on this checkout. A linked worktree does not change the source repo."""
    _worktree_config(target)
    subprocess.run(
        ["git", "-C", target, "config", "--worktree", "remote.origin.pushurl", value],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", target, "config", "--worktree", "cockpit.push", "disabled"],
        check=False,
        capture_output=True,
        text=True,
    )
    return value


def _clear_push(target: str) -> str:
    """Human mode uses the real origin. The blocking push URL is removed."""
    _worktree_config(target)
    subprocess.run(
        ["git", "-C", target, "config", "--worktree", "--unset", "remote.origin.pushurl"],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", target, "config", "--worktree", "cockpit.push", "allowed"],
        check=False,
        capture_output=True,
        text=True,
    )
    return "ALLOWED"


def _checkout(ticket: str, repo: str, pack=None) -> str:
    """The ticket's checkout of the repo: its worktree wt/<ticket>/<repo>."""
    side = dest(ticket, repo)
    if os.path.isdir(side):
        return side
    raise CockpitError(f"no worktree {side}")


def _git(source, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", source, *args], check=False, capture_output=True, text=True)


def _held_branches(source: str) -> set:
    """Branches some checkout of this repo has checked out (the main one included)."""
    listed = _git(source, "worktree", "list", "--porcelain").stdout
    return {
        line.split(" ", 1)[1].removeprefix("refs/heads/") for line in listed.splitlines() if line.startswith("branch ")
    }


def _start_point(source: str, base: str, branch_from: str) -> str:
    """--from, else origin/<base> after a fetch, else <base>. No start point is a refusal, never a detached checkout."""
    if branch_from:
        if _git(source, "rev-parse", "--verify", "--quiet", branch_from).returncode != 0:
            raise CockpitError(f"no ref {branch_from} in {source}")
        return branch_from
    if base:
        _git(source, "fetch", "--quiet", "origin", base)
        for ref in (f"origin/{base}", base):
            if _git(source, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
                return ref
        raise CockpitError(f"no {base} to branch from in {source}")
    return "HEAD"


def _refresh(target: str, branch_from: str) -> None:
    """--from on a checkout that is already there: fetch, then move it to the ref when it is clean and holds no commit of
    its own (its branch keeps its name; a checkout on no branch stays on none). A checkout with changes or unpushed
    commits is left as it is and the caller is told where it stands: never a silent answer at the old head."""
    _git(target, "fetch", "--quiet", "origin")
    want = _git(target, "rev-parse", "--verify", "--quiet", f"{branch_from}^{{commit}}").stdout.strip()
    if not want:
        raise CockpitError(f"no ref {branch_from} in {target}")
    head = _git(target, "rev-parse", "HEAD").stdout.strip()
    if head == want:
        return
    branch = _git(target, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    changed = len(
        [
            line
            for line in _git(target, "status", "--porcelain", "--untracked-files=no").stdout.splitlines()
            if line.strip()
        ]
    )
    ahead = _git(target, "rev-list", "--count", "HEAD", "--not", "--remotes").stdout.strip()
    held = [
        text
        for text in (
            f"{changed} changed file(s)" if changed else "",
            f"{ahead} unpushed commit(s)" if ahead not in ("", "0") else "",
        )
        if text
    ]
    if held:
        raise CockpitError(
            f"{target} is at {head[:10]} ({branch or 'no branch'}) with {' and '.join(held)}: --from {branch_from} "
            f"was not applied (it is at {want[:10]}). Commit and push, or set the work aside, then run it again"
        )
    if branch in ("", "HEAD"):
        _run(["git", "-C", target, "checkout", "--quiet", "--detach", want])
        return
    _run(["git", "-C", target, "checkout", "--quiet", "-B", branch, want])


def add(ticket: str, repo: str, prefix: str, source: str, branch_from: str = "", base: str = "", setup=None) -> str:
    """One checkout for this ticket and repo, on its own branch. A branch the human's checkout holds is used under
    the repo's branch_suffix_when_held name; then the repo's copy, hooks_path, worktree_files, and after_add apply.
    --from on a checkout that is already there moves it to that ref, or refuses and says why (_refresh)."""
    target = dest(ticket, repo)
    if os.path.isdir(target):
        if branch_from:
            _refresh(target, branch_from)
        return target
    if not os.path.isdir(os.path.join(source, ".git")) and not os.path.isfile(os.path.join(source, ".git")):
        raise CockpitError(f"no repo at {source}")
    setup = setup or {}
    os.makedirs(os.path.dirname(target), exist_ok=True)
    branch = f"{prefix}/{ticket}"
    if branch in _held_branches(source):
        suffix = str(setup.get("branch_suffix_when_held") or "")
        if not suffix:
            raise CockpitError(
                f"{branch} is checked out in another checkout of {repo}; set branch_suffix_when_held in repos.yaml"
            )
        branch = branch + suffix
    if _git(source, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        done = _git(source, "worktree", "add", target, branch)
    else:
        done = _git(source, "worktree", "add", "-b", branch, target, _start_point(source, base, branch_from))
    if done.returncode != 0 or not os.path.isdir(target):
        raise CockpitError((done.stderr or done.stdout or "git worktree add failed").strip())
    _push(target, "DISABLED")
    _prepare(target, source, setup, ticket)
    return target


def _prepare(target: str, source: str, setup: dict, ticket: str) -> None:
    import shutil

    for item in setup.get("copy") or []:
        origin = os.path.join(source, item)
        copied = os.path.join(target, item)
        if os.path.isdir(origin):
            shutil.copytree(origin, copied, dirs_exist_ok=True, symlinks=True)
        elif os.path.isfile(origin):
            os.makedirs(os.path.dirname(copied), exist_ok=True)
            shutil.copy2(origin, copied)
    if setup.get("hooks_path"):
        hooks = setup["hooks_path"] if os.path.isabs(setup["hooks_path"]) else os.path.join(source, setup["hooks_path"])
        _worktree_config(target)
        _run(["git", "-C", target, "config", "--worktree", "core.hooksPath", hooks])
    for item in setup.get("worktree_files") or []:
        written = os.path.join(target, item["target"])
        os.makedirs(os.path.dirname(written), exist_ok=True)
        shutil.copy2(item["source"], written)
    for argv in setup.get("after_add") or []:
        done = subprocess.run(
            argv,
            cwd=target,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "COCKPIT_TICKET": ticket, "COCKPIT_WORKTREE": target},
        )
        if done.returncode != 0:
            raise CockpitError(f"after_add {' '.join(argv)}: {(done.stderr or done.stdout).strip()[-200:]}")


def head_of(ticket: str, repo: str, pack=None) -> str:
    """The checkout HEAD, or empty when this ticket has no checkout."""
    try:
        folder = _checkout(ticket, repo, pack)
    except CockpitError:
        return ""
    done = subprocess.run(["git", "-C", folder, "rev-parse", "HEAD"], check=False, capture_output=True, text=True)
    if done.returncode != 0:
        return ""
    return (done.stdout or "").strip()


def mode(ticket: str, repo: str, human: bool, pack=None) -> str:
    """Lane mode cannot push. Human mode can."""
    target = _checkout(ticket, repo, pack)
    if human:
        return _clear_push(target)
    return _push(target, "DISABLED")


def list_worktrees(ticket: str = "") -> list:
    """The folders under wt/<ticket>: the ticket's own worktrees and whatever else was put beside them. A name that
    starts with a dot is neither a ticket nor a checkout."""
    base = wt()
    found = []
    if not os.path.isdir(base):
        return found
    tickets = [ticket] if ticket else sorted(os.listdir(base))
    for name in tickets:
        folder = worktree_of(name)
        if name.startswith(".") or not os.path.isdir(folder):
            continue
        for repo in sorted(os.listdir(folder)):
            path = os.path.join(folder, repo)
            if not repo.startswith(".") and os.path.isdir(path):
                found.append(path)
    return found


def _ticket_repos(ticket: str, pack=None) -> dict:
    """{repo: the ticket's worktree of it} for the checkouts under wt/<ticket>."""
    return (
        {os.path.basename(path): path for path in list_worktrees(ticket) if os.path.exists(os.path.join(path, ".git"))}
        if ticket
        else {}
    )


def ticket_checkouts(ticket: str, pack=None) -> list:
    """The folders of a ticket (list_worktrees)."""
    return list_worktrees(ticket)


def _git_out(folder: str, *args) -> str:
    """git's output in a checkout; empty when git fails or is slow (one stuck checkout never fails the Tickets page)."""
    try:
        done = subprocess.run(["git", "-C", folder, *args], check=False, capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def worktree_status(ticket: str, pack=None) -> list:
    """Each checkout of a ticket: {repo, dir, branch, unpushed, dirty}. `unpushed` counts the commits no remote branch has
    (a detached checkout, a pull request read at its author's head, has nothing of ours to push); `dirty` the changed files."""
    found = []
    for repo, path in _ticket_repos(ticket, pack).items():
        branch = _git_out(path, "rev-parse", "--abbrev-ref", "HEAD")
        ahead = "0" if branch in ("", "HEAD") else _git_out(path, "rev-list", "--count", "HEAD", "--not", "--remotes")
        changed = [
            line
            for line in _git_out(path, "status", "--porcelain", "--untracked-files=all").splitlines()
            if line.strip()
        ]
        found.append(
            {
                "repo": repo,
                "dir": path,
                "branch": branch,
                "unpushed": int(ahead) if ahead.isdigit() else 0,
                "dirty": len(changed),
            }
        )
    return found


def card_checkout(ticket: str, workspace: str = "", repos=(), body: str = "") -> dict:
    """{ticket, repo} of the checkout a card works in, or {}: its workspace when that is one checkout
    (wt/<ticket>/<repo>), else the first of its repos that is checked out (its pull
    requests', then a `Repo:` line of its body), else the ticket's only checkout. The card shows that checkout's diff,
    the patch left for the human's review included."""
    if not ticket:
        return {}
    base = os.path.realpath(worktree_of(ticket))
    checkouts = _ticket_repos(ticket)
    if workspace:
        real = os.path.realpath(workspace)
        parts = os.path.relpath(real, base).split(os.sep)
        if len(parts) == 1 and parts[0] not in (".", "..") and os.path.exists(os.path.join(base, parts[0], ".git")):
            return {"ticket": ticket, "repo": parts[0]}
    import re

    named = [str(repo) for repo in repos or () if repo] + re.findall(r"(?m)^\s*Repo:\s*([A-Za-z0-9_.-]+)", body or "")
    for repo in named:
        if repo in checkouts:
            return {"ticket": ticket, "repo": repo}
    if len(checkouts) == 1:
        return {"ticket": ticket, "repo": next(iter(checkouts))}
    return {}


def repo_source(pack, name: str) -> str:
    for repo in pack["repos"]["repos"]:
        if repo["name"] == name:
            path = repo["path"]
            if not os.path.isabs(path):
                path = os.path.join(root(), path)
            return path
    raise CockpitError(f"unknown repo {name}")
