# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The git side of a push intent: what a push would send (probed when the intent is written), and the push itself.

A push leaves from the repo's main checkout, as the human: a lane's worktree cannot push. It fast-forwards, or
pushes with --force-with-lease on the remote tip recorded when the intent was written, then reads the remote back.
A rebase-only push re-applies the same patches on a new base; its proof compares patch-ids.
"""

import re
import subprocess

from .errors import CockpitError

REMOTE = "origin"
FIXUP = re.compile(r"^(fixup|squash|amend)! ")


def _git(folder, *args, check=True) -> str:
    done = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, check=False)
    if check and done.returncode != 0:
        raise CockpitError(f"git {' '.join(args[:3])}: {(done.stderr or done.stdout).strip()[-300:]}")
    return (done.stdout or "").strip() if done.returncode == 0 else ""


def repo_entry(pack, name: str) -> dict:
    for repo in (pack.get("repos") or {}).get("repos") or []:
        if repo.get("name") == name:
            return repo
    raise CockpitError(f"unknown repo {name}")


def source(pack, name: str) -> str:
    from .worktree import repo_source

    return repo_source(pack, name)


def checkout(pack, ticket: str, name: str) -> str:
    """The ticket's checkout of the repo, else the repo's main checkout."""
    from .worktree import _checkout

    try:
        return _checkout(ticket, name, pack)
    except CockpitError:
        return source(pack, name)


def base_ref(pack, name: str) -> str:
    branch = repo_entry(pack, name).get("base") or pack.get("base_branch") or "main"
    return f"{REMOTE}/{branch}"


def repo_branch(pack, name: str) -> str:
    """The branch a repo's work starts from and its PRs target: its repos.yaml base, else the pack's base_branch."""
    try:
        entry = repo_entry(pack, name)
    except CockpitError:
        entry = {}
    return entry.get("base") or (pack or {}).get("base_branch") or "main"


def protected(pack, name: str) -> set:
    """The branches of a repo only the human writes: the pack's protected branches, the repo's base, the pack's base
    and the workspace branch."""
    pack = pack or {}
    found = set(pack.get("protected_branches") or ())
    found |= {repo_branch(pack, name), pack.get("base_branch"), pack.get("workspace_branch")}
    return found - {None, ""}


def publish_name(pack, name: str, branch: str) -> str:
    """The remote branch a local branch publishes as: the repo's held-branch suffix comes off."""
    suffix = repo_entry(pack, name).get("branch_suffix_when_held") or ""
    if suffix and branch.endswith(suffix):
        return branch[: -len(suffix)]
    return branch


def remote_url(folder: str) -> str:
    """The remote's real address. A checkout a lane works in has its push address disabled; the human's push uses this."""
    url = _git(folder, "config", "--get", f"remote.{REMOTE}.url", check=False)
    if not url:
        raise CockpitError(f"{folder} has no {REMOTE} remote")
    return url


