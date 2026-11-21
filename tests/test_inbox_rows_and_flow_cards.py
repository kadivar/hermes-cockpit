# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Inbox and the flows as the human relies on them: the rows that ask the human, what each answer does,
and the cards a flow makes. Both fixture packs."""

import json
import os
import shutil
import sqlite3

import pytest
import yaml

from cockpitlib.errors import CockpitError, Conflict
from cockpitlib.pack import load
from tests.support import words
from tests.support.boards import put_card, raw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _status(board, card):
    from cockpitlib.kanban import board_cards

    return {item["id"]: item["status"] for item in board_cards(board)}[card]


def _block(board, card, reason):
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(board)
    writes.block(card, reason)
    writes.flush()


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _copy_pack(pack_file, tmp_path, change) -> str:
    """The fixture pack with one change, loaded from a copy."""
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(data, copied)
    (copied / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_refusal_waits_for_its_card_then_is_sent_back_or_dismissed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import refusals

    ticket = f"{pack['tracker']['project']}-501"
    card = put_card(pack["board"], f"{ticket}: work", "worker-1", "running")
    refusals.record(ticket, "open-pr", card, "worker-1", "the body names no plan", intent=f"{ticket}/001-open-pr")
    assert refusals.unresolved(pack) == []  # the card may still put it right
    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'done' where id = ?", (card,))
    connection.commit()
    connection.close()
    rows = refusals.unresolved(pack)
    assert [row["type"] for row in rows] == ["open-pr"] and rows[0]["card_status"] == "done" and rows[0]["time"]
    assert _client().get("/refusals").json()["refusals"][0]["key"] == rows[0]["key"]
    answer = _client().post("/refusal-send-back", json={"key": rows[0]["key"], "note": "add the plan link"}).json()
    from cockpitlib.kanban import board_cards

    made = next(item for item in board_cards(pack["board"]) if item["id"] == answer["card_id"])
    assert "the body names no plan" in made["body"] and "Human: add the plan link" in made["body"] and answer["out"]
    assert refusals.unresolved(pack) == []  # sent back: the row leaves
    refusals.record(ticket, "tracker-comment", "", "tester-1", "no results")
    key = refusals.unresolved(pack)[0]["key"]
    assert _client().post("/refusal-dismiss", json={"key": key}).json()["ok"] is True and refusals.find(key) == {}
    assert refusals.dismiss("missing") is False


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_later_intent_of_the_same_type_settles_a_refusal(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import refusals

    ticket = f"{pack['tracker']['project']}-502"
    refusals.record(ticket, "push-branch", "", "worker-1", "the lease moved")
    stamp = refusals.find(refusals.unresolved(pack)[0]["key"])["at"]
    monkeypatch.setattr(
        "cockpitlib.intents.all_intents",
        lambda *a: [{"ticket": ticket, "type": "push-branch", "created_at": stamp + 5}],
    )
    assert refusals.unresolved(pack) == []
    assert refusals._stamp("not a time") == 0.0 and refusals._stamp(12) == 12.0


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_run_that_ended_without_a_board_call_shows_its_error_then_its_last_comment(env, pack_file):
    pack = load(pack_file)
    from cockpitlib.kanban import BoardWrites, block_reason, db_path

    card = put_card(pack["board"], f"{pack['tracker']['project']}-503: work", "worker-1", "triage")
    connection = sqlite3.connect(f"file:{db_path(pack['board'])}?mode=ro", uri=True)
    assert block_reason(connection, card) == ""
    connection.close()
    writes = BoardWrites(pack["board"])
    writes.comment(card, "worker-1", "I stopped: the slot is down")
    writes.flush()
    connection = sqlite3.connect(f"file:{db_path(pack['board'])}?mode=ro", uri=True)
    assert block_reason(connection, card) == "I stopped: the slot is down"
    connection.close()
    setup = raw(pack["board"])
    setup.execute("update tasks set last_failure_error = ? where id = ?", ("exited without a board call", card))
    setup.commit()
    setup.close()
    connection = sqlite3.connect(f"file:{db_path(pack['board'])}?mode=ro", uri=True)
    assert block_reason(connection, card) == "exited without a board call"
    connection.close()


def _results(ticket, rows, pack=None):
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import run_folders, run_pattern

    base = os.path.join(qa(), ticket)
    runs = run_folders(pack, base) if os.path.isdir(base) else []
    folder = os.path.join(base, runs[-1] if runs else run_pattern(pack).format(n=1))
    os.makedirs(folder, exist_ok=True)
    table = "\n".join(
        ["# Run", "", "## Summary", "", "| # | Scenario | Result | Evidence |", "|---|---|---|---|", *rows, ""]
    )
    open(os.path.join(folder, "test-results.md"), "w", encoding="utf-8").write(table)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tester_asking_for_review_of_an_unfinished_run_gets_send_back_not_go(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import open_card_rows
    from cockpitlib.test_flow import run_not_ready

    ticket = f"{pack['tracker']['project']}-504"
    asks = words.worded(pack, "Run 001 ready for your review: 1 pass, 1 fail")
    assert run_not_ready(pack, ticket, "where is the account?") == []
    assert run_not_ready(pack, ticket, asks) == ["(no results table)"]
    _results(
        ticket,
        [
            f"| 1 | login | ✅ | [s]({words.evidence(pack)}/1-login.png) |",
            f"| 2 | report | ❌ | [n]({words.evidence(pack)}/2.md) |",
            "| 3 | export | Not run | |",
        ],
        pack,
    )
    assert run_not_ready(pack, ticket, asks) == ["2·screenshot", "3·open"]
    card = put_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    _block(pack["board"], card, asks)
    row = next(item for item in open_card_rows(pack["board"], pack) if item["id"] == card)
    # a test kickoff's run card: the Fail row also needs its failure video
    assert (
        row["not_ready"] == ["2·screenshot", "3·open", "2·video"] and row["parked"] is False and row["pack_ask"] == {}
    )
    with pytest.raises(Conflict, match="not ready for your go"):
        answer_card(pack, card, "go")
    _results(
        ticket,
        [
            f"| 1 | login | ✅ | [s]({words.evidence(pack)}/1-login.png) |",
            f"| 2 | report | ❌ | [n]({words.evidence(pack)}/2.md) |",
        ],
        pack,
    )
    with pytest.raises(Conflict, match="2·video"):  # waiving the screenshots does not waive the video
        answer_card(pack, card, "go without screenshots")
    _results(
        ticket,
        [
            f"| 1 | login | ✅ | [s]({words.evidence(pack)}/1-login.png) |",
            f"| 2 | report | ❌ video: not possible — no browser target | [n]({words.evidence(pack)}/2.md) |",
        ],
        pack,
    )
    assert answer_card(pack, card, "go without screenshots")["out"] == "unblocked"
    custom = {**pack, "testflow": {**(pack.get("testflow") or {}), "review_mark": "please review"}}
    assert run_not_ready(custom, ticket, asks) == [] and run_not_ready(custom, ticket, "Please review run 001") == [
        "2·screenshot"
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_pack_review_mark_is_checked(bare, pack_file, tmp_path):
    bad = _copy_pack(pack_file, tmp_path, lambda data, _dir: data.setdefault("testflow", {}).update(review_mark=""))
    with pytest.raises(CockpitError, match="review_mark"):
        load(bad)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_packs_own_approval_runs_its_command_and_resumes_the_card(env, pack_file, tmp_path, monkeypatch):
    def add(data, folder):
        script = folder / "bin" / "approve"
        script.parent.mkdir(exist_ok=True)
        script.write_text(
            '#!/bin/sh\n[ "$1" = fail ] && { echo boom >&2; exit 1; }\necho "client made for $1"\n', encoding="utf-8"
        )
        script.chmod(0o755)
        data["asks"] = {
            "client": {
                "mark": "CLIENT NEEDED",
                "label": "Make it",
                "command": ["{pack}/bin/approve", "{lane}"],
                "deny": "no client",
            }
        }

    pack_file = _copy_pack(pack_file, tmp_path, add)
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import asks
    from cockpitlib.kanban import open_card_rows

    ticket = f"{pack['tracker']['project']}-505"
    card = put_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    _block(pack["board"], card, "CLIENT NEEDED · staging · rows 4-6")
    row = next(item for item in open_card_rows(pack["board"], pack) if item["id"] == card)
    assert row["pack_ask"] == {"name": "client", "label": "Make it", "deny": "no client"}
    done = _client().post("/ask-approve", json={"id": card}).json()
    assert (
        done["ok"] is True and "client approved for tester-1" in done["out"] and _status(pack["board"], card) == "ready"
    )
    with pytest.raises(CockpitError, match="not waiting"):
        asks.approve(pack, card)
    other = put_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    _block(pack["board"], other, "a plain question")
    with pytest.raises(CockpitError, match="not asking"):
        asks.approve(pack, other)
    failing = put_card(pack["board"], f"{ticket}: test", "fail", "ready")
    _block(pack["board"], failing, "CLIENT NEEDED · staging · rows 7")
    with pytest.raises(CockpitError, match="boom"):
        asks.approve(pack, failing)
    with pytest.raises(CockpitError, match="no card"):
        asks.approve(pack, "t_missing")
    assert asks.row(pack, "nothing") == {} and asks.match(pack, "") == (None, None)
    bad = _copy_pack(
        pack_file,
        tmp_path / "bad",
        lambda data, _dir: data.update(asks={"x": {"label": "no mark", "command": ["true"]}}),
    )
    with pytest.raises(CockpitError, match="asks.x"):
        load(bad)
    with pytest.raises(CockpitError, match="asks maps"):
        load(_copy_pack(pack_file, tmp_path / "bad2", lambda data, _dir: data.update(asks=["x"])))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_review_waiting_for_the_tester_starts_when_the_tester_card_is_done(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import release_reviewers
    from cockpitlib.kanban import place_card

    ticket = f"{pack['tracker']['project']}-506"
    tester = put_card(pack["board"], f"{ticket}: tester", "tester-1", "running")
    review = place_card(
        pack["board"],
        f"{ticket}: review",
        "reviewer",
        "blocked",
        reason="waiting for the tester",
        kind="review",
        ticket=ticket,
    )
    treat = put_card(pack["board"], f"{ticket}: review the PR", "worker-1", "ready")
    _block(pack["board"], treat, "Patch plan: go?")
    assert release_reviewers(pack) == "0" and _status(pack["board"], review) == "blocked"
    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'done' where id = ?", (tester,))
    connection.commit()
    connection.close()
    assert release_reviewers(pack) == "1"
    assert _status(pack["board"], review) in ("ready", "todo") and _status(pack["board"], treat) == "blocked"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_sets_a_kickoff_modes_checks(bare, pack_file, tmp_path):
    from cockpitlib.registry import kickoff_modes

    pack = load(
        _copy_pack(
            pack_file, tmp_path, lambda data, _dir: data.update(kickoff={"preflight": {"test": ["tester_slot"]}})
        )
    )
    assert (
        kickoff_modes(pack)["test"]["preflight"] == ["tester_slot"]
        and kickoff_modes(pack)["review"]["preflight"] == kickoff_modes()["review"]["preflight"]
    )
    for wrong, said in (
        ({"preflight": {"nope": []}}, "no such kickoff mode"),
        ({"preflight": {"test": ["fly"]}}, "steps are"),
        ({"preflight": ["test"]}, "maps a mode"),
    ):
        with pytest.raises(CockpitError, match=said):
            load(_copy_pack(pack_file, tmp_path / str(abs(hash(said))), lambda data, _dir: data.update(kickoff=wrong)))


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_advisor_answers_that_hold_the_worker_are_the_packs(bare, pack_file, tmp_path, monkeypatch):
    from cockpitlib import plan_gate

    pack = load(pack_file)
    answers = (((pack.get("advisor") or {}).get("checkpoints") or {}).get("C0") or {}).get("answers")
    if not answers or len(answers) < 2:
        pytest.skip("this fixture's advisor has one C0 answer")
    monkeypatch.setattr(
        "cockpitlib.advise.calls", lambda ticket: [{"card": "t_1", "checkpoint": "C0", "verdict": answers[1]}]
    )
    assert plan_gate._deviated(pack, "T-1", "t_1") is True
    held = {
        **pack,
        "advisor": {**pack["advisor"], "checkpoints": {"C0": {"answers": answers, "block_on": answers[2:]}}},
    }
    monkeypatch.setattr("cockpitlib.advise.config", lambda p: p["advisor"])
    assert plan_gate._deviated(held, "T-1", "t_1") is False


@pytest.mark.parametrize("pack_file", PACKS)
def test_block_on_names_some_of_the_checkpoints_answers(bare, pack_file, tmp_path):
    def change(data, _dir):
        data["advisor"] = {"checkpoints": {"C0": {"answers": ["OK", "NO"], "block_on": ["MAYBE"]}}}

    with pytest.raises(CockpitError, match="block_on"):
        load(_copy_pack(pack_file, tmp_path, change))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_go_with_changes_resumes_unless_it_names_a_path_to_read(env, pack_file):
    pack = load(pack_file)
    from cockpitlib.acts import answer_card

    card = put_card(pack["board"], f"{pack['tracker']['project']}-507: intake", "intake", "ready")
    _block(pack["board"], card, "go? the plan is on the card")
    assert answer_card(pack, card, "go with changes: keep the old endpoint")["out"] == "unblocked"


@pytest.mark.parametrize("pack_file", PACKS)
def test_only_a_test_kickoffs_go_ends_in_ticket_done(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card

    ticket = f"{pack['tracker']['project']}-508"
    chain = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready", kind="tester", ticket=ticket)
    _block(pack["board"], chain, "rows 1-3 pass")
    assert answer_card(pack, chain, "go")["published"] == ""
    kickoff = place_card(pack["board"], f"{ticket}: test", "tester-2", "ready", kind="test", ticket=ticket)
    _block(pack["board"], kickoff, "rows 1-3 pass")
    monkeypatch.setattr("cockpitlib.acts.attach_evidence", lambda *a: None)
    assert answer_card(pack, kickoff, "go")["published"].endswith("ticket-done")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_ci_failure_of_a_commit_already_diagnosed_makes_no_second_card(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import ci_watch

    monkeypatch.setattr(ci_watch, "_tail", lambda *a: "")
    ticket = f"{pack['tracker']['project']}-509"
    run = {"id": 7, "name": "tests", "run_attempt": 1, "html_url": ""}
    first = ci_watch._card(pack, ticket, "api", "abcdef1234567", "work", run, None)
    assert (
        first
        and ci_watch._card(pack, ticket, "api", "abcdef1234567", "work", {**run, "id": 8, "run_attempt": 2}, None)
        == first
    )
    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'done' where id = ?", (first,))
    connection.commit()
    connection.close()
    # its verdict stands: the finished card answers the attempt (so the commit is handled), and no second card is made
    from cockpitlib.kanban import board_cards

    before = len(board_cards(pack["board"]))
    assert (
        ci_watch._card(pack, ticket, "api", "abcdef1234567", "work", {**run, "id": 9, "run_attempt": 3}, None) == first
    )
    assert len(board_cards(pack["board"])) == before


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_chain_and_the_handoff_make_the_chains_tester(bare, pack_file):
    from cockpitlib.decompose import DEFAULT_CHAIN

    assert DEFAULT_CHAIN == ("work", "tester", "review")


def test_a_compare_diff_needs_both_commits_and_no_test_run(monkeypatch):
    from cockpitlib.acts import compare_diff_text

    assert compare_diff_text("o", "r", "a", "b") == ""
    assert compare_diff_text("o", "r", "a", "b", runner=lambda *args: "diff --git") == "diff --git"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_inbox_says_when_the_gateway_is_down_unless_cockpit_is_switched_off(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setattr("cockpitlib.pack_migration._gateway_running", lambda: False)
    monkeypatch.setattr("cockpitlib.setup.gateway_status", lambda: "running")
    rows = _client().get("/needs-you").json()["watchers"]
    assert rows[0]["name"] == "gateway" and "gateway is down" in rows[0]["reason"]
    monkeypatch.setattr("cockpitlib.setup.gateway_status", lambda: "stopped")
    assert not any(row["name"] == "gateway" for row in _client().get("/needs-you").json()["watchers"])


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_rereview_diff_is_what_changed_since_the_review(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setattr("cockpitlib.acts.pr_state", lambda *a: {"reviewed_sha": "a" * 40, "head_sha": "b" * 40})
    monkeypatch.setattr("cockpitlib.acts.compare_diff_text", lambda *a: "diff --git a/x b/x\n")
    got = _client().get("/pr-diff", params={"repo": "api", "number": 3, "ticket": "TASK-1", "mode": "since"}).json()
    assert (
        got["diff"].startswith("diff --git")
        and got["commits"] == ["aaaaaaaaa..bbbbbbbbb"]
        and "since your review" in got["note"]
    )
    monkeypatch.setattr("cockpitlib.acts.compare_diff_text", lambda *a: "")
    monkeypatch.setattr("cockpitlib.acts.pr_diff_text", lambda *a: "whole pr\n")
    assert (
        _client()
        .get("/pr-diff", params={"repo": "api", "number": 3, "ticket": "TASK-1", "mode": "since"})
        .json()["diff"]
        == "whole pr\n"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_watcher_run_and_a_kickoff_answer_with_a_line_for_the_toast(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.setattr("cockpitlib.acts.run_watcher", lambda name: {"ok": True, "summary": "pr-watch 2"})
    assert _client().post("/watcher-run", json={"name": "pr-watch"}).json()["out"] == "pr-watch 2"
    monkeypatch.setattr("cockpitlib.acts.run_watcher", lambda name: {"ok": False, "error": "boom"})
    assert _client().post("/watcher-run", json={"name": "pr-watch"}).json()["out"] == "boom"
    kicked = _client().post("/kickoff", json={"mode": "bumps", "repo": "api", "prs": ["#4", "#5"]})
    assert kicked.status_code == 200, kicked.text
    from cockpitlib.kanban import board_cards
    from cockpitlib.kickoff import batch_key

    cards = {item["id"]: item for item in board_cards(load(pack_file)["board"])}
    assert kicked.json()["card_id"] in cards, (kicked.json(), list(cards))
    card = cards[kicked.json()["card_id"]]
    assert (
        card["title"].startswith(batch_key(load(pack_file)))
        and "the human's pick" in card["body"]
        and kicked.json()["out"]
    )


def test_a_compare_asks_the_forge_and_survives_its_failure(monkeypatch):
    import subprocess

    from cockpitlib.acts import compare_diff_text

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("Done", (), {"returncode": 0, "stdout": "diff"})())
    assert compare_diff_text("o", "r", "a", "b") == "diff"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("Done", (), {"returncode": 1, "stdout": "no"})())
    assert compare_diff_text("o", "r", "a", "b") == ""

    def broken(*a, **k):
        raise OSError("no gh")

    monkeypatch.setattr(subprocess, "run", broken)
    assert compare_diff_text("o", "r", "a", "b") == ""


def test_the_since_review_counts_come_from_the_forge_once_per_head():
    from cockpitlib.pr_watch import _since_review

    class Forge:
        calls = 0

        def repo(self, name):
            return f"org/{name}"

        def get(self, path):
            Forge.calls += 1
            if "bad" in path:
                raise RuntimeError("rewritten")
            return {"total_commits": 3, "files": [{}, {}]}

    record = {"reviewed_sha": "a1", "head_sha": "b2"}
    found = _since_review(Forge(), "api", record, {})
    assert found["commits"] == 3 and found["files"] == 2
    assert _since_review(Forge(), "api", record, {"since_review": found}) == found and Forge.calls == 1
    assert _since_review(Forge(), "api", {"reviewed_sha": "bad", "head_sha": "c3"}, {})["commits"] == 1
    assert _since_review(Forge(), "api", {"reviewed_sha": "b2", "head_sha": "b2"}, {}) == {"commits": 0, "files": 0}


@pytest.mark.parametrize("pack_file", PACKS)
def test_rereview_is_the_reviewers_on_a_pr_you_reviewed_and_the_authors_on_yours(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import pr_watch

    ticket = f"{pack['tracker']['project']}-510"
    path = pr_watch.record_path(ticket, "api", 8)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(
        {
            "ticket": ticket,
            "repo": "api",
            "number": 8,
            "role": "reviewer",
            "state": "open",
            "reviewed_sha": "a" * 40,
            "head_sha": "b" * 40,
            "url": "u",
            "last_activity": 0,
        },
        open(path, "w"),
    )
    dropped = []
    monkeypatch.setattr("cockpitlib.outbox.drop", lambda iid, note="": dropped.append(iid))
    got = (
        _client()
        .post(
            "/pr-rereview",
            json={"ticket": ticket, "repo": "api", "number": 8, "supersede": f"{ticket}/001-pr-review-submit"},
        )
        .json()
    )
    assert got["ok"] and got["card_id"] and dropped == [f"{ticket}/001-pr-review-submit"] and "dropped" in got["out"]
    assert json.load(open(path))["rereview"]["card"] == got["card_id"]
    json.dump({"ticket": ticket, "repo": "api", "number": 8, "role": "author", "state": "open"}, open(path, "w"))
    monkeypatch.setattr("cockpitlib.acts.treat_pr", lambda *a: {"ok": True, "out": "treated"})
    assert (
        _client().post("/pr-rereview", json={"ticket": ticket, "repo": "api", "number": 8}).json()["out"] == "treated"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_releasing_reviewers_stops_when_the_board_is_gone(env, pack_file, monkeypatch):
    pack = load(pack_file)
    from cockpitlib.acts import release_reviewers
    from cockpitlib.kanban import place_card

    ticket = f"{pack['tracker']['project']}-511"
    place_card(
        pack["board"],
        f"{ticket}: review",
        "reviewer",
        "blocked",
        reason="waiting for the tester",
        kind="review",
        ticket=ticket,
    )
    monkeypatch.setattr("cockpitlib.acts._open", lambda board: None)
    assert release_reviewers(pack) == "0"
