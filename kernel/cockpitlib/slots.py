# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slot owner files and the three reference providers. CI does not start a runtime."""

import json
import os
import signal
import subprocess
import threading
import time

from .errors import CockpitError
from .fence import outside
from .paths import qa_of, volumes, worktree_of
from .store import append_line, dump_json, write_text


def state_dir(slot: int) -> str:
    return os.path.join(volumes(), f"slot-{slot}")


_STATE_TEMPLATES: dict = {}


def pack_state_dir(slot: int) -> str:
    """The folder the pack's `slots.state_dir` names for this slot, else empty. The scripts behind a pack's slot commands read
    owner and ticket there (the kernel keeps its own record under volumes/slot-N), so a change the kernel makes alone (a session
    handoff or close) is written to both."""
    try:
        from .pack import load
        from .paths import pack_path, root, workspace

        path = pack_path()
        stamp = (path, os.path.getmtime(path))
        if stamp not in _STATE_TEMPLATES:
            _STATE_TEMPLATES.clear()
            _STATE_TEMPLATES[stamp] = str(((load(path).get("slots") or {}).get("state_dir")) or "")
        template = _STATE_TEMPLATES[stamp]
        return template.format(slot=slot, root=root(), workspace=workspace()) if template else ""
    except (OSError, KeyError, IndexError, ValueError, CockpitError):  # no bound pack (a test, a bare call): no mirror
        return ""


def _mirror(slot: int, name: str, text: str) -> None:
    folder = pack_state_dir(slot)
    if not folder or os.path.realpath(folder) == os.path.realpath(state_dir(slot)):
        return
    try:
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, name)
        write_text(target, text)  # whole or not at all: a slot script never reads half a file
    except OSError:
        pass


def read_owner(slot: int) -> str:
    path = os.path.join(state_dir(slot), "owner")
    if not os.path.isfile(path):
        return "free"
    return open(path, encoding="utf-8").read().strip() or "free"


def write_owner(slot: int, owner: str) -> None:
    os.makedirs(state_dir(slot), exist_ok=True)
    write_text(os.path.join(state_dir(slot), "owner"), owner + "\n")
    _mirror(slot, "owner", owner + "\n")


def write_ticket(slot: int, ticket: str) -> None:
    os.makedirs(state_dir(slot), exist_ok=True)
    write_text(os.path.join(state_dir(slot), "ticket"), ticket + "\n")
    _mirror(slot, "ticket", ticket + "\n")


def _runtime_path(slot: int) -> str:
    return os.path.join(state_dir(slot), "runtime.json")


def _read_runtime(slot: int) -> dict:
    path = _runtime_path(slot)
    if not os.path.isfile(path):
        return {}
    try:
        loaded = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _reap(pid: int, timeout: float) -> bool:
    """True when the pid is gone. A zombie is collected. A live process waits out the timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            got, _status = os.waitpid(pid, os.WNOHANG)
        except OSError:
            return True
        if got == pid:
            return True
        if not _pid_alive(pid):
            return True
        time.sleep(0.01)
    return False


def _stop_pid(pid) -> None:
    """SIGTERM first. A process that is still alive is then SIGKILL."""
    if not pid:
        return
    pid = int(pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    if _reap(pid, 0.2):
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return
    _reap(pid, 0.2)


def start_slot_runtime(pack, slot: int) -> dict:
    """Start the pack's slot browser and dev servers with this slot's ports and folders, and remember their pids."""
    provider = CommandProvider(pack)
    browser = (
        provider.argv([str(part) for part in (pack.get("slot_browser") or [])], slot)
        if pack.get("slot_browser")
        else []
    )
    servers = [
        provider.argv([str(part) for part in command], slot) for command in (pack.get("dev_servers") or []) if command
    ]
    record = {"browser": None, "browser_command": browser, "servers": [], "server_commands": servers}
    if browser:
        record["browser"] = subprocess.Popen(browser, start_new_session=True).pid
    for command in servers:
        if not command:
            continue
        record["servers"].append(subprocess.Popen(command, start_new_session=True).pid)
    if record["browser"] or record["servers"]:
        os.makedirs(state_dir(slot), exist_ok=True)
        dump_json(_runtime_path(slot), record)
    return record


def _baseline_path(slot: int) -> str:
    return os.path.join(state_dir(slot), "baseline.json")


def _stores_path(slot: int) -> str:
    return os.path.join(state_dir(slot), "stores.json")


def capture_baseline(pack, slot: int) -> dict:
    """Remember the provider's store snapshot. Reset puts this copy back."""
    stores = []
    for item in (pack or {}).get("stores") or []:
        stores.append(
            {
                "name": str(item.get("name") or ""),
                "present": bool(item.get("present")),
                "capacity": item.get("capacity"),
                "minimum": int(item.get("minimum") or 0),
                "names": [str(label) for label in (item.get("names") or [])],
                "have": [str(label) for label in (item.get("have") or [])],
            }
        )
    record = {"provider": str((pack or {}).get("slot_provider") or "none"), "stores": stores}
    os.makedirs(state_dir(slot), exist_ok=True)
    dump_json(_baseline_path(slot), record)
    _write_stores(slot, stores)
    return record


