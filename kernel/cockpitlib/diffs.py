# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a push or a checkout changes, as the Inbox's diff pane shows it: the commits and the diff against the base
branch's merge-base, against origin (what a force push drops, marked replaced or lost), the pair's real change after
a rebase step, and the rebase itself. Read-only: never fetches, never pushes."""

import os
import re
import subprocess

from .errors import CockpitError

MAX_DIFF = 600_000
SHA = re.compile(r"^[0-9a-f]{7,40}$")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def git(repo_dir: str, *args, timeout: int = 30) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", repo_dir, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise CockpitError("git not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise CockpitError(f"git {args[0]} timed out") from exc
    if done.returncode != 0:
        raise CockpitError((done.stderr or done.stdout or f"git {args[0]} failed").strip()[-400:])
    return done.stdout


def _ok(repo_dir: str, *args) -> bool:
    return subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, check=False).returncode == 0


def ref_ok(value: str) -> bool:
    return bool(value) and ".." not in value and bool(REF.match(value))


def checkout_of(ticket: str, repo: str, pack=None) -> str:
    from .worktree import _checkout

    if not re.match(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+$", ticket or "") or not re.match(
        r"^[a-z0-9._-]+$", repo or ""
    ):
        raise CockpitError("bad ticket or repo")
    return _checkout(ticket, repo, pack)


def last_fetch(repo_dir: str):
    try:
        common = git(repo_dir, "rev-parse", "--git-common-dir").strip()
        if not os.path.isabs(common):
            common = os.path.join(repo_dir, common)
        import datetime

        return (
            datetime.datetime.fromtimestamp(os.stat(os.path.join(common, "FETCH_HEAD")).st_mtime)
            .astimezone()
            .isoformat(timespec="minutes")
        )
    except (CockpitError, OSError):
        return None


MODES = ("base", "origin", "change", "rebase")


def mode_of(mode: str) -> str:
    """The mode a diff is asked in, checked: one of MODES."""
    if mode not in MODES:
        raise CockpitError(f"a diff is asked as one of {', '.join(MODES)}, not {str(mode)[:40]!r}")
    return mode


def held_suffix(pack) -> str:
    """The suffix that comes off a branch name of a repo that names no branch_suffix_when_held: the pack's
    desktop.diff_held_suffix, none for a pack that names none."""
    given = ((pack or {}).get("desktop") or {}).get("diff_held_suffix")
    return "" if given is None else str(given)


def remote_branch_of(local_branch: str, publish_as: str = "", pack=None, repo: str = "") -> str:
    """The remote branch a checkout's branch is compared with: the name it publishes as when the intent gives one, else
    the branch without the repo's held-branch suffix (git_push.publish_name), else, for a repo that names no suffix,
    without the pack's desktop.diff_held_suffix."""
    if publish_as:
        return publish_as
    if pack is not None and repo:
        from .git_push import publish_name, repo_entry

        try:
            named = repo_entry(pack, repo).get("branch_suffix_when_held")
        except CockpitError:  # a repo the pack does not list has no suffix of its own
            named = ""
        if named:
            return publish_name(pack, repo, local_branch)
    suffix = held_suffix(pack)
    return local_branch[: -len(suffix)] if suffix and local_branch.endswith(suffix) else local_branch


def _cut(out: dict) -> dict:
    for key in ("diff", "uncommitted_diff"):
        if len(out.get(key) or "") > MAX_DIFF:
            out[key] = out[key][:MAX_DIFF] + f"\n\n… truncated at {MAX_DIFF} bytes; open the IDE for the rest\n"
    return out


def _uncommitted(repo_dir: str, out: dict) -> dict:
    out["uncommitted_status"] = git(repo_dir, "status", "--porcelain", "--untracked-files=all").strip()
    out["uncommitted_diff"] = git(repo_dir, "diff", "--no-color", "HEAD", timeout=60)
    return out


def diff_payload(repo_dir: str, base_ref: str, head_ref: str, include_uncommitted: bool) -> dict:
    """The checkout against the base: merge-base..head, its commits, stat and diff."""
    try:
        base = git(repo_dir, "merge-base", base_ref, head_ref).strip()
    except CockpitError:
        base = base_ref
    rng = f"{base}..{head_ref}"
    out = {
        "repo_dir": repo_dir,
        "base": base_ref,
        "merge_base": base[:12],
        "head": head_ref,
        "range": rng,
        "commits": git(repo_dir, "log", "--no-decorate", "--format=%h %s (%an, %ar)", rng).strip().splitlines(),
        "stat": git(repo_dir, "diff", "--stat=120", rng).strip(),
        "diff": git(repo_dir, "diff", "--no-color", "--find-renames", rng, timeout=60),
    }
    if include_uncommitted:
        _uncommitted(repo_dir, out)
    return _cut(out)


