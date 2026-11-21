# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Moving this installation to another repository: the checkout follows a new `origin` and not one working file changes.

It only happens when the new repository's branch has the very tree that is installed (the two tree hashes are compared and
printed), so the code on disk is already the code over there, whatever the two histories look like. The move itself is
made of refs and configuration alone: remotes are renamed, a branch ref is written and HEAD is pointed at it. No command
that writes a working file or the index is run, and afterwards git's status and every tracked file's time, size and mode
are compared with what they were. The old repository stays as the remote `previous`, with pushing switched off, and is
the way back: `undo` restores the branch, the remotes and the records for as long as no update was applied since.

Each step is checked before the next, and a step that fails takes back every step before it."""

import json
import os
import re
import time

from .errors import CockpitError
from .self_update import _git, _out, _read_check, _root, _write_check

# fmt: off
INCOMING = "rehome-incoming"   # the new remote's name until the trees are known to be equal
PREVIOUS = "previous"          # the old origin afterwards: its refs are the rollback
DISABLED = "DISABLED"          # the old origin's push URL: no URL, so nothing is pushed there by accident
NOTE = "cockpit.rehome"        # the checkout's own git config: what `undo` needs, kept where no working file is
# fmt: on
CREDENTIALS = re.compile(r"^[a-z][a-z0-9+.-]*://[^/@]*:[^/@]*@", re.IGNORECASE)


class _Moves:
    """The steps taken so far, each with what takes it back: a failure takes them all back, the last one first."""

    def __init__(self):
        self.back = []

    def did(self, back) -> None:
        self.back.append(back)

    def undo(self) -> list:
        failed = []
        for back in reversed(self.back):
            try:
                back()
            except CockpitError as exc:
                failed.append(str(exc))
        self.back = []
        return failed


def _checkout(root: str) -> dict:
    """{head, branch, tree, status}: the checkout as it stands, refused when it has local edits or is on no branch."""
    from .self_update import status

    seen = status(root)
    if seen.get("error"):
        raise CockpitError(seen["error"])
    if seen["dirty"]:
        raise CockpitError(
            "the plugin checkout has local changes: commit or stash them before moving it to another repository"
        )
    branch = _out(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise CockpitError(
            "the plugin checkout is on no branch: put it on one first (git switch -c installed), which changes no file"
        )
    return {
        "head": seen["installed"]["sha"],
        "branch": branch,
        "tree": _out(root, "rev-parse", "HEAD^{tree}"),
        "status": _out(root, "status", "--porcelain"),
    }


def _stamps(root: str) -> dict:
    """Every tracked file's time, size and mode as the disk has them now; None for one that is not there."""
    found = {}
    for name in _out(root, "ls-files", "-z").split("\0"):
        if name:
            try:
                seen = os.lstat(os.path.join(root, name))
                found[name] = (seen.st_mtime_ns, seen.st_size, seen.st_mode)
            except OSError:
                found[name] = None
    return found


def _untouched(root: str, was: dict, stamps: dict) -> int:
    """The proof after the move: the same tree is checked out, git's status reads as it did, and no tracked file's
    time, size or mode differs. The number of files compared; a difference raises."""
    if _out(root, "rev-parse", "HEAD^{tree}") != was["tree"]:
        raise CockpitError("the checked-out tree is not the one that was installed")
    if _out(root, "status", "--porcelain") != was["status"]:
        raise CockpitError("git's status of the working files is not what it was")
    now = _stamps(root)
    differs = sorted(name for name in set(now) | set(stamps) if now.get(name) != stamps.get(name))
    if differs:
        raise CockpitError("working files changed: " + ", ".join(differs[:5]))
    return len(now)


def _remotes(root: str) -> list:
    return _out(root, "remote").split()


def _default_branch(root: str, url: str) -> str:
    """The branch the repository at that URL names as its HEAD."""
    done = _git(root, "ls-remote", "--symref", "--", url, "HEAD")
    if done.returncode != 0:
        raise CockpitError(
            f"{url} did not answer: " + (done.stderr or done.stdout or "ls-remote failed").strip()[-200:]
        )
    for line in done.stdout.splitlines():
        if line.startswith("ref: refs/heads/"):
            return line.split()[1][len("refs/heads/") :]
    raise CockpitError(f"{url} names no default branch: say which one, e.g. cockpit update rehome {url} --branch main")


