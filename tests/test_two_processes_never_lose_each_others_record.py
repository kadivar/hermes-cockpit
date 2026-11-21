# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Several processes write the same records at once and none loses another's change.

Each test starts real processes (the kernel as a lane, a cron or the CLI runs it) in the test's own workspace and lets
them work on one ticket, one intent, one card index or one file together. What is checked is what is on disk at the
end: every number taken once, every change either there or refused with a Conflict, every card kept, and a reader
that never sees half a file.
"""

import json
import os
import subprocess
import sys
import time

from cockpitlib import store
from cockpitlib.intents import all_intents, load
from cockpitlib.outbox import create
from cockpitlib.pack import load as load_pack
from cockpitlib.paths import outbox, receipt_log
from tests.support.both_packs import PACKS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TICKET = "TASK-100"
PACK = PACKS[0]
# every process waits for the same moment, so they work at once however long each took to start
HEAD = (
    f"import json, os, sys, time\nsys.path.insert(0, {os.path.join(ROOT, 'kernel')!r})\nme = sys.argv[1]\n"
    "time.sleep(max(0.0, float(os.environ['START_AT']) - time.time()))\n"
)


def _run(code: str, count: int, timeout: int = 120) -> list:
    """The printed lines of `count` processes running the same code at once, each told its number."""
    shell = {**os.environ, "START_AT": str(time.time() + 0.1 * count)}
    children = [
        subprocess.Popen(
            [sys.executable, "-c", HEAD + code, str(index)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=shell,
        )
        for index in range(count)
    ]
    lines = []
    for child in children:
        out, err = child.communicate(timeout=timeout)
        assert child.returncode == 0, err[-2000:]
        lines += out.split()
    return lines


CREATE = f"""
from cockpitlib.outbox import create
from cockpitlib.pack import load
pack = load(os.environ["COCKPIT_PACK"])
for index in range(25):
    made = create(pack, {TICKET!r}, "infra-note", "card", f"note {{me}}-{{index}}", {{"body": f"{{me}}-{{index}}"}})
    print(made["id"])
"""


def test_eight_processes_creating_on_one_ticket_each_get_their_own_number(bare):
    ids = _run(CREATE, 8)
    assert len(ids) == 200 and len(set(ids)) == 200, "two creators were given one number"
    folder = os.path.join(outbox(), TICKET)
    files = sorted(name for name in os.listdir(folder) if name.endswith(".json"))
    assert files == [f"{number:03d}-infra-note.json" for number in range(1, 201)]
    bodies = []
    for name in files:
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            record = json.load(handle)  # every intent is whole
        assert record["id"] == f"{TICKET}/{name[:-5]}"
        bodies.append(record["payload"]["body"])
    assert sorted(bodies) == sorted(f"{process}-{index}" for process in range(8) for index in range(25)), (
        "an intent was overwritten"
    )
    assert sorted(row["id"] for row in all_intents(TICKET)) == sorted(ids)
    assert [name for name in os.listdir(folder) if name.startswith(".")] == [
        store.LOCK_NAME
    ]  # the lock, and no temp file


APPEND = f"""
from cockpitlib.errors import Conflict
from cockpitlib.intents import load, save
done = refused = 0
while done < 20:
    intent = load({TICKET!r} + "/001-infra-note")
    intent.setdefault("history", []).append({{"event": f"{{me}}-{{done}}"}})
    try:
        save(intent)
        done += 1
    except Conflict:
        refused += 1
print(refused)
"""


def test_a_change_decided_on_an_older_copy_is_refused_and_none_is_lost(bare):
    create(load_pack(PACK), TICKET, "infra-note", "card", "note", {"body": "x"})
    refused = _run(APPEND, 6)
    events = [row["event"] for row in load(f"{TICKET}/001-infra-note")["history"]]
    assert sorted(events) == sorted(f"{process}-{index}" for process in range(6) for index in range(20)), (
        "a change was lost"
    )
    assert sum(int(count) for count in refused) > 0, "six writers of one record never met: the test proved nothing"


DECIDE = f"""
from cockpitlib.errors import CockpitError, Conflict
from cockpitlib import outbox
iid = {TICKET!r} + "/001-infra-note"
acts = {{"endorse": lambda tag: outbox.endorse(iid, "low", tag, "gatekeeper", "", ""),
        "amend": lambda tag: outbox.amend(iid, summary=tag),
        "hold": lambda tag: outbox.hold(iid, tag)}}
name = ("endorse", "amend", "hold")[int(me) % 3]
for index in range(15):
    tag = f"{{name}}-{{me}}-{{index}}"
    try:
        acts[name](tag)
        print("done:" + tag)
    except Conflict:
        print("conflict:" + tag)
    except CockpitError:   # the act does not fit the status another one left: refused before anything was written
        print("refused:" + tag)
"""


def test_endorse_amend_and_hold_on_one_intent_leave_a_record_one_of_them_made(bare):
    create(load_pack(PACK), TICKET, "infra-note", "card", "note", {"body": "x"})
    lines = _run(DECIDE, 6)
    done = [line.split(":", 1)[1] for line in lines if line.startswith("done:")]
    assert len(lines) == 90 and done, lines[:5]
    final = load(f"{TICKET}/001-infra-note")
    # the record is what the last change to land made of it, whole: never one act's status with another's fields
    if final["status"] == "endorsed":
        assert final["endorsement"]["notes"] in done and "hold" not in final
    elif final["status"] == "held":
        assert final["hold"]["reason"] in done and "endorsement" not in final
    else:
        assert (
            final["status"] == "pending"
            and final["agent_summary"] in done
            and "hold" not in final
            and "endorsement" not in final
        )
    with open(receipt_log(), encoding="utf-8") as handle:
        amends = sum(1 for line in handle if line.startswith("AMEND "))
    assert amends == sum(1 for tag in done if tag.startswith("amend-"))  # an amend that was refused wrote nothing


CARDS = """
from cockpitlib.kanban import mark_card, remember_card
for index in range(25):
    remember_card("board", f"t_{me}_{index}", "worker", "TASK-100", key=f"{me}-{index}")
    mark_card("board", f"t_{me}_{index}", seen=True)
"""


def test_cards_remembered_by_eight_processes_at_once_are_all_in_the_index(bare):
    from cockpitlib.kanban import _index

    _run(CARDS, 8)
    board = _index()["board"]
    assert len(board) == 200
    assert all(
        board[f"t_{process}_{index}"]
        == {"kind": "worker", "ticket": "TASK-100", "key": f"{process}-{index}", "seen": True}
        for process in range(8)
        for index in range(25)
    )


REWRITE = """
from cockpitlib.store import dump_json, write_json
path = sys.argv[2]
for index in range(500):
    (write_json if index % 2 else dump_json)(path, {"n": index, "rows": ["row"] * (index % 50)})
"""


def test_a_reader_never_sees_half_a_record_while_it_is_rewritten_five_hundred_times(tmp_path):
    path = str(tmp_path / "record.json")
    store.dump_json(path, {"n": -1, "rows": []})
    writer = subprocess.Popen(
        [sys.executable, "-c", HEAD + REWRITE, "0", path],
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "START_AT": "0"},
    )
    reads = 0
    while writer.poll() is None:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)  # a decode error here is half a file
        assert len(record["rows"]) == record["n"] % 50 or record["n"] == -1
        reads += 1
    assert writer.returncode == 0, writer.stderr.read()[-2000:]
    assert store.read_json(path)["n"] == 499 and reads > 0 and os.listdir(tmp_path) == ["record.json"]
