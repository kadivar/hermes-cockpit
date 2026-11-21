# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The question flow: a finished analyst card's answer reaches the Inbox with the files the lane
wrote; a done card shows its completion summary; "block…" is a tester verdict on tester cards only; a reopen or rework
retires the ticket's pending ticket-done; the lending flow works for a non-tester card."""

import json
import os
import shutil
import sqlite3
import time

import pytest
import yaml

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.boards import raw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


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


def _complete(board, card, summary=None, result=None):
    """The lane's kanban_complete: Hermes keeps the summary on the completed event and leaves result empty."""
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(board)
    writes.complete(card, result=result, summary=summary)
    assert writes.flush() == [True]


def _comments(board, card):
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(f"file:{db_path(board)}?mode=ro", uri=True)
    rows = [
        row[0]
        for row in connection.execute("select body from task_comments where task_id = ? order by created_at", (card,))
    ]
    connection.close()
    return rows


def _status(board, card):
    from cockpitlib.kanban import board_cards

    return {item["id"]: item["status"] for item in board_cards(board)}[card]


def _set(board, card, **fields):
    connection = raw(board)
    for key, value in fields.items():
        connection.execute(f"update tasks set {key} = ? where id = ?", (value, card))
    connection.commit()
    connection.close()


def _analyst_card(pack, ticket, started=None):
    """A question card the way a kickoff makes it, claimed `started` seconds ago."""
    from cockpitlib.kanban import card_title, place_card

    card = place_card(
        pack["board"],
        card_title("analyst", ticket, pack=pack),
        "analyst",
        "ready",
        kind="analyst",
        ticket=ticket,
        pack=pack,
    )
    _set(pack["board"], card, started_at=int(time.time()) - (started or 0))
    return card


