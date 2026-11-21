# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the test commands a pack lists on each repo. The kernel does not invent them.

Each run has an id, a log, and a record under <records>/qa/<ticket>/gates/. The repo's failures pattern names the
failing tests; `--baseline` records the names already failing on this ticket's slot, and later runs list only new
ones. The exit code is the gate's own. One run per ticket at a time; a gate command already running in one of the
ticket's checkouts (even one started outside cockpit) counts.
"""

import json
import os
import re
import subprocess
import sys
import time

from .paths import qa_of, workspace, worktree_of
from .store import dump_json


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def gates_dir(ticket: str) -> str:
    return qa_of(ticket or "workspace", "gates")


def _record_path(ticket: str, run_id: str) -> str:
    return os.path.join(gates_dir(ticket), f"{run_id}.json")


def _read(path: str) -> dict:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, data)


def _is_gate(argv, command: str) -> bool:
    """The process is that gate command, not a process that merely mentions it."""
    if not argv:
        return False
    program = os.path.basename(argv[0])
    if program in ("bash", "sh") and "-c" in argv:
        index = argv.index("-c") + 1
        if index < len(argv) and argv[index] == command:
            return True
    if argv[0] == command:
        return True
    parts = command.split()
    if parts and argv[: len(parts)] == parts:
        return True
    return False


def _outside(command: str, roots) -> bool:
    """That gate command already running with its working folder inside one of these checkouts. A process
    elsewhere on the machine that happens to run the same command does not count."""
    if not command:
        return False
    real_roots = [os.path.realpath(root) for root in roots if root]
    inside = lambda cwd: any(cwd == root or cwd.startswith(root + os.sep) for root in real_roots)
    me = os.getpid()
    if os.path.isdir("/proc"):
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == me:
                continue
            try:
                raw = open(os.path.join("/proc", name, "cmdline"), "rb").read()
                cwd = os.path.realpath(os.readlink(os.path.join("/proc", name, "cwd")))
            except OSError:
                continue
            argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
            if inside(cwd) and _is_gate(argv, command):
                return True
        return False
    for (
        pid,
        argv,
    ) in _ps_processes():  # no /proc (macOS): ps lists every command line; lsof answers one matching process's folder
        if pid == me or not _is_gate(argv, command):
            continue
        cwd = _cwd_of(pid)
        if cwd and inside(os.path.realpath(cwd)):
            return True
    return False


def _ps_processes() -> list:
    """(pid, argv) for every process, from `ps`. A `bash -c <script>` keeps the script as one argv word, as /proc reports it."""
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,args="], capture_output=True, text=True, check=False, timeout=5
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        words = parts[1].split()
        if len(words) > 2 and os.path.basename(words[0]) in ("bash", "sh") and words[1] == "-c":
            words = words[:2] + [parts[1].split(None, 2)[2]]
        rows.append((int(parts[0]), words))
    return rows


def _cwd_of(pid: int) -> str:
    """A process's working folder through lsof, or "" when lsof is missing or the process is gone."""
    try:
        out = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, check=False, timeout=5
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def _running(ticket: str) -> dict:
    """This ticket's live run, if any."""
    folder = gates_dir(ticket)
    if not os.path.isdir(folder):
        return {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or name == "baseline.json":
            continue
        record = _read(os.path.join(folder, name))
        if record.get("status") == "running" and _alive(int(record.get("pid") or 0)):
            return record
    return {}


def stop_gate(ticket: str) -> str:
    """Stop this ticket's running gate. Another ticket's gate stays running."""
    record = _running(ticket)
    if not record:
        return ""
    from .slots import _stop_pid

    for pid in (record.get("child"), record.get("pid")):
        if pid and int(pid) != os.getpid():
            _stop_pid(int(pid))
    record.update({"status": "stopped", "code": 143})
    _write(_record_path(ticket, record["id"]), record)
    return str(record.get("pid"))


def _gate_folder(pack, repo, ticket: str) -> str:
    """The ticket's checkout of this repo; else the workspace."""
    name = str((repo or {}).get("name") or "")
    folder = worktree_of(ticket, name) if ticket and name else ""
    if folder and os.path.isdir(folder):
        return folder
    return workspace()


def _slot_key(ticket: str) -> str:
    from .slots import slot_of

    number = slot_of(ticket)
    return f"slot-{number}" if number else "no-slot"


def _baseline_path(ticket: str) -> str:
    return os.path.join(gates_dir(ticket), "baseline.json")


def baseline(ticket: str) -> list:
    return list((_read(_baseline_path(ticket)).get(_slot_key(ticket))) or [])


def _failures(repo, text: str) -> list:
    """The failing test names the repo's failures pattern finds (its first group, else the whole match)."""
    found = []
    for pattern in (repo or {}).get("failures") or []:
        for match in re.finditer(pattern, text, re.MULTILINE):
            name = (match.group(1) if match.groups() else match.group(0)).strip()
            if name and name not in found:
                found.append(name)
    return found


def _repos(pack, repo_name: str) -> list:
    repos = (pack.get("repos") or {}).get("repos") or []
    if repo_name:
        repos = [repo for repo in repos if repo.get("name") == repo_name]
    return repos


def run_gates(pack, repo_name: str = "", record_baseline: bool = False, run_id: str = "", ticket: str = "") -> tuple:
    """Run every gate of the ticket's repos (or the one named). (exit code, lines). The ticket is the one given, else
    the caller's card's; each gate runs with COCKPIT_TICKET set to it."""
    from .skill_log import current_ticket
    from .slots import touch_ticket

    ticket = ticket or current_ticket()
    repos = _repos(pack, repo_name)
    if repo_name and not repos:
        return 2, [f"unknown repo {repo_name}"]
    live = _running(ticket)
    if live and live.get("id") != run_id:
        return 1, [f"gate already running ({live['id']})"]
    roots = [_gate_folder(pack, repo, ticket) for repo in repos]
    if not repo_name:
        repos, roots = _ticket_repos(repos, roots, ticket)
    for repo, root in zip(repos, roots):
        for command in repo.get("gates") or []:
            if _outside(command, [root]):
                return 1, ["gate already running"]
    touch_ticket(ticket)
    run_id = run_id or time.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    record = {"id": run_id, "ticket": ticket, "pid": os.getpid(), "status": "running", "started": int(time.time())}
    _write(_record_path(ticket, run_id), record)
    log_path = os.path.join(gates_dir(ticket), f"{run_id}.log")
    try:
        code, lines, failing = _run(pack, repos, roots, log_path, record, ticket)
    except BaseException:
        record.update({"status": "done", "code": 1})
        _write(_record_path(ticket, run_id), record)
        raise
    known = baseline(ticket)
    if record_baseline:
        saved = _read(_baseline_path(ticket))
        saved[_slot_key(ticket)] = failing
        _write(_baseline_path(ticket), saved)
        known = failing
        lines.append(f"baseline: {len(failing)} known failures")
    new = [name for name in failing if name not in known]
    lines += [f"new failure: {name}" for name in new]
    if failing and not new and not record_baseline:
        lines.append(f"only known failures ({len(failing)})")
    record.update({"status": "done", "code": code, "failures": failing, "new": new, "log": log_path, "lines": lines})
    _write(_record_path(ticket, run_id), record)
    return code, lines + [f"log: {log_path}"]


def _ticket_repos(repos, roots, ticket: str) -> tuple:
    """The repos a gate run covers: the ones the ticket has a checkout of (or a source on a ticket branch). A repo
    that falls back to the workspace holds nothing of the ticket's to gate, and its tools fail there. When the ticket
    has no checkout at all, every repo runs, as before."""
    if not ticket:
        return repos, roots
    from .paths import workspace

    base = os.path.realpath(workspace())
    kept = [(repo, root) for repo, root in zip(repos, roots) if os.path.realpath(root) != base]
    if not kept:
        return repos, roots
    return [repo for repo, _root in kept], [root for _repo, root in kept]


def _run(pack, repos, roots, log_path, record, ticket) -> tuple:
    lines = []
    failing = []
    code = 0
    ran = False
    with open(log_path, "a", encoding="utf-8") as log:
        for repo, folder in zip(repos, roots):
            for command in repo.get("gates") or []:
                ran = True
                log.write(f"$ ({repo.get('name')}) {command}\n")
                log.flush()
                proc = subprocess.Popen(
                    ["bash", "-o", "pipefail", "-c", command],
                    cwd=folder,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    env={**os.environ, "COCKPIT_TICKET": ticket} if ticket else None,
                )
                record["child"] = proc.pid
                _write(_record_path(ticket, record["id"]), record)
                output, _ = proc.communicate()
                log.write(output or "")
                log.flush()
                status = proc.returncode if proc.returncode is not None else 1
                tail = (output or "").strip().splitlines()[-1:] or [""]
                lines.append(
                    f"{repo.get('name')}: {'ok' if status == 0 else 'failed'} {command}"
                    + (f" — {tail[0]}" if tail[0] else "")
                )
                failing += [name for name in _failures(repo, output or "") if name not in failing]
                if status != 0 and not code:
                    code = status
    if not ran:
        return 1, ["no repo gates"], []
    return code, lines, failing


def start_background(pack, repo_name: str = "", record_baseline: bool = False) -> str:
    """Start the run in its own session and answer its id at once. `cockpit gate --wait ID` collects it."""
    from .paths import PLUGIN_ROOT
    from .skill_log import current_ticket

    ticket = current_ticket()
    live = _running(ticket)
    if live:
        return ""
    run_id = time.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}-bg"
    argv = [sys.executable, os.path.join(PLUGIN_ROOT, "bin", "cockpit"), "gate", "--run-id", run_id]
    if repo_name:
        argv += ["--repo", repo_name]
    if record_baseline:
        argv.append("--baseline")
    os.makedirs(gates_dir(ticket), exist_ok=True)
    env = {**os.environ, "COCKPIT_TICKET": ticket}
    child = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    _write(
        _record_path(ticket, run_id),
        {"id": run_id, "ticket": ticket, "pid": child.pid, "status": "running", "started": int(time.time())},
    )
    return run_id


def wait(run_id: str, timeout: float = 3600.0) -> tuple:
    """Block until that run of this ticket ends. Its exit code and lines."""
    from .skill_log import current_ticket

    path = _record_path(current_ticket(), run_id)
    deadline = time.time() + timeout
    while True:
        record = _read(path)
        if not record:
            return 2, [f"no gate run {run_id}"]
        if record.get("status") != "running":
            return int(record.get("code") or 0), list(record.get("lines") or []) + [f"log: {record.get('log', '')}"]
        if not _alive(int(record.get("pid") or 0)):
            return 1, [f"gate run {run_id} ended without a result"]
        if time.time() > deadline:
            return 2, [f"gate run {run_id} still running"]
        time.sleep(0.2)
