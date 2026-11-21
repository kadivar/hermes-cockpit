# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A release worker card and its slot: one slot runs one ticket, and a finished ticket hands its slot on."""

import os
import sys

import pytest

from cockpitlib.pack import load
from tests.support.both_packs import PACKS, _client


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ticket_s_own_idle_slot_is_the_seat_of_its_next_card(env, pack_file, monkeypatch):
    from cockpitlib import plugin_api
    from cockpitlib.errors import Conflict
    from cockpitlib.kanban import place_card
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import write_owner, write_ticket

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 1}})
    ticket, other = f"{pack['tracker']['project']}-508", f"{pack['tracker']['project']}-509"
    write_owner(1, "lane:worker-1")
    write_ticket(1, ticket)
    # the only slot is the ticket's: another ticket's card has no seat, the ticket's own next card has
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", other, policy="release")
    started = plugin_api.start_card("rework", ticket, policy="release")
    assert started["lane"].startswith("worker")
    # while a card of the ticket is working in it, the slot is taken
    running = place_card(pack["board"], f"{ticket}: tester", "tester-1", kind="tester")
    import sqlite3

    from cockpitlib.kanban import db_path

    db = sqlite3.connect(db_path(pack["board"]))
    db.execute("update tasks set status = 'running' where id = ?", (running,))
    db.execute("update tasks set status = 'done' where id = ?", (started["card_id"],))
    db.commit()
    db.close()
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", ticket, policy="release")
    # a human session is never lent to a card
    write_owner(1, "human")
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", ticket, policy="release")


def _card_status(pack, card_id, status):
    import sqlite3

    from cockpitlib.kanban import db_path

    db = sqlite3.connect(db_path(pack["board"]))
    db.execute("update tasks set status = ? where id = ?", (status, card_id))
    db.commit()
    db.close()


def _slot_rows(pack):
    from cockpitlib.slots import provider_for

    return [
        (row["slot"], row["ticket"])
        for row in provider_for(pack.get("slot_provider"), pack).status(count=pack["seats"]["slots"])
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_release_worker_card_takes_the_free_slot_and_one_slot_runs_one_ticket(env, pack_file, monkeypatch):
    """A release starts its worker cards without an intake: the first worker card of a ticket claims the free slot
    the way intake does, so with one slot a second ticket's worker card waits (also right after, in the same process),
    the ticket's own next card is seated by its idle slot, and slot gc frees the slot once the ticket is idle."""
    import time

    from cockpitlib import plugin_api
    from cockpitlib.errors import Conflict
    from cockpitlib.ops import slot_gc
    from cockpitlib.paths import qa
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import free_slots, read_owner, slot_of, state_dir
    from dashboard.cockpit.router import held_slots

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 1}})
    first, second = f"{pack['tracker']['project']}-1510", f"{pack['tracker']['project']}-1511"
    assert free_slots(1) == [1]
    started = plugin_api.start_card("rework", first, body="unit 1", policy="release")
    # (1) the slot is the ticket's, in slot status, the Slots pane and the capacity pane, and its seat owns it
    assert slot_of(first, 1) == 1 and read_owner(1) == started["lane"] and started["lane"] == "worker-1"
    assert _slot_rows(pack) == [(1, first)] and free_slots(1) == []
    assert [(row["slot"], row["ticket"]) for row in _client().get("/slots").json()["slots"]] == [(1, first)]
    assert held_slots(1) == [f"slot 1 is {first}'s"]
    assert not os.path.isfile(os.path.join(qa(), first, "ticket.md")) and not os.path.isfile(
        os.path.join(qa(), first, "trace.md")
    )
    # (2) another ticket's worker card has no seat while the ticket holds the only slot: the same tick, and later
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", second, body="unit 2", policy="release")
    assert plugin_api.board_cards(second) == [] and _slot_rows(pack) == [(1, first)]
    _card_status(pack, started["card_id"], "running")
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", second, body="unit 2", policy="release")
    # (3) the first card is done: the ticket's own next worker card is seated by its idle slot, which it keeps
    _card_status(pack, started["card_id"], "done")
    following = plugin_api.start_card(
        "rework", first, body="unit 1 fix", policy="release", idempotency_key=f"{pack['name']}-1510-fix"
    )
    assert following["card_id"] != started["card_id"] and slot_of(first, 1) == 1 and _slot_rows(pack) == [(1, first)]
    # an open card of the ticket keeps the slot from slot gc, idle or not
    old = time.time() - 24 * 3600
    open(os.path.join(state_dir(1), "last_activity"), "w", encoding="utf-8").write(str(old))
    assert slot_gc(pack) == "slot-gc 0" and slot_of(first, 1) == 1
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", second, body="unit 2", policy="release")
    # (4) every card of the ticket done and the slot idle past idle_minutes: gc frees it and the other ticket starts
    _card_status(pack, following["card_id"], "done")
    open(os.path.join(state_dir(1), "last_activity"), "w", encoding="utf-8").write(str(time.time()))
    assert slot_gc(pack) == "slot-gc 0" and slot_of(first, 1) == 1  # recently active: kept
    open(os.path.join(state_dir(1), "last_activity"), "w", encoding="utf-8").write(str(old))
    assert slot_gc(pack) == "slot-gc 1" and slot_of(first, 1) == 0 and free_slots(1) == [1]
    other = plugin_api.start_card("rework", second, body="unit 2", policy="release")
    assert slot_of(second, 1) == 1 and _slot_rows(pack) == [(1, second)] and other["lane"] == "worker-1"