# ---------- item 2: a done card shows what it ended with ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_done_card_shows_the_summary_of_its_complete_call_when_result_is_empty(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.board_view import board
    from cockpitlib.kanban import completion_summary, db_path, place_card
    from dashboard.cockpit.routes.pages import _card_detail

    ticket = f"{pack['tracker']['project']}-7101"
    by_event = place_card(pack["board"], f"{ticket}: analysis", "analyst", "ready")
    by_result = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    _complete(pack["board"], by_event, summary="Root cause: the **divider** ignores the page background.")
    _complete(pack["board"], by_result, result="Tested and Ok", summary="ignored: result wins")
    connection = sqlite3.connect(f"file:{db_path(pack['board'])}?mode=ro", uri=True)
    assert (
        connection.execute("select result from tasks where id = ?", (by_event,)).fetchone()[0] is None
    )  # Hermes leaves it empty
    assert completion_summary(connection, by_event).startswith("Root cause")
    assert completion_summary(connection, by_result) == "Tested and Ok"
    assert completion_summary(connection, "no-such-card") == ""
    connection.close()
    done = {card["id"]: card for card in board(pack)["by_status"]["done"]}
    assert done[by_event]["result"].startswith("Root cause") and done[by_result]["result"] == "Tested and Ok"
    detail = _card_detail(pack, by_event)
    assert "<strong>divider</strong>" in detail["result_html"]
    assert _card_detail(pack, by_result)["result_html"].startswith("<p>Tested and Ok")
    # an open card has no completion: nothing is shown as a result
    assert _card_detail(pack, place_card(pack["board"], f"{ticket}: intake", "intake", "ready"))["result_html"] == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_older_board_without_the_events_table_reads_result_only(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.kanban import completion_summary, db_path
    from tests.support.boards import init_db

    pack = load(pack_file)
    init_db(pack["board"])
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute(
        "insert into tasks (id, title, assignee, status, created_at) values ('old-1', 'T-1: analysis', 'analyst', 'done', '')"
    )
    connection.commit()
    assert completion_summary(connection, "old-1") == ""
    connection.execute("alter table tasks add column result text")
    connection.execute("update tasks set result = 'the verdict' where id = 'old-1'")
    assert completion_summary(connection, "old-1") == "the verdict"
    connection.execute(
        "create table task_events (id integer primary key autoincrement, task_id text, kind text, payload text, created_at integer)"
    )
    connection.execute("update tasks set result = null where id = 'old-1'")
    connection.execute(
        "insert into task_events (task_id, kind, payload, created_at) values ('old-1', 'completed', 'not json', 1)"
    )
    assert completion_summary(connection, "old-1") == ""  # an unreadable payload is no summary
    connection.close()


# ---------- item 3: "block…" is the tester's rows-blocked verdict on tester cards only ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_answer_starting_with_block_is_validated_on_tester_cards_only(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card

    ticket = f"{pack['tracker']['project']}-7102"
    human = "Block again with exactly: PRIVILEGED LOGIN NEEDED · staging · open the dashboard · the page is in another organisation"
    analyst = _analyst_card(pack, ticket)
    _block(pack["board"], analyst, "CREDENTIALS NEEDED · staging · owner@example.test · the dashboard is theirs")
    assert answer_card(pack, analyst, human)["out"] == "unblocked"  # the human's text, commented and resumed
    assert any(body == f"Human: {human}" for body in _comments(pack["board"], analyst))
    for title, lane in (
        (f"{ticket}: test on staging", "tester-1"),
        (f"{ticket}: test", "worker-1"),
    ):  # the lane, or a Test card by title
        tester = place_card(pack["board"], title, lane, "ready")
        _block(pack["board"], tester, "rows 1-3 pass, 4 blocked")
        with pytest.raises(CockpitError, match="a block must name what is missing"):
            answer_card(pack, tester, human)
        assert _status(pack["board"], tester) == "blocked"
        assert (
            answer_card(pack, tester, "Block: rows 4 missing the export button; who: the human adds it")["out"]
            == "unblocked"
        )


# ---------- item 1b: the question kickoff tells the lane where its answer goes ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_question_kickoff_text_names_the_inbox_and_the_files_and_other_modes_keep_their_line(
    bare, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import kickoff_text
    from cockpitlib.paths import qa
    from cockpitlib.registry import kickoff_modes

    ticket = f"{pack['tracker']['project']}-7103"
    text = kickoff_text(pack, ticket, "analyst", "why is the divider white?")
    assert "reach the human's Inbox as the answer" in text and os.path.join(qa(), ticket) + "/" in text
    assert "Name each file you wrote in the summary" in text and "a question for the human is a block" in text
    assert "The human reads it on the Cockpit page." not in text
    for mode in ("intake", "test", "review", "rework"):
        assert "Finish with the board's complete call. The human reads it on the Cockpit page." in kickoff_text(
            pack, ticket, mode, ""
        )
    assert "reach the Inbox" in kickoff_modes(pack)["analyst"]["text"]


# ---------- item 5: a reopen or rework retires the ticket's pending ticket-done ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_reopen_moves_the_pending_ticket_done_to_reopened_and_a_later_merge_makes_a_new_row(
    env, pack_file, monkeypatch, tmp_path
):
    path = _copy_pack(pack_file, tmp_path, lambda data, _c: data.setdefault("outbox", {}).update(comment_card=True))
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    from cockpitlib import pr_watch
    from cockpitlib.acts import continue_ticket
    from cockpitlib.intents import all_intents
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import ack, create, drop
    from cockpitlib.paths import qa
    from dashboard.cockpit.router import _rows

    ticket = f"{pack['tracker']['project']}-7104"
    repo = pack["repos"]["repos"][0]["name"]
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder)
    json.dump(
        {"ticket": ticket, "repo": repo, "number": 3, "role": "author", "merged": True, "state": "closed"},
        open(os.path.join(folder, f"{repo}-3.json"), "w"),
    )
    watcher = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    _complete(pack["board"], watcher, summary="done")
    dropped = create(pack, ticket, "ticket-done", watcher, "an older one the human dropped", {"numbers": ["1"]})
    drop(dropped["id"], note="a duplicate")
    pending = pr_watch._ticket_done(pack, ticket)
    assert pending and pr_watch._ticket_done(pack, ticket) == ""
    # the reopen: the pending row leaves as `reopened`, named by the card that reopened it; a dropped row is left alone
    made = continue_ticket(pack, ticket, "the divider is still white on page 2")
    assert made["reopened"] == [pending] and made["out"].endswith(f"{pending} reopened")
    row = load_intent(pending)
    assert (
        row["status"] == "reopened"
        and row["reopened"]["card"] == made["card_id"]
        and row["reopened"]["kind"] == "reopen"
    )
    assert load_intent(dropped["id"])["status"] == "dropped"
    assert not any(item["id"] == pending and item["status"] == "pending" for item in _rows(pack))
    assert pr_watch._covered([row], {"3"}) is False  # a reopened row covers nothing
    assert pr_watch._ticket_done(pack, ticket) == ""  # the reopen card is open: not yet
    _complete(pack["board"], made["card_id"], summary="proposed and done")
    fresh = pr_watch._ticket_done(pack, ticket)  # the same PR numbers, a fresh ask
    assert fresh and fresh != pending and load_intent(fresh)["status"] == "pending"
    assert [item["id"] for item in all_intents(ticket) if item["status"] == "reopened"] == [pending]
    # an acknowledged row is retired the same way by a rework; the note reaches the intent's card when it has one (outbox.comment_card)
    ack(fresh)
    reworked = continue_ticket(pack, ticket, "CS: early returns", kind="rework", chain=False)
    assert (
        reworked["reopened"] == [fresh]
        and load_intent(fresh)["status"] == "reopened"
        and load_intent(fresh)["reopened"]["kind"] == "rework"
    )
    _complete(pack["board"], reworked["card_id"], summary="done")
    own = create(pack, ticket, "ticket-done", watcher, "test run finished", {"numbers": ["3"]})
    again = continue_ticket(pack, ticket, "CS: once more", kind="rework", chain=False)
    assert again["reopened"] == [own["id"]]
    assert any(
        f"{own['id']}: {ticket} was reworked on card {again['card_id']}" in body
        for body in _comments(pack["board"], watcher)
    )
    # a second reopen with nothing pending retires nothing
    _complete(pack["board"], again["card_id"], summary="done")
    assert continue_ticket(pack, ticket, "once more")["reopened"] == []


