# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Atomic records and the receipt log: the one place a record is written.

A record is a plain file that crons, lanes, the routes and the human's CLI write and read at the same time. Every
writer here puts the bytes in a temp file beside the target, syncs it, and replaces the target in one step, so a
reader sees the old file or the new one and never half of either; reads take no lock.
"""

import contextlib
import errno
import itertools
import json
import os
import re
import stat
import sys
import threading
import time

from .errors import CockpitError, Conflict
from .paths import receipt_log

_COUNT = itertools.count()


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _sync(fd) -> None:
    try:
        os.fsync(fd)
    except OSError as exc:  # a filesystem that cannot sync still gets the write: it worked there before
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise


def _temp(path: str, payload: bytes, mode) -> str:
    """A synced temp file beside the target holding the bytes: it has the target's mode, or for a new file the given
    one (as open() would create it when none is given)."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    try:
        kept = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        kept = None
    if kept is not None and not os.access(path, os.W_OK):  # a file made read-only is not replaced behind its mode
        raise PermissionError(errno.EACCES, "the file is not writable", path)
    temp = os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}.{next(_COUNT)}.{os.urandom(3).hex()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode)
    try:
        try:
            if kept is not None:
                os.fchmod(fd, kept)
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view) :]
            _sync(fd)
        finally:
            os.close(fd)
    except BaseException:
        _drop(temp)
        raise
    return temp


def _drop(temp: str) -> None:
    try:
        os.unlink(temp)
    except OSError:
        pass


def write_bytes(path, payload: bytes, mode=None, exclusive: bool = False) -> None:
    """The file holds exactly these bytes, whole or not at all: an existing file keeps its mode, a link is written
    through, and missing parent folders are made. An exclusive write makes a new file or raises FileExistsError: of two
    writers of one name exactly one wins, and the file is whole from the moment it has its name."""
    path = os.fspath(path)
    if os.path.islink(path):
        path = os.path.realpath(path)
    temp = _temp(path, bytes(payload), mode)
    try:
        if exclusive:
            _link(temp, path)
        else:
            os.replace(temp, path)
    finally:
        _drop(temp)


def _link(temp: str, path: str) -> None:
    """The temp file gets the name only when nothing has it. Where the filesystem has no hard links the name is taken
    with an exclusive create first, and the bytes are moved onto it."""
    try:
        os.link(temp, path)
    except FileExistsError:
        raise
    except OSError:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        os.replace(temp, path)


def write_text(path, text: str, encoding="utf-8", mode=None, exclusive: bool = False) -> None:
    """The file holds exactly this text, whole or not at all. An encoding of None is the one open() would use."""
    import locale

    write_bytes(path, text.encode(encoding or locale.getpreferredencoding(False)), mode, exclusive)


def write_existing_text(path, text: str, encoding="utf-8") -> bool:
    """Replace the text of a file that is already there. A missing file stays missing: a replace would create it.
    True when the text was written."""
    import locale

    path = os.fspath(path)
    if os.path.islink(path):
        path = os.path.realpath(path)
    payload = text.encode(encoding or locale.getpreferredencoding(False))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC)
    except FileNotFoundError:
        return False
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)
    return True


def dump_json(path, data, mode=None, exclusive: bool = False, **dumps) -> None:
    """The file holds exactly what json.dump(data, handle, **dumps) writes, whole or not at all."""
    write_bytes(path, json.dumps(data, **dumps).encode("utf-8"), mode, exclusive)


def write_json(path, data) -> bytes:
    """A record in the kernel's own form (two spaces, sorted keys, a final newline), whole or not at all. A new one is
    private to its owner, as it always was. The bytes written."""
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_bytes(path, payload, 0o600)
    return payload


def copy_file(source, path) -> None:
    """The file holds the bytes of the source, whole or not at all."""
    with open(source, "rb") as handle:
        write_bytes(path, handle.read())


def append_line(path, line: str, encoding="utf-8", mode=None) -> None:
    """The text is added to the end of the file in one write, so two writers never interleave inside a line. A missing
    final newline is added; the folder is made."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = line if line.endswith("\n") else line + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666 if mode is None else mode)
    try:
        os.write(fd, text.encode(encoding))
    finally:
        os.close(fd)


def log(line: str) -> None:
    append_line(receipt_log(), line.rstrip())


# ---- the lock a read-modify-write takes ----
#
# A change that reads a record, decides and writes it back takes the record's lock for exactly that: re-read, check
# that what was decided on is still true, write. Never across the network, a subprocess or a gate run: the slow work
# happens before, on a copy, and the lock is asked for only once the answer is known. Reads take no lock.

LOCK_NAME = ".lock"
WAIT = 30.0  # seconds a writer waits for the lock before it is refused
CLAIM_MAX = 1800  # seconds after which a claim left in a lock file no longer counts
_GUARD = threading.Lock()
_HELD = {}  # lock path -> what this process holds of it


class _Held:
    def __init__(self):
        self.gate, self.fd, self.depth, self.pid = threading.RLock(), None, 0, 0


def scratch(name: str) -> bool:
    """Whether a file in the records is store's own (a lock, a temp file) and no record: never listed, committed or
    compared."""
    name = os.path.basename(name)
    return name.startswith(".") and name.endswith((".lock", ".tmp"))


def lock_file(path) -> str:
    """The lock of one shared file: a dot file beside it."""
    path = os.fspath(path)
    return os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.lock")


def ticket_lock(ticket: str) -> str:
    """The lock of a ticket's intents: outbox/<ticket>/.lock."""
    from .paths import outbox_of, segment

    return outbox_of(
        segment(ticket, "ticket"), LOCK_NAME
    )  # no ticket has no lock: a write never falls back to the outbox's own level