@pytest.mark.parametrize("pack_file", PACKS)
def test_release_cards_of_other_lanes_and_kickoff_worker_cards_take_no_slot(env, pack_file, monkeypatch):
    """Only a release worker card claims a slot: a release reviewer or analyst card does not, nor does a worker card
    a human kicks off (policy kickoff), and a reviewer card still starts while a worker card holds the slot."""
    from cockpitlib import plugin_api
    from cockpitlib.plan import init
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import free_slots, slot_of

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 1}})
    reviewed, asked = f"{pack['tracker']['project']}-1520", f"{pack['tracker']['project']}-1521"
    # (5) a release reviewer card and a release analyst card leave the slot alone
    review = plugin_api.start_card("review", reviewed, policy="release")
    assert review["lane"].startswith("reviewer") and slot_of(reviewed, 1) == 0 and free_slots(1) == [1]
    analyst = plugin_api.start_card("analyst", asked, policy="release")
    assert analyst["lane"].startswith("analyst") and slot_of(asked, 1) == 0 and free_slots(1) == [1]
    # (6) worker cards a human kicks off are as before: no slot taken, a second ticket's starts too
    kicked, also = f"{pack['tracker']['project']}-1522", f"{pack['tracker']['project']}-1523"
    for ticket in (kicked, also):
        init(ticket, f"# Plan {ticket}", "go")
        assert plugin_api.start_card("rework", ticket)["lane"].startswith("worker") and slot_of(ticket, 1) == 0
    assert free_slots(1) == [1] and _slot_rows(pack) == [(1, "")]
    # a release worker card now holds the slot; the release reviewer card of another ticket still starts
    held = f"{pack['tracker']['project']}-1524"
    plugin_api.start_card("rework", held, policy="release")
    assert slot_of(held, 1) == 1
    from cockpitlib.acts import archive_card

    archive_card(pack, review["card_id"])  # the fixture's one review seat is free again
    again = plugin_api.start_card("review", f"{pack['tracker']['project']}-1525", policy="release")
    assert again["lane"].startswith("reviewer") and slot_of(held, 1) == 1


