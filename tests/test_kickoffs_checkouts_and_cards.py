# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kickoffs, checkouts and cards: a Test kickoff's plan go, the checkouts a
session opens, a kept stack's cleanup, the treat card's words, the diagnosis on a mechanical CI rework, intake's outline after
the go, a row covered by a failed row, a staging card and the slots, one repo's bumps. Both fixture packs."""

import os
import shutil

import pytest
import yaml

from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _copy_pack(pack_file, tmp_path, change) -> str:
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(data, copied)
    (copied / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


def _block(board, card, reason):
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(board)
    writes.block(card, reason)
    writes.flush()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_go_on_the_offered_test_plan_accepts_it_and_makes_no_done_row(env, pack_file, monkeypatch):
    from cockpitlib.acts import _plan_accepted, answer_card
    from cockpitlib.intents import all_intents
    from cockpitlib.kanban import place_card

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-1701"
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "ready", kind="test", ticket=ticket, pack=pack)
    _block(pack["board"], card, "Test plan ready: 9 rows, go?")
    answer_card(pack, card, "go")
    assert _plan_accepted(ticket) and not any(row["type"] == "ticket-done" for row in all_intents(ticket))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_session_opens_the_tickets_own_checkouts_when_it_has_some(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.acts import session_open
    from cockpitlib.paths import wt

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-1702"
    repo = pack["repos"]["repos"][-1]["name"]
    os.makedirs(os.path.join(wt(), ticket, repo))
    added = []
    monkeypatch.setattr("cockpitlib.ops.worktree_add", lambda _p, tkt, name="": added.append(name) or [])
    monkeypatch.setattr("cockpitlib.slots.warm_slot", lambda *a, **k: None)
    session_open(pack, 1, ticket)
    assert added == [repo]  # not every repo of the pack


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_stack_kept_at_close_is_taken_down_by_the_cleanup_once_idle(bare, pack_file, monkeypatch, tmp_path):
    from cockpitlib.acts import session_close
    from cockpitlib.slots import NoneProvider, read_owner, state_dir, write_owner

    path = _copy_pack(
        pack_file, tmp_path, lambda data, _c: data.setdefault("slots", {}).update(close={"keep_stack": True})
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    write_owner(1, "human")
    session_close(pack, 1)
    marker = os.path.join(state_dir(1), "stack-kept")
    assert os.path.isfile(marker) and read_owner(1) == "free"
    downs = []
    provider = NoneProvider(pack)
    monkeypatch.setattr(provider, "down", lambda slot: downs.append(slot))
    monkeypatch.setattr("cockpitlib.slots.last_active", lambda _slot: 0)
    assert provider.gc(0, 1) == [1] and downs == [1] and not os.path.exists(marker)
    assert provider.gc(0, 1) == []  # a free slot without the mark is left


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_mechanical_ci_rework_carries_the_diagnosis(bare, pack_file, monkeypatch):
    from cockpitlib.cli import main

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    seen = {}
    monkeypatch.setattr("cockpitlib.acts._diagnosis_of", lambda _p, _t, _s: "the formatter flags src/a.ts")
    monkeypatch.setattr(
        "cockpitlib.acts.continue_ticket", lambda _p, tkt, text, **kw: seen.update(text=text) or {"ok": True}
    )
    assert main(["ci", "rework", f"{pack['tracker']['project']}-1703", "abcdef1234"]) == 0
    assert "The analyst's diagnosis:\nthe formatter flags src/a.ts" in seen["text"]
    monkeypatch.setattr("cockpitlib.acts._diagnosis_of", lambda _p, _t, _s: "")
    assert (
        main(["ci", "rework", f"{pack['tracker']['project']}-1703", "abcdef1234"]) == 0
        and "diagnosis" not in seen["text"]
    )


def test_intakes_outline_after_the_go_takes_the_proposals_place_until_work_is_recorded(bare):
    from cockpitlib.plan import append, init, show

    init("T-1704", "# Proposal\nraw", "go")
    init("T-1704", "# Outline\napproved", "go", outline=True)
    assert "approved" in show("T-1704") and "raw" not in show("T-1704") and "Decision" in show("T-1704")
    append("T-1704", "Delivered", "x")
    init("T-1704", "# Later\nnot taken", "go", outline=True)
    assert "not taken" not in show("T-1704")  # once work is recorded the plan stays
    init("T-1704", "# Ignored", "go")
    assert "Ignored" not in show("T-1704")


def test_a_row_covered_by_a_row_that_did_not_pass_is_still_open():
    from cockpitlib.test_flow import unfinished

    rows = [
        {"n": "1", "result": "❌ Fail", "evidence": "evidence/1.png"},
        {"n": "2", "result": "Not run (covered by row 1)", "evidence": ""},
        {"n": "3", "result": "✅ Pass", "evidence": "evidence/3.png"},
        {"n": "4", "result": "Not run", "note": "covered by row 3", "evidence": ""},
    ]
    assert unfinished(rows) == ["2·open"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_whose_environment_has_no_slot_warms_none_and_waits_for_none(env, pack_file, monkeypatch):
    from cockpitlib.housekeeping import _no_slot, slot_assign, warm_waiting

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import place_card

    staging = place_card(
        pack["board"],
        f"{pack['tracker']['project']}-1705: test",
        "tester-1",
        "ready",
        body="Environment: staging (no slot)\n",
    )
    assert _no_slot("x", "Environment: staging (no slot)\n") and not _no_slot(
        "x", "Environment: local (a slot of this machine)\n"
    )
    monkeypatch.setattr("cockpitlib.housekeeping.data_ready", lambda *a, **k: "ready")
    monkeypatch.setattr("cockpitlib.housekeeping._unbound", lambda _n: [1])
    warmed = []
    monkeypatch.setattr("cockpitlib.housekeeping.warm_slot", lambda slot, tkt, owner, _p: warmed.append(tkt))
    monkeypatch.setattr("cockpitlib.housekeeping.claim", lambda _s: None)
    warm_waiting(pack)
    slot_assign(pack)
    from tests.test_slots_plan_gate_and_privileged_lend import _comments

    assert warmed == [] and _comments(pack["board"], staging) == []


def test_the_ci_watch_reads_an_older_records_date():
    from cockpitlib.ci_watch import _epoch

    assert (
        _epoch("2026-10-13T16:40:23+02:00", 0) == 1791902423.0
        and _epoch(12.5, 0) == 12.5
        and _epoch(None, 7) == 7.0
        and _epoch("x", 3) == 0.0
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_publishing_an_intent_a_later_stage_already_published_answers_already_published(env, pack_file, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cockpitlib.intents import save
    from cockpitlib.outbox import create
    from dashboard.cockpit.router import router

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    intent = create(
        pack,
        f"{pack['tracker']['project']}-1706",
        "push-branch",
        "c",
        "p",
        {"repo": pack["repos"]["repos"][0]["name"], "branch": "work/x"},
    )
    intent["status"] = "published"
    intent["receipt"] = {"ok": True, "url": "https://forge.test/pr/1"}
    save(intent)
    app = FastAPI()
    app.include_router(router)
    answer = TestClient(app).post("/publish", json={"id": intent["id"], "confirm": intent["id"]})
    assert (
        answer.status_code == 200
        and answer.json()["receipt"]["already"]
        and answer.json()["receipt"]["url"] == "https://forge.test/pr/1"
    )