def _write_stores(slot: int, stores: list) -> None:
    """The slot's copy of the stores. A pack that declares none has no copy: an empty list would read as a copy whose
    stores never loaded, and the slot would never be ready."""
    path = _stores_path(slot)
    if stores:
        dump_json(path, stores)
    elif os.path.isfile(path):
        os.remove(path)


def restore_baseline(slot: int) -> dict:
    """Put the captured stores back and stop processes that were started later."""
    path = _baseline_path(slot)
    if not os.path.isfile(path):
        stop_slot_runtime(slot)
        return {}
    try:
        record = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stop_slot_runtime(slot)
        return {}
    if not isinstance(record, dict):
        stop_slot_runtime(slot)
        return {}
    stop_slot_runtime(slot)
    _write_stores(slot, record.get("stores") or [])
    write_text(os.path.join(state_dir(slot), "state"), "ready\n")
    return record


def stop_slot_runtime(slot: int) -> dict:
    """Stop the slot browser and dev servers. A pid that has already exited is cleared too."""
    record = _read_runtime(slot)
    _stop_pid(record.get("browser"))
    for pid in record.get("servers") or []:
        _stop_pid(pid)
    path = _runtime_path(slot)
    if os.path.isfile(path):
        os.remove(path)
    return {"browser": record.get("browser"), "servers": list(record.get("servers") or [])}


def _slot_secret_path(slot: int) -> str:
    return os.path.join(state_dir(int(slot or 1)), "data", "login.json")


def write_slot_secret(slot: int, secret) -> str:
    """The slot's own data copy. This is not the main runtime and not the demo file."""
    path = _slot_secret_path(slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, secret, mode=0o600)
    return path


def read_slot_secret(slot: int) -> dict:
    """The slot's demo login: data/login.json, else the login.json or demo.json the pack's login command keeps in the
    slot's state folder. {username, email, password} plus whatever else the file says."""
    folder = state_dir(int(slot or 1))
    mirror = pack_state_dir(
        int(slot or 1)
    )  # the pack's own state folder (slots.state_dir), where its login command keeps them
    extra = [os.path.join(mirror, "login.json"), os.path.join(mirror, "demo.json")] if mirror else []
    for path in (
        _slot_secret_path(slot),
        os.path.join(folder, "login.json"),
        os.path.join(folder, "demo.json"),
        *extra,
    ):
        if not os.path.isfile(path):
            continue
        try:
            loaded = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(loaded, dict):
            continue
        # a file that names a username names the login; one with only an email (the login command's note) leaves the account to the record
        return {
            **loaded,
            "username": loaded.get("username") or "",
            "email": loaded.get("email") or loaded.get("username") or "",
        }
    return {}


def keep_stack(slot: int) -> None:
    """A session close that leaves the stack up marks it, so the cleanup takes it down once the slot is idle."""
    os.makedirs(state_dir(int(slot)), exist_ok=True)
    write_text(os.path.join(state_dir(int(slot)), "stack-kept"), "kept\n")


def slot_apps(pack, slot: int, ticket: str = "") -> list:
    """The pack's slots.session_card.apps for one slot: [{name, url, repo}], the URL with {slot}, {ticket} and {port.<name>} filled in."""
    apps = (((pack or {}).get("slots") or {}).get("session_card") or {}).get("apps") or {}
    if not apps:
        return []
    values = CommandProvider(pack).values(int(slot), ticket)
    found = []
    for name, spec in apps.items():
        url = spec.get("url") if isinstance(spec, dict) else spec
        for key, value in values.items():
            url = url.replace("{" + key + "}", str(value))
        found.append({"name": name, "url": url, "repo": (spec.get("repo") if isinstance(spec, dict) else "") or ""})
    return found


def read_ticket(slot: int) -> str:
    path = os.path.join(state_dir(slot), "ticket")
    if not os.path.isfile(path):
        return ""
    return open(path, encoding="utf-8").read().strip()


def slot_of(ticket: str, count: int = 8, but: int = 0) -> int:
    """The slot this ticket is bound to, or 0. One ticket holds one slot."""
    for number in range(1, max(count, 1) + 1):
        if number != but and ticket and read_ticket(number) == ticket and read_owner(number) not in ("free", ""):
            return number
    return 0


def _lock_wait(pack) -> float:
    return float(((pack or {}).get("slots") or {}).get("lock_wait_seconds") or 0)


