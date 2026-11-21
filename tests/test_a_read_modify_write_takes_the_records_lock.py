# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A change that reads a record and writes it back takes the record's lock, and a record changed underneath is refused.

The lock is a flock on outbox/<ticket>/.lock (or the dot file beside a shared file), re-entrant in one thread, waited
for a bounded time and then refused with a Conflict that names the holder. It is held for re-read, check and write
only; a publish, which is slow, holds a claim kept in the lock file instead. The lock file is no record anywhere.
"""

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from cockpitlib import intents, store
from cockpitlib.errors import CockpitError, Conflict
from cockpitlib.intents import (
    Intent,
    all_intents,
    is_intent_file,
    load,
    next_seq,
    release_seq,
    reserve_seq,
    save,
    settle,
)
from cockpitlib.paths import outbox, receipt_log

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TICKET = "TASK-100"
IID = f"{TICKET}/001-infra-note"
HOLD = (
    f"import sys, time\nsys.path.insert(0, {os.path.join(ROOT, 'kernel')!r})\nfrom cockpitlib import store\n"
    "with store.{how}:\n    {inside}\n    print('held', flush=True)\n    time.sleep(30)\n"
)


def _intent(status="pending") -> dict:
    return {"id": IID, "type": "infra-note", "ticket": TICKET, "status": status, "payload": {"body": "x"}}


class _Other:
    """Another process that holds a lock (and whatever it did inside) until the block ends."""

    def __init__(self, how: str, inside: str = "pass"):
        self.code = HOLD.format(how=how, inside=inside)

    def __enter__(self):
        self.child = subprocess.Popen(
            [sys.executable, "-c", self.code, "outbox", "endorse", "a secret"], stdout=subprocess.PIPE, text=True
        )
        assert self.child.stdout.readline().strip() == "held"
        return self.child

    def __exit__(self, *_exc):
        self.child.kill()
        self.child.wait()


def test_the_lock_is_taken_again_freely_by_its_holder_and_is_gone_when_the_block_ends(bare):
    path = store.ticket_lock(TICKET)
    with store.locked(TICKET) as first:
        with store.locked(TICKET) as second:
            assert first == second and json.load(open(path))["pid"] == os.getpid()
        assert store._HELD[path].depth == 1
    assert store._HELD[path].depth == 0 and store._HELD[path].fd is None
    assert os.path.basename(path) == ".lock" and os.path.dirname(path) == os.path.join(outbox(), TICKET)
    with pytest.raises(CockpitError):
        store.ticket_lock("../elsewhere")


def test_a_writer_waits_a_bounded_time_and_is_then_refused_with_who_holds_the_lock(bare, monkeypatch):
    with _Other(f"locked({TICKET!r})") as other:
        started = time.monotonic()
        with pytest.raises(Conflict) as refused:
            with store.locked(TICKET, wait=0.2):
                pass
        assert 0.15 < time.monotonic() - started < 5
        said = str(refused.value)
        assert f"the intents of {TICKET}" in said and f"pid {other.pid}" in said and "try again" in said
        assert "outbox endorse" in said and "secret" not in said  # the command's words, never an argument's value
        monkeypatch.setattr(store, "WAIT", 0.2)  # the wait every writer has when it names none
        with pytest.raises(Conflict):
            save(_intent())
    with store.locked(TICKET, wait=0.2):  # the holder is gone: the lock is free at once
        pass


def test_a_writer_that_waits_gets_the_lock_when_the_holder_lets_go(bare):
    with _Other(f"locked({TICKET!r})") as other:
        threading.Timer(0.2, other.kill).start()
        with store.locked(TICKET, wait=10):
            pass


def test_two_threads_of_one_process_do_not_hold_the_lock_together(tmp_path):
    path, inside, most = str(tmp_path / "cards.json"), [], []

    def work():
        for _ in range(50):
            with store.locked_file(path):
                inside.append(1)
                most.append(len(inside))
                inside.pop()

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert max(most) == 1 and sorted(os.listdir(tmp_path)) == [".cards.json.lock"]
    held = store._HELD[store.lock_file(path)]
    held.gate.acquire()
    try:
        refused = []
        waiter = threading.Thread(
            target=lambda: refused.append(
                pytest.raises(Conflict, lambda: store.locked_file(path, wait=0.05).__enter__())
            )
        )
        waiter.start()
        waiter.join()
        assert "cards.json: another process is writing" in str(refused[0].value)
    finally:
        held.gate.release()


def test_a_system_without_flock_is_told_so_and_nothing_crashes(bare, monkeypatch):
    monkeypatch.setitem(sys.modules, "fcntl", None)
    with pytest.raises(CockpitError) as refused:
        save(_intent())
    assert "no fcntl" in str(refused.value) and not isinstance(refused.value, Conflict)


def test_a_lock_that_cannot_be_asked_for_is_an_error_and_not_a_wait(bare, monkeypatch):
    import fcntl

    monkeypatch.setattr(fcntl, "flock", lambda *_args: (_ for _ in ()).throw(OSError(5, "no locks here")))
    with pytest.raises(OSError):
        with store.locked(TICKET, wait=0.1):
            pass
    assert store._HELD[store.ticket_lock(TICKET)].depth == 0


def test_an_intent_that_changed_underneath_is_not_written_over(bare):
    save(_intent())
    mine, theirs = load(IID), load(IID)
    assert isinstance(mine, Intent) and mine == _intent() and "seen" not in json.dumps(mine)
    theirs["status"] = "held"
    save(theirs)
    mine["status"] = "endorsed"
    with pytest.raises(Conflict) as refused:
        save(mine)
    assert (
        "it is held now" in str(refused.value)
        and "nothing was written" in str(refused.value)
        and load(IID)["status"] == "held"
    )
    theirs["status"] = "pending"
    save(theirs)  # the copy that was written is the copy that is there: it is saved again without a re-read
    assert load(IID)["status"] == "pending"
    os.remove(intents.path_of(IID))
    with pytest.raises(Conflict) as gone:
        save(theirs)
    assert "it is gone now" in str(gone.value)
    save(dict(theirs))  # a plain record (a new intent, a copy) is written as it always was
    assert [row["id"] for row in all_intents(TICKET)] == [IID] and isinstance(all_intents()[0], Intent)


def test_a_number_is_taken_by_an_empty_file_no_reader_takes_for_an_intent(bare):
    assert reserve_seq(TICKET, "infra-note") == "001" and reserve_seq(TICKET, "open-pr") == "002"
    folder = os.path.join(outbox(), TICKET)
    assert sorted(os.listdir(folder)) == [".lock", "001-infra-note.json", "002-open-pr.json"]
    assert all_intents(TICKET) == [] and next_seq(TICKET) == "003"
    with pytest.raises(FileNotFoundError):
        load(IID)
    release_seq(TICKET, "002", "open-pr")
    release_seq(TICKET, "002", "open-pr")  # twice is nothing
    save(_intent())
    release_seq(TICKET, "001", "infra-note")  # a written intent is never taken away
    assert (
        load(IID) == _intent()
        and next_seq(TICKET) == "002"
        and oct(os.stat(intents.path_of(IID)).st_mode & 0o777) == "0o600"
    )


def test_a_refused_intent_gives_its_number_back(bare, monkeypatch):
    from cockpitlib import outbox as box
    from cockpitlib.pack import load as load_pack
    from tests.support.both_packs import PACKS

    pack, real = load_pack(PACKS[0]), box._prepare
    for error in (CockpitError("not this one"), RuntimeError("the probe broke")):
        monkeypatch.setattr(box, "_prepare", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
        with pytest.raises(type(error)):
            box.create(pack, TICKET, "infra-note", "card", "note", {"body": "x"})
        assert [name for name in os.listdir(os.path.join(outbox(), TICKET)) if not store.scratch(name)] == []
    monkeypatch.setattr(box, "_prepare", real)  # never monkeypatch.undo(): it would drop the test's own workspace too
    assert box.create(pack, TICKET, "infra-note", "card", "note", {"body": "x"})["id"] == IID


def test_an_intent_being_published_elsewhere_is_neither_written_nor_published_under_it(bare):
    save(_intent("endorsed"))
    with _Other(f"locked({TICKET!r})", f"store.claim({TICKET!r}, {IID!r})") as other:
        other.kill()
        other.wait()
        save(load(IID))  # a claim whose process is gone no longer counts
    code = (
        f"import sys, time\nsys.path.insert(0, {os.path.join(ROOT, 'kernel')!r})\nfrom cockpitlib import store\n"
        f"store.claim({TICKET!r}, {IID!r})\nprint('held', flush=True)\ntime.sleep(30)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        for write in (
            lambda: save(load(IID)),
            lambda: save(_intent("dropped")),
            lambda: intents.publishing(load(IID)).__enter__(),
        ):
            with pytest.raises(Conflict) as refused:
                write()
            assert f"{IID} is being published right now (pid {child.pid}" in str(refused.value)
        assert load(IID)["status"] == "endorsed"
    finally:
        child.kill()
        child.wait()


def test_a_publisher_claims_its_intent_only_while_it_runs_and_only_as_it_read_it(bare, monkeypatch):
    save(_intent("endorsed"))
    seen = []

    @intents.claimed
    def execute(intent, forge=None, dry_run=False):
        claims = json.load(open(store.ticket_lock(TICKET))).get("claims") or {}
        seen.append(dict(claims.get(intent["id"]) or {}))
        if not dry_run and len(seen) < 3:
            execute(intent, forge)  # a pair: the same intent again, inside its own claim
        intent["status"] = "published"
        save(intent)  # the claim is this thread's own: its writes go through
        return "out"

    mine = load(IID)
    assert execute(mine, None, dry_run=True) == "out" and seen == [{}]
    save(_intent("endorsed"))
    stale = load(IID)
    stale_twin = load(IID)
    stale_twin["agent_summary"] = "amended meanwhile"
    save(stale_twin)
    with pytest.raises(Conflict):
        execute(stale)  # what the human decided to publish is no longer what the file says
    assert len(seen) == 1
    assert execute(load(IID)) == "out"
    assert [row["depth"] for row in seen[1:]] == [1, 2] and seen[1]["pid"] == os.getpid()
    assert json.load(open(store.ticket_lock(TICKET)))["claims"] == {}
    store.unclaim(TICKET, IID)  # letting go of nothing is nothing
    monkeypatch.setattr(store, "CLAIM_MAX", 0)
    store.claim(TICKET, IID)
    store.refuse_claimed(TICKET, IID)  # a claim past its time no longer counts


def test_the_record_of_what_left_is_written_whatever_the_file_says_and_the_log_says_so(bare):
    save(_intent("endorsed"))
    out, twin = load(IID), load(IID)
    twin["agent_summary"] = "changed"
    save(twin)
    out["status"] = "published"
    settle(out)
    settle(out)
    assert load(IID)["status"] == "published" and "agent_summary" not in load(IID)
    with open(receipt_log(), encoding="utf-8") as handle:
        assert [line.split()[0] for line in handle] == ["OVERWRITE?"]
    settle({**_intent("published"), "id": f"{TICKET}/002-infra-note"})  # a plain record too
    assert load(f"{TICKET}/002-infra-note")["status"] == "published"


def test_a_lock_or_a_temp_file_is_no_record_anywhere(bare, monkeypatch):
    from cockpitlib import state_commit
    from scripts.replay_support import tool

    assert not is_intent_file(".lock") and not is_intent_file(".001-open-pr.json.12.0.abc.tmp")
    for name, own in (
        (".lock", True),
        (".cards.json.lock", True),
        (".001-open-pr.json.7.0.ab12cd.tmp", True),
        ("001-open-pr.json", False),
        ("lock", False),
        (".gitkeep", False),
        ("outbox/TASK-100/.lock", True),
    ):
        assert store.scratch(name) is own and tool.scratch(os.path.basename(name)) is own
    monkeypatch.setattr(state_commit, "records_name", lambda: "hermes")
    assert (
        state_commit._concern("hermes/outbox/TASK-100/.lock") == ""
        and state_commit._concern("hermes/qa/TASK-100/pr/.api-1.json.lock") == ""
    )
    assert state_commit._concern("hermes/outbox/TASK-100/001-open-pr.json") == "ticket:TASK-100"
    save(_intent())
    folder = os.path.join(outbox(), TICKET)
    assert [os.path.basename(path) for path in tool.walk_files(folder)] == ["001-infra-note.json"]
    copy = os.path.join(os.path.dirname(outbox()), "copy")
    tool.copy_tree(folder, copy, 0)
    assert os.listdir(copy) == ["001-infra-note.json"]


def test_the_slot_lock_appears_with_its_holder_in_it_and_is_handed_over_whole(bare):
    from cockpitlib import slots

    assert slots._acquire(1) is True and slots._acquire(1) is False
    path = slots._lock_path(1)
    assert open(path).read() == slots._lock_token() and oct(os.stat(path).st_mode & 0o777) == "0o600"
    slots._hand_lock(1, os.getppid())
    assert open(path).read() == f"{os.getppid()}:0" and os.listdir(os.path.dirname(path)) == ["lock"]
    with pytest.raises(CockpitError):
        slots._acquire(1)