def _who() -> dict:
    """Who holds a lock, for the one who waits: the pid and the command's own words (never an argument's value)."""
    words = [os.path.basename(sys.argv[0] or "python")] if sys.argv else ["python"]
    for word in sys.argv[1:3]:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", word):
            break
        words.append(word)
    return {"pid": os.getpid(), "command": " ".join(words), "since": int(time.time())}


def _lock_data(fd) -> dict:
    try:
        data = json.loads(os.pread(fd, 1 << 20, 0) or b"{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _lock_write(fd, data: dict) -> None:
    payload = json.dumps(data).encode("utf-8")
    os.ftruncate(fd, 0)
    os.pwrite(fd, payload, 0)


def _busy(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            data = json.loads(handle.read() or b"{}")
    except (OSError, ValueError):
        data = {}
    folder = os.path.basename(os.path.dirname(path))
    what = (
        f"the intents of {folder}" if os.path.basename(path) == LOCK_NAME else os.path.basename(path)[1 : -len(".lock")]
    )
    if isinstance(data, dict) and data.get("pid"):
        held = f" (pid {data['pid']}, {data.get('command') or '?'}, for {max(0, int(time.time()) - int(data.get('since') or 0))} s)"
    else:
        held = ""
    return f"{what}: another process is writing{held}; nothing was changed, try again"


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except OSError:  # it is there and is another user's
        return True
    return True


@contextlib.contextmanager
def _flock(path: str, wait=None):
    try:
        import fcntl
    except ImportError as exc:
        raise CockpitError(
            "records cannot be locked on this system (no fcntl): cockpit writes records on macOS and Linux"
        ) from exc
    limit = WAIT if wait is None else wait
    with _GUARD:
        held = _HELD.setdefault(path, _Held())
    if not held.gate.acquire(timeout=max(0.0, limit)):
        raise Conflict(_busy(path))
    try:
        if held.depth == 0 or held.pid != os.getpid():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            deadline, pause = time.monotonic() + limit, 0.001
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EINTR) or time.monotonic() >= deadline:
                        os.close(fd)
                        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EINTR):
                            raise Conflict(_busy(path)) from exc
                        raise
                    time.sleep(pause)
                    pause = min(pause * 2, 0.02)
            held.fd, held.pid, held.depth = fd, os.getpid(), 0
            _lock_write(fd, {**_lock_data(fd), **_who()})
        held.depth += 1
    except BaseException:
        held.gate.release()
        raise
    try:
        yield held.fd
    finally:
        held.depth -= 1
        if held.depth == 0:
            fd, held.fd = held.fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        held.gate.release()


@contextlib.contextmanager
def locked(ticket: str, wait=None):
    """The ticket's intents are this caller's alone inside the block: an exclusive lock on outbox/<ticket>/.lock, taken
    again freely by the same thread, waited for at most `wait` seconds (30) and then refused with a Conflict that names
    the holder. Hold it for re-read, check and write only."""
    with _flock(ticket_lock(ticket), wait) as fd:
        yield fd


@contextlib.contextmanager
def locked_file(path, wait=None):
    """The same for one shared file (watch/cards.json, a watch record): the lock is the dot file beside it."""
    with _flock(lock_file(path), wait) as fd:
        yield fd


def _owner() -> str:
    return f"{os.getpid()}:{threading.get_ident()}"


def claim(ticket: str, name: str) -> None:
    """This thread is doing something slow with the named record (publishing an intent) that others must not write
    under: the claim is kept in the ticket's lock file, so it costs no lock while the slow work runs. Another live
    claim on it is a Conflict."""
    with locked(ticket) as fd:
        refuse_claimed(ticket, name)
        data = _lock_data(fd)
        claims = {key: row for key, row in (data.get("claims") or {}).items() if _claim_counts(row)}
        mine = claims.get(name) or {**_who(), "owner": _owner(), "depth": 0}
        claims[name] = {**mine, "depth": int(mine.get("depth") or 0) + 1}
        _lock_write(fd, {**data, "claims": claims})


def unclaim(ticket: str, name: str) -> None:
    """The slow work is over: the claim goes when its last holder in this thread lets go."""
    with locked(ticket) as fd:
        data = _lock_data(fd)
        claims = dict(data.get("claims") or {})
        mine = claims.get(name)
        if isinstance(mine, dict) and mine.get("owner") == _owner():
            if int(mine.get("depth") or 1) > 1:
                claims[name] = {**mine, "depth": int(mine["depth"]) - 1}
            else:
                claims.pop(name)
            _lock_write(fd, {**data, "claims": claims})


def _claim_counts(row) -> bool:
    return isinstance(row, dict) and _alive(row.get("pid")) and time.time() - int(row.get("since") or 0) < CLAIM_MAX


def refuse_claimed(ticket: str, name: str) -> None:
    """A record another process or thread is doing slow work with is not written under it."""
    with locked(ticket) as fd:
        row = (_lock_data(fd).get("claims") or {}).get(name)
    if _claim_counts(row) and row.get("owner") != _owner():
        raise Conflict(
            f"{name} is being published right now (pid {row.get('pid')}, {row.get('command') or '?'}): "
            "nothing was changed, try again once it is out"
        )


def read_db(path, timeout=None):
    """A connection to one of Hermes's databases (a board's kanban.db, a seat's state.db) that can only read: opened
    read-only, waiting out a writer for `timeout` seconds (sqlite's own five when none is given), and told not to
    write where sqlite knows how. Cockpit never writes these files; a board write goes through Hermes's own functions."""
    import sqlite3

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, **({} if timeout is None else {"timeout": timeout}))
    try:
        connection.execute("PRAGMA query_only = ON")
    except Exception:  # noqa: BLE001, S110 - a belt over mode=ro: a build or a stand-in without it reads all the same
        pass
    return connection
