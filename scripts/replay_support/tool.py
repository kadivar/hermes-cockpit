# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Replay: prove that a new kernel reads an installation's real records exactly as the kernel running now does.

snapshot  copies the records, the pack and the board out of a workspace, reading only
capture   runs one kernel over a copy of that snapshot, clock frozen and network denied, and keeps what it answers
compare   says which answers differ between two captures
receipt   writes the hashes and counts that may leave the machine

Standard library only. The kernel under replay runs in its own process (replay_support/driver.py).
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

VERSION = "1"
SUPPORT = os.path.dirname(os.path.abspath(__file__))
SPARSE_MB = 16
# seat -> the lane its fence is asked as. `human` is no lane at all; `editor` is an editor session outside the lanes.
SEATS = (
    ("human", ""),
    ("worker", "worker-1"),
    ("tester", "tester-1"),
    ("reviewer", "reviewer"),
    ("intake", "intake"),
    ("analyst", "analyst"),
    ("gatekeeper", "gatekeeper"),
    ("editor", ""),
)
# commands a kernel may start that would leave the machine or reach the live runtime: each is a stand-in that refuses
REFUSED = (
    "hermes",
    "curl",
    "wget",
    "ssh",
    "scp",
    "sftp",
    "rsync",
    "nc",
    "open",
    "xdg-open",
    "osascript",
    "docker",
    "kubectl",
    "glab",
    "mail",
    "sendmail",
)
# what the views parse is copied whole whatever its size; anything else over the limit (a video, an archive) is listed, not read
WHOLE = (
    ".json",
    ".jsonl",
    ".md",
    ".yaml",
    ".yml",
    ".txt",
    ".log",
    ".db",
    ".csv",
    ".html",
    ".patch",
    ".diff",
    ".py",
    ".sh",
    "",
)
HEAVY = (".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build", ".tmp")
DIFFS_SHOWN = 5


def scratch(name: str) -> bool:
    """A lock or a temp file a kernel keeps beside its records: no record, so never copied, hashed or compared (one
    kernel writes them and another does not, and what they hold is a pid)."""
    return name.startswith(".") and name.endswith((".lock", ".tmp"))


class ReplayError(Exception):
    """The tool cannot go on; the message says what to do."""


# ---- files ----


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def inside(path: str, folder: str) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def emptied(path: str, size: int, limit: int) -> bool:
    """Whether a copy holds this file by size only: over the limit, and not of a kind the views parse."""
    return bool(limit) and size > limit and os.path.splitext(path)[1].lower() not in WHOLE


def top_files(folder: str, copy: str, top: str) -> int:
    """A link that leads out of the tree is skipped, and counts as one. When it is a folder that lives elsewhere (a
    pack's plugin) the copy is a real folder with its top files and nothing below them: a loader asks that the folder is
    there and reads those. Never a folder the tree itself lies in."""
    if not os.path.isdir(folder) or inside(top, folder):
        return 1
    os.makedirs(copy, exist_ok=True)
    for name in sorted(os.listdir(folder)):
        given = os.path.join(folder, name)
        if os.path.isfile(given) and not os.path.islink(given) and os.path.getsize(given) <= 1 << 20:
            shutil.copyfile(given, os.path.join(copy, name))
    return 1


def copy_tree(source: str, target: str, limit: int, skip=()) -> dict:
    """A copy that only reads its source. Times are kept (a view reads a record's age). A file over the limit becomes an
    empty file of the same size and time, unless it is of a kind the views parse: evidence videos are listed, never read.
    A link is kept only when it stays inside the tree, so nothing in the copy leads back to the original."""
    counts = {"files": 0, "bytes": 0, "sparse": 0, "links_skipped": 0}
    top = os.path.realpath(source)
    folders = []
    for folder, dirs, files in os.walk(source):
        relative = os.path.relpath(folder, source)
        made = os.path.normpath(os.path.join(target, relative))
        os.makedirs(made, exist_ok=True)
        folders.append((folder, made))
        for name in sorted(files) + [name for name in dirs if os.path.islink(os.path.join(folder, name))]:
            if scratch(name):
                continue
            path, copy = os.path.join(folder, name), os.path.join(made, name)
            if os.path.islink(path):
                aim = os.readlink(path)
                if os.path.isabs(aim) or not inside(os.path.join(os.path.realpath(folder), aim), top):
                    counts["links_skipped"] += top_files(path, copy, top)
                    continue
                if not os.path.lexists(copy):
                    os.symlink(aim, copy)
                continue
            seen = os.stat(path)
            if not os.path.isfile(path):
                continue
            if emptied(path, seen.st_size, limit):
                with open(copy, "wb") as handle:
                    handle.truncate(seen.st_size)
                counts["sparse"] += 1
            else:
                with open(path, "rb") as given, open(copy, "wb") as handle:
                    shutil.copyfileobj(given, handle, 1 << 20)
                counts["bytes"] += seen.st_size
            os.chmod(copy, (seen.st_mode & 0o777) | 0o600)
            os.utime(copy, ns=(seen.st_atime_ns, seen.st_mtime_ns))
            counts["files"] += 1
        dirs[:] = sorted(name for name in dirs if name not in skip and not os.path.islink(os.path.join(folder, name)))
    for folder, made in reversed(folders):  # a folder's own time, once nothing more is written into it
        seen = os.stat(folder)
        os.utime(made, ns=(seen.st_atime_ns, seen.st_mtime_ns))
    return counts


