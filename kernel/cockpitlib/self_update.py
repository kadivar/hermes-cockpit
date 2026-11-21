# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cockpit updating itself from its own repository, from the Settings page or the shell: what is installed, whether the
repository is ahead (checked on demand and hourly), and the update: a fast-forward pull, the kernel's dependencies when
they changed, no stale bytecode, the Desktop bundle time, Hermes's install record, and a gateway restart. Hermes's own
updater runs a security scan that calls a kernel built on subprocess "caution" and has no way to accept it; this path
does the same work without it, for a plugin whose repository is the human's own.

Before the checkout moves, the incoming tree is run against the live pack (the pre-flight): a pack that fails to load
stops every lane, so a commit the live pack does not load under is never merged.

The record (watch/plugin-update.json) also keeps `previous`, the commit the last update moved the checkout from, which
is where `rollback` goes back to, and `rolled_back_from`, so a check after a rollback says that the commits it counts
as ahead are the ones that were rolled back."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from .errors import CockpitError
from .store import dump_json

CHECK_EVERY = 3600
PREFLIGHT_TIMEOUT = 120
FLOOR_FILE = "UPDATE-FLOOR"  # tracked, at the root: its first line is the commit a rollback never goes below
CHANGES_FILE = "UPDATE-CHANGES.json"  # in a release's tree: {"effective_changes": [key, ...]}, the pack values it changes on purpose
SIGNERS_FILE = "UPDATE-SIGNERS"  # tracked, at the root of the INSTALLED tree: ssh allowed signers; then only a signed tag is an update
SIGNERS_ENV = "COCKPIT_UPDATE_SIGNERS"  # or this: a file of ssh allowed signers, or a GPG keyring folder
LOCK_FILE = (
    "requirements.lock"  # tracked, at the root: the run-time dependencies, each file with its hash (scripts/lock)
)
PYCACHE_ROOTS = ("kernel/cockpitlib", "kernel/cockpitlib/advisories", "dashboard/cockpit", "hooks", "hermes_bridge")


def _root(root: str = "") -> str:
    """The checkout to update: the one named, else COCKPIT_PLUGIN_ROOT (tests point it at a stand-in), else this plugin."""
    from .paths import PLUGIN_ROOT

    return root or os.environ.get("COCKPIT_PLUGIN_ROOT") or PLUGIN_ROOT


def _git(root: str, *args, timeout: int = 120, env=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise CockpitError(f"git {args[0]} timed out") from exc


def _out(root: str, *args) -> str:
    done = _git(root, *args)
    if done.returncode != 0:
        raise CockpitError((done.stderr or done.stdout or f"git {args[0]} failed").strip()[-300:])
    return done.stdout.strip()


def _check_path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "plugin-update.json")


def _read_check() -> dict:
    """The last check as recorded; nothing on an installation with no workspace bound (the record lives in its records)."""
    from .errors import NeedMigrate

    try:
        data = json.load(open(_check_path(), encoding="utf-8"))
    except (OSError, ValueError, NeedMigrate):
        return {}
    return data if isinstance(data, dict) else {}


def _write_check(data: dict) -> None:
    from .errors import NeedMigrate

    try:
        path = _check_path()
    except NeedMigrate:
        return  # no workspace bound: there is nowhere to keep the record, and nothing reads it
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, data)


KEPT = ("previous", "rolled_back_from")
SIGNED = (
    "tag",
    "unsigned_ahead",
    "signers",
)  # in the record only when signers are named: the tag offered, what is ahead of it


def _kept(root: str, head: str) -> dict:
    """What a new check carries over from the last record: where the last update came from, and the commit a rollback
    left, for as long as the checkout is still behind it."""
    last = _read_check()
    found = {"previous": last["previous"]} if last.get("previous") else {}
    if last.get("rehomed_from"):
        found["rehomed_from"] = last["rehomed_from"]  # the repository this checkout was moved from (rehome.py)
    left = str(last.get("rolled_back_from") or "")
    if left and not _is_ancestor(root, left, head):
        found["rolled_back_from"] = left
    return found


def branch_of(root: str) -> str:
    name = _out(root, "rev-parse", "--abbrev-ref", "HEAD")
    return name if name and name != "HEAD" else "master"