def test_a_worktree_pack_with_three_slots_works_its_kickoff_flow_as_before(env, monkeypatch):
    """A cockpit-only pack (a worktree runtime, no supervisor, three slots, every card a human kickoff): intake claims a slot, the ticket's
    worker card works in it without a second one, and another ticket's worker card takes none. Release worker cards
    of three tickets fill the three slots, and a fourth waits."""
    from cockpitlib import plugin_api
    from cockpitlib.errors import Conflict
    from cockpitlib.plan import init
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import free_slots, slot_of

    pack_file = PACKS[1]
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert pack["runtime"] == "worktree"
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 3}})
    project = pack["tracker"]["project"]
    intake = plugin_api.start_card("intake", f"{project}-1530", prompt="read it")
    assert intake["lane"].startswith("intake") and slot_of(f"{project}-1530", 3) == 1 and free_slots(3) == [2, 3]
    _card_status(pack, intake["card_id"], "done")
    init(f"{project}-1530", f"# Plan {project}-1530", "go")
    plugin_api.start_card("rework", f"{project}-1530")
    assert slot_of(f"{project}-1530", 3) == 1 and free_slots(3) == [2, 3]
    init(f"{project}-1531", f"# Plan {project}-1531", "go")
    plugin_api.start_card("rework", f"{project}-1531")
    assert slot_of(f"{project}-1531", 3) == 0 and free_slots(3) == [2, 3]
    for number, ticket in ((2, f"{project}-1532"), (3, f"{project}-1533")):
        plugin_api.start_card("rework", ticket, policy="release")
        assert slot_of(ticket, 3) == number
    assert free_slots(3) == []
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", f"{project}-1534", policy="release")


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_seat_chips_colour_follows_the_free_count(env, pack_file, monkeypatch):
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import write_owner, write_ticket

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 1, "intake": 1}})
    dev = lambda: next(flow for flow in _client().get("/capacity").json()["flows"] if flow["key"] == "dev")
    # one seat, all free: green, not the amber of "the last one left"
    shown = dev()
    assert (shown["free"], shown["of"], shown["tone"]) == (1, 1, "ok")
    # the only slot is a ticket's: none free for another ticket, red, and the tooltip names whose it is
    write_owner(1, "lane:worker-1")
    write_ticket(1, f"{pack['tracker']['project']}-511")
    shown = dev()
    assert (shown["free"], shown["tone"]) == (0, "danger") and f"slot 1 is {pack['tracker']['project']}-511's" in shown[
        "why"
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_waiting_on_the_human_keeps_its_seat_unless_the_pack_says_otherwise(
    env, pack_file, monkeypatch, tmp_path
):
    """By default a blocked card holds its seat, as cockpit always did. A pack with capacity.waiting_holds_seat: false
    lets other cards start while one waits for an answer: one question does not freeze every lane."""
    import shutil
    import sqlite3

    from cockpitlib.capacity import caps_for
    from cockpitlib.errors import PackError
    from cockpitlib.kanban import db_path, open_cards, place_card
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 1, "intake": 1}})
    seats = load_settings(pack)["seats"]
    card = place_card(pack["board"], f"{pack['tracker']['project']}-603: intake", "intake", "ready", kind="intake")
    db = sqlite3.connect(db_path(pack["board"]))
    db.execute("update tasks set status = 'blocked' where id = ?", (card,))
    db.commit()
    db.close()
    assert caps_for(pack, seats, 1, open_cards(pack["board"]))["dev"] == 0, "default: the waiting card holds the seat"
    relaxed = {**pack, "capacity": {**(pack.get("capacity") or {}), "waiting_holds_seat": False}}
    assert caps_for(relaxed, seats, 1, open_cards(pack["board"]))["dev"] == 1
    with pytest.raises(PackError, match="waiting_holds_seat"):
        copied = tmp_path / "packs" / pack["name"]  # the packs/<name> layout, so @skills still resolves
        shutil.copytree(os.path.dirname(pack_file), copied)
        (copied / "pack.yaml").write_text(
            (copied / "pack.yaml").read_text(encoding="utf-8") + "\ncapacity:\n  waiting_holds_seat: maybe\n",
            encoding="utf-8",
        )
        load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_per_repo_card_names_its_ticket_before_the_repo_and_warms_no_second_slot(env, pack_file, monkeypatch):
    """A per-repo card title like `TASK-122 web-app: test …` read as ticket `TASK-122 web-app` matches no held slot and
    warms a second one for a ticket already on slot 1; the review-report and unfinished-run steps would look under
    `qa/TASK-122 web-app/` for the same reason. The tracker key is the ticket, as everywhere else in the kernel."""
    from cockpitlib.housekeeping import _report, warm_waiting
    from cockpitlib.kanban import place_card
    from cockpitlib.pack import load
    from cockpitlib.slots import write_owner, write_ticket

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    shaped = dict(pack)
    shaped["seats"] = dict(pack["seats"], slots=2)
    shaped["stores"] = [dict(pack["stores"][0], present=True)]
    monkeypatch.setattr("cockpitlib.housekeeping.data_ready", lambda *a, **k: "ready")
    monkeypatch.setattr("cockpitlib.housekeeping._unbound", lambda _n: [2])
    warmed = []
    monkeypatch.setattr("cockpitlib.housekeeping.warm_slot", lambda slot, tkt, owner, _p: warmed.append((slot, tkt)))
    monkeypatch.setattr("cockpitlib.housekeeping.claim", lambda _s: None)
    place_card(shaped["board"], "TASK-8880 web-app: test pinch-zoom (tester)", "tester-1", "ready")
    write_owner(1, "lane:tester-1")
    write_ticket(1, "TASK-8880")
    write_owner(2, "free")
    write_ticket(2, "")
    assert warm_waiting(shaped) == "0" and warmed == []  # the ticket already holds slot 1
    write_owner(1, "free")
    write_ticket(1, "")
    assert warm_waiting(shaped) == "1" and warmed == [
        (2, "TASK-8880")
    ]  # a free ticket gets a slot under its Jira key, not "TASK-8880 web-app"
    # the review report of a per-repo card is read from qa/<ticket>/review.md
    import os

    from cockpitlib.paths import qa

    os.makedirs(os.path.join(qa(), "TASK-8881"), exist_ok=True)
    open(os.path.join(qa(), "TASK-8881", "review.md"), "w", encoding="utf-8").write("reviewed\n")
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(shaped["board"]))
    assert _report(connection, set(), "t_none", "TASK-8881 api-service: review the change (reviewer)") == "reviewed\n"
    connection.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_release_worker_card_whose_slot_is_still_warming_elsewhere_waits(env, pack_file, monkeypatch):
    """warm_slot answers 'warming' without claiming when another process holds the slot's lock: the release card must
    not start without its slot (the one-slot cap would not hold), it waits for the next tick."""
    from cockpitlib import plugin_api, slots
    from cockpitlib.errors import Conflict
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 1}})
    ticket = f"{pack['tracker']['project']}-1520"
    monkeypatch.setattr(slots, "lock_busy", lambda slot: True)
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", ticket, body="unit", policy="release")
    assert plugin_api.board_cards(ticket) == [] and slots.slot_of(ticket, 1) == 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_release_ticket_done_with_its_slot_hands_it_to_the_next_release_ticket_at_once(env, pack_file, monkeypatch):
    """A release moves ticket to ticket: a slot a release card claimed keeps nothing warm, so once its ticket has no
    open card (claimed and in_progress count as open) and the slot has sat idle a short grace, the next release ticket
    takes it (no slot-gc wait, which cost up to ~10 min per ticket). Within the grace the ticket keeps it for its next
    step. A slot an intake claimed later (the release mark is gone, even if it once was a release slot) and a human's
    slot are never taken."""
    import time

    from cockpitlib import plugin_api
    from cockpitlib.acts import free_ticket_slots
    from cockpitlib.errors import Conflict
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import (
        RELEASE_GRACE_SECONDS,
        RELEASE_MARK,
        free_slots,
        read_ticket,
        slot_of,
        state_dir,
        write_owner,
        write_ticket,
    )

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 1}})
    first, second, third, fourth = (f"{pack['tracker']['project']}-{n}" for n in (1530, 1531, 1532, 1533))
    mark = os.path.join(state_dir(1), RELEASE_MARK)

    def idle(seconds):
        stamp = str(time.time() - seconds)
        for name in ("last_activity", "claim"):
            open(os.path.join(state_dir(1), name), "w", encoding="utf-8").write(stamp)

    assert 30 < RELEASE_GRACE_SECONDS < 200
    started = plugin_api.start_card("rework", first, body="unit 1", policy="release")
    assert open(mark, encoding="utf-8").read().strip() == first  # the mark names the claiming ticket
    idle(200)
    for status in ("ready", "claimed", "in_progress", "running", "blocked"):  # an open card keeps the slot
        _card_status(pack, started["card_id"], status)
        with pytest.raises(Conflict, match="no free dev seat"):
            plugin_api.start_card("rework", second, body="unit 2", policy="release")
        assert slot_of(first, 1) == 1
    _card_status(pack, started["card_id"], "done")
    idle(30)  # done, but used 30 s ago: its next step (the tester card on the next tick) keeps it
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", second, body="unit 2", policy="release")
    assert slot_of(first, 1) == 1
    idle(200)
    other = plugin_api.start_card("rework", second, body="unit 2", policy="release")  # no gc in between
    assert slot_of(second, 1) == 1 and slot_of(first, 1) == 0 and other["card_id"]
    assert open(mark, encoding="utf-8").read().strip() == second
    # the 'claim' stamp went with the free: an old one would hide the slot from free_slots for ten minutes
    _card_status(pack, other["card_id"], "done")
    assert free_ticket_slots(pack, second) == [1] and not os.path.isfile(mark) and free_slots(1) == [1]
    # an intake claims the slot (a real claim): no release mark, so it is never handed over
    intake = plugin_api.start_card("intake", third, prompt="read it")
    assert slot_of(third, 1) == 1 and not os.path.isfile(mark)
    _card_status(pack, intake["card_id"], "done")
    idle(200)
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", fourth, body="unit 4", policy="release")
    assert slot_of(third, 1) == 1
    # a stale mark naming another ticket than the slot's is not a release claim of this ticket
    open(mark, "w", encoding="utf-8").write(first + "\n")
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", fourth, body="unit 4", policy="release")
    assert read_ticket(1) == third
    # a human's slot is never handed over, even with a matching mark
    write_owner(1, "human")
    write_ticket(1, third)
    open(mark, "w", encoding="utf-8").write(third + "\n")
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("rework", fourth, body="unit 4", policy="release")
    assert read_ticket(1) == third


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_release_slot_handover_skips_a_locked_or_failing_slot_and_frees_only_one(env, pack_file, monkeypatch):
    """The handover frees under the slot's lock: a slot another process holds is skipped. A slot whose down fails is
    skipped too and start_card answers no seat rather than raising. With two handable slots only one is freed."""
    import subprocess
    import time

    from cockpitlib import plugin_api, slots
    from cockpitlib.errors import Conflict
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import CockpitError, slot_of, state_dir

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}})
    a, b, c, d = (f"{pack['tracker']['project']}-{n}" for n in (1540, 1541, 1542, 1543))
    cards = [plugin_api.start_card("rework", ticket, body=f"unit {ticket}", policy="release") for ticket in (a, b)]
    assert slot_of(a, 2) == 1 and slot_of(b, 2) == 2
    for card in cards:
        _card_status(pack, card["card_id"], "done")
    for slot in (1, 2):
        open(os.path.join(state_dir(slot), "last_activity"), "w", encoding="utf-8").write(str(time.time() - 200))
    # another live process holds both slots' locks: nothing is freed
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        for slot in (1, 2):
            open(os.path.join(state_dir(slot), "lock"), "w", encoding="utf-8").write(f"{holder.pid}:0")
        with pytest.raises(Conflict, match="no free dev seat"):
            plugin_api.start_card("rework", c, body="unit c", policy="release")
        assert slot_of(a, 2) == 1 and slot_of(b, 2) == 2
    finally:
        holder.kill()
        holder.wait()
    for slot in (1, 2):
        os.remove(os.path.join(state_dir(slot), "lock"))

    # the provider's down fails: the slot is skipped, no error escapes start_card
    def broken(self, slot):
        raise CockpitError("slot down failed: boom")

    downs = (slots.NoneProvider.down, slots.CommandProvider.down)
    slots.NoneProvider.down = slots.CommandProvider.down = broken
    try:
        with pytest.raises(Conflict, match="no free dev seat"):
            plugin_api.start_card("rework", c, body="unit c", policy="release")
    finally:
        slots.NoneProvider.down, slots.CommandProvider.down = downs
    assert slot_of(a, 2) == 1 and slot_of(b, 2) == 2
    # two slots could go: only the first is handed over, the other ticket keeps its slot
    started = plugin_api.start_card("rework", c, body="unit c", policy="release")
    assert started["card_id"] and slot_of(c, 2) == 1 and slot_of(a, 2) == 0 and slot_of(b, 2) == 2