def tree_digest(folder: str, limit: int = 0, times: bool = False, skip=()) -> str:
    """One hash for a folder: every file's path and content, and its time when asked. A file over the limit counts by size."""
    digest = hashlib.sha256()
    for path in walk_files(folder, skip):
        seen = os.lstat(path)
        if os.path.islink(path):
            content = "link:" + os.readlink(path)
        elif emptied(path, seen.st_size, limit):
            content = f"sparse:{seen.st_size}"
        else:
            content = sha256_file(path)
        when = f"\0{seen.st_mtime_ns}" if times and not os.path.islink(path) else ""
        digest.update(f"{os.path.relpath(path, folder)}\0{content}{when}\n".encode())
    return digest.hexdigest()


def walk_files(folder: str, skip=()) -> list:
    found = []
    for top, dirs, files in os.walk(folder):
        dirs[:] = sorted(name for name in dirs if name not in skip)
        found += [os.path.join(top, name) for name in sorted(files) if not name.endswith(".pyc") and not scratch(name)]
    return found


def empty_folder(path: str, what: str) -> str:
    """The folder to write into: new, or there and empty. Never one that holds something."""
    path = os.path.abspath(path)
    if os.path.isdir(path) and os.listdir(path):
        raise ReplayError(f"{what} {path} is not empty: name a new folder")
    os.makedirs(path, exist_ok=True)
    return path


def iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_of(text: str) -> float:
    try:
        return float(datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp())
    except ValueError as exc:
        raise ReplayError(f"--clock {text}: an ISO moment is wanted, like 2030-01-02T09:00:00Z") from exc


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, indent=1, ensure_ascii=False)
        handle.write("\n")


def read_json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# ---- the kernel ----


def kernel_python(kernel: str, given: str = "") -> str:
    """The interpreter a kernel runs on: the one named, its own .venv, or this one."""
    own = os.path.join(kernel, ".venv", "bin", "python")
    return given or (own if os.path.exists(own) else sys.executable)