def follows(root: str) -> str:
    """What the checkout is installed from, as git names it: `origin/<branch>`, or empty when the checked-out branch
    follows nothing. Read from the checkout alone, with no call to the remote."""
    done = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return done.stdout.strip() if done.returncode == 0 else ""


def remote_branch(root: str) -> str:
    """The branch on origin the checkout follows: its upstream, else origin's default branch, else master. A local
    branch with no counterpart on origin (a fix branch checked out in place) still updates from the default branch."""
    done = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    name = done.stdout.strip() if done.returncode == 0 else ""
    if name.startswith("origin/"):
        return name[len("origin/") :]
    done = _git(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    name = done.stdout.strip() if done.returncode == 0 else ""
    if name.startswith("refs/remotes/origin/"):
        return name[len("refs/remotes/origin/") :]
    done = _git(root, "ls-remote", "--symref", "origin", "HEAD")
    for line in (done.stdout or "").splitlines() if done.returncode == 0 else []:
        if line.startswith("ref: refs/heads/"):
            return line.split()[1][len("refs/heads/") :]  # "ref: refs/heads/<branch>\tHEAD"
    return "master"


def _signers(root: str):
    """Who may sign an update, or None when nobody is named (then an update is the branch's head, as it always was).
    {kind: ssh | gpg, path, source}. The environment names a file of ssh allowed signers or a GPG keyring folder; else
    the installed commit's own SIGNERS_FILE counts, read from that commit and never from the tree an update would bring:
    a candidate cannot vouch for itself. A name that leads nowhere refuses, so a typing error is not an open door."""
    named = os.environ.get(SIGNERS_ENV, "").strip()
    if named:
        if os.path.isdir(named):
            return {"kind": "gpg", "path": named, "source": f"{SIGNERS_ENV}={named}"}
        if os.path.isfile(named):
            return {"kind": "ssh", "path": named, "source": f"{SIGNERS_ENV}={named}"}
        raise CockpitError(
            f"{SIGNERS_ENV} names {named}, which is neither a file of allowed signers nor a keyring folder: no update is "
            "offered or applied until it is one"
        )
    if not _out(root, "ls-tree", "--name-only", "HEAD", "--", SIGNERS_FILE):
        return None
    path = os.path.join(
        _out(root, "rev-parse", "--absolute-git-dir"), "cockpit-update-signers"
    )  # beside git's own files, no working file
    from .store import write_text

    write_text(
        path, _out(root, "show", f"HEAD:{SIGNERS_FILE}") + "\n"
    )  # whole or not at all: two checks may write it at once
    return {"kind": "ssh", "path": path, "source": f"{SIGNERS_FILE} of the installed commit"}


def _verify_tag(root: str, tag: str, signers: dict) -> str:
    """Empty when that tag is signed by one of the signers; else why it is not. Only the signers' own kind of signature
    is looked at: with ssh signers a PGP signature verifies against nothing, and the other way round."""
    ref = f"refs/tags/{tag}"
    if _git(root, "cat-file", "-t", ref).stdout.strip() != "tag":
        return "it is not a signed tag (a plain tag, or no tag at all, carries no signature)"
    if signers["kind"] == "ssh":
        done = _git(
            root,
            "-c",
            f"gpg.ssh.allowedSignersFile={signers['path']}",
            "-c",
            "gpg.program=false",
            "-c",
            "gpg.openpgp.program=false",
            "verify-tag",
            ref,
        )
    else:
        done = _git(
            root,
            "-c",
            f"gpg.ssh.allowedSignersFile={os.devnull}",
            "verify-tag",
            ref,
            env={**os.environ, "GNUPGHOME": signers["path"]},
        )
    return "" if done.returncode == 0 else f"its signature is not one of an allowed signer ({_last_line(done)})"


def _tags_ahead(root: str, branch: str, local: str) -> list:
    """Every tag on origin's branch that is ahead of the checkout, the furthest first: [(name, commit, commits ahead)]."""
    listed = _out(
        root,
        "for-each-ref",
        "--merged",
        f"origin/{branch}",
        "--contains",
        local,
        "--format=%(refname:strip=2)%09%(objectname)%09%(*objectname)",
        "refs/tags",
    )
    rows = []
    for line in listed.splitlines():
        name, target, peeled = (line.split("\t") + ["", ""])[:3]
        commit = peeled or target
        if commit != local:
            rows.append((int(_out(root, "rev-list", "--count", f"{local}..{commit}") or 0), name, commit))
    return [(name, commit, ahead) for ahead, name, commit in sorted(rows, reverse=True)]


def _offer(root: str, branch: str, local: str, signers: dict) -> dict:
    """{tag, commit, behind, refused}: the furthest tag ahead that one of the signers signed, and why each tag beyond it
    was passed over. With none, the offer is the installed commit itself: nothing."""
    refused = []
    for name, commit, ahead in _tags_ahead(root, branch, local):
        why = _verify_tag(root, name, signers)
        if not why:
            return {"tag": name, "commit": commit, "behind": ahead, "refused": refused}
        refused.append(f"{name}: {why}")
    return {"tag": "", "commit": local, "behind": 0, "refused": refused}


def _fetch_tags(root: str) -> None:
    """origin's tags, for the signed mode. A tag that would replace a local one is left alone by git, and that is fine:
    whatever tag is here must verify."""
    _git(root, "fetch", "-q", "origin", "refs/tags/*:refs/tags/*")


def status(root: str = "") -> dict:
    """What is installed and what the last check saw: {installed: {sha, short, subject, date, branch, follows}, dirty, remote:
    {sha, short, behind, checked_at, error}, desktop_stale}."""
    root = _root(root)
    if not os.path.isdir(os.path.join(root, ".git")) and not os.path.isfile(os.path.join(root, ".git")):
        return {
            "installed": None,
            "dirty": False,
            "remote": {},
            "desktop_stale": "",
            "error": f"{root} is not a git checkout",
        }
    sha = _out(root, "rev-parse", "HEAD")
    subject = _out(root, "log", "-1", "--format=%s")
    date = _out(root, "log", "-1", "--format=%cI")
    dirty = bool(_out(root, "status", "--porcelain", "--untracked-files=no"))
    check = _read_check()
    remote = {
        key: check.get(key)
        for key in ("sha", "short", "behind", "checked_at", "error", "branch", *KEPT, *SIGNED)
        if key in check
    }
    if check.get("local") and check.get("local") != sha:
        remote["behind"] = None  # the checkout moved since the check: the count no longer means anything
    from .setup import desktop_copy_stale

    return {
        "installed": {
            "sha": sha,
            "short": sha[:7],
            "subject": subject,
            "date": date,
            "branch": branch_of(root),
            "follows": follows(root),
        },
        "dirty": dirty,
        "remote": remote,
        "desktop_stale": desktop_copy_stale(root),
        "error": "",
    }


def check(root: str = "", now=None) -> dict:
    """Fetch the branch from origin (a read) and count the commits the checkout is behind; recorded for the page and
    the Inbox row. A forge that does not answer is recorded as an error, not raised: the check runs from housekeeping."""
    root = _root(root)
    moment = time.time() if now is None else now
    branch = remote_branch(root)
    local = _out(root, "rev-parse", "HEAD")
    done = _git(root, "fetch", "-q", "origin", branch)
    record = {**_kept(root, local), "local": local, "branch": branch, "checked_at": moment}
    if done.returncode != 0:
        record.update(
            error=(done.stderr or done.stdout or "fetch failed").strip()[-200:], behind=None, sha="", short=""
        )
        _write_check(record)
        return status(root)
    remote = _out(root, "rev-parse", f"origin/{branch}")
    behind = int(_out(root, "rev-list", "--count", f"HEAD..origin/{branch}") or 0)
    record.update(sha=remote, short=remote[:7], behind=behind, error="")
    signers = _signers(root)
    if signers:  # only a tag one of them signed is an update: the head itself, unsigned, is not offered
        _fetch_tags(root)
        record.update(_signed_fields(_offer(root, branch, local, signers), behind, signers))
    _write_check(record)
    return status(root)


def _signed_fields(offer: dict, head_ahead: int, signers: dict) -> dict:
    """What the record says in the signed mode: the offered tag's commit and distance, and how much lies beyond it."""
    return {
        "sha": offer["commit"],
        "short": offer["commit"][:7],
        "behind": offer["behind"],
        "tag": offer["tag"],
        "unsigned_ahead": max(0, head_ahead - offer["behind"]),
        "signers": signers["source"],
    }


def check_if_due(root: str = "", now=None) -> str:
    """The hourly check for housekeeping: a line, never a failure."""
    moment = time.time() if now is None else now
    last = _read_check()
    if last.get("checked_at") and moment - float(last["checked_at"]) < CHECK_EVERY:
        return f"{last.get('behind') or 0} behind" if last.get("behind") else "up to date"
    try:
        seen = check(root, now=moment)
    except CockpitError as exc:
        return f"check skipped: {exc}"
    remote = seen.get("remote") or {}
    if remote.get("error"):
        return f"check skipped: {remote['error'][:80]}"
    return f"{remote.get('behind') or 0} behind" if remote.get("behind") else "up to date"


def inbox_row() -> dict:
    """An Inbox row while the repository is ahead of the checkout; else an empty dict."""
    check_ = _read_check()
    behind = check_.get("behind")
    if not behind:
        return {}
    try:
        current = _out(_root(), "rev-parse", "HEAD")
    except CockpitError:
        return {}
    if check_.get("local") and check_.get("local") != current:
        return {}
    from .after_update import launcher

    left = str(check_.get("rolled_back_from") or "")
    text = (
        f"cockpit is {behind} commit(s) behind its repository ({str(check_.get('short') or '')})"
        + (f", after a rollback from {left[:7]} (an update brings those commits back)" if left else "")
        + f": Settings → Update, or `{launcher('cockpit', _root())} update apply`"
    )
    return {
        "name": "update",
        "update": True,
        "ok": False,
        "reason": text,
        "summary": text,
        "fails": 0,
        "last_ok": None,
        "last_error": None,
        "error": "",
    }  # `update`: an update to apply, not a watcher that failed (the Inbox offers the update, not a run)


RESTART_WAIT = 6.0  # seconds: a refusal comes at once; a restart that began drains running jobs for minutes


def _spawn(argv: list, wait: float = 0.0) -> str:
    """Start a command detached from this process (the gateway restart drains running jobs for minutes). With `wait`,
    what the command said when it gave up within that time (Hermes refuses a restart while a session is live); "" when
    it ended well or is still at work."""
    if not wait:
        subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        return ""
    import tempfile

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as said:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=said, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            code = process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            return ""
        if code == 0:
            return ""
        said.seek(0)
        lines = [line.strip() for line in said.read().splitlines() if line.strip()]
        return (lines[0] if lines else f"exit {code}")[:300]


def _clear_bytecode(root: str) -> int:
    cleared = 0
    for folder in PYCACHE_ROOTS:
        cache = os.path.join(root, folder, "__pycache__")
        if os.path.isdir(cache):
            shutil.rmtree(cache, ignore_errors=True)
            cleared += 1
    return cleared


def _record_hermes_revision(name: str, revision: str) -> str:
    """Hermes's install record of the plugin, so `hermes plugins check-updates` agrees with the checkout. Best effort."""
    try:
        from .hermes_runtime import run_helper

        results = (
            run_helper("plugins", {"ops": [{"op": "record_revision", "name": name, "revision": revision}]}).get(
                "results"
            )
            or []
        )
        first = results[0] if results else {}
        return (
            ""
            if first is True
            else str((first or {}).get("error") or "not recorded")
            if isinstance(first, dict)
            else ""
        )
    except Exception as exc:  # noqa: BLE001 - the update stands whether or not Hermes's record follows
        return str(exc)[:160]


def _refresh_dependencies(root: str) -> str:
    """The plugin's environment brought to what the checked-out tree asks for. A tree with a lock file is installed from
    it, every file checked against its recorded hash, and then the plugin itself with nothing resolved; a tree without
    one is installed as it always was."""
    tool = os.path.join(root, ".venv", "bin", "pip")
    steps = [["install", "-q", "-e", "."]]
    if os.path.isfile(os.path.join(root, LOCK_FILE)):
        steps = [["install", "-q", "--require-hashes", "-r", LOCK_FILE], ["install", "-q", "--no-deps", "-e", "."]]
    for step in steps:
        done = subprocess.run([tool, *step], cwd=root, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            return f"pip failed: {(done.stderr or done.stdout).strip()[-200:]}"
    return "dependencies refreshed"


def _is_ancestor(root: str, older: str, newer: str) -> bool:
    return _git(root, "merge-base", "--is-ancestor", older, newer).returncode == 0


def _commit(root: str, name: str) -> str:
    """The commit a human named (a hash, a tag, a branch), as its full hash. A name git would read as an option, or one
    that is no commit of this checkout, is refused."""
    name = str(name or "").strip()
    done = (
        _git(root, "rev-parse", "--verify", "--quiet", name + "^{commit}")
        if name and not name.startswith("-")
        else None
    )
    if done is None or done.returncode != 0 or not done.stdout.strip():
        raise CockpitError(f"{name or '(nothing)'} is not a commit of this checkout")
    return done.stdout.strip()


def _bound_pack() -> str:
    """The live pack's file, or empty on an installation with no workspace bound."""
    from .errors import NeedMigrate
    from .paths import pack_path

    try:
        return pack_path()
    except NeedMigrate:
        return ""


def _scratch() -> str:
    return tempfile.mkdtemp(prefix="cockpit-preflight-")


def _export(root: str, commit: str, folder: str) -> str:
    """That commit's tree as plain files under the folder: an archive, so the checkout and its index are not touched."""
    tree = os.path.join(folder, "tree")
    os.makedirs(tree)
    archive = os.path.join(folder, "tree.tar")
    _out(root, "archive", "--format=tar", "-o", archive, commit)
    done = subprocess.run(
        ["tar", "-xf", archive, "-C", tree], capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL
    )
    if done.returncode != 0:
        raise CockpitError(f"update refused: the tree of {commit[:7]} could not be unpacked: {_last_line(done)}")
    return tree


def _python(root: str) -> str:
    """The interpreter the installed plugin runs on: its own venv when it has one, else this one."""
    venv = os.path.join(root, ".venv", "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


def _last_line(done) -> str:
    """What a failed command said last: its last line on stderr, else on stdout, else its exit status."""
    for text in (done.stderr, done.stdout):
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if lines:
            return lines[-1][-300:]
    return f"exit {done.returncode}"


def _cockpit(tree: str, python: str, env: dict, *args) -> subprocess.CompletedProcess:
    """A tree's own `bin/cockpit` in its own process, so the code that answers is that tree's and none of this one's.
    A command that does not answer in time has failed."""
    argv = [python, os.path.join(tree, "bin", "cockpit"), *args]
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=PREFLIGHT_TIMEOUT,
            env=env,
            cwd=tree,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"no answer within {PREFLIGHT_TIMEOUT} s")


def _effective(tree: str, python: str, env: dict, which: str):
    """A tree's `pack effective --json` as a dict, or None when that kernel has no such command (it refuses the word as
    usage: exit 2 with its example). A command that exists and fails, or answers no JSON object, refuses the update."""
    done = _cockpit(tree, python, env, "pack", "effective", "--json")
    said = (done.stderr or "").lower()
    if done.returncode == 2 and ("examples:" in said or "unknown" in said):
        return None
    if done.returncode != 0:
        raise CockpitError(f"update refused: `pack effective` failed on {which}: {_last_line(done)}")
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise CockpitError(f"update refused: `pack effective --json` on {which} answered no JSON object")
    return data


def _flat(value, prefix: str = "") -> dict:
    """Nested JSON values as {dotted.key: leaf}, so two descriptions compare key by key. An empty mapping is a leaf, save
    the whole description: an empty one has no keys."""
    if isinstance(value, dict) and (value or not prefix):
        found = {}
        for key, inner in value.items():
            found.update(_flat(inner, f"{prefix}.{key}" if prefix else key))
        return found
    return {prefix: value}


def _declared(tree: str) -> list:
    """The pack keys a release says it changes on purpose (CHANGES_FILE in its tree). An unreadable file declares none."""
    try:
        data = json.load(open(os.path.join(tree, CHANGES_FILE), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keys = data.get("effective_changes") if isinstance(data, dict) else None
    return [key for key in keys if isinstance(key, str) and key] if isinstance(keys, list) else []


def _preflight(root: str, commit: str, compare: bool = True) -> dict:
    """The commit's own code run against the live pack before the checkout moves to it. Its `pack check` must pass; and
    when both it and the installed kernel print the pack's effective values, every value must be the same, save the keys
    the commit's tree declares (CHANGES_FILE). A refusal raises; the exported tree is removed either way. Nothing can
    skip it; an installation with no workspace has no live pack and says so."""
    pack = _bound_pack()
    if not pack:
        return {
            "ran": False,
            "checks": [],
            "effective_changes": [],
            "notes": [
                "pre-flight skipped: no workspace is bound, so there is no live pack to check the new code against"
            ],
        }
    from .paths import hermes_home

    env = {**os.environ, "COCKPIT_PACK": pack, "COCKPIT_HERMES_HOME": hermes_home(), "PYTHONDONTWRITEBYTECODE": "1"}
    python = _python(root)
    found = {"ran": True, "checks": ["pack check"], "effective_changes": [], "notes": []}
    folder = _scratch()
    try:
        tree = _export(root, commit, folder)
        checked = _cockpit(tree, python, env, "pack", "check")
        if checked.returncode != 0:
            # a new dependency is installed only after the merge, so the new code may fail here for lack of it: say so
            hint = (
                (
                    " (pyproject.toml changes with it: if the new code needs a dependency this environment lacks, install it "
                    "into the plugin's environment and apply again)"
                )
                if _out(root, "diff", "--name-only", "HEAD", commit, "--", "pyproject.toml")
                else ""
            )
            raise CockpitError(
                f"update refused: the live pack ({pack}) does not load under {commit[:7]}, and a pack that does not "
                f"load stops every lane: {_last_line(checked)}{hint}"
            )
        theirs = _effective(tree, python, env, commit[:7]) if compare else None
        ours = _effective(root, python, env, "the installed kernel") if theirs is not None else None
        if theirs is not None and ours is None:
            found["notes"].append(
                f"pre-flight: {commit[:7]} prints the pack's effective values and the installed kernel does not, "
                "so they were not compared this once"
            )
        if theirs is not None and ours is not None:
            found["checks"].append("pack effective")
            before, after = _flat(ours), _flat(theirs)
            missing = object()
            differs = sorted(
                key for key in set(before) | set(after) if before.get(key, missing) != after.get(key, missing)
            )
            declared = _declared(tree)
            silent = [key for key in differs if not any(key == name or key.startswith(name + ".") for name in declared)]
            if silent:
                raise CockpitError(
                    f"update refused: {commit[:7]} changes what the live pack means without declaring it ("
                    + ", ".join(silent[:8])
                    + (f" and {len(silent) - 8} more" if len(silent) > 8 else "")
                    + f"): a release lists such keys under effective_changes in {CHANGES_FILE}"
                )
            if differs:
                found["effective_changes"] = differs
                found["notes"].append(
                    "pre-flight: the update changes these pack values, as it declares: " + ", ".join(differs)
                )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return found


def apply(root: str = "", restart: bool = True, now=None, to: str = "") -> dict:
    """Fast-forward the checkout to origin, or to the commit named when it lies between the checkout and origin; refresh
    the kernel's dependencies when they changed, drop stale bytecode, bump the Desktop bundle time when the UI changed,
    record the revision with Hermes, restart the gateway (detached: it drains running jobs). Refuses a checkout with
    local edits, and a commit the live pack does not load under."""
    root = _root(root)
    seen = status(root)
    if seen.get("error"):
        raise CockpitError(seen["error"])
    if seen["dirty"]:
        raise CockpitError("the plugin checkout has local changes: commit or stash them before updating")
    branch = remote_branch(root)
    before = seen["installed"]["sha"]
    fetched = _git(root, "fetch", "-q", "origin", branch)
    if fetched.returncode != 0:
        raise CockpitError((fetched.stderr or fetched.stdout or "fetch failed").strip()[-200:])
    target = _out(root, "rev-parse", f"origin/{branch}")
    signers = _signers(root)
    offer = None
    if signers:
        _fetch_tags(root)
        offer = _offer(root, branch, before, signers)
        if to:
            why = _verify_tag(root, to, signers)
            if why:
                raise CockpitError(
                    f"--to {to}: update refused, {why}. With signers named ({signers['source']}) an update goes to a signed tag"
                )
            to = f"refs/tags/{to}"
        else:
            ahead = int(_out(root, "rev-list", "--count", f"{before}..{target}") or 0)
            if ahead and not offer["tag"]:
                raise CockpitError(
                    f"update refused: origin/{branch} is {ahead} commit(s) ahead and none of them carries a tag signed by an "
                    f"allowed signer ({signers['source']})" + "".join(f"; {line}" for line in offer["refused"][:3])
                )
            to = (
                f"refs/tags/{offer['tag']}" if offer["tag"] else ""
            )  # nothing ahead: the head is where the checkout is already
    if to:
        newest, target = target, _commit(root, to)
        if not _is_ancestor(root, target, newest):
            raise CockpitError(
                f"--to {to}: {target[:7]} is not on origin/{branch}, and an update only moves along its repository's line"
            )
        if not _is_ancestor(root, before, target):
            raise CockpitError(
                f"--to {to}: {target[:7]} is not ahead of the installed {before[:7]}: `update rollback --to` goes back"
            )
    # only a commit the checkout would move to is checked: one already here changes nothing, one off its line is refused below
    checked = _preflight(root, target) if target != before and _is_ancestor(root, before, target) else {}
    pulled = _git(root, "merge", "--ff-only", target)
    if pulled.returncode != 0:
        raise CockpitError("not a fast-forward: " + (pulled.stderr or pulled.stdout or "").strip()[-200:])
    result = _finish(root, before, branch, restart, now, checked)
    if signers:  # the record counts what is still offered (a signed tag beyond a named one), not the unsigned head
        after = _out(root, "rev-parse", "HEAD")
        head_ahead = int(_out(root, "rev-list", "--count", f"{after}..origin/{branch}") or 0)
        left = int(_out(root, "rev-list", "--count", f"{after}..{offer['commit']}") or 0)
        still = {**offer, "behind": left} if left else {"tag": "", "commit": after, "behind": 0}
        _write_check({**_read_check(), **_signed_fields(still, head_ahead, signers)})
    return result


def _summary(before: str, after: str, commits: list, back: bool, pip: str, restarted: str, desktop) -> str:
    """One line on what an update or a rollback did, and what it could not do."""
    if after == before:
        moved = f"already at {after[:7]}" if back else "already up to date"
    elif back:
        moved = f"rolled back {before[:7]} → {after[:7]}: {len(commits)} commit(s) left"
    else:
        moved = f"updated {before[:7]} → {after[:7]}: {len(commits)} commit(s)"
    parts = [moved]
    if pip:
        parts.append(pip)
    if restarted == "requested":
        parts.append("gateway restart requested")
    if restarted.startswith("refused: "):
        parts.append(
            "THE GATEWAY DID NOT RESTART and still runs the code from before: run `hermes gateway restart` when no "
            f"session is live ({restarted[len('refused: ') :]})"
        )
    if desktop:
        parts.append("restart the Desktop to load the new UI")
    return "; ".join(parts)


def _finish(root: str, before: str, branch: str, restart: bool, now, checked: dict, back: bool = False) -> dict:
    """What follows a checkout that moved, forward or back: the kernel's dependencies when pyproject changed, no stale
    bytecode, the Desktop bundle time, Hermes's record, the update record, the gateway restart, the line left to the human."""
    after = _out(root, "rev-parse", "HEAD")
    changed = _out(root, "diff", "--name-only", f"{before}..{after}").splitlines() if after != before else []
    span = f"{after}..{before}" if back else f"{before}..{after}"  # a rollback lists the commits it left
    commits = _out(root, "log", "--no-decorate", "--format=%h %s", span).splitlines() if after != before else []
    pip = ""
    if (set(changed) & {"pyproject.toml", LOCK_FILE}) and os.path.exists(os.path.join(root, ".venv", "bin", "pip")):
        pip = _refresh_dependencies(root)
    cleared = _clear_bytecode(root) if after != before else 0
    from .setup import desktop_refresh

    desktop = desktop_refresh(root) or any(name.startswith("desktop/") for name in changed)
    recorded = _record_hermes_revision(os.path.basename(root), after) if after != before else ""
    # the checkout may now be short of origin (a named commit, a rollback): the record says how far, and of which commit
    counted = _git(root, "rev-list", "--count", f"HEAD..origin/{branch}")
    behind = (
        int(counted.stdout.strip() or 0) if counted.returncode == 0 else None
    )  # no origin branch here to count against
    newest = _out(root, "rev-parse", f"origin/{branch}") if behind else "" if behind is None else after
    record = {
        "local": after,
        "branch": branch,
        "checked_at": time.time() if now is None else now,
        "sha": newest,
        "short": newest[:7],
        "behind": behind,
        "error": "",
    }
    if after == before:
        record.update(_kept(root, after))  # nothing moved: what the record knew still holds
    elif back:
        record["rolled_back_from"] = before  # and no `previous`: a second rollback names its commit
    else:
        record["previous"] = before  # where `rollback` goes back to
    _write_check(record)
    restarted = "skipped"
    if restart and after != before:
        hermes = shutil.which("hermes")
        if hermes:
            refused = _spawn([hermes, "gateway", "restart"], wait=RESTART_WAIT)
            restarted = f"refused: {refused}" if refused else "requested"
        else:
            restarted = "hermes not found"
    result = {
        "ok": True,
        "from": before[:7],
        "to": after[:7],
        "changed": after != before,
        "commits": commits,
        "files": len(changed),
        "pip": pip,
        "bytecode_cleared": cleared,
        "desktop": bool(desktop),
        "hermes_record": recorded,
        "restart": restarted,
        "preflight": checked,
        "out": _summary(before, after, commits, back, pip, restarted, desktop),
    }
    # what is left to the human, as one line for this machine's shell: the launcher resolved, the seats, doctor, the Desktop
    from .after_update import after as next_steps

    result["next"] = next_steps(result, root)
    return result


def _floor(root: str) -> str:
    """The commit a rollback never goes below, from the first line of FLOOR_FILE as the installed commit tracks it; empty
    when that commit has no such file. A file that names no commit of this checkout refuses every rollback."""
    if not _out(root, "ls-tree", "--name-only", "HEAD", "--", FLOOR_FILE):
        return ""
    lines = _out(root, "show", f"HEAD:{FLOOR_FILE}").splitlines()
    try:
        return _commit(root, lines[0] if lines else "")
    except CockpitError as exc:
        raise CockpitError(
            f"rollback refused: {FLOOR_FILE} names no commit of this checkout, so how far back is safe is unknown"
        ) from exc


def rollback(root: str = "", restart: bool = True, now=None, to: str = "") -> dict:
    """Move the checkout back to the commit its last update came from, or to the commit named: only to a commit behind
    the installed one on its own history, never below the floor (FLOOR_FILE), never with local edits, and only to a
    commit the live pack loads under (its own `pack check`, as before an update). Then what follows an update follows."""
    root = _root(root)
    seen = status(root)
    if seen.get("error"):
        raise CockpitError(seen["error"])
    if seen["dirty"]:
        raise CockpitError("the plugin checkout has local changes: commit or stash them before rolling back")
    before = seen["installed"]["sha"]
    name = to or str(_read_check().get("previous") or "")
    if not name:
        raise CockpitError(
            "nothing to roll back to: no update is recorded since the last rollback; name the commit: "
            "`cockpit update rollback --to <commit>`"
        )
    target = _commit(root, name)
    if not _is_ancestor(root, target, before):
        raise CockpitError(
            f"{target[:7]} is not behind the installed {before[:7]}: a rollback only goes back along the checkout's own history"
        )
    floor = _floor(root)
    if floor and not _is_ancestor(root, floor, target):
        raise CockpitError(
            f"rollback refused: {target[:7]} is below the floor {floor[:7]} ({FLOOR_FILE}): this installation does not go back that far"
        )
    branch = remote_branch(root)
    checked = {}
    if target != before:
        # the older code meets the same live pack: its own pack check, not the comparison of values (they differ on purpose)
        checked = _preflight(root, target, compare=False)
        on_branch = _out(root, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD"
        moved = (
            _git(root, "checkout", "-q", "-B", branch_of(root), target)
            if on_branch
            else _git(root, "checkout", "-q", "--detach", target)
        )
        if moved.returncode != 0:
            raise CockpitError("rollback failed: " + (moved.stderr or moved.stdout or "").strip()[-200:])
    return _finish(root, before, branch, restart, now, checked, back=True)