def _release_worker_modes(monkeypatch):
    """The supervisor's worker-lane kinds as it registers them (binding.py): dev and publish, lane worker, bucket dev."""
    from cockpitlib import plugin_api, registry

    monkeypatch.setattr(registry, "_kinds", {})
    monkeypatch.setattr(registry, "_modes", {})
    for kind in ("dev", "publish"):
        plugin_api.register_card_kind(kind, "{ticket}: " + kind, role="worker", owner="supervisor")
        plugin_api.register_kickoff_mode(kind, "worker", capacity_bucket="dev", title_kind=kind, owner="supervisor")


@pytest.mark.parametrize("slots", [1, 2])
@pytest.mark.parametrize("pack_file", PACKS)
def test_a_release_worker_card_waits_while_another_worker_card_of_its_ticket_works_the_slot(
    env, pack_file, slots, monkeypatch
):
    """One slot runs one worker card at a time (owner rule). A ticket spanning several units gets a dev, a publish
    and a ci-check card from the supervisor: while one is ready, claimed or running on the ticket's slot, the next is
    refused 'no free dev seat' (the supervisor retries next tick), even with another slot free; once it ends, the next
    starts. A blocked card of the ticket does no work and does not hold it back (as before)."""
    from cockpitlib import plugin_api
    from cockpitlib.errors import Conflict
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import slot_of

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": slots}})
    _release_worker_modes(monkeypatch)
    ticket = f"{pack['tracker']['project']}-1560"
    first = plugin_api.start_card("dev", ticket, body="unit A", policy="release")
    held = slot_of(ticket, slots)
    assert held
    for status in ("ready", "claimed", "in_progress", "running", "scheduled"):
        _card_status(pack, first["card_id"], status)
        with pytest.raises(Conflict, match="no free dev seat"):
            plugin_api.start_card("publish", ticket, body="unit B", policy="release")
        assert [card["id"] for card in plugin_api.board_cards(ticket)] == [first["card_id"]]
        assert slot_of(ticket, slots) == held
    _card_status(pack, first["card_id"], "blocked")  # waiting on an answer: no work on the slot
    blocked_next = plugin_api.start_card("publish", ticket, body="unit B", policy="release")
    assert blocked_next["card_id"] and slot_of(ticket, slots) == held
    _card_status(pack, blocked_next["card_id"], "done")
    _card_status(pack, first["card_id"], "done")
    second = plugin_api.start_card("publish", ticket, body="unit C", policy="release")
    assert second["card_id"] and slot_of(ticket, slots) == held