def _patch_ids(repo_dir: str, rng: str) -> list:
    """(patch-id, commit) for every commit in the range, oldest first."""
    out = []
    revs = subprocess.run(
        ["git", "-C", repo_dir, "rev-list", "--reverse", rng, "--"], capture_output=True, text=True, check=False
    ).stdout.split()
    for commit in revs:
        shown = subprocess.run(
            ["git", "-C", repo_dir, "show", "--no-color", "--format=", commit],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        pid = subprocess.run(
            ["git", "patch-id", "--stable"], input=shown, capture_output=True, text=True, check=False
        ).stdout.split()
        if pid:
            out.append((pid[0], commit))
    return out


def dropped_classified(repo_dir: str, remote_ref: str, local_ref: str) -> list:
    """Commits on origin that the push removes: replaced when a local commit carries the same patch, rewritten when a
    local commit has the same subject with other content (a squash), lost when nothing local carries it."""
    local = _patch_ids(repo_dir, f"{remote_ref}..{local_ref}")
    local_pids = {pid for pid, _sha in local}
    local_subjects = {git(repo_dir, "log", "-1", "--format=%s", sha).strip() for _pid, sha in local}
    out = []
    for pid, sha in _patch_ids(repo_dir, f"{local_ref}..{remote_ref}"):
        line = git(repo_dir, "log", "-1", "--no-decorate", "--format=%h %s (%an, %ar)", sha).strip()
        subject = git(repo_dir, "log", "-1", "--format=%s", sha).strip()
        state = "replaced" if pid in local_pids else ("rewritten" if subject in local_subjects else "lost")
        out.append({"line": line, "replaced": state == "replaced", "state": state})
    return out


def origin_diff_payload(
    repo_dir: str, local_ref: str, remote_branch: str, base_ref: str, include_uncommitted: bool
) -> dict:
    """What a (force) push of local_ref to origin/<remote_branch> changes: the commits only local (added), the commits
    only on origin (dropped), the diff origin..local, from the remote-tracking ref as last fetched."""
    remote_ref = f"origin/{remote_branch}"
    exists = _ok(repo_dir, "rev-parse", "--verify", "-q", remote_ref + "^{commit}")
    out = {
        "repo_dir": repo_dir,
        "mode": "origin",
        "head": local_ref,
        "remote": remote_ref,
        "remote_exists": exists,
        "last_fetch": last_fetch(repo_dir),
    }
    if not exists:
        out.update(
            range=f"(new branch) ..{local_ref}",
            commits=[],
            commits_base=[],
            dropped=[],
            stat="",
            diff="",
            fast_forward=True,
            note=f"{remote_ref} is not known locally: either the branch is not on origin yet (everything local is new) or it was never fetched. Fetch to compare.",
        )
    else:
        rng = f"{remote_ref}..{local_ref}"
        own = set(git(repo_dir, "rev-list", rng, "--not", base_ref).split())
        added = git(repo_dir, "log", "--no-decorate", "--format=%H %h %s (%an, %ar)", rng).strip().splitlines()
        out.update(
            range=rng,
            commits=[line.split(" ", 1)[1] for line in added if line.split(" ", 1)[0] in own],
            commits_base=[line.split(" ", 1)[1] for line in added if line.split(" ", 1)[0] not in own],
            dropped=dropped_classified(repo_dir, remote_ref, local_ref),
            stat=git(repo_dir, "diff", "--stat=120", rng).strip(),
            diff=git(repo_dir, "diff", "--no-color", "--find-renames", rng, timeout=60),
            fast_forward=_ok(repo_dir, "merge-base", "--is-ancestor", remote_ref, local_ref),
        )
    if include_uncommitted:
        _uncommitted(repo_dir, out)
    return _cut(out)


def _base_name(pack, repo: str) -> str:
    from .git_push import repo_branch

    return repo_branch(pack, repo)


def _base_ref(pack, folder: str, repo: str = ""):
    """origin/<the repo's base> when the checkout knows it, else the local base branch, else None (a checkout with no
    history to compare against)."""
    name = _base_name(pack, repo)
    for ref in (f"origin/{name}", name):
        if _ok(folder, "rev-parse", "--verify", "-q", ref + "^{commit}"):
            return ref
    return None


def _bare(folder: str, ticket: str, repo: str, note: str) -> dict:
    return {
        "repo_dir": folder,
        "ticket": ticket,
        "repo": repo,
        "base": "",
        "merge_base": "",
        "head": "",
        "range": "",
        "commits": [],
        "stat": "",
        "diff": "",
        "dropped": [],
        "uncommitted_status": "",
        "uncommitted_diff": "",
        "note": note,
    }


def intent_diff(pack, row: dict, rows: list, mode: str = "base") -> dict:
    """The diff pane of one intent: a push's base..sha (base), what it
    changes on origin (origin), the pair's real change after its rebase step (change), or the rebase itself (rebase)."""
    payload = row.get("payload") or {}
    ticket = row.get("ticket") or ""
    # A forge intent (a CI rerun, a PR edit) names the repo as the forge does, owner/name; the checkout is the name.
    repo = str(payload.get("repo") or "").rstrip("/").rsplit("/", 1)[-1]
    if not repo:
        raise CockpitError(f"{row.get('type')} intents have no repo to diff")
    try:
        folder = checkout_of(ticket, repo)
    except CockpitError:
        # No worktree for the ticket (a release card works in the repo's own checkout): an intent that names its
        # commit can be read in any clone that has it.
        sha_named = SHA.match(str(payload.get("sha") or ""))
        try:
            from .worktree import repo_source

            source = repo_source(pack, repo) if sha_named else ""
        except (CockpitError, KeyError, TypeError):
            source = ""
        if not (source and os.path.isdir(source) and _ok(source, "cat-file", "-e", f"{payload['sha']}^{{commit}}")):
            raise
        folder = source
    base_ref = _base_ref(pack, folder, repo)
    if base_ref is None or not _ok(folder, "rev-parse", "--verify", "-q", "HEAD^{commit}"):
        return {
            **_bare(
                folder, ticket, repo, f"the checkout at {folder} has no {_base_name(pack, repo)} to compare against yet"
            ),
            "intent": row.get("id"),
            "mode": mode,
        }
    # the commit the intent is about: what a push sends, what a patch applies, the head a CI run is rerun on
    sha = (
        payload.get("sha")
        if row.get("type") in ("push-branch", "pr-patch-apply", "ci-rerun") and SHA.match(str(payload.get("sha") or ""))
        else ""
    )
    local = sha or "HEAD"
    if mode in ("origin", "change", "rebase"):
        branch = payload.get("branch") or git(folder, "rev-parse", "--abbrev-ref", "HEAD").strip()
        step1 = None
        if payload.get("after"):
            previous = next((item for item in rows if item.get("id") == payload["after"]), None)
            step1 = (previous or {}).get("payload") or None
        if mode == "change" and step1 and SHA.match(str(step1.get("sha") or "")):
            tip = step1["sha"]
            base_after = (
                step1.get("base_after")
                if SHA.match(str(step1.get("base_after") or ""))
                else git(folder, "merge-base", base_ref, local).strip()
            )
            out = {
                "repo_dir": folder,
                "ticket": ticket,
                "repo": repo,
                "intent": row.get("id"),
                "mode": "change",
                "base": tip,
                "merge_base": tip[:12],
                "head": local,
                "remote": f"rebase step {payload['after']} @ {tip[:9]}",
                "remote_exists": True,
                "fast_forward": True,
                "dropped": [],
                "commits_base": [],
                "last_fetch": None,
                "range": f"{tip[:9]} → {local[:9]} (tree diff after the rebase step)",
                "commits": git(folder, "log", "--no-decorate", "--format=%h %s (%an, %ar)", f"{base_after}..{local}")
                .strip()
                .splitlines(),
                "stat": git(folder, "diff", "--stat=120", tip, local).strip(),
                "diff": git(folder, "diff", "--no-color", "--find-renames", tip, local, timeout=60),
            }
            _uncommitted(folder, out)
            try:
                out["range_diff"] = git(
                    folder, "range-diff", "--no-color", f"{base_after}..{tip}", f"{base_after}..{local}", timeout=60
                )[:20000]
            except CockpitError as exc:
                out["range_diff"] = f"(range-diff failed: {exc})"
            return _cut(out)
        if mode == "rebase":
            tip = (
                step1["sha"]
                if step1 and SHA.match(str(step1.get("sha") or ""))
                else (local if payload.get("rebase_only") else None)
            )
            if not tip:
                raise CockpitError("no rebase step for this intent")
            source = step1 if step1 else payload
            out = origin_diff_payload(
                folder,
                tip,
                remote_branch_of(branch, payload.get("publish_as") or "", pack, repo),
                base_ref,
                include_uncommitted=False,
            )
            out.update(ticket=ticket, repo=repo, intent=row.get("id"), mode="rebase")
            if SHA.match(str(source.get("base_before") or "")) and SHA.match(str(source.get("base_after") or "")):
                remote_sha = source.get("remote_sha") if SHA.match(str(source.get("remote_sha") or "")) else ""
                out["rebase"] = {
                    "proof": source.get("rebase_proof", ""),
                    "base_before": source["base_before"][:9],
                    "base_after": source["base_after"][:9],
                    "commits": source.get("rebase_commits"),
                    "step": payload.get("after") or row.get("id"),
                    "range_diff": (
                        _safe(
                            lambda: git(
                                folder,
                                "range-diff",
                                "--no-color",
                                f"{source['base_before']}..{remote_sha}",
                                f"{source['base_after']}..{tip}",
                                timeout=60,
                            )[:20000]
                        )
                        if remote_sha
                        else ""
                    ),
                    "base_log": _safe(
                        lambda: git(
                            folder,
                            "log",
                            "--no-decorate",
                            "--format=%h %s (%an)",
                            f"{source['base_before']}..{source['base_after']}",
                        ).strip()
                    ),
                }
            return out
        out = origin_diff_payload(
            folder,
            local,
            remote_branch_of(branch, payload.get("publish_as") or "", pack, repo),
            base_ref,
            include_uncommitted=True,
        )
        out.update(ticket=ticket, repo=repo, intent=row.get("id"))
        if (
            payload.get("rebase_only")
            and SHA.match(str(payload.get("base_before") or ""))
            and SHA.match(str(payload.get("base_after") or ""))
        ):
            old_tip = payload.get("remote_sha") if SHA.match(str(payload.get("remote_sha") or "")) else ""
            out["rebase"] = {
                "proof": payload.get("rebase_proof", ""),
                "base_before": payload["base_before"][:9],
                "base_after": payload["base_after"][:9],
                "commits": payload.get("rebase_commits"),
                "range_diff": _safe(
                    lambda: git(
                        folder,
                        "range-diff",
                        "--no-color",
                        f"{payload['base_before']}..{old_tip}",
                        f"{payload['base_after']}..{local}",
                        timeout=60,
                    )[:20000]
                )
                if old_tip
                else "",
                "base_log": _safe(
                    lambda: git(
                        folder,
                        "log",
                        "--no-decorate",
                        "--format=%h %s (%an)",
                        f"{payload['base_before']}..{payload['base_after']}",
                    ).strip()
                ),
            }
        return out
    if sha:
        base = payload.get("base") if ref_ok(str(payload.get("base") or "")) else base_ref
        out = diff_payload(folder, base, sha, include_uncommitted=True)
    else:
        out = diff_payload(folder, base_ref, "HEAD", include_uncommitted=True)
    out.update(ticket=ticket, repo=repo, intent=row.get("id"))
    return out


def checkout_diff(pack, ticket: str, repo: str, mode: str = "base") -> dict:
    """The diff pane of a ticket checkout: against the base (base), or against origin (origin)."""
    folder = checkout_of(ticket, repo)
    base_ref = _base_ref(pack, folder, repo)
    if base_ref is None or not _ok(folder, "rev-parse", "--verify", "-q", "HEAD^{commit}"):
        return _bare(
            folder, ticket, repo, f"the checkout at {folder} has no {_base_name(pack, repo)} to compare against yet"
        )
    if mode == "origin":
        branch = git(folder, "rev-parse", "--abbrev-ref", "HEAD").strip()
        out = origin_diff_payload(
            folder, "HEAD", remote_branch_of(branch, "", pack, repo), base_ref, include_uncommitted=True
        )
    else:
        out = diff_payload(folder, base_ref, "HEAD", include_uncommitted=True)
    out.update(ticket=ticket, repo=repo)
    return out


def _safe(call):
    try:
        return call()
    except CockpitError as exc:
        return f"(git failed: {exc})"