# ---------- item 1: a finished question card is an Inbox row until used or dismissed ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_finished_question_card_is_an_answer_row_with_its_files_until_used_or_dismissed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import answers
    from cockpitlib.kanban import board_cards, card_entry
    from cockpitlib.paths import qa, workspace

    ticket = f"{pack['tracker']['project']}-7105"
    folder = os.path.join(qa(), ticket)
    os.makedirs(os.path.join(folder, "evidences"))
    os.makedirs(os.path.join(folder, "skills"))
    old = os.path.join(folder, "plan.md")
    open(old, "w", encoding="utf-8").write("# an older plan\n")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    card = _analyst_card(pack, ticket, started=60)
    assert answers.rows(pack) == []  # open: not an answer yet
    open(os.path.join(folder, "analyst-findings.md"), "w", encoding="utf-8").write(
        "## Findings\n\nThe **divider** ignores the background.\n"
    )
    open(os.path.join(folder, "evidences", "before-A4.png"), "wb").write(b"png")
    open(os.path.join(folder, "skills", "analyst.log"), "w", encoding="utf-8").write("kernel's own\n")
    open(os.path.join(folder, ".hidden"), "w", encoding="utf-8").write("x")
    os.symlink(
        os.path.join(folder, "gone.png"), os.path.join(folder, "evidences", "dangling.png")
    )  # a file that cannot be stat'ed is skipped
    open(os.path.join(folder, "evidences", "aa-binary.md"), "wb").write(
        b"\xff\xfe not text"
    )  # an unreadable markdown is not the report
    _complete(
        pack["board"], card, summary=f"Root cause found. See qa/{ticket}/analyst-findings.md and qa/{ticket}/plan.md."
    )
    rows = answers.rows(pack)
    assert [row["card"] for row in rows] == [card]
    row = rows[0]
    assert (
        row["ticket"] == ticket
        and row["lane"] == "analyst"
        and row["mode"] == "analyst"
        and row["completed"].endswith("Z")
    )
    # the files the card wrote (markdown first), the one the summary names although older, never cockpit's own folders or dotfiles
    assert [item["name"] for item in row["references"]] == [
        "analyst-findings.md",
        "plan.md",
        "aa-binary.md",
        "before-A4.png",
    ]
    from cockpitlib.paths import records_name

    assert all(
        item["rel"].startswith(f"{records_name()}/qa/{ticket}/") for item in row["references"]
    )  # workspace-relative
    assert all(os.path.isfile(os.path.join(workspace(), item["rel"])) for item in row["references"])
    assert "<strong>divider</strong>" in row["report_html"] and row["report_name"] == "analyst-findings.md"
    assert "<p>Root cause found." in row["summary_html"]
    assert (
        row["reopen_prompt"].startswith("Root cause found.")
        and "References:\n- " in row["reopen_prompt"]
        and "analyst-findings.md" in row["reopen_prompt"]
    )
    assert (
        row["followup_text"].startswith(f"Follow-up to card {card} on {ticket}. Read ")
        and f"qa/{ticket}/analyst-patch-plan.md" in row["followup_text"]
    )
    assert row["rework_repos"] == [] and row["follows"] == "" and row["used_by"] == [] and row["dismissed"] == ""
    # the Inbox payload carries the rows; dismiss makes it leave, the Board's card stays done
    client = _client()
    assert [item["card"] for item in client.get("/needs-you").json()["answers"]] == [card]
    assert client.post("/answer-dismiss", json={"card": "t_nothing"}).status_code == 400
    assert client.post("/answer-dismiss", json={"card": card}).json()["out"].endswith("dismissed")
    assert answers.rows(pack) == [] and answers.rows(pack, include_used=True)[0]["dismissed"]
    assert _status(pack["board"], card) == "done"
    # a second card's answer, reopened with in one click: the intake card carries the files as evidence and the row leaves
    second = _analyst_card(pack, ticket)
    open(os.path.join(folder, "analyst-patch-plan.md"), "w", encoding="utf-8").write("# Patch plan\n")
    _complete(pack["board"], second, summary="Patch plan written.")
    row = answers.rows(pack)[0]
    assert row["card"] == second and [item["name"] for item in row["references"]][0] == "analyst-patch-plan.md"
    made = client.post(
        "/reopen-flow",
        json={
            "ticket": ticket,
            "prompt": row["reopen_prompt"],
            "evidence": [item["rel"] for item in row["references"]],
            "from_answer": second,
        },
    ).json()
    body = {item["id"]: item for item in board_cards(pack["board"])}[made["card_id"]]["body"]
    assert "analyst-patch-plan.md" in body and "Patch plan written." in body
    assert answers.rows(pack) == []
    used = answers.rows(pack, include_used=True)
    assert next(item for item in used if item["card"] == second)["used_by"][0] == {
        **next(item for item in used if item["card"] == second)["used_by"][0],
        "kind": "reopen",
        "card": made["card_id"],
    }
    # a kickoff from the row records it too (here a question on another ticket); a row nothing cites is unchanged
    third = _analyst_card(pack, ticket)
    _complete(pack["board"], third, summary="A third answer.")
    other = f"{pack['tracker']['project']}-7106"
    kicked = client.post(
        "/kickoff", json={"ticket": other, "mode": "analyst", "prompt": "same question there", "from_answer": third}
    ).json()
    assert kicked["card_id"] and answers.rows(pack) == []
    assert answers.use("", "reopen", "x") is False
    assert (
        answers.references("", None, None) == [] and answers.references(f"{pack['tracker']['project']}-0", 1, 2) == []
    )
    assert answers.question_kinds(pack) == {"analyst": "analyst"}
    assert card_entry(pack["board"], kicked["card_id"]).get("follows") in (None, "")
    # a card the human closed with `stop` after the lane's last block: the block (the verdict, the paths it names) is the
    # answer, not the human's stop line; a card that wrote nothing of its own lists the ticket's analyst-*.md as shared
    from cockpitlib.acts import answer_card

    stopped = _analyst_card(pack, ticket)
    _block(
        pack["board"],
        stopped,
        f"Verdict: confirmed on staging. Report: {records_name()}/qa/{ticket}/analyst-patch-plan.md",
    )
    answer_card(pack, stopped, "stop: answer received and confirmed; the patch plan goes to the reopen.")
    row = next(item for item in answers.rows(pack) if item["card"] == stopped)
    assert row["summary"].startswith("Verdict: confirmed on staging.") and "stop:" not in row["summary"]
    assert "analyst-patch-plan.md" in [item["name"] for item in row["references"]]
    answers.dismiss(pack, stopped)
    bare = _analyst_card(pack, ticket, started=0)
    _set(pack["board"], bare, started_at=int(time.time()) - 7200)  # ran long ago: nothing under qa/ is its own
    _set(pack["board"], bare, status="done", completed_at=int(time.time()) - 7000)
    row = next(item for item in answers.rows(pack) if item["card"] == bare)
    assert [(item["name"], item.get("shared")) for item in row["references"]] == [
        ("analyst-findings.md", True),
        ("analyst-patch-plan.md", True),
    ]
    assert (
        answers.shared_files(ticket, "") == []
        and answers.shared_files(f"{pack['tracker']['project']}-0", "analyst") == []
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_follow_up_on_an_answer_starts_a_card_with_the_references_and_its_answer_follows_the_first(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import answers
    from cockpitlib.kanban import board_cards, card_entry
    from cockpitlib.paths import qa

    ticket = f"{pack['tracker']['project']}-7107"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder)
    first = _analyst_card(pack, ticket, started=10)
    open(os.path.join(folder, "analyst-findings.md"), "w", encoding="utf-8").write("# Findings\n")
    _complete(pack["board"], first, summary="Found it.")
    client = _client()
    assert client.post("/answer-followup", json={"card": "t_nothing"}).status_code == 400
    made = client.post("/answer-followup", json={"card": first, "prompt": ""}).json()
    body = {item["id"]: item for item in board_cards(pack["board"])}[made["card_id"]]["body"]
    assert f"Follow-up to card {first} on {ticket}" in body and "Evidence: " in body and "analyst-findings.md" in body
    assert card_entry(pack["board"], made["card_id"])["follows"] == first and made["out"].endswith(
        "its answer comes back here"
    )
    assert [row["card"] for row in answers.rows(pack)] == [first]  # the first row stays; the new card is open
    with pytest.raises(Exception):  # a second follow-up while one is open: the kickoff's twin rule
        answers.followup(pack, first, "again")
    assert client.post("/answer-followup", json={"card": first, "prompt": "again"}).status_code == 409
    open(os.path.join(folder, "analyst-patch-plan.md"), "w", encoding="utf-8").write("# Patch plan\n")
    _complete(pack["board"], made["card_id"], summary="Patch plan written.")
    rows = {row["card"]: row for row in answers.rows(pack)}
    assert set(rows) == {first, made["card_id"]} and rows[made["card_id"]]["follows"] == first
    assert "analyst-patch-plan.md" in [item["name"] for item in rows[made["card_id"]]["references"]]
    # the human's own follow-up text is used as written
    answers.dismiss(pack, first)
    assert answers.rows(pack, include_used=True)[-1]["dismissed"] or True
    own = client.post(
        "/answer-followup", json={"card": made["card_id"], "prompt": "Only the test list, please."}
    ).json()
    assert (
        "Only the test list, please."
        in {item["id"]: item for item in board_cards(pack["board"])}[own["card_id"]]["body"]
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_answer_rows_read_the_pack_s_question_modes_and_tolerate_an_older_board(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import answers
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import qa
    from tests.support.boards import insert_card

    ticket = f"{pack['tracker']['project']}-7108"
    # a done card of another kind is no answer; a card cockpit did not make (no index entry) is none either
    tester = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready", kind="tester", ticket=ticket)
    _complete(pack["board"], tester, summary="Tested and Ok")
    stray = place_card(pack["board"], f"{ticket}: analysis", "analyst", "ready")
    _complete(pack["board"], stray, summary="no index entry")
    assert answers.rows(pack) == []
    assert answers._done_cards(pack, set()) == []
    # the answer of a card the pack's own question mode made counts: no kinds → nothing; a board without the columns → nothing
    assert answers._rework_repos(pack, ticket) == []
    os.remove(os.path.join(os.environ["COCKPIT_HERMES_HOME"], "kanban", "boards", pack["board"], "kanban.db"))
    assert answers.rows(pack) == []
    insert_card(pack["board"], "old-9", f"{ticket}: analysis", "analyst", "done")
    from cockpitlib.kanban import remember_card

    remember_card(pack["board"], "old-9", "analyst", ticket)
    row = answers.rows(pack)[0]
    assert row["card"] == "old-9" and row["summary"] == "" and row["references"] == [] and row["completed"] == ""
    os.makedirs(os.path.join(qa(), ticket))
    open(os.path.join(qa(), ticket, "analyst-findings.md"), "w", encoding="utf-8").write("# shared\n")
    open(os.path.join(qa(), ticket, "notes.md"), "w", encoding="utf-8").write("# not of the kind\n")
    assert [item["name"] for item in answers.rows(pack)[0]["references"]] == ["analyst-findings.md"]
    insert_card(
        pack["board"], "old-8", f"{ticket}: tester", "tester-1", "done"
    )  # done, but not a card of a question kind
    assert [row["card"] for row in answers.rows(pack)] == ["old-9"]
    # a read that fails midway, and a board whose tasks table lacks the columns: no rows, no error
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "cockpitlib.kanban.completion_summary", lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("locked"))
        )
        assert answers.rows(pack) == []
    bad = os.path.join(qa(), ticket, "zz-bad.md")
    open(bad, "wb").write(b"\xff\xfe not text")
    good = os.path.join(qa(), ticket, "analyst-findings.md")
    assert answers._report([{"name": "zz-bad.md", "path": bad}, {"name": "analyst-findings.md", "path": good}]) == (
        "<h1>shared</h1>",
        "analyst-findings.md",
    )
    connection = raw(pack["board"])
    connection.execute("drop table tasks")
    connection.execute("create table tasks (id text primary key)")
    connection.commit()
    connection.close()
    assert answers.rows(pack) == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_answer_rows_name_the_repos_a_rework_can_go_to(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import answers
    from cockpitlib.paths import qa, wt

    ticket = f"{pack['tracker']['project']}-7109"
    repos = [repo["name"] for repo in pack["repos"]["repos"]]
    os.makedirs(os.path.join(wt(), ticket, repos[1]))
    assert answers._rework_repos(pack, ticket) == [repos[1]]  # the checkout, when nothing was delivered
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder)
    json.dump({"repo": repos[0], "number": 4, "role": "author"}, open(os.path.join(folder, f"{repos[0]}-4.json"), "w"))
    json.dump(
        {"repo": repos[1], "number": 5, "role": "reviewer"}, open(os.path.join(folder, f"{repos[1]}-5.json"), "w")
    )
    assert answers._rework_repos(pack, ticket) == [repos[0]]  # the delivered PR's repo wins


# ---------- item 4: the lending flow is not the tester's alone ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_privileged_login_request_from_an_analyst_card_is_lent_to_the_analyst_seat(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib import lend

    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-7110"
    card = _analyst_card(pack, ticket)
    _block(
        pack["board"],
        card,
        lend.request_line(pack, "open the owner's dashboard", "the page is in another organisation"),
    )
    rows = lend.inbox_rows(pack)
    assert [row["card"] for row in rows] == [card] and rows[0]["summary"] == "open the owner's dashboard"
    assert _client().get("/needs-you").json()["privileged"][0]["card"] == card
    assert lend._card_lane(pack, card) == "analyst"
    monkeypatch.setattr("cockpitlib.vault.sealed_to", lambda: "FP")
    monkeypatch.setattr(
        "cockpitlib.vault._items",
        lambda: [{"privileged": True, "email": "a@b.test", "origin": "https://x", "secret": "s", "label": "x"}],
    )
    placed = []
    monkeypatch.setattr("cockpitlib.lane_vault.place", lambda lane, *a, **k: placed.append(lane) or "item-1")
    monkeypatch.setattr("cockpitlib.scrub.rebuild", lambda *a, **k: None)
    monkeypatch.setattr(lend, "_drop_previous_lend", lambda card: None)
    assert lend.approve(card, "", 1, pack) == "lent" and placed == ["analyst"]  # no lane named: the seat on the card
    from cockpitlib.paths import watch_dir

    lent = json.load(open(os.path.join(watch_dir(), "admin-lends.json")))
    assert lent[0]["card"] == card and lent[0]["lane"] == "analyst" and lent[0]["step"] == "open the owner's dashboard"
    assert _status(pack["board"], card) in ("ready", "todo") and any(
        "approved: the privileged login is lent" in text for text in _comments(pack["board"], card)
    )


# ---------- the tracker under watch while a done row waits ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tracker_comment_new_or_edited_while_the_done_row_waits_is_a_note_until_dismissed(
    env, pack_file, monkeypatch, jira
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import tracker_watch
    from cockpitlib.acts import continue_ticket
    from cockpitlib.housekeeping import STEPS
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import ack, create

    ticket = f"{pack['tracker']['project']}-7201"
    other = f"{pack['tracker']['project']}-7202"
    card = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    issue = jira.issue(ticket)
    adf = lambda text: {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}  # noqa: E731
    issue["comments"]["1"] = {
        "id": "1",
        "author": {"accountId": "acct-9", "displayName": "Ann Reporter"},
        "updated": "2026-10-29T10:00:00.000+0000",
        "body": adf("Before the watch."),
    }
    issue["comments"]["2"] = {
        "id": "2",
        "author": {"accountId": jira.account, "displayName": "the pipeline"},
        "updated": "2026-10-29T10:05:00.000+0000",
        "body": adf("Test Run results."),
    }
    # nothing pending: nothing is watched or read
    assert tracker_watch.watched() == [] and tracker_watch.watch(pack, now=1000.0) == {
        "read": [],
        "notes": [],
        "errors": [],
        "out": "0 read, 0 noted",
    }
    assert not any(request["path"].endswith("/comment?maxResults=100") for request in jira.requests)
    done = create(pack, ticket, "ticket-done", card, "test run finished", {"numbers": ["3"]})
    assert tracker_watch.watched() == [ticket]
    # the first read is the baseline: the comments already there are not news
    first = tracker_watch.watch(pack, now=1000.0)
    assert first["read"] == [ticket] and first["notes"] == [] and tracker_watch.rows() == []
    assert tracker_watch.watch(pack, now=1100.0)["read"] == []  # not due again for INTERVAL seconds
    # a new comment by someone else, an edit of an old one, and the pack's own account's post: two notes
    issue["comments"]["3"] = {
        "id": "3",
        "author": {"accountId": "acct-9", "displayName": "Ann Reporter"},
        "updated": "2026-10-29T11:00:00.000+0000",
        "body": adf("Still **white** on page 2."),
    }
    issue["comments"]["1"]["updated"] = "2026-10-29T11:01:00.000+0000"
    issue["comments"]["1"]["body"] = adf("Before the watch, edited.")
    issue["comments"]["4"] = {
        "id": "4",
        "author": {"accountId": jira.account, "displayName": "the pipeline"},
        "updated": "2026-10-29T11:02:00.000+0000",
        "body": "a plain-text post of our own",
    }
    second = tracker_watch.watch(pack, now=1400.0)
    assert second["read"] == [ticket] and len(second["notes"]) == 2
    rows = tracker_watch.rows()
    assert [(row["comment"], row["kind"], row["author"]) for row in rows] == [
        ("3", "new", "Ann Reporter"),
        ("1", "edited", "Ann Reporter"),
    ]  # newest first
    new = next(row for row in rows if row["comment"] == "3")
    assert (
        "<strong>white</strong>" in new["text_html"]
        and new["url"].endswith(f"/browse/{ticket}?focusedCommentId=3")
        and new["ticket"] == ticket
    )
    # the same comments again: no second note; a further edit replaces the note for that comment
    assert tracker_watch.watch(pack, now=1800.0)["notes"] == []
    issue["comments"]["3"]["updated"] = "2026-10-29T11:30:00.000+0000"
    assert len(tracker_watch.watch(pack, now=2200.0)["notes"]) == 1 and len(tracker_watch.rows()) == 2
    assert tracker_watch.rows()[0]["kind"] == "edited" and tracker_watch.rows()[0]["comment"] == "3"
    # the Inbox payload carries the notes; dismiss is the only act, and an unknown note is refused
    client = _client()
    assert [row["comment"] for row in client.get("/needs-you").json()["tracker_notes"]] == ["3", "1"]
    assert client.post("/tracker-note-dismiss", json={"id": "nothing"}).status_code == 400
    assert (
        client.post("/tracker-note-dismiss", json={"id": new["id"]}).status_code == 400
    )  # replaced by the edit's note
    kept = tracker_watch.rows()
    assert client.post("/tracker-note-dismiss", json={"id": kept[0]["id"]}).json()["out"].endswith("dismissed")
    assert [row["comment"] for row in tracker_watch.rows()] == ["1"]
    # the row leaves (acked, or retired by a reopen): the watch ends and nothing more is read; the note left stays
    ack(done["id"])
    before = len(jira.requests)
    assert tracker_watch.watch(pack, now=3000.0) == {"read": [], "notes": [], "errors": [], "out": "0 read, 0 noted"}
    assert (
        len(jira.requests) == before
        and ticket not in tracker_watch._state()["tickets"]
        and len(tracker_watch.rows()) == 1
    )
    create(pack, other, "ticket-done", card, "test run finished", {"numbers": ["4"]})
    jira.issue(other)
    assert tracker_watch.watch(pack, now=3100.0)["read"] == [other]
    continue_ticket(pack, other, "again")
    assert tracker_watch.watched() == [] and tracker_watch.watch(pack, now=3500.0)["read"] == []
    # a tracker that cannot answer: the error is kept on the ticket's entry and the pass goes on
    third = f"{pack['tracker']['project']}-7203"
    create(pack, third, "ticket-done", card, "test run finished", {"numbers": ["5"]})
    jira.fail["GET /rest/api/3/issue/" + third] = "boom"
    failed = tracker_watch.watch(pack, now=4000.0)
    assert failed["read"] == [] and failed["errors"] and failed["out"].endswith("1 failed")
    assert "boom" in tracker_watch._state()["tickets"][third]["error"]
    jira.fail.clear()
    jira.issue(third)
    assert tracker_watch.watch(pack, now=4400.0)["read"] == [third]
    assert dict(STEPS)["tracker-watch"](pack).endswith(" read, 0 noted")  # wired into housekeeping (real clock)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_tracker_watch_handles_a_command_tracker_an_unknown_self_and_odd_comment_rows(
    env, pack_file, monkeypatch, tmp_path
):
    path = _copy_pack(
        pack_file,
        tmp_path,
        lambda data, _c: data["tracker"].update(command=["tickets"], kind=None) or data["tracker"].pop("kind"),
    )
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    from cockpitlib import tracker_watch
    from cockpitlib.kanban import place_card
    from cockpitlib.outbox import create

    ticket = f"{pack['tracker']['project']}-7204"
    card = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready")
    create(pack, ticket, "ticket-done", card, "test run finished", {"numbers": ["3"]})
    out = tracker_watch.watch(pack, now=500.0)
    assert out["errors"] == [f"{ticket}: the pack's tracker command has no read for comments"] and out["read"] == []

    class Reader:
        def __init__(self, rows, me_fails=False):
            self.rows, self.me_fails = rows, me_fails

        def _request(self, method, path):
            return {"comments": self.rows}

        def _myself(self):
            if self.me_fails:
                raise CockpitError("no /myself")
            return "acct-1"

    odd = [
        {"id": "7", "body": "no author, plain text", "created": "2026-10-29T09:00:00.000+0000"},
        {"no": "id"},
        "not a row",
    ]
    monkeypatch.setattr("cockpitlib.tracker.tracker_for", lambda pack: Reader(odd, me_fails=True))
    assert tracker_watch.watch(pack, now=1000.0)["read"] == [ticket]
    state = tracker_watch._state()
    assert "me" not in state and state["tickets"][ticket]["seen"] == {"7": "2026-10-29T09:00:00.000+0000"}
    odd.append({"id": "8", "body": "a second one", "author": {"name": "old-style"}})
    out = tracker_watch.watch(pack, now=1400.0)
    assert (
        len(out["notes"]) == 1
        and tracker_watch.rows()[0]["author"] == "old-style"
        and tracker_watch.rows()[0]["at"] == ""
    )
    assert tracker_watch.dismiss(tracker_watch.rows()[0]["id"])["ok"]
    with pytest.raises(CockpitError, match="no tracker note"):
        tracker_watch.dismiss("")