def kernel_identity(kernel: str) -> dict:
    """The kernel's commit, whether its tree has edits, and a hash of the code a replay runs."""

    def git(*argv) -> str:
        try:
            done = subprocess.run(["git", "-C", kernel, *argv], capture_output=True, text=True, check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return done.stdout.strip() if done.returncode == 0 else ""

    commit = git("rev-parse", "HEAD")
    digest = hashlib.sha256()
    for name in ("kernel", "dashboard", "hooks", "hermes_bridge"):
        if os.path.isdir(os.path.join(kernel, name)):
            digest.update(
                f"{name}\0{tree_digest(os.path.join(kernel, name), skip=('__pycache__', 'node_modules'))}\n".encode()
            )
    return {
        "commit": commit or "unknown",
        "edited": bool(git("status", "--porcelain", "--untracked-files=no")) if commit else False,
        "tree": digest.hexdigest(),
    }


def run_driver(python: str, job: dict, env: dict, timeout: int) -> dict:
    """One driver process for one job; its answer file is what it has to say."""
    job_file = job["answer"] + ".job"
    write_json(job_file, job)
    try:
        done = subprocess.run(
            [python, os.path.join(SUPPORT, "driver.py"), job_file],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd=env["COCKPIT_ROOT"],
        )
    except subprocess.TimeoutExpired as exc:
        raise ReplayError(f"the kernel gave no answer in {timeout} seconds ({job['mode']})") from exc
    if done.returncode != 0 or not os.path.isfile(job["answer"]):
        raise ReplayError(
            f"the kernel could not be replayed ({job['mode']}, exit {done.returncode}):\n{(done.stderr or done.stdout).strip()[-2000:]}"
        )
    return read_json(job["answer"])


def sandbox_env(box: dict, python: str) -> dict:
    """The whole environment of a kernel under replay: nothing of this shell's, no lane, no credentials, no way out."""
    closed = "http://127.0.0.1:9"
    env = {
        "PATH": os.pathsep.join([box["bin"], "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "HOME": box["user"],
        "TMPDIR": box["tmp"],
        "TZ": "UTC",
        "LC_ALL": "C",
        "PYTHONUTF8": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "COCKPIT_WORKSPACE": box["ws"],
        "COCKPIT_ROOT": box["root"],
        "COCKPIT_HERMES_HOME": box["home"],
        "COCKPIT_PACK": box["pack"],
        "COCKPIT_WT": os.path.join(box["root"], "wt"),
        "COCKPIT_VOLUMES": os.path.join(box["root"], "volumes"),
        "COCKPIT_CURSOR_HOOKS": os.path.join(box["user"], "cursor", "hooks.json"),
        "COCKPIT_NO_VENV": "1",
        "HERMES_HOME": box["home"],
        "GNUPGHOME": os.path.join(box["user"], "gnupg"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "file",
        "REPLAY_FORGE_READS": box["reads"],
        "REPLAY_CALLS": box["calls"],
    }
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[name] = env[name.lower()] = closed
    return env


def stand_ins(box: dict, python: str) -> None:
    """The commands first on the kernel's PATH: a forge that answers recorded reads, and refusals for the rest."""

    def put(name: str, script: str) -> None:
        path = os.path.join(box["bin"], name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f'#!/bin/sh\nREPLAY_STANDIN={name} exec "{python}" "{os.path.join(SUPPORT, script)}" "$@"\n')
        os.chmod(path, 0o755)  # noqa: S103 - a stand-in program has to be executable

    put("gh", "standin_gh.py")
    for name in REFUSED:
        put(name, "standin_refuse.py")


# ---- snapshot ----


def records_of(folder: str) -> list:
    """Every JSON record of a folder, read plainly."""
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            try:
                record = read_json(os.path.join(folder, name))
            except (OSError, ValueError):
                continue
            if isinstance(record, dict):
                found.append(record)
    return found


def pr_records(records: str) -> list:
    qa = os.path.join(records, "qa")
    found = []
    for ticket in sorted(os.listdir(qa)) if os.path.isdir(qa) else []:
        found += records_of(os.path.join(qa, ticket, "pr"))
    return found + records_of(os.path.join(records, "platform", "pr"))


def forge_reads(records: str) -> dict:
    """A quiet forge, made from the records themselves: each pull request as its record last saw it, with no comment,
    review or thread since. The login is the author of most of the pull requests the installation opened."""
    pulls, authors = {}, {}
    for record in pr_records(records):
        repo, number = str(record.get("repo") or ""), record.get("number")
        if not repo or not number:
            continue
        merged = bool(record.get("merged"))
        state = str(record.get("state") or "open").lower()
        pull = {
            "number": int(number),
            "title": record.get("title") or "",
            "html_url": record.get("url") or "",
            "state": "open" if state == "open" else "closed",
            "merged": merged,
            "merged_at": record.get("last_check") if merged else None,
            "head": {"ref": record.get("head") or "", "sha": record.get("head_sha") or ""},
            "base": {"ref": record.get("base") or ""},
            "user": {"login": record.get("author") or ""},
            "requested_reviewers": [],
            "created_at": record.get("first_sight") or "",
        }
        named = re.search(r"//[^/]+/([^/]+)/([^/]+)/pull/\d+", str(record.get("url") or ""))
        pulls[f"{named.group(1)}/{named.group(2)}#{int(number)}" if named else f"*/{repo}#{int(number)}"] = pull
        pulls.setdefault(f"*/{repo}#{int(number)}", pull)
        if record.get("role") == "author" and record.get("author"):
            authors[record["author"]] = authors.get(record["author"], 0) + 1
    login = sorted(authors, key=lambda name: (-authors[name], name))[0] if authors else "replay-human"
    return {"login": login, "pulls": pulls}


def record_counts(snapshot: str, records: str, board: str) -> dict:
    """How much was replayed: counts only."""
    root = os.path.join(snapshot, "ws", records)
    outbox = os.path.join(root, "outbox")
    tickets = (
        [
            name
            for name in sorted(os.listdir(outbox))
            if not name.startswith("_") and os.path.isdir(os.path.join(outbox, name))
        ]
        if os.path.isdir(outbox)
        else []
    )
    qa = os.path.join(root, "qa")
    counts = {
        "intents": sum(
            1 for ticket in tickets for name in os.listdir(os.path.join(outbox, ticket)) if name.endswith(".json")
        ),
        "outbox_tickets": len(tickets),
        "qa_tickets": sum(1 for name in os.listdir(qa) if os.path.isdir(os.path.join(qa, name)))
        if os.path.isdir(qa)
        else 0,
        "pr_records": len(pr_records(root)),
        "watch_files": len(walk_files(os.path.join(root, "watch")))
        if os.path.isdir(os.path.join(root, "watch"))
        else 0,
        "cards": 0,
    }
    path = os.path.join(snapshot, "home", "kanban", "boards", board, "kanban.db")
    if board and os.path.isfile(path):
        connection = sqlite3.connect(path)
        try:
            counts["cards"] = int(connection.execute("select count(*) from tasks").fetchone()[0])
        except sqlite3.Error:
            counts["cards"] = 0
        finally:
            connection.close()
    return counts


def copy_board(home: str, board: str, target_home: str) -> str:
    """The board's database, copied as files (the database is never opened where it lives) and settled in the copy. A copy
    torn by a write under way is taken again. Says `copied`, or `absent` when the home has no such board."""
    source = os.path.join(home, "kanban", "boards", board)
    if not board or not os.path.isfile(os.path.join(source, "kanban.db")):
        return "absent"
    target = os.path.join(target_home, "kanban", "boards", board)
    os.makedirs(target, exist_ok=True)
    for _attempt in range(3):
        for name in ("kanban.db", "kanban.db-wal", "kanban.db-shm", "board.json"):
            if os.path.lexists(os.path.join(target, name)):
                os.unlink(os.path.join(target, name))
            if os.path.isfile(os.path.join(source, name)):
                with open(os.path.join(source, name), "rb") as given, open(os.path.join(target, name), "wb") as handle:
                    shutil.copyfileobj(given, handle, 1 << 20)
        seen = os.stat(os.path.join(source, "kanban.db"))
        try:
            connection = sqlite3.connect(os.path.join(target, "kanban.db"))
            try:
                connection.execute("pragma wal_checkpoint(truncate)")
                sound = connection.execute("pragma quick_check").fetchone()[0] == "ok"
            finally:
                connection.close()
        except sqlite3.Error:
            sound = False
        if sound:
            for name in ("kanban.db-wal", "kanban.db-shm"):
                if os.path.lexists(os.path.join(target, name)):
                    os.unlink(os.path.join(target, name))
            os.utime(os.path.join(target, "kanban.db"), ns=(seen.st_atime_ns, seen.st_mtime_ns))
            return "copied"
    raise ReplayError("the board's database could not be copied whole in three tries: try again in a quiet moment")


def copy_home_bits(home: str, target: str, limit: int) -> None:
    """What a pack load reads of the runtime's home, and no more: the providers it knows (never config.yaml itself, which
    holds keys), the names of its model-provider plugins, and the other plugins installed there (a pack's block for one is
    checked by that plugin's own code). The kernel's own folder among them is named by its plugin.yaml only."""
    os.makedirs(target, exist_ok=True)
    providers = []
    listed = os.path.join(home, "known-providers")
    if os.path.isfile(listed):
        providers += [
            line.strip() for line in open(listed, encoding="utf-8") if line.strip() and not line.startswith("#")
        ]
    config = os.path.join(home, "config.yaml")
    if os.path.isfile(config):
        match = re.search(
            r"(?m)^model:\n(?:  .*\n)*?  provider:\s*['\"]?([^\s'\"]+)",
            open(config, encoding="utf-8", errors="replace").read(),
        )
        if match:
            providers.append(match.group(1))
    if providers:
        with open(os.path.join(target, "known-providers"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(dict.fromkeys(providers)) + "\n")
    plugins = os.path.join(home, "plugins")
    for name in sorted(os.listdir(plugins)) if os.path.isdir(plugins) else []:
        folder = os.path.join(plugins, name)
        if name == "model-providers" and os.path.isdir(folder):
            for provider in sorted(os.listdir(folder)):
                if os.path.isdir(os.path.join(folder, provider)):
                    os.makedirs(os.path.join(target, "plugins", name, provider), exist_ok=True)
            continue
        if not os.path.isfile(os.path.join(folder, "plugin.yaml")):
            continue
        if os.path.isdir(os.path.join(folder, "kernel", "cockpitlib")):
            os.makedirs(os.path.join(target, "plugins", name), exist_ok=True)
            shutil.copyfile(os.path.join(folder, "plugin.yaml"), os.path.join(target, "plugins", name, "plugin.yaml"))
            continue
        copy_tree(folder, os.path.join(target, "plugins", name), limit, skip=HEAVY)


def snapshot(
    kernel: str,
    workspace: str,
    pack: str,
    home: str,
    out: str,
    clock: str = "",
    python: str = "",
    sparse_mb: int = SPARSE_MB,
) -> dict:
    """Copy what a replay reads out of a live installation, reading only: the pack, the records folder the pack names,
    the board, and what a pack load reads of the runtime's home."""
    workspace, pack, home = os.path.realpath(workspace), os.path.realpath(pack), os.path.realpath(home)
    if not os.path.isdir(workspace):
        raise ReplayError(f"no workspace at {workspace}")
    if not os.path.isfile(pack):
        raise ReplayError(f"no pack at {pack}: name its pack.yaml")
    pack_dir = os.path.dirname(pack)
    for place, what in ((workspace, "the workspace"), (home, "the runtime's home"), (pack_dir, "the pack")):
        if inside(out, place):
            raise ReplayError(
                f"{os.path.abspath(out)} is inside {what}: a replay writes nothing there, name a folder elsewhere"
            )
    if inside(workspace, pack_dir) and workspace != pack_dir:
        raise ReplayError("the workspace is inside the pack's folder: this layout is not replayed")
    out = empty_folder(out, "the snapshot folder")
    limit = sparse_mb << 20
    counts = {"files": 0, "bytes": 0, "sparse": 0, "links_skipped": 0}

    def add(done: dict) -> None:
        for key, value in done.items():
            counts[key] += value

    ws, box_home = os.path.join(out, "ws"), os.path.join(out, "home")
    os.makedirs(ws)
    if inside(pack_dir, workspace):
        pack_copy = os.path.join("ws", os.path.relpath(pack, workspace))
    else:
        # under a folder named packs: a fixture pack names its own folders only when it lives in one
        pack_copy = os.path.join("packs", os.path.basename(pack_dir), os.path.basename(pack))
    add(copy_tree(pack_dir, os.path.dirname(os.path.join(out, pack_copy)), limit))
    copy_home_bits(home, box_home, limit)
    moment = epoch_of(clock) if clock else float(int(datetime.datetime.now(datetime.UTC).timestamp()))
    with tempfile.TemporaryDirectory(prefix="replay-") as scratch:
        box = _box(scratch, ws, box_home, os.path.join(out, pack_copy))
        told = run_driver(
            kernel_python(kernel, python),
            _job(box, kernel, "describe", moment),
            sandbox_env(box, kernel_python(kernel, python)),
            300,
        )
    records, board = told["records"], told["board"]
    source = os.path.join(workspace, records)
    if not os.path.isdir(source) or not inside(source, workspace):
        raise ReplayError(
            f"this kernel keeps its records in {records}/ and the workspace has no such folder: is it the kernel this workspace runs on?"
        )
    add(copy_tree(source, os.path.join(ws, records), limit))
    meta = {
        "tool": "replay",
        "version": VERSION,
        "clock": moment,
        "clock_iso": iso(moment),
        "records": records,
        "board": board,
        "board_copy": copy_board(home, board, box_home),
        "pack": pack_copy,
        "copied": counts,
        "sparse_mb": sparse_mb,
        "pack_digest": tree_digest(os.path.dirname(os.path.join(out, pack_copy)), limit),
        "counts": record_counts(out, records, board),
    }
    meta["digest"] = hashlib.sha256(
        "\n".join(
            f"{name}:{tree_digest(os.path.join(out, name), limit, times=True)}"
            for name in ("ws", "home", "packs")
            if os.path.isdir(os.path.join(out, name))
        ).encode()
    ).hexdigest()
    write_json(os.path.join(out, "snapshot.json"), meta)
    return meta


# ---- capture ----


def _box(sandbox: str, ws: str, home: str, pack: str) -> dict:
    box = {
        "sandbox": sandbox,
        "ws": ws,
        "home": home,
        "pack": pack,
        "root": os.path.join(sandbox, "root"),
        "user": os.path.join(sandbox, "user"),
        "tmp": os.path.join(sandbox, "tmp"),
        "bin": os.path.join(sandbox, "bin"),
        "reads": os.path.join(sandbox, "forge-reads.json"),
        "calls": os.path.join(sandbox, "calls.jsonl"),
        "answers": os.path.join(sandbox, "answers"),
    }
    for name in ("root", "user", "tmp", "bin", "answers"):
        os.makedirs(box[name], exist_ok=True)
    for path in (os.path.join(box["root"], "wt"), os.path.join(box["root"], "volumes")):
        os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(box["user"], "gnupg"), mode=0o700, exist_ok=True)
    return box


def _both(path: str) -> list:
    """A path as it was given and as the system resolves it (a temp folder is often a link)."""
    return list(dict.fromkeys([path, os.path.realpath(path)]))


def _job(box: dict, kernel: str, mode: str, clock: float, out: str = "", seat: str = "") -> dict:
    places = {
        "{WORKSPACE}": _both(box["ws"]),
        "{HERMES_HOME}": _both(box["home"]),
        "{ROOT}": _both(box["root"]),
        "{HOME}": _both(box["user"]),
        "{TMP}": _both(box["tmp"]),
        "{PACK}": _both(os.path.dirname(box["pack"])),
        "{SANDBOX}": _both(box["sandbox"]),
        "{KERNEL}": _both(kernel),
        "{REPLAY}": _both(SUPPORT),
    }
    return {
        "mode": mode,
        "kernel": kernel,
        "clock": clock,
        "out": out,
        "pack": box["pack"],
        "seat": seat,
        "places": places,
        "watched": {"{WORKSPACE}": box["ws"], "{HERMES_HOME}": box["home"], "{ROOT}": box["root"]},
        "commands": os.path.join(SUPPORT, "commands.txt"),
        "answer": os.path.join(box["answers"], f"{mode}{'-' + seat if seat else ''}.json"),
        "env": {
            "COCKPIT_WORKSPACE": box["ws"],
            "COCKPIT_HERMES_HOME": box["home"],
            "COCKPIT_WT": os.path.join(box["root"], "wt"),
            "COCKPIT_VOLUMES": os.path.join(box["root"], "volumes"),
        },
    }


def outward(box: dict, network: list, places: dict) -> dict:
    """What the kernel tried to reach, by view: each stand-in's calls, counted, and the addresses it tried itself."""
    by_view = {}
    writes = 0
    if os.path.isfile(box["calls"]):
        for line in open(box["calls"], encoding="utf-8"):
            try:
                call = json.loads(line)
            except ValueError:
                continue
            what = f"{call.get('tool')} {call.get('kind')}: {call.get('what')}"
            for token, paths in places.items():
                for path in sorted(paths, key=len, reverse=True):
                    what = what.replace(path, token)
            counts = by_view.setdefault(call.get("view") or "", {})
            counts[what] = counts.get(what, 0) + 1
            writes += call.get("kind") == "write"
    return {"calls": by_view, "network": sorted(network), "forge_writes_refused": writes}


def capture(
    kernel: str, snapshot_dir: str, out: str, clock: str = "", python: str = "", timeout: int = 3600, keep: bool = False
) -> dict:
    """One kernel's answers over a fresh copy of the snapshot. The snapshot is only read; the copy is thrown away."""
    kernel = os.path.realpath(kernel)
    if not os.path.isdir(os.path.join(kernel, "kernel", "cockpitlib")):
        raise ReplayError(f"{kernel} is not a kernel checkout (no kernel/cockpitlib)")
    try:
        meta = read_json(os.path.join(snapshot_dir, "snapshot.json"))
    except (OSError, ValueError) as exc:
        raise ReplayError(
            f"{snapshot_dir} is not a snapshot (no snapshot.json): make one with `replay snapshot`"
        ) from exc
    if inside(out, snapshot_dir):
        raise ReplayError("the capture folder is inside the snapshot: name a folder elsewhere")
    out = empty_folder(out, "the capture folder")
    python = kernel_python(kernel, python)
    moment = epoch_of(clock) if clock else float(meta["clock"])
    limit = int(meta.get("sparse_mb") or SPARSE_MB) << 20
    sandbox = tempfile.mkdtemp(prefix="replay-", dir=os.path.realpath(tempfile.gettempdir()))
    try:
        for name in ("ws", "home", "packs"):
            if os.path.isdir(os.path.join(snapshot_dir, name)):
                copy_tree(os.path.join(snapshot_dir, name), os.path.join(sandbox, name), limit)
        os.makedirs(os.path.join(sandbox, "home"), exist_ok=True)
        box = _box(
            sandbox, os.path.join(sandbox, "ws"), os.path.join(sandbox, "home"), os.path.join(sandbox, meta["pack"])
        )
        write_json(box["reads"], forge_reads(os.path.join(box["ws"], meta["records"])))
        stand_ins(box, python)
        env = sandbox_env(box, python)
        job = _job(box, kernel, "views", moment, out)
        answers = [run_driver(python, job, env, timeout)]
        for seat, lane in SEATS:
            seat_env = {**env, **({"COCKPIT_LANE": lane} if lane else {})}
            answers.append(run_driver(python, _job(box, kernel, "fence", moment, out, seat), seat_env, timeout))
        tried = outward(
            box, sorted({item for answer in answers for item in answer.get("network") or []}), job["places"]
        )
        os.makedirs(os.path.join(out, "views", "effects"), exist_ok=True)
        write_json(os.path.join(out, "views", "effects", "outward.json"), {"result": tried})
    finally:
        if keep:
            print(f"replay: the sandbox is kept at {sandbox}", file=sys.stderr)
        else:
            shutil.rmtree(sandbox, ignore_errors=True)
    files = {os.path.relpath(path, out): sha256_file(path) for path in walk_files(os.path.join(out, "views"))}
    skipped, errors = {}, []
    for answer in answers:
        skipped.update(answer.get("skipped") or {})
        errors += answer.get("errors") or []
    manifest = {
        "tool": "replay",
        "version": VERSION,
        "kernel": {**kernel_identity(kernel), "path": kernel},
        "clock": moment,
        "clock_iso": iso(moment),
        "pack_digest": meta["pack_digest"],
        "snapshot_digest": meta["digest"],
        "counts": meta["counts"],
        "views": len(files),
        "files": files,
        "skipped": skipped,
        "errors": sorted(errors),
        "forge_writes_refused": tried["forge_writes_refused"],
        "network_attempts": len(tried["network"]),
    }
    write_json(os.path.join(out, "manifest.json"), manifest)
    return manifest


# ---- compare ----


def _show(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 120 else text[:117] + "..."


def differences(left, right, path: str = "$", found=None) -> list:
    """Where two JSON values differ: [(json path, what)]. A list is compared place by place, and its length too."""
    found = [] if found is None else found
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            where = f"{path}.{key}"
            if key not in left:
                found.append((where, f"only in B: {_show(right[key])}"))
            elif key not in right:
                found.append((where, f"only in A: {_show(left[key])}"))
            else:
                differences(left[key], right[key], where, found)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            found.append((f"{path}.length", f"{len(left)} -> {len(right)}"))
        for index, (one, other) in enumerate(zip(left, right)):
            differences(one, other, f"{path}[{index}]", found)
    elif left != right or type(left) is not type(right):
        found.append((path, f"{_show(left)} -> {_show(right)}"))
    return found


def load_allow(path: str) -> list:
    """The reviewed differences: [{file, path, reason}], each a file glob and a JSON-path glob with why it is expected."""
    if not path:
        return []
    try:
        rules = read_json(path)
    except (OSError, ValueError) as exc:
        raise ReplayError(
            f'--allow {path}: a JSON list of {{"file": glob, "path": glob, "reason": text}} is wanted'
        ) from exc
    if not isinstance(rules, list) or any(
        not isinstance(rule, dict)
        or not str(rule.get("file") or "")
        or not str(rule.get("path") or "")
        or not str(rule.get("reason") or "").strip()
        for rule in rules
    ):
        raise ReplayError(f"--allow {path}: each entry names a file glob, a path glob and a reason")
    return rules


def glob(pattern: str, text: str) -> bool:
    """`*` is any run of characters; everything else is itself (a JSON path's brackets are not a character class)."""
    return re.fullmatch(".*".join(re.escape(part) for part in str(pattern).split("*")), text, re.S) is not None


def allowed(rules: list, name: str, where: str) -> bool:
    return any(glob(rule["file"], name) and glob(rule["path"], where) for rule in rules)


def compare(first: str, second: str, allow: str = "", across: bool = False) -> dict:
    """Two captures, file by file. {result: identical | allowed | different, files, different, differences, allowed, lines}.
    `across`: the two were cut from different snapshots on purpose (what does a change of records do to the views)."""
    try:
        one, other = read_json(os.path.join(first, "manifest.json")), read_json(os.path.join(second, "manifest.json"))
    except (OSError, ValueError) as exc:
        raise ReplayError(f"not a capture (no manifest.json): {exc}") from exc
    for key, what in (
        ("version", "tool versions"),
        ("snapshot_digest", "snapshots"),
        ("clock", "clocks"),
        ("pack_digest", "packs"),
    ):
        if one.get(key) != other.get(key) and not (across and key != "version"):
            raise ReplayError(
                f"the two captures are not of the same replay: their {what} differ. Capture both kernels from one snapshot."
            )
    for folder, manifest in ((first, one), (second, other)):
        for name, digest in manifest["files"].items():
            if not os.path.isfile(os.path.join(folder, name)) or sha256_file(os.path.join(folder, name)) != digest:
                raise ReplayError(f"{os.path.join(folder, name)} is not the file its manifest names: capture again")
    rules = load_allow(allow)
    lines, differing, total, excused = [], 0, 0, 0
    for name in sorted(set(one["files"]) | set(other["files"])):
        if one["files"].get(name) == other["files"].get(name):
            continue
        if name not in one["files"] or name not in other["files"]:
            found = [("$", f"only in {'B' if name not in one['files'] else 'A'}")]
        else:
            found = differences(read_json(os.path.join(first, name)), read_json(os.path.join(second, name)))
        open_ = [(where, what) for where, what in found if not allowed(rules, name, where)]
        total += len(found)
        excused += len(found) - len(open_)
        if not open_:
            continue
        differing += 1
        lines.append(f"{name}: {len(open_)} difference(s)")
        lines += [f"  {where}: {what}" for where, what in open_[:DIFFS_SHOWN]]
        if len(open_) > DIFFS_SHOWN:
            lines.append(f"  ... and {len(open_) - DIFFS_SHOWN} more")
    for name in sorted(set(one.get("skipped") or {}) ^ set(other.get("skipped") or {})):
        side = "A" if name in (one.get("skipped") or {}) else "B"
        lines.append(
            f"skipped only in {side}: {name} ({(one.get('skipped') or {}).get(name) or (other.get('skipped') or {}).get(name)})"
        )
    result = "different" if differing else "allowed" if total else "identical"
    return {
        "result": result,
        "files": len(set(one["files"]) | set(other["files"])),
        "different": differing,
        "differences": total,
        "allowed": excused,
        "lines": lines,
        "skipped_a": len(one.get("skipped") or {}),
        "skipped_b": len(other.get("skipped") or {}),
    }


# ---- receipt ----

COUNTED = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")


def effective_result(baseline: str, candidate: str) -> dict:
    """Whether the two kernels read the same effective settings from the pack; `unavailable` when one has no such verb."""
    name = os.path.join("views", "pack", "effective.json")
    paths = [os.path.join(folder, name) for folder in (baseline, candidate)]
    if not all(os.path.isfile(path) for path in paths):
        return {"result": "unavailable"}
    found = differences(read_json(paths[0]), read_json(paths[1]))
    return {
        "result": "different" if found else "identical",
        "differences": len(found),
        "baseline": sha256_file(paths[0]),
        "candidate": sha256_file(paths[1]),
    }


def pack_tests(command: str, kernel: str) -> dict:
    """The adopter's own pack tests against the candidate kernel: the exit status and the counts its last lines name."""
    if not command:
        return {"result": "not run"}
    done = subprocess.run(  # noqa: S602 - the pack's own gate command is a shell line, as the kernel runs it
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "COCKPIT_PLUGIN_DIR": kernel},
    )
    counts = {}
    for line in reversed((done.stdout + "\n" + done.stderr).strip().splitlines()[-15:]):
        found = COUNTED.findall(line)
        if found:
            counts = {name.rstrip("s") if name.startswith("error") else name: int(number) for number, name in found}
            break
    return {"result": "passed" if done.returncode == 0 else "failed", "exit": done.returncode, "counts": counts}


def receipt(
    baseline: str, candidate: str, command: str = "", allow: str = "", out: str = "", across: bool = False
) -> dict:
    """What may leave the machine about one adopter's replay: hashes, counts and verdicts. No record, no pack content, no
    ticket, no path."""
    compared = compare(baseline, candidate, allow, across)
    one, other = read_json(os.path.join(baseline, "manifest.json")), read_json(os.path.join(candidate, "manifest.json"))

    def kernel(manifest: dict) -> dict:
        return {key: manifest["kernel"][key] for key in ("commit", "edited", "tree")}

    tests = pack_tests(command, other["kernel"]["path"])
    effective = effective_result(baseline, candidate)
    passed = (
        compared["result"] in ("identical", "allowed")
        and effective["result"] != "different"
        and tests["result"] == "passed"
    )
    found = {
        "tool": "replay",
        "version": VERSION,
        "date": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"),
        "baseline": kernel(one),
        "candidate": kernel(other),
        "pack_digest": one["pack_digest"],
        "snapshot_digest": one["snapshot_digest"],
        "records": one["counts"],
        "effective": effective,
        "replay": {
            key: compared[key]
            for key in ("result", "files", "different", "differences", "allowed", "skipped_a", "skipped_b")
        },
        "replay_errors": {"baseline": len(one.get("errors") or []), "candidate": len(other.get("errors") or [])},
        "forge_writes_refused": {
            "baseline": one.get("forge_writes_refused", 0),
            "candidate": other.get("forge_writes_refused", 0),
        },
        "allow_file": sha256_file(allow) if allow else None,
        "pack_tests": tests,
        "verdict": "accept"
        if passed
        else "incomplete"
        if tests["result"] == "not run" and compared["result"] != "different" and effective["result"] != "different"
        else "refuse",
    }
    if out:
        write_json(out, found)
    return found


# ---- the command line ----


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="scripts/replay", description="Prove a new kernel reads an installation's records as the old one does."
    )
    verbs = top.add_subparsers(dest="verb", required=True)
    home = os.path.expanduser("~/.hermes")

    def source(verb, needed: bool) -> None:
        verb.add_argument("--workspace", required=needed, help="the adopter's workspace (only read)")
        verb.add_argument("--pack", required=needed, help="the adopter's pack.yaml (only read)")
        verb.add_argument(
            "--hermes-home", default=home, help="the runtime's home, for the board (only read; default ~/.hermes)"
        )
        verb.add_argument(
            "--clock", default="", help="the moment the replay runs at (ISO); default: when the snapshot was cut"
        )
        verb.add_argument(
            "--python", default="", help="the interpreter the kernel runs on (default: its .venv, else this one)"
        )
        verb.add_argument(
            "--sparse-mb",
            type=int,
            default=SPARSE_MB,
            help="files larger than this are copied as empty files of the same size",
        )

    cut = verbs.add_parser("snapshot", help="copy the records, the pack and the board, reading only")
    cut.add_argument(
        "--kernel", required=True, help="a kernel checkout, asked which records folder and board the pack names"
    )
    source(cut, True)
    cut.add_argument(
        "--out", required=True, help="a new folder for the snapshot (it holds private records: keep it on this machine)"
    )
    take = verbs.add_parser("capture", help="run one kernel over the snapshot and keep what it answers")
    take.add_argument("--kernel", required=True, help="the kernel checkout to replay")
    take.add_argument(
        "--snapshot", default="", help="a snapshot made by `replay snapshot` (both kernels must use the same one)"
    )
    source(take, False)
    take.add_argument("--out", required=True, help="a new folder for the capture")
    take.add_argument("--timeout", type=int, default=3600, help="seconds each kernel process may take")
    take.add_argument(
        "--keep-sandbox", action="store_true", help="leave the sandbox in place, to look at what a view read"
    )
    both = verbs.add_parser("compare", help="say which answers differ between two captures")
    both.add_argument("a")
    both.add_argument("b")
    both.add_argument("--allow", default="", help="a JSON list of reviewed differences: {file, path, reason}")
    both.add_argument(
        "--across-snapshots",
        action="store_true",
        help="compare captures of two different snapshots (never for a receipt)",
    )
    slip = verbs.add_parser("receipt", help="write the hashes and counts that may leave the machine")
    slip.add_argument("--baseline", required=True)
    slip.add_argument("--candidate", required=True)
    slip.add_argument(
        "--pack-tests",
        default="",
        help="the adopter's own pack test command; it gets COCKPIT_PLUGIN_DIR=<candidate kernel>",
    )
    slip.add_argument("--allow", default="")
    slip.add_argument("--out", required=True)
    return top


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.verb == "snapshot":
            meta = snapshot(
                args.kernel,
                args.workspace,
                args.pack,
                args.hermes_home,
                args.out,
                args.clock,
                args.python,
                args.sparse_mb,
            )
            print(
                f"snapshot at {os.path.abspath(args.out)}: {meta['counts']['intents']} intents, {meta['counts']['qa_tickets']} QA folders, "
                f"{meta['counts']['pr_records']} PR records, {meta['counts']['cards']} cards; clock {meta['clock_iso']}"
            )
            return 0
        if args.verb == "capture":
            if args.snapshot:
                made = capture(
                    args.kernel, args.snapshot, args.out, args.clock, args.python, args.timeout, args.keep_sandbox
                )
            else:
                if not args.workspace or not args.pack:
                    raise ReplayError("capture needs --snapshot <folder>, or --workspace and --pack to cut one first")
                with tempfile.TemporaryDirectory(prefix="replay-snapshot-") as scratch:
                    snapshot(
                        args.kernel,
                        args.workspace,
                        args.pack,
                        args.hermes_home,
                        os.path.join(scratch, "snapshot"),
                        args.clock,
                        args.python,
                        args.sparse_mb,
                    )
                    made = capture(
                        args.kernel,
                        os.path.join(scratch, "snapshot"),
                        args.out,
                        "",
                        args.python,
                        args.timeout,
                        args.keep_sandbox,
                    )
            print(
                f"capture of {made['kernel']['commit'][:12]} at {os.path.abspath(args.out)}: {made['views']} views, "
                f"{len(made['skipped'])} skipped, {len(made['errors'])} raised, {made['forge_writes_refused']} forge writes refused"
            )
            return 0
        if args.verb == "compare":
            found = compare(args.a, args.b, args.allow, args.across_snapshots)
            for line in found["lines"]:
                print(line)
            print(
                f"{found['result']}: {found['files']} views compared, {found['different']} differ, "
                f"{found['differences']} difference(s), {found['allowed']} allowed"
            )
            return 0 if found["result"] != "different" else 1
        found = receipt(args.baseline, args.candidate, args.pack_tests, args.allow, args.out)
        print(
            f"receipt at {os.path.abspath(args.out)}: replay {found['replay']['result']}, effective settings {found['effective']['result']}, "
            f"pack tests {found['pack_tests']['result']}: {found['verdict']}"
        )
        return 0 if found["verdict"] == "accept" else 1
    except ReplayError as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2