@pytest.mark.parametrize("pack_file", PACKS)
def test_release_worker_cards_of_different_tickets_each_take_their_own_slot_as_before(env, pack_file, monkeypatch):
    """Two tickets on two slots run side by side, one worker card each; a third ticket waits for a slot; the second
    card of a ticket waits for its own first card, not for the other ticket's."""
    from cockpitlib import plugin_api
    from cockpitlib.errors import Conflict
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import slot_of

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}})
    _release_worker_modes(monkeypatch)
    a, b, c = (f"{pack['tracker']['project']}-{n}" for n in (1570, 1571, 1572))
    first = plugin_api.start_card("dev", a, body="a", policy="release")
    other = plugin_api.start_card("dev", b, body="b", policy="release")
    assert {slot_of(a, 2), slot_of(b, 2)} == {1, 2}
    for card in (first, other):
        _card_status(pack, card["card_id"], "running")
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("dev", c, body="c", policy="release")
    with pytest.raises(Conflict, match="no free dev seat"):
        plugin_api.start_card("publish", a, body="a2", policy="release")
    _card_status(pack, other["card_id"], "done")
    with pytest.raises(Conflict, match="no free dev seat"):  # b is done; a's own card still works a's slot
        plugin_api.start_card("publish", a, body="a2", policy="release")
    _card_status(pack, first["card_id"], "done")
    assert plugin_api.start_card("publish", a, body="a2", policy="release")["card_id"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_kickoff_policy_worker_card_is_not_held_by_the_release_worker_rule(env, pack_file, monkeypatch):
    """A cockpit-only pack's kickoff (policy kickoff) keeps its capacity rules: a rework the human kicks off while the ticket's other
    worker card runs and a slot is free starts as it did."""
    from cockpitlib import plugin_api
    from cockpitlib.plan import init
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings
    from cockpitlib.slots import write_owner, write_ticket

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}})
    _release_worker_modes(monkeypatch)
    ticket = f"{pack['tracker']['project']}-1580"
    write_owner(1, "lane:worker-1")
    write_ticket(1, ticket)
    init(ticket, "# Plan", "go")
    running = plugin_api.start_card("dev", ticket, body="unit", policy="release")
    _card_status(pack, running["card_id"], "running")
    assert plugin_api.start_card("rework", ticket, prompt="human rework")["card_id"]