def _worktree_on(root: str, branch: str) -> str:
    """The linked worktree of this checkout that has that branch checked out, if one does: its branch cannot be moved
    from here without changing what that worktree means."""
    here = os.path.realpath(_out(root, "rev-parse", "--show-toplevel"))
    path = ""
    for line in _out(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
        elif line == f"branch refs/heads/{branch}" and os.path.realpath(path) != here:
            return path
    return ""


def _config(root: str, key: str) -> str:
    done = _git(root, "config", "--get", key)
    return done.stdout.strip() if done.returncode == 0 else ""


def _set_config(root: str, key: str, value: str) -> None:
    """That key of the checkout's own git config at that value; an empty value removes the key."""
    if value:
        _out(root, "config", key, value)
    else:
        _git(root, "config", "--unset-all", key)


def _hermes(op: dict, what: str) -> dict:
    """One op of the plugins helper, in Hermes's own environment. A helper that fails or answers an error raises."""
    from .hermes_runtime import run_helper

    try:
        results = run_helper("plugins", {"ops": [op]}).get("results") or []
    except Exception as exc:  # noqa: BLE001 - whatever stopped the helper, the record was not written: the move is refused
        raise CockpitError(f"Hermes's install record was not {what}: {str(exc)[:200]}") from exc
    first = results[0] if results else None
    if not isinstance(first, dict) or first.get("error"):
        raise CockpitError(
            f"Hermes's install record was not {what}: {(first or {}).get('error') if isinstance(first, dict) else 'no answer'}"
        )
    return first


def _launcher(root: str) -> str:
    from .after_update import launcher

    return launcher("cockpit", root)


def rehome(url: str, branch: str = "", dry_run: bool = False, root: str = "", now=None) -> dict:
    """Make the repository at that URL this checkout's origin, on its default branch or the one named. Refused unless
    that branch's tree is the installed tree; with dry_run the comparison is made and reported and nothing is kept."""
    root = _root(root)
    url = str(url or "").strip()
    if not url or url.startswith("-"):
        raise CockpitError("which repository? e.g. cockpit update rehome https://example.test/team/cockpit.git")
    if CREDENTIALS.match(url):
        raise CockpitError(
            "the URL carries a password: give it without one (git's credential helper keeps secrets, a remote's URL is plain text)"
        )
    was = _checkout(root)
    remotes = _remotes(root)
    if "origin" not in remotes:
        raise CockpitError("the plugin checkout has no remote named origin: there is nothing to move from")
    for name, why in (
        (PREVIOUS, "an earlier move left it as the way back: remove it when that way back is no longer wanted"),
        (INCOMING, "a move that was interrupted left it"),
    ):
        if name in remotes:
            raise CockpitError(f"a remote named {name} exists ({why}): git -C {root} remote remove {name}")
    old_url = _out(root, "remote", "get-url", "origin")
    if old_url == url:
        raise CockpitError(f"origin is {url} already")
    branch = str(branch or "").strip() or _default_branch(root, url)
    if branch.startswith("-") or _git(root, "check-ref-format", "--branch", branch).returncode != 0:
        raise CockpitError(f"{branch} is no branch name, e.g. cockpit update rehome {url} --branch main")
    held = _worktree_on(root, branch)
    if held:
        raise CockpitError(
            f"the worktree {held} has the branch {branch} checked out: remove that worktree or put it on another branch first"
        )
    moves = _Moves()
    try:
        _out(root, "remote", "add", "--", INCOMING, url)
        moves.did(lambda: _out(root, "remote", "remove", INCOMING))
        fetched = _git(
            root, "fetch", "-q", "--no-tags", INCOMING, f"+refs/heads/{branch}:refs/remotes/{INCOMING}/{branch}"
        )
        if fetched.returncode != 0:
            raise CockpitError(
                f"the branch {branch} of {url} could not be fetched: "
                + (fetched.stderr or fetched.stdout or "").strip()[-200:]
            )
        commit = _out(root, "rev-parse", f"refs/remotes/{INCOMING}/{branch}^{{commit}}")
        theirs = _out(root, "rev-parse", f"{commit}^{{tree}}")
        found = {
            "ok": True,
            "dry_run": dry_run,
            "changed": False,
            "from": {"url": old_url, "branch": was["branch"], "commit": was["head"], "tree": was["tree"]},
            "to": {"url": url, "branch": branch, "commit": commit, "tree": theirs},
        }
        if theirs != was["tree"]:
            raise CockpitError(
                f"refused: the tree of {branch} at {url} ({commit[:7]}) is {theirs} and the installed tree ({was['head'][:7]}) "
                f"is {was['tree']}. They must be equal: update to the commit that repository was made from first"
            )
        if dry_run:
            moves.undo()
            found["out"] = (
                f"the trees are equal ({theirs}): `cockpit update rehome {url} --branch {branch}` would make it origin "
                "and change no working file; nothing was changed now"
            )
            return found
        stamps = _stamps(root)
        prior = _read_check()
        ref = f"refs/heads/{branch}"
        moment = time.time() if now is None else now
        note = {
            "url": old_url,
            "branch": was["branch"],
            "commit": was["head"],
            "to_url": url,
            "to_branch": branch,
            "to": commit,
            "branch_was": _git(root, "rev-parse", "--verify", "--quiet", ref).stdout.strip(),
            "upstream_was": [_config(root, f"branch.{branch}.remote"), _config(root, f"branch.{branch}.merge")],
            "pushurl": _config(root, "remote.origin.pushurl"),
            "record": prior,
            "at": moment,
        }
        _out(root, "config", NOTE, json.dumps(note))
        moves.did(lambda: _set_config(root, NOTE, ""))
        # the remotes: the old one keeps its refs under its new name, and the new one takes the name every command reads
        _out(root, "remote", "rename", "origin", PREVIOUS)
        moves.did(lambda: _out(root, "remote", "rename", PREVIOUS, "origin"))
        _out(root, "remote", "rename", INCOMING, "origin")
        moves.did(lambda: _out(root, "remote", "rename", "origin", INCOMING))
        if _out(root, "remote", "get-url", "origin") != url or _out(root, "remote", "get-url", PREVIOUS) != old_url:
            raise CockpitError("the remotes are not as they were set")
        if (
            _git(root, "remote", "set-head", "origin", "-a").returncode != 0
        ):  # its HEAD may be a branch that was not fetched
            _out(root, "remote", "set-head", "origin", branch)
        # the branch: refs only. The trees are equal, so the index and every working file already are what it holds
        _out(root, "update-ref", "-m", f"rehome: {url}", ref, commit)
        moves.did(
            lambda: (
                _out(root, "update-ref", ref, note["branch_was"])
                if note["branch_was"]
                else _out(root, "update-ref", "-d", ref)
            )
        )
        _out(root, "symbolic-ref", "-m", f"rehome: {url}", "HEAD", ref)
        moves.did(lambda: _out(root, "symbolic-ref", "HEAD", f"refs/heads/{was['branch']}"))
        if _out(root, "rev-parse", "HEAD") != commit:
            raise CockpitError("the checkout is not at the fetched commit")
        upstream = [_config(root, f"branch.{branch}.remote"), _config(root, f"branch.{branch}.merge")]
        _out(root, "branch", "-q", f"--set-upstream-to=origin/{branch}", branch)
        moves.did(
            lambda: [
                _set_config(root, f"branch.{branch}.{key}", value) for key, value in zip(("remote", "merge"), upstream)
            ]
        )
        _out(root, "remote", "set-url", "--push", PREVIOUS, DISABLED)
        moves.did(lambda: _set_config(root, f"remote.{PREVIOUS}.pushurl", note["pushurl"]))
        name = os.path.basename(root)
        found["hermes_record"] = _hermes({"op": "rehome", "name": name, "source": url, "revision": commit}, "updated")
        moves.did(lambda: _hermes({"op": "restore_record", "name": name}, "restored"))
        _write_check(
            {
                "local": commit,
                "branch": branch,
                "checked_at": moment,
                "sha": commit,
                "short": commit[:7],
                "behind": 0,
                "error": "",
                "rehomed_from": {"url": old_url, "branch": was["branch"], "commit": was["head"], "at": moment},
            }
        )
        moves.did(lambda: _write_check(prior))
        found["files_compared"] = _untouched(root, was, stamps)
    except BaseException as exc:
        failed = moves.undo()
        if failed:
            raise CockpitError(f"{exc}; and taking the move back failed at: " + "; ".join(failed)) from exc
        raise
    from .after_update import after

    # no code changed, so the gateway keeps running what it runs: the line is the seats and doctor
    found.update(
        changed=True,
        undo=f"{_launcher(root)} update rehome --undo",
        next=after({"changed": True, "restart": "requested"}, root),
        out=f"origin is now {url} ({branch} at {commit[:7]}); the old origin is the remote `{PREVIOUS}`, with pushing off; "
        f"the tree is {theirs} as before and {found['files_compared']} tracked files were compared: none changed",
    )
    return found


def undo(root: str = "", now=None) -> dict:
    """Take the move back: the branch, the remotes, Hermes's record and the update record as they were. Only while the
    checkout is still at the commit the move left it at: an update applied since came from the new repository."""
    root = _root(root)
    try:
        note = json.loads(_config(root, NOTE) or "null")
    except ValueError:
        note = None
    if not isinstance(note, dict):
        raise CockpitError(
            "nothing to undo: this checkout was not moved to another repository, or the move was taken back already"
        )
    was = _checkout(root)
    if was["head"] != note["to"]:
        raise CockpitError(
            f"refused: the checkout is at {was['head'][:7]}, and the move left it at {note['to'][:7]}: an update was applied "
            f"since, so the old repository no longer has this code (its refs are still under the remote `{PREVIOUS}`)"
        )
    remotes = _remotes(root)
    if PREVIOUS not in remotes or "origin" not in remotes or INCOMING in remotes:
        raise CockpitError(
            f"refused: the remotes are not as the move left them (origin and {PREVIOUS}, and no {INCOMING})"
        )
    old, new = note["branch"], note["to_branch"]
    if _git(root, "rev-parse", "--verify", "--quiet", f"{note['commit']}^{{tree}}").stdout.strip() != was["tree"]:
        raise CockpitError(
            f"refused: the commit the move came from ({note['commit'][:7]}) is not here with the installed tree"
        )
    if (
        old != new
        and _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{old}").stdout.strip() != note["commit"]
    ):
        raise CockpitError(f"refused: the branch {old} is no longer at {note['commit'][:7]}, where the move left it")
    held = _worktree_on(root, old)
    if held:
        raise CockpitError(
            f"the worktree {held} has the branch {old} checked out: remove that worktree or put it on another branch first"
        )
    stamps = _stamps(root)
    name = os.path.basename(root)
    if old != new:
        _out(root, "symbolic-ref", "-m", "rehome: undo", "HEAD", f"refs/heads/{old}")
    if note["branch_was"]:
        _out(root, "update-ref", "-m", "rehome: undo", f"refs/heads/{new}", note["branch_was"])
    else:
        _out(root, "update-ref", "-d", f"refs/heads/{new}")
    _out(root, "remote", "rename", "origin", INCOMING)
    _out(root, "remote", "rename", PREVIOUS, "origin")
    _out(root, "remote", "remove", INCOMING)  # with its refs and the upstream of any branch that followed it
    _set_config(root, "remote.origin.pushurl", note["pushurl"])
    if note["branch_was"]:
        for key, value in zip(("remote", "merge"), note["upstream_was"]):
            _set_config(root, f"branch.{new}.{key}", value)
    hermes = _hermes({"op": "restore_record", "name": name}, "restored")
    record = (
        note["record"]
        if isinstance(note.get("record"), dict) and note["record"]
        else {
            "local": note["commit"],
            "branch": old,
            "checked_at": time.time() if now is None else now,
            "sha": "",
            "short": "",
            "behind": None,
            "error": "",
        }
    )
    _write_check(record)
    _set_config(root, NOTE, "")
    try:
        compared = _untouched(root, was, stamps)
    except CockpitError as exc:
        raise CockpitError(f"the move was taken back, and then: {exc}") from exc
    return {
        "ok": True,
        "changed": True,
        "from": {"url": note["to_url"], "branch": new, "commit": note["to"]},
        "to": {"url": note["url"], "branch": old, "commit": note["commit"]},
        "hermes_record": hermes,
        "files_compared": compared,
        "out": f"origin is {note['url']} again ({old} at {note['commit'][:7]}); {compared} tracked files were compared: none changed",
    }