def warm_slot(slot: int, ticket: str, owner: str, pack=None) -> str:
    """Claim the slot and take its lock, then hand the lock to a detached bring-up (`cockpit slot bringup N`), which
    outlives the process that asked. A slot already warming answers warming."""
    other = slot_of(ticket, but=slot)
    if other:
        raise CockpitError(f"{ticket} is already on slot {other}")
    folder = state_dir(slot)
    os.makedirs(folder, exist_ok=True)
    if lock_busy(slot):
        return "warming"
    _acquire(slot)
    write_owner(slot, owner)
    write_ticket(slot, ticket)
    clear_release_claim(slot)  # a new claim: a release claim marks it again (kickoff._claim_for_release)
    write_text(os.path.join(folder, "state"), "warming\n")
    write_text(os.path.join(folder, "bringup.log"), "started\n")
    touch(slot)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "warming"
    import sys

    from .paths import PLUGIN_ROOT

    with open(os.path.join(folder, "bringup.log"), "a", encoding="utf-8") as log:
        child = subprocess.Popen(
            [sys.executable, os.path.join(PLUGIN_ROOT, "bin", "cockpit"), "slot", "bringup", str(slot)],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    _hand_lock(slot, child.pid)
    return "warming"


READY_POLL_SECONDS = 2.0
READY_LIMIT_SECONDS = 1800


def bringup(slot: int, pack) -> str:
    """The slot's bring-up: the pack's warm command (it may background itself) or its up, then the slot browser and
    dev servers, then the ready command until it answers. The state and the log tail land in the slot folder; a down
    that arrived meanwhile wins."""
    provider = provider_for((pack or {}).get("slot_provider"), pack)
    log = os.path.join(state_dir(slot), "bringup.log")
    state = "failed"
    try:
        has = getattr(provider, "has", lambda _verb: False)
        if has("warm") or has("up"):
            first = provider.run("warm" if has("warm") else "up", slot, read_ticket(slot))
            _log_line(log, f"{first['verb']}: {first['state']} {first['tail']}".strip())
            if first["state"] not in ("ok", "working"):
                return _finish(slot, "failed")
        if (pack or {}).get("slot_browser") or (pack or {}).get("dev_servers"):
            start_slot_runtime(pack, slot)
        deadline = time.time() + READY_LIMIT_SECONDS
        while has("ready"):
            answer = provider.run("ready", slot)
            if answer["state"] == "ok":
                break
            if answer["state"] in ("failed", "dependency down") or time.time() > deadline:
                _log_line(log, f"ready: {answer['state']} {answer['tail']}".strip())
                return _finish(slot, "failed")
            time.sleep(READY_POLL_SECONDS)
        state = "ready"
    except CockpitError as exc:
        _log_line(log, str(exc))
    return _finish(slot, state)


def _log_line(path: str, line: str) -> None:
    append_line(path, line + "\n")


def _finish(slot: int, state: str) -> str:
    mark_ready(slot, state)
    return open(os.path.join(state_dir(slot), "state"), encoding="utf-8").read().strip()


def _lock_path(slot: int) -> str:
    return os.path.join(state_dir(slot), "lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock_token() -> str:
    return f"{os.getpid()}:{threading.get_ident()}"


def _holder(slot: int):
    """(pid, thread) of a live holder, or None. A dead holder's lock is cleared."""
    path = _lock_path(slot)
    try:
        text = open(path, encoding="utf-8").read().strip()
    except OSError:
        return None
    pid_text, _sep, thread = text.partition(":")
    try:
        pid = int(pid_text or "0")
    except ValueError:
        pid = 0
    if not _pid_alive(pid):
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return pid, thread


def lock_busy(slot: int) -> bool:
    """Another process or thread holds the slot lock. The holder itself may still up, reset, or down."""
    holder = _holder(slot)
    if holder is None:
        return False
    return holder != (os.getpid(), str(threading.get_ident()))


def _acquire(slot: int, wait: float = 0.0) -> bool:
    """Take the lock atomically. True when taken now; False when this thread already holds it. A live holder is
    waited for up to wait seconds."""
    path = _lock_path(slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.time() + max(0.0, wait)
    while True:
        try:  # the lock appears with its holder's name in it: nobody reads an empty lock and takes it for a dead one
            write_text(path, _lock_token(), mode=0o600, exclusive=True)
        except FileExistsError:
            holder = _holder(slot)
            if holder == (os.getpid(), str(threading.get_ident())):
                return False
            if holder is None:
                continue
            if time.time() >= deadline:
                raise CockpitError(f"slot {slot} lock is held")  # noqa: B904 - the caller reads the message; the chain is left as it was
            time.sleep(0.05)
            continue
        return True


def _hand_lock(slot: int, pid: int) -> None:
    """The bring-up process holds the lock from here on."""
    write_text(_lock_path(slot), f"{pid}:0")


class _held:
    """Hold the slot lock for one up, reset, or down; wait for another holder up to the pack's lock_wait_seconds."""

    def __init__(self, slot: int, wait: float = 0.0):
        self.slot = slot
        self.wait = wait
        self.took = False

    def __enter__(self):
        self.took = _acquire(self.slot, self.wait)
        return self

    def __exit__(self, *_exc):
        path = _lock_path(self.slot)
        if self.took and os.path.isfile(path):
            os.remove(path)
        return False


def touch(slot: int) -> None:
    """The slot was used now: a tool call on its ticket, a session, a gate, or a warm."""
    os.makedirs(state_dir(slot), exist_ok=True)
    write_text(os.path.join(state_dir(slot), "last_activity"), str(time.time()))


def last_active(slot: int) -> float:
    stamps = []
    for name in ("last_activity", "claim"):
        try:
            stamps.append(float(open(os.path.join(state_dir(slot), name), encoding="utf-8").read().strip()))
        except (OSError, ValueError):
            continue
    return max(stamps, default=0.0)


def touch_ticket(ticket: str, count: int = 8) -> None:
    number = slot_of(ticket, count)
    if number:
        touch(number)


def apply_capacity(pack, slot: int) -> list:
    """Write the pack's current store capacities onto the slot copy. An empty copy is filled here. A pack without stores
    writes nothing."""
    path = _stores_path(slot)
    if not (pack or {}).get("stores"):
        return []
    existing = []
    if os.path.isfile(path):
        try:
            loaded = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = []
        if isinstance(loaded, list):
            existing = [dict(item) for item in loaded if isinstance(item, dict)]
    by_name = {str(item.get("name") or ""): item for item in existing}
    written = []
    for item in (pack or {}).get("stores") or []:
        name = str(item.get("name") or "")
        row = by_name.get(name) or {
            "name": name,
            "present": bool(item.get("present")),
            "have": [str(label) for label in (item.get("have") or [])],
            "minimum": item.get("minimum") or 0,
        }
        row["name"] = name
        row["capacity"] = item.get("capacity")
        row["minimum"] = int(item.get("minimum") or 0)
        row["names"] = [str(label) for label in (item.get("names") or [])]
        written.append(row)
    os.makedirs(state_dir(slot), exist_ok=True)
    dump_json(path, written)
    return written


def slot_up(slot: int, ticket: str, pack=None) -> None:
    from .halt import refuse

    refuse(ticket)
    other = slot_of(ticket, but=slot)
    if other:
        raise CockpitError(f"{ticket} is already on slot {other}")
    with _held(slot, _lock_wait(pack)):
        check_access(slot, ticket)
        write_owner(slot, caller())
        write_ticket(slot, ticket)
        state_path = os.path.join(state_dir(slot), "state")
        if os.path.isfile(state_path) and open(state_path, encoding="utf-8").read().strip() == "down":
            write_text(state_path, "ready\n")
        if pack is not None:
            apply_capacity(pack, slot)


def slot_down(slot: int):
    if lock_busy(slot):
        note_down(slot)
        return "down held"
    with _held(slot):
        path = os.path.join(state_dir(slot), "state")
        if os.path.isfile(path) and open(path, encoding="utf-8").read().strip() == "warming":
            note_down(slot)
            return "down held"
        return None


def down_said(slot: int, held) -> str:
    """What `slot down` answers. It stops the stack and keeps the binding (a ticket keeps its slot while it has cards),
    and a down that arrives during a bring-up only waits for it: a bare "down" for either reads as released while
    `status` shows the slot as before, so the answer says which it was."""
    ticket, owner = read_ticket(slot), read_owner(slot)
    if held == "down held":
        return f"down held: a bring-up holds slot {slot}; it goes down when that ends"
    if ticket and owner not in ("free", ""):
        return f"down: slot {slot} is stopped and still bound to {ticket} ({owner}); `cockpit slot release {slot}` gives it back"
    return "down"


def release(slot: int, pack, provider) -> str:
    """The human gives a slot back: stopped, no owner, no ticket, no claim (what the idle cleanup does). The cleanup
    never frees a ticket that has an open card, so a reservation gone wrong (a kickoff's claim nobody uses) had no way
    out. Not a lane's to do, not during a bring-up, and not from under a card that is running on it."""
    if caller() != "human":
        raise CockpitError("slot release is the human's")
    ticket, owner = read_ticket(slot), read_owner(slot)
    if owner in ("free", "") and not ticket:
        return f"slot {slot} is free"
    if lock_busy(slot):
        raise CockpitError(f"slot {slot}: a bring-up holds it; release it when that ends")
    from .browser_card import RUNNING
    from .kanban import board_cards

    board = str((pack or {}).get("board") or "")
    running = [
        card["id"]
        for card in (board_cards(board) if board else [])
        if card.get("ticket") == ticket and card.get("status") in RUNNING
    ]
    if ticket and running:
        raise CockpitError(f"slot {slot}: {ticket} has a card running ({', '.join(running)}); stop it first")
    with _held(slot):
        provider.free(slot)
    from .store import log

    log(f"SLOT-RELEASE {slot} was {ticket or '-'} ({owner})")
    return f"released slot {slot} (was {ticket or 'unbound'}, {owner})"


def slot_reset(slot: int, pack=None):
    with _held(slot, _lock_wait(pack)):
        restore_baseline(slot)
        _record_reset(slot)
        return None


def note_down(slot: int) -> None:
    """A down that arrives while warm holds the lock. Bring-up must not turn the slot back on."""
    os.makedirs(state_dir(slot), exist_ok=True)
    write_text(os.path.join(state_dir(slot), "down"), "1\n")


def mark_ready(slot: int, state: str) -> None:
    """The bring-up's last word: ready or failed, and the lock is released. A down that landed meanwhile wins."""
    os.makedirs(state_dir(slot), exist_ok=True)
    down = os.path.join(state_dir(slot), "down")
    if state == "ready" and os.path.isfile(down):
        state = "down"
        write_owner(slot, "free")
        write_ticket(slot, "")
        clear_release_claim(slot)
        os.remove(down)
    write_text(os.path.join(state_dir(slot), "state"), state + "\n")
    lock = os.path.join(state_dir(slot), "lock")
    if os.path.isfile(lock):
        os.remove(lock)


def _slot_count(pack) -> int:
    seats = (pack or {}).get("seats")
    if not isinstance(seats, dict):
        return 1
    raw = seats.get("slots")
    if not isinstance(raw, int) or raw < 1:
        return 1
    return raw


def _tester_slot_for(pack, ticket: str) -> int:
    """The slot that already holds this ticket, or the first slot another ticket does not hold."""
    count = _slot_count(pack)
    if ticket:
        for number in range(1, count + 1):
            if read_ticket(number) == ticket:
                return number
    for number in range(1, count + 1):
        bound = read_ticket(number)
        owner = read_owner(number)
        if bound and bound != ticket and owner not in ("free", ""):
            continue
        return number
    return 1


def tester_slot(pack, ticket: str, slot: int = 0) -> None:
    """A tester starts only when this ticket's slot is ready. A human session on that slot stops it."""
    chosen = slot or _tester_slot_for(pack, ticket)
    owner = read_owner(chosen)
    if owner == "human":
        raise CockpitError(f"slot {chosen} is a manual session")
    ready = data_ready(pack, chosen)
    if ready != "ready":
        raise CockpitError(ready)
    answer = ready_answer(chosen, pack)
    if answer != "ready":
        raise CockpitError(answer)
    bound = read_ticket(chosen)
    if bound and bound != ticket and owner not in ("free", ""):
        raise CockpitError(f"slot {chosen} is bound to {bound}")


def _probed(pack, slot: int) -> list:
    """The stores as the pack's probe commands report them on this slot: present, what it has, and its capacity."""
    provider = CommandProvider(pack)
    found = []
    for store in (pack.get("slots") or {}).get("stores") or []:
        probe = provider.run(f"probe-{store['name']}", slot, words=store["probe"])
        answer = probe["out"] if isinstance(probe["out"], dict) else {}
        row = {
            "name": store["name"],
            "present": probe["state"] == "ok" and answer.get("present", True) is not False,
            "have": [str(item) for item in answer.get("have") or []],
            "minimum": int(store.get("minimum") or 0),
            "names": [str(item) for item in store.get("names") or []],
            "capacity": None,
        }
        if store.get("capacity"):
            counted = provider.run(f"capacity-{store['name']}", slot, words=store["capacity"])
            text = str(counted["out"]).strip()
            row["capacity"] = int(text) if counted["state"] == "ok" and text.isdigit() else None
        found.append(row)
    return found


def data_ready(pack, slot: int = 0) -> str:
    """A store is ready when it is present, at its minimum capacity, with its required names. The pack's probes
    answer for a slot when it names them; an empty copy of declared stores is never marked ready (a pack that declares
    none has nothing to copy, so an empty copy left by an older kernel is no refusal)."""
    stores = pack.get("stores") or []
    if slot and ((pack.get("slots") or {}).get("stores")):
        stores = _probed(pack, slot)
        slot = 0
    if slot:
        path = _stores_path(slot)
        if os.path.isfile(path):
            try:
                copied = json.load(open(path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                copied = None
            if copied == [] and stores:
                return "not ready empty copy"
            if isinstance(copied, list) and copied and all(isinstance(item, dict) for item in copied):
                stores = copied
    if not stores:
        return "ready"
    missing = []
    for item in stores:
        name = str(item.get("name") or "?")
        if not item.get("present"):
            missing.append(name)
            continue
        minimum = int(item.get("minimum") or 0)
        capacity = item.get("capacity")
        if minimum and (capacity is None or int(capacity) < minimum):
            missing.append(name)
            continue
        needed = [str(label) for label in (item.get("names") or [])]
        have = {str(label) for label in (item.get("have") or [])}
        if any(label not in have for label in needed):
            missing.append(name)
    if missing:
        return "not ready " + ",".join(missing)
    return "ready"


def ready_answer(slot: int, pack=None) -> str:
    """Ready, the bring-up log tail when the slot failed, or still warming. An empty copy stays unmarked, unless the pack
    given declares no stores (then there is nothing the copy could be missing)."""
    stores = _stores_path(slot)
    if os.path.isfile(stores):
        try:
            copied = json.load(open(stores, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            copied = None
        if copied == [] and (pack is None or (pack or {}).get("stores")):
            return "not ready empty copy"
    path = os.path.join(state_dir(slot), "state")
    if not os.path.isfile(path):
        return "ready"
    state = open(path, encoding="utf-8").read().strip()
    if state == "warming":
        return "still warming"
    if state == "down":
        return "down"
    if state != "failed":
        return "ready"
    log = os.path.join(state_dir(slot), "bringup.log")
    if not os.path.isfile(log):
        return "failed"
    lines = [line.strip() for line in open(log, encoding="utf-8").read().splitlines() if line.strip()]
    if not lines:
        return "failed"
    return " ".join(lines[-5:])


def claim(slot: int) -> None:
    os.makedirs(state_dir(slot), exist_ok=True)
    write_text(os.path.join(state_dir(slot), "claim"), str(time.time()))


def claimed_recently(slot: int, seconds: int = 600) -> bool:
    path = os.path.join(state_dir(slot), "claim")
    if not os.path.isfile(path):
        return False
    try:
        stamp = float(open(path, encoding="utf-8").read().strip())
    except ValueError:
        return False
    return (time.time() - stamp) < seconds


def _record_reset(slot: int) -> None:
    ticket = read_ticket(slot)
    if not ticket:
        return
    folder = qa_of(ticket)
    os.makedirs(folder, exist_ok=True)
    append_line(os.path.join(folder, "reset.log"), f"reset slot {slot}\n")


def caller() -> str:
    lane = os.environ.get("COCKPIT_LANE")
    if lane:
        return f"lane:{lane}"
    return "human"


def check_access(slot: int, ticket: str = "") -> None:
    if outside():
        raise CockpitError("outside the lanes: work on the main checkout")
    owner = read_owner(slot)
    who = caller()
    if owner == "free":
        return
    if owner == "human" and who != "human":
        raise CockpitError(f"slot {slot} is a manual session")
    if owner.startswith("lane:") and who == "human":
        raise CockpitError(f"slot {slot} is busy with the pipeline ({owner})")
    bound = read_ticket(slot)
    if ticket and bound and ticket != bound:
        raise CockpitError(f"slot {slot} is bound to {bound}")


def free_slots(count: int) -> list:
    found = []
    for slot in range(1, count + 1):
        if read_owner(slot) == "free" and not claimed_recently(slot):
            found.append(slot)
    return found


def exec_refused(pack, argv) -> str:
    """The pack's slots.exec_refuse patterns: a command a slot never runs."""
    import re

    text = " ".join(str(word) for word in argv)
    for pattern in ((pack or {}).get("slots") or {}).get("exec_refuse") or []:
        if re.search(pattern, text):
            return "slot exec refused"
    return ""


# A slot a release card claimed (kickoff._claim_for_release) rather than an intake: it keeps no worktree or data warm
# for its ticket, so once that ticket has no open card the next release ticket takes it at once instead of waiting
# for slot gc (one ticket after another, as a release moves). The mark names the claiming ticket; any new claim
# (warm_slot) and every path that frees the slot removes it (clear_release_claim).
RELEASE_MARK = "release-claim"
# How long a release-claimed slot must sit idle (last_active) before it is handed over: the ticket's next step (its
# tester card, placed on the next supervisor tick) keeps the slot it just used.
RELEASE_GRACE_SECONDS = 120


def mark_release_claim(slot: int, ticket: str) -> None:
    folder = state_dir(slot)
    os.makedirs(folder, exist_ok=True)
    write_text(os.path.join(folder, RELEASE_MARK), ticket + "\n")


def clear_release_claim(slot: int) -> None:
    path = os.path.join(state_dir(slot), RELEASE_MARK)
    if os.path.isfile(path):
        os.remove(path)


def release_claim_of(slot: int) -> str:
    """The ticket whose release card claimed the slot, or "" for any other claim."""
    path = os.path.join(state_dir(slot), RELEASE_MARK)
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _open_card_tickets(pack) -> set:
    """Tickets with a card that is not finished, claimed and in_progress included (kanban.OPEN), and scheduled too."""
    from .kanban import OPEN, OPEN_STATUSES, board_cards

    board = str((pack or {}).get("board") or "")
    statuses = set(OPEN) | set(OPEN_STATUSES)
    return {card["ticket"] for card in board_cards(board) if card.get("status") in statuses} if board else set()


def hand_over_release_slots(pack, count: int, ticket: str) -> list:
    """Free one release-claimed slot whose ticket (not this one) has no open card and that has been idle the grace;
    a human's or an intake's slot is never taken, and nothing is freed while a slot is already free. The slots freed,
    for the capacity check that follows.

    This runs inside start_card: a CommandProvider's down is the pack's down command, run synchronously (up to its
    timeout), so the card's start waits for it. A slot whose free fails, or whose lock another process holds, is
    skipped; the slot gc takes it later."""
    count = int(count or 0)
    if free_slots(count):
        return []
    provider = provider_for((pack or {}).get("slot_provider"), pack)
    open_tickets = _open_card_tickets(pack)
    for slot in range(1, count + 1):
        holder = read_ticket(slot)
        if not holder or holder == ticket or release_claim_of(slot) != holder or read_owner(slot) in ("human", "free"):
            continue
        if holder in open_tickets or time.time() - last_active(slot) < RELEASE_GRACE_SECONDS:
            continue
        try:
            with _held(slot):  # no wait: a slot another process holds is skipped
                if release_claim_of(slot) != holder or read_ticket(slot) != holder:
                    continue
                provider.free(slot)
        except Exception:  # noqa: BLE001, S112 - a failing or refused down must never fail the card's start; gc retries the slot
            continue
        return [slot]
    return []


class NoneProvider:
    """Worktrees on the host. No runtime to start."""

    name = "none"

    def __init__(self, pack=None):
        self.pack = pack

    def up(self, slot, ticket):
        slot_up(slot, ticket, self.pack)

    def down(self, slot):
        return slot_down(slot)

    def reset(self, slot):
        return slot_reset(slot, self.pack)

    def status(self, slot=None, count=1):
        slots = [slot] if slot else list(range(1, count + 1))
        return [
            {
                "slot": item,
                "owner": read_owner(item),
                "ticket": read_ticket(item),
                "ready": ready_answer(item, self.pack),
            }
            for item in slots
        ]

    def exec(self, slot, argv):
        if exec_refused(self.pack, argv):
            raise CockpitError("slot exec refused")
        return {"argv": argv, "slot": slot}

    def gc(self, idle_minutes, count):
        """Free lane slots that have been idle. A human session, recent activity, and a ticket that still has an
        open card keep their slot."""
        collected = []
        window = max(0, int(idle_minutes)) * 60
        open_tickets = self._open_tickets()
        for slot in range(1, count + 1):
            owner = read_owner(slot)
            kept = os.path.isfile(os.path.join(state_dir(slot), "stack-kept"))
            if owner == "human" or (owner == "free" and not kept):
                continue
            if time.time() - last_active(slot) < window or read_ticket(slot) in open_tickets:
                continue
            self.free(slot)
            collected.append(slot)
        return collected

    def free(self, slot) -> None:
        """Give the slot back: its runtime stopped and down, no owner, no ticket, no claim (what gc does to an idle slot)."""
        stop_slot_runtime(slot)
        self.down(slot)
        write_owner(slot, "free")
        write_ticket(slot, "")
        clear_release_claim(slot)
        for name in ("stack-kept", "claim"):
            path = os.path.join(state_dir(slot), name)
            if os.path.isfile(path):
                os.remove(path)

    def login(self, ticket, user):
        return {"ticket": ticket, "user": user, "password": "slot-local"}

    def _open_tickets(self) -> set:
        from .kanban import OPEN_STATUSES, board_cards

        board = str((self.pack or {}).get("board") or "")
        return (
            {card["ticket"] for card in board_cards(board) if card.get("status") in OPEN_STATUSES} if board else set()
        )


# A pack command's exit code: 0 ok, 1 failed (its last lines are kept), 2 still working, 3 a dependency is down.
EXIT_STATES = {0: "ok", 1: "failed", 2: "working", 3: "dependency down"}
# Who may run a standard verb when the pack does not say.
VERB_WHO = {"login": "human"}


class CommandProvider(NoneProvider):
    """The pack's slots.commands run each verb. Bookkeeping (owner, ticket, lock) stays the kernel's."""

    name = "command"

    def __init__(self, pack=None):
        super().__init__(pack)
        self.config = (pack or {}).get("slots") or {}

    def values(self, slot, ticket="", repo="") -> dict:
        from .paths import records, root, workspace

        slot = int(slot)
        ticket = ticket or read_ticket(slot)
        found = {
            "slot": str(slot),
            "ticket": ticket,
            "owner": read_owner(slot),
            "repo": repo,
            "records": records(),
            "worktree": worktree_of(ticket) if ticket else "",
        }
        for field in ("state_dir", "data_dir"):
            template = self.config.get(field)
            found[field] = (
                template.format(slot=slot, root=root(), workspace=workspace()) if template else state_dir(slot)
            )
        for name, base in (self.config.get("ports") or {}).items():
            found[f"port.{name}"] = str(int(base) + slot)
        return found

    def argv(self, words, slot, ticket="", args=(), repo="") -> list:
        values = self.values(slot, ticket, repo)
        filled = []
        for word in words:
            if word == "{args...}":
                filled += [str(arg) for arg in args]
                continue
            for name, value in values.items():
                word = word.replace("{" + name + "}", value)
            filled.append(word)
        if filled and "/" in filled[0] and not os.path.isabs(filled[0]):
            filled[0] = os.path.join(self.pack["_dir"], filled[0])
        return filled

    def has(self, verb) -> bool:
        return verb in (self.config.get("commands") or {})

    def _allowed(self, verb, entry) -> None:
        who = entry.get("who") or VERB_WHO.get(verb, "both")
        if who == "human" and caller() != "human":
            raise CockpitError(f"slot {verb} is the human's")
        if who == "lane" and caller() == "human":
            raise CockpitError(f"slot {verb} is a lane's")

    def run(self, verb, slot, ticket="", args=(), words=None, repo="") -> dict:
        """Run one command with COCKPIT_SLOT, COCKPIT_TICKET, COCKPIT_OWNER, and COCKPIT_LANE set."""
        entry = {"argv": words} if words else (self.config.get("commands") or {}).get(verb)
        if not entry:
            raise CockpitError(f"the pack names no slot {verb}")
        if not words:
            self._allowed(verb, entry)
            if args and not entry.get("passthrough"):
                raise CockpitError(f"slot {verb} takes no arguments")
        argv = self.argv(entry["argv"], slot, ticket, args, repo)
        values = self.values(slot, ticket, repo)
        env = {
            **os.environ,
            "COCKPIT_SLOT": values["slot"],
            "COCKPIT_TICKET": values["ticket"],
            "COCKPIT_OWNER": values["owner"],
            "COCKPIT_LANE": os.environ.get("COCKPIT_LANE") or "",
        }
        try:
            done = subprocess.run(argv, capture_output=True, text=True, env=env, check=False, timeout=3600)
            code, out, err = done.returncode, done.stdout or "", done.stderr or ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, out, err = 1, "", str(exc)
        state = EXIT_STATES.get(code, "failed")
        tail = [line for line in (err or out).splitlines() if line.strip()][-5:]
        os.makedirs(state_dir(int(slot)), exist_ok=True)
        with open(os.path.join(state_dir(int(slot)), f"{verb}.log"), "w", encoding="utf-8") as handle:
            handle.write(f"exit {code}\n{out}{err}")
        try:
            parsed = json.loads(out) if out.strip().startswith(("{", "[")) else None
        except ValueError:
            parsed = None
        return {
            "verb": verb,
            "slot": int(slot),
            "code": code,
            "state": state,
            "out": parsed if parsed is not None else out.strip(),
            "tail": " ".join(tail),
        }

    def _checked(self, verb, slot, ticket="", args=()) -> dict:
        result = self.run(verb, slot, ticket, args)
        if result["state"] not in ("ok", "working"):
            raise CockpitError(f"slot {verb} {result['state']}: {result['tail']}".strip(": "))
        return result

    def up(self, slot, ticket):
        slot_up(slot, ticket, self.pack)
        if self.has("up"):
            return self._checked("up", slot, ticket)
        return None

    def down(self, slot):
        held = slot_down(slot)
        if held or not self.has("down"):
            return held
        return self._checked("down", slot)

    def reset(self, slot):
        slot_reset(slot, self.pack)
        if self.has("reset"):
            return self._checked("reset", slot)
        return None

    def ready(self, slot) -> dict:
        """The pack's ready command: ok, failed with its last lines, still working, or a dependency down."""
        if not self.has("ready"):
            answer = ready_answer(slot, self.pack)
            return {
                "state": "ok" if answer == "ready" else ("working" if answer == "still warming" else "failed"),
                "tail": answer,
            }
        return self.run("ready", slot)

    def status(self, slot=None, count=1):
        rows = super().status(slot, count)
        if not self.has("status"):
            return rows
        for row in rows:
            result = self.run("status", row["slot"])
            if isinstance(result["out"], dict):
                row.update(
                    {key: value for key, value in result["out"].items() if key not in ("slot", "owner", "ticket")}
                )
            row["runtime"] = result["state"]
        return rows

    def exec(self, slot, argv):
        if exec_refused(self.pack, argv):
            raise CockpitError("slot exec refused")
        if not self.has("exec"):
            return super().exec(slot, argv)
        return self._checked("exec", slot, args=argv)

    def login(self, ticket, user):
        """The pack's login command sets a demo password on the slot copy. Only the human page shows it."""
        if not self.has("login"):
            return super().login(ticket, user)
        slot = next((number for number in range(1, 9) if read_ticket(number) == ticket), 1)
        result = self._checked(
            "login", slot, ticket, args=[user] if (self.config["commands"]["login"].get("passthrough")) else ()
        )
        answer = result["out"] if isinstance(result["out"], dict) else {}
        return {"ticket": ticket, "user": answer.get("user") or user, "password": answer.get("password") or ""}

    def toggle(self, name, action, slot) -> dict:
        """A per-slot switch the pack defines (slots.toggles). It is the human's."""
        toggles = self.config.get("toggles") or {}
        if name not in toggles or action not in ("on", "off", "status"):
            raise CockpitError(f"no slot toggle {name} {action}")
        if caller() != "human":
            raise CockpitError("slot toggles are the human's")
        return self.run(f"toggle-{name}", slot, words=toggles[name][action])


def provider_for(name, pack=None):
    """The pack's slots.provider (command or none); the old slot_provider names still load."""
    config = (pack or {}).get("slots")
    if isinstance(config, dict) and config.get("provider", "command") == "command":
        return CommandProvider(pack)
    if name in ("none", "", None, "pack") or isinstance(config, dict):
        return NoneProvider(pack)
    raise CockpitError(f"unknown slot provider {name}: use slots.provider command")