def remote_tip(folder: str, branch: str) -> str:
    done = subprocess.run(
        ["git", "-C", folder, "ls-remote", "--heads", REMOTE, branch],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        raise CockpitError(f"git ls-remote {REMOTE} {branch}: {(done.stderr or '').strip()[-200:]}")
    words = (done.stdout or "").split()
    return words[0] if words else ""


def _range(folder, base, sha) -> list:
    """[(sha, author email, subject)] of base..sha, oldest first."""
    text = _git(folder, "log", "--reverse", "--format=%H%x09%ae%x09%s", f"{base}..{sha}", check=False)
    rows = []
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append(tuple(parts))
    return rows


class WorktreeMismatch(CockpitError):
    """The intent's branch or sha is not what the ticket's worktree holds: `outbox new` refuses it, because `verify`
    and `push` would. A different thing from git being unreadable, which the intent records as `probe_error`."""


def _worktree_facts(pack, ticket: str, repo: str, branch: str):
    """(branch, sha) from the ticket's own worktree when it has one, is on the intent's branch (or none was given)
    and no --sha was given, else (branch, ""): the caller then falls back to the repo's primary ref exactly as before. `verify` compares an intent's sha with the
    worktree HEAD, so an intent filed from the primary ref could never pass it. The checks here refuse early what
    `verify`/`push` would refuse later, so no new intent is rejected."""
    from .worktree import _checkout

    try:
        wt = _checkout(ticket, repo, pack)
    except CockpitError:
        return branch, ""
    head = _git(wt, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False)
    if not re.fullmatch(r"[0-9a-f]{40}", head or ""):
        return branch, ""
    on = _git(wt, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    if not on or (branch and branch != on):
        return branch, ""  # a different or absent worktree branch: exactly the old path
    branch = on
    tip = _git(source(pack, repo), "rev-parse", "--verify", f"refs/heads/{branch}", check=False)
    if not tip:
        return branch, ""
    if tip != head:
        raise WorktreeMismatch(
            f"branch {branch} is at {tip[:10]} but the ticket worktree is at {head[:10]}: check the worktree out at "
            f"{tip[:10]}, or move {branch} to {head[:10]}, then file again"
        )
    return branch, head


def probe(pack, ticket: str, payload: dict) -> dict:
    """Fill a push intent's facts: the full sha, the base, the commits and files it sends, and the remote tip now (the
    lease). Commits by someone other than this checkout's author are named in `foreign`."""
    repo = payload["repo"]
    folder = checkout(pack, ticket, repo)
    branch = payload.get("branch") or ""
    if not payload.get("sha"):
        branch, wt_sha = _worktree_facts(pack, ticket, repo, branch)
        if wt_sha:
            payload["branch"] = branch
            payload["sha"] = wt_sha
    sha = (
        payload.get("sha")
        or _git(source(pack, repo), "rev-parse", "--verify", f"refs/heads/{branch}", check=False)
        or _git(folder, "rev-parse", "HEAD")
    )
    full = _git(folder, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}", check=False)
    if not re.fullmatch(r"[0-9a-f]{40}", full or ""):
        raise CockpitError(f"--sha {sha} is not a commit of {folder}")
    payload["sha"] = full
    payload.setdefault("publish_as", publish_name(pack, repo, branch))
    base = payload.get("base") or base_ref(pack, repo)
    if _git(folder, "rev-parse", "--verify", "-q", base, check=False):
        payload["base"] = base
        rows = _range(folder, base, full)
        payload["commits"] = [f"{commit[:9]} {subject}" for commit, _email, subject in rows]
        payload["diffstat"] = _git(folder, "diff", "--shortstat", f"{base}...{full}", check=False)
        payload["files"] = [
            line for line in _git(folder, "diff", "--name-only", f"{base}...{full}", check=False).splitlines() if line
        ]
        me = _git(folder, "config", "user.email", check=False)
        mine = {me, *(((pack or {}).get("forge") or {}).get("human_emails") or [])}
        payload["foreign"] = sorted({email for _commit, email, _subject in rows if me and email not in mine})
        payload["fixups"] = [f"{commit[:9]} {subject}" for commit, _email, subject in rows if FIXUP.match(subject)]
    payload["remote_sha"] = remote_tip(source(pack, repo), payload["publish_as"])
    return payload


def _patch_ids(folder, rng) -> list:
    found = []
    for commit in _git(folder, "rev-list", "--reverse", rng, check=False).splitlines():
        shown = subprocess.run(
            ["git", "-C", folder, "show", "--no-color", "--format=", commit], capture_output=True, check=False
        )
        pid = subprocess.run(["git", "patch-id", "--stable"], input=shown.stdout, capture_output=True, check=False)
        words = pid.stdout.decode("utf-8", "replace").split()
        found.append(words[0] if words else "")
    return found


def rebase_proof(folder: str, payload: dict) -> str:
    """A rebase-only push changes nothing but the base: the patches on the remote and on the branch must be the same."""
    old = payload.get("remote_sha") or ""
    if not old:
        raise CockpitError("rebase-only: the remote has no such branch, so there is nothing to rebase")
    base = payload.get("base") or ""
    before = _git(folder, "merge-base", base, old)
    after = _git(folder, "merge-base", base, payload["sha"])
    if before == after:
        raise CockpitError("rebase-only: the base did not move, so this is not a rebase")
    old_ids, new_ids = _patch_ids(folder, f"{before}..{old}"), _patch_ids(folder, f"{after}..{payload['sha']}")
    if old_ids != new_ids:
        raise CockpitError(
            f"rebase-only: the patches differ ({len(old_ids)} on the remote, {len(new_ids)} on the branch); "
            "put content changes in a second push after this one"
        )
    payload["base_before"], payload["base_after"] = before, after
    return f"rebase of {len(new_ids)} commit(s) from {before[:9]} to {after[:9]}; patches identical"


def push(pack, intent: dict, dry_run: bool = False) -> str:
    """Send the branch from the repo's main checkout and read the remote back."""
    payload = intent["payload"]
    repo = source(pack, payload["repo"])
    target = payload.get("publish_as") or payload["branch"]
    head = _git(repo, "rev-parse", "--verify", f"refs/heads/{payload['branch']}", check=False)
    if not head:
        raise CockpitError(f"no branch {payload['branch']} in {repo}")
    if head != payload.get("sha"):
        raise CockpitError(
            f"branch {payload['branch']} is at {head[:10]}, not the intent's {str(payload.get('sha'))[:10]}: amend the intent"
        )
    base = payload.get("base") or base_ref(pack, payload["repo"])
    fixups = [subject for _commit, _email, subject in _range(repo, base, head) if FIXUP.match(subject)]
    if fixups:
        raise CockpitError(f"unsquashed fixups: {fixups[:3]}; autosquash the branch and amend the intent")
    url = remote_url(repo)
    tip = remote_tip(repo, target)
    if payload.get("rebase_only"):
        rebase_proof(repo, {**payload, "remote_sha": tip, "base": base})
    if tip == head:
        return "already on the remote (nothing pushed)"
    if (
        not tip
        or subprocess.run(
            ["git", "-C", repo, "merge-base", "--is-ancestor", tip, head], check=False, capture_output=True
        ).returncode
        == 0
    ):
        argv, how = ["git", "-C", repo, "push", url, f"{head}:refs/heads/{target}"], "fast-forward"
    else:
        lease = payload.get("remote_sha")
        if lease is None:
            raise CockpitError(
                f"{REMOTE}/{target} is not an ancestor of {head[:10]} and the intent has no lease: amend it after rebasing"
            )
        if lease != tip:
            raise CockpitError(
                f"{REMOTE}/{target} moved since the intent was written ({lease[:10] or 'absent'} → {tip[:10]}): rebase and amend"
            )
        argv, how = (
            [
                "git",
                "-C",
                repo,
                "push",
                f"--force-with-lease=refs/heads/{target}:{lease}",
                url,
                f"{head}:refs/heads/{target}",
            ],
            f"force-with-lease on {lease[:10]}",
        )
    if dry_run:
        return f"would push ({how}): {REMOTE} {argv[-1]}"
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        text = (done.stderr or done.stdout or "").strip()
        said = [line[7:].strip() for line in text.splitlines() if line.startswith("remote:") and line[7:].strip()]
        detail = "; ".join(said) or (text.splitlines()[-1] if text else "the remote said no")
        raise CockpitError(f"push refused: {detail}")
    after = remote_tip(repo, target)
    if after != head:
        raise CockpitError(f"read-back: {REMOTE}/{target} is {after[:10] or 'absent'} after the push, not {head[:10]}")
    return f"{how}; {REMOTE}/{target} = {head[:10]}"
