# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional settings of slots, plans and lends (slot state, plan commands, the plan gate and the in-tool advisor,
the privileged lend, the test flow, CI, uploads). Both fixture packs; every setting is optional and its default is what the
kernel did before."""

import base64
import json
import os
import shutil
import sqlite3

import pytest
import yaml

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support import words
from tests.support.boards import put_card

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


def _status(board, card):
    from cockpitlib.kanban import board_cards

    return {item["id"]: item["status"] for item in board_cards(board)}[card]


def _comments(board, card):
    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(f"file:{db_path(board)}?mode=ro", uri=True)
    rows = [
        row[0]
        for row in connection.execute("select body from task_comments where task_id = ? order by created_at", (card,))
    ]
    connection.close()
    return rows


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_session_change_the_kernel_makes_alone_reaches_the_packs_state_folder(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.slots import pack_state_dir, write_owner, write_ticket

    pack = load(pack_file)
    folder = pack_state_dir(2)
    assert folder and folder != os.path.join(os.environ["COCKPIT_VOLUMES"], "slot-2")
    write_owner(2, "human")
    write_ticket(2, "TASK-9")
    assert (
        open(os.path.join(folder, "owner")).read() == "human\n"
        and open(os.path.join(folder, "ticket")).read() == "TASK-9\n"
    )
    assert open(os.path.join(os.environ["COCKPIT_VOLUMES"], "slot-2", "owner")).read() == "human\n"
    assert (
        pack["slots"]["state_dir"].format(
            slot=2, root=os.environ["COCKPIT_ROOT"], workspace=os.environ["COCKPIT_WORKSPACE"]
        )
        == folder
    )


def test_no_pack_means_no_mirror(bare, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", "/nonexistent/pack.yaml")
    from cockpitlib.slots import pack_state_dir, write_owner

    assert pack_state_dir(1) == ""
    write_owner(1, "free")  # nothing to mirror, nothing breaks


@pytest.mark.parametrize("pack_file", PACKS)
def test_plan_init_and_append_take_a_file_stdin_and_a_decision_flag(bare, pack_file, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.cli import main
    from cockpitlib.plan import sections, show

    outline = tmp_path / "outline.md"
    outline.write_text("# Plan\n\n## Impacted areas\n\nthe report\n", encoding="utf-8")
    assert (
        main(["plan", "init", "TASK-50", "--file", str(outline), "--decision", "go with changes: keep it small"]) == 0
    )
    assert "Impacted areas" in sections("TASK-50") and "go with changes" in show("TASK-50")
    note = tmp_path / "note.md"
    note.write_text("run 1: 3 pass", encoding="utf-8")
    assert main(["plan", "append", "TASK-50", "Tested", "--file", str(note)]) == 0 and "run 1: 3 pass" in show(
        "TASK-50"
    )
    capsys.readouterr()
    assert (
        main(["plan", "init", "TASK-52", "--file"]) == 2
        and main(["plan", "init", "TASK-52", "--file", "/nonexistent/x.md"]) == 2
    )
    assert main(["plan", "show", "TASK-50"]) == 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_go_reads_the_proposal_where_the_intake_filed_it(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.acts import answer_card, proposal_path
    from cockpitlib.paths import qa
    from cockpitlib.plan import show

    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-52"
    assert proposal_path(ticket) == ""
    folder = os.path.join(qa(), ticket, "intake")
    os.makedirs(folder)
    older, newer = os.path.join(folder, "proposal-1.md"), os.path.join(folder, "proposal-2.md")
    open(older, "w").write("# Old\n")
    open(newer, "w").write("# The outline\n\n## Scope\n\nx\n")
    os.utime(older, (1, 1))
    assert proposal_path(ticket) == newer
    direct = os.path.join(qa(), ticket, "proposal.md")
    open(direct, "w").write("# Direct\n")
    assert proposal_path(ticket) == direct
    os.remove(direct)
    card = put_card(pack["board"], f"{ticket}: intake", "intake", "ready")
    _block(pack["board"], card, "go? the plan is on the card")
    answer_card(pack, card, "go")
    assert "The outline" in show(ticket)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_inbox_go_is_the_plan_ok_and_an_in_tool_advisors_line_is_the_c0_answer(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib import advise as advisor
    from cockpitlib import plan_gate

    pack = load(pack_file)
    assert (
        plan_gate.PLAN_OK.match("Human: go")
        and plan_gate.PLAN_OK.match("Human: go with changes: x")
        and plan_gate.PLAN_OK.match("Human: plan ok")
    )
    assert not plan_gate.PLAN_OK.match("Human: gone fishing")
    answers = ["APPROVED", "CHANGES", "DEVIATES"]
    assert advisor.parse_said(answers, "C0", "ADVISOR: C0=CHANGES the outline misses X. C2=CLEAN") == "CHANGES"
    assert (
        advisor.parse_said(answers, "C0", "DEVIATES: the plan differs") == "DEVIATES"
        and advisor.parse_said(answers, "C0", "nothing") == ""
    )
    config = {
        "in_tool": True,
        "report_line": "^ADVISOR:",
        "checkpoints": {"C0": {"answers": answers, "block_on": ["DEVIATES"]}},
    }
    monkeypatch.setattr(advisor, "config", lambda p: config)
    ticket = f"{pack['tracker']['project']}-53"
    card = put_card(pack["board"], f"{ticket}: work", "worker-1", "running")
    with pytest.raises(CockpitError, match="--said"):
        advisor.advise(pack, "C0", ticket=ticket, card=card)
    said = advisor.advise(pack, "C0", ticket=ticket, card=card, said="ADVISOR: C0=CHANGES small things C2=CLEAN")
    assert said["verdict"] == "CHANGES" and said["ok"]
    assert plan_gate._deviated(pack, ticket, card) is False  # the pack holds the worker only on DEVIATES
    advisor.advise(pack, "C0", ticket=ticket, card=card, said="ADVISOR: C0=DEVIATES the plan differs")
    assert plan_gate._deviated(pack, ticket, card) is True
    nothing = advisor.advise(pack, "C0", ticket=ticket, card="", said="no verdict here")
    assert nothing["verdict"] == "" and not nothing["ok"]
    from cockpitlib.cli import main

    assert main(["advise", "C0", "--ticket", ticket, "--said", "ADVISOR: C0=APPROVED C2=CLEAN"]) == 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_privileged_request_is_an_inbox_row_from_the_board_and_approve_resumes_the_card(
    env, pack_file, monkeypatch, tmp_path
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib import lend

    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-54"
    card = put_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    assert lend.inbox_rows(pack) == []
    _block(pack["board"], card, lend.request_line(pack, "Admin → Users → x → set Y", "row 4 needs it"))
    rows = lend.inbox_rows(pack)
    assert (
        [row["card"] for row in rows] == [card]
        and rows[0]["summary"] == "Admin → Users → x → set Y"
        and lend._step_for(card, pack).startswith("Admin")
    )
    assert (
        lend.inbox_rows() and _client().get("/needs-you").json()["privileged"][0]["card"] == card
    )  # the route passes the pack
    monkeypatch.setattr("cockpitlib.vault.sealed_to", lambda: "FP")
    monkeypatch.setattr(
        "cockpitlib.vault._items",
        lambda: [{"privileged": True, "email": "a@b.test", "origin": "https://x", "secret": "s", "label": "x"}],
    )
    monkeypatch.setattr("cockpitlib.lane_vault.place", lambda *a, **k: "item-1")
    monkeypatch.setattr("cockpitlib.scrub.rebuild", lambda *a, **k: None)
    monkeypatch.setattr(lend, "_drop_previous_lend", lambda card: None)
    assert lend.approve(card, "tester-1", 1, pack) == "lent"
    assert _status(pack["board"], card) in ("ready", "todo") and any(
        "approved: the privileged login is lent" in text for text in _comments(pack["board"], card)
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_denied_privileged_request_blocks_or_resumes_as_the_pack_says(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import lend

    base = load(pack_file)
    ticket = f"{base['tracker']['project']}-55"
    for setting, resumed in (("resume", True), ("block", False)):
        pack_path = _copy_pack(
            pack_file, tmp_path / setting, lambda data, _dir: data.setdefault("privileged", {}).update(on_deny=setting)
        )
        monkeypatch.setenv("COCKPIT_PACK", pack_path)
        pack = load(pack_path)
        card = put_card(pack["board"], f"{ticket}: test {setting}", "tester-1", "ready")
        _block(pack["board"], card, lend.request_line(pack, "a step", "why"))
        assert lend.deny(card, pack) == "denied"
        assert (_status(pack["board"], card) in ("ready", "todo")) is resumed
    bad = _copy_pack(
        pack_file, tmp_path / "bad", lambda data, _dir: data.setdefault("privileged", {}).update(on_deny="never")
    )
    with pytest.raises(CockpitError, match="on_deny"):
        load(bad)


def test_human_rows_covered_rows_and_api_proofs_count_as_done():
    from cockpitlib.test_flow import results_still_open, unfinished

    rows = [
        {"n": "1", "result": "✅ Pass", "scenario": "login", "evidence": "evidence/1.png"},
        {"n": "2", "result": "✅ Pass", "scenario": "👤 email arrives", "evidence": ""},  # the human's proof
        {"n": "3", "result": "Not run (covered by row 1)", "scenario": "same page", "note": "", "evidence": ""},
        {"n": "4", "result": "✅ Pass", "scenario": "api", "evidence": "evidence/4-call.mcp.json"},
        {"n": "5", "result": "✅ Pass", "scenario": "ui", "evidence": "evidence/5.md"},
        {"n": "6", "result": "Not run", "scenario": "x", "note": "covered by row 2", "evidence": ""},
        {"n": "7", "result": "Blocked", "scenario": "y", "evidence": ""},
    ]
    assert unfinished(rows) == ["5·screenshot", "7·open"]
    assert not results_still_open("| 3 | x | Not run (covered by row 1) |") and results_still_open(
        "| 3 | x | Not run |"
    )
    assert not results_still_open("| 2 | 👤 mail | ✅ Pass |") and results_still_open("| 2 | 👤 mail | |")


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_unfinished_review_is_sent_back_when_the_pack_says_how_long_to_wait(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib.housekeeping import _send_back_testers
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import run_folders, run_pattern

    ticket = "TASK-56"
    base = load(pack_file)
    ticket = f"{base['tracker']['project']}-56"
    pack_path = _copy_pack(pack_file, tmp_path, lambda data, _dir: data.setdefault("testflow", {}).update(send_back=0))
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    folder = os.path.join(
        qa(),
        ticket,
        run_folders(pack, os.path.join(qa(), ticket))[-1]
        if os.path.isdir(os.path.join(qa(), ticket))
        else run_pattern(pack).format(n=1),
    )
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "test-results.md"), "w").write(
        "# r\n\n## Summary\n\n| # | Scenario | Result | Evidence |\n|---|---|---|---|\n| 1 | a | Not run | |\n"
    )
    card = put_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    _block(pack["board"], card, words.worded(pack, "Run 001 ready for your review: 0 pass"))
    assert _send_back_testers(pack) == 1
    assert _status(pack["board"], card) in ("ready", "todo") and any(
        "Not ready for the human's review" in text for text in _comments(pack["board"], card)
    )
    assert _send_back_testers(load(pack_file)) == 0  # without the setting nothing is sent back


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_test_run_report_needs_a_test_kickoff_and_the_humans_go_when_the_pack_says_so(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.kanban import BoardWrites
    from cockpitlib.test_flow import _test_cards, human_go_after_review, post_problems

    base = load(pack_file)
    ticket = f"{base['tracker']['project']}-57"
    pack_path = _copy_pack(
        pack_file, tmp_path, lambda data, _dir: data.setdefault("testflow", {}).update(test_run_posts="kickoff")
    )
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    intent = {
        "type": "tracker-comment",
        "ticket": ticket,
        "payload": {"body": words.worded(pack, "## Test Run\n\nTested and Ok")},
    }
    monkeypatch.setattr("cockpitlib.outbox._body_text", lambda payload: payload.get("body") or "")
    assert "belongs to a Test kickoff" in post_problems(pack, intent)[0]
    assert (
        post_problems(pack, {**intent, "payload": {"body": "just a note"}}) == []
        and post_problems(pack, {**intent, "type": "pr-comment"}) == []
    )
    card = put_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    assert [row[0] for row in _test_cards(pack, ticket)] == [card] and not human_go_after_review(pack, ticket)
    assert 'no "go"' in post_problems(pack, intent)[0]
    _block(pack["board"], card, words.worded(pack, "Run 001 ready for your review: all pass"))
    assert not human_go_after_review(pack, ticket)
    writes = BoardWrites(pack["board"])
    writes.comment(card, "human", "Human: go")
    writes.flush()
    assert human_go_after_review(pack, ticket)
    assert not any("belongs to" in text or 'no "go"' in text for text in post_problems(pack, intent))
    bad = _copy_pack(
        pack_file, tmp_path / "bad", lambda data, _dir: data.setdefault("testflow", {}).update(test_run_posts="always")
    )
    with pytest.raises(CockpitError, match="test_run_posts"):
        load(bad)


@pytest.mark.parametrize("pack_file", PACKS)
def test_ci_announces_a_failure_comments_a_failing_rerun_and_rereads_a_settled_commit_when_asked(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import ci_watch

    base = load(pack_file)
    ticket = f"{base['tracker']['project']}-58"
    pack_path = _copy_pack(
        pack_file, tmp_path, lambda data, _dir: data.setdefault("hours", {}).update(ci_reread_minutes=5)
    )
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    monkeypatch.setattr(ci_watch, "_tail", lambda *a: "")
    run = {"id": 7, "name": "tests", "run_attempt": 1, "html_url": "https://ci/7"}
    first = ci_watch._card(pack, ticket, "api", "abcdef1234567", "work", run, None)
    again = ci_watch._card(
        pack,
        ticket,
        "api",
        "abcdef1234567",
        "work",
        {**run, "id": 8, "run_attempt": 2, "html_url": "https://ci/8"},
        None,
    )
    assert again == first and any(
        "failed again: attempt 2" in text and "https://ci/8" in text for text in _comments(pack["board"], first)
    )
    sent = []
    monkeypatch.setattr(ci_watch, "_announce", lambda pack, ticket, sha, what: sent.append(what) or "ok")
    monkeypatch.setattr(ci_watch, "commits", lambda pack: [(ticket, "api", "feedface12345", "work")])

    class Forge:
        runs = [
            {
                "id": 11,
                "name": "tests",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 1,
                "html_url": "u",
            }
        ]

        def repo(self, name):
            return f"org/{name}"

        def get(self, path):
            return {"workflow_runs": Forge.runs}

    monkeypatch.setattr("cockpitlib.publish.forge_for", lambda pack: Forge())
    done = ci_watch.watch(pack, now=1000)
    assert len(done["cards"]) == 1 and sent == ["failed"]
    path = ci_watch.record_path(ticket, "api", "feedface12345")
    record = json.load(open(path))
    record["settled"] = True
    record["last_check"] = "2026-10-26T10:00:00Z"
    json.dump(record, open(path, "w"))
    Forge.runs = [{**Forge.runs[0], "id": 12, "run_attempt": 2}]
    assert (
        len(ci_watch.watch(pack, now=1e12)["cards"]) == 1
    )  # settled and old enough: read again, the new attempt is seen
    record = json.load(open(path))
    record["settled"], record["last_check"] = True, "2026-10-26T10:00:00Z"
    json.dump(record, open(path, "w"))
    assert (
        ci_watch.watch(load(pack_file), now=1e12)["cards"] == []
    )  # without the setting a settled commit is not read again
    assert ci_watch._stamp("not a time") == 0.0


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_failed_commit_settles_and_is_not_read_every_pass_and_a_pack_without_the_setting_still_rereads_it(
    env, pack_file, monkeypatch
):
    from cockpitlib import ci_watch

    base = load(pack_file)
    ticket = f"{base['tracker']['project']}-59"
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert "ci_reread_minutes" not in (pack.get("hours") or {})
    monkeypatch.setattr(ci_watch, "_tail", lambda *a: "")
    monkeypatch.setattr(ci_watch, "_announce", lambda pack, ticket, sha, what: "ok")
    monkeypatch.setattr(ci_watch, "commits", lambda pack: [(ticket, "api", "deadbeef12345", "work")])
    reads = []

    class Forge:
        runs = [
            {
                "id": 21,
                "name": "tests",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 1,
                "html_url": "u",
            }
        ]

        def repo(self, name):
            return f"org/{name}"

        def get(self, path):
            reads.append(path)
            return {"workflow_runs": Forge.runs}

    monkeypatch.setattr("cockpitlib.publish.forge_for", lambda pack: Forge())
    path = ci_watch.record_path(ticket, "api", "deadbeef12345")
    ci_watch.watch(pack, now=1000)
    assert not json.load(open(path)).get("settled")  # just failed: the settle window has not passed
    settle = float((pack.get("hours") or {}).get("ci_settle_minutes") or ci_watch.SETTLE_MINUTES) * 60
    ci_watch.watch(pack, now=1000 + 60)  # completed_at is stamped on this pass
    ci_watch.watch(pack, now=1000 + 60 + settle + 1)
    assert json.load(open(path))["settled"] is True
    seen = len(reads)
    ci_watch.watch(pack, now=1000 + 60 + settle + 120)
    assert len(reads) == seen  # settled: the forge is not read again
    record = json.load(open(path))
    record["last_check"] = "2026-10-26T10:00:00Z"
    json.dump(record, open(path, "w"))
    Forge.runs = [{**Forge.runs[0], "id": 22, "run_attempt": 2}]
    assert (
        len(ci_watch.watch(pack, now=1e12)["cards"]) == 1
    )  # no pack setting: the default re-read still sees a hand-run attempt


def test_a_record_is_written_only_when_it_says_something_new(tmp_path):
    from cockpitlib.record_write import write_record

    path = str(tmp_path / "qa" / "T-1" / "pr" / "r-1.json")
    assert write_record(path, {"state": "open", "last_check": "2026-10-27T10:00:00Z"})
    mtime = os.path.getmtime(path)
    assert not write_record(
        path, {"state": "open", "last_check": "2026-10-27T11:00:00Z"}
    )  # only the time moved, however long ago
    assert os.path.getmtime(path) == mtime and json.load(open(path))["last_check"] == "2026-10-27T10:00:00Z"
    assert write_record(
        path, {"state": "merged", "last_check": "2026-10-27T11:05:00Z"}
    )  # a real change brings its time along
    assert json.load(open(path)) == {"state": "merged", "last_check": "2026-10-27T11:05:00Z"}
    json.dump(["not", "a", "record"], open(path, "w"))
    assert write_record(path, {"state": "merged"})  # a file that is no record is replaced


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_real_ci_verdict_gives_intake_the_diagnosis_and_a_rerun_names_its_card(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib import acts, ci_watch
    from cockpitlib.kanban import BoardWrites, board_cards

    pack = load(pack_file)
    monkeypatch.setattr(ci_watch, "_tail", lambda *a: "")
    ticket = f"{pack['tracker']['project']}-59"
    sha = "1234567890abcdef"
    diag = ci_watch._card(
        pack, ticket, "api", sha, "work", {"id": 3, "name": "tests", "run_attempt": 1, "html_url": ""}, None
    )
    assert acts._diagnosis_card(pack, ticket, sha) == diag and acts._diagnosis_of(pack, ticket, sha) == ""
    writes = BoardWrites(pack["board"])
    writes.comment(diag, "analyst-1", "Real: the date helper uses today's offset.")
    writes.flush()
    assert (
        "the date helper uses today's offset" in acts._diagnosis_of(pack, ticket, sha)
        and acts._diagnosis_of(pack, "", "") == ""
    )
    marked = acts.mark_ci(pack, ticket, sha, "real", "api")
    cards = {card["id"]: card for card in board_cards(pack["board"])}
    assert "The analyst's diagnosis" in cards[marked["card_id"]]["body"]
    flaky = acts.mark_ci(pack, ticket, sha, "flaky", "api", "3")
    from cockpitlib.intents import load as load_intent

    assert load_intent(flaky["intent"])["card_id"] == diag


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_rework_cards_skills_count_for_the_gate(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.kanban import place_card
    from cockpitlib.skill_log import missing

    pack = load(pack_file)
    kind = next((name for name, need in (pack.get("skills") or {}).get("intent", {}).items() if need), "")
    if not kind:
        pytest.skip("this fixture pack requires no skill for any intent")
    needed = [
        item for entry in pack["skills"]["intent"][kind] for item in (entry if isinstance(entry, list) else [entry])
    ]
    ticket = f"{pack['tracker']['project']}-60"
    own = put_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    rework = place_card(
        pack["board"], f"{ticket}: rework", "worker-1", "ready", skills=needed, kind="rework", ticket=ticket
    )
    intent = {"type": kind, "ticket": ticket, "created_by": "worker-1", "card_id": own}
    assert missing(pack, intent)
    assert (
        missing(pack, {**intent, "returned": {"card": rework}}) == []
        and missing(pack, {**intent, "treatments": [{"card": rework}]}) == []
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_card_goes_to_its_slots_seat_when_the_pack_asks(bare, pack_file, monkeypatch, tmp_path):
    from cockpitlib.lanes import free_lane
    from cockpitlib.slots import write_owner, write_ticket

    wide = lambda data, _dir: data.update(seats={**data["seats"], "slots": 3})
    base = load(_copy_pack(pack_file, tmp_path / "plain", wide))
    pack_path = _copy_pack(
        pack_file, tmp_path, lambda data, _dir: (wide(data, _dir), data.update(lanes={"by_slot": True}))
    )
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    write_owner(2, "lane:worker-2")
    write_ticket(2, "TASK-61")
    assert (
        free_lane("worker", pack, {"worker-2": 5}, ticket="TASK-61") == "worker-2"
        and free_lane("tester", pack, {}, ticket="TASK-61") == "tester-2"
    )
    assert (
        free_lane("worker", pack, {"worker-2": 5}, ticket="TASK-62") == "worker-1"
        and free_lane("reviewer", pack, {}, ticket="TASK-61") == "reviewer"
    )
    assert (
        free_lane("worker", base, {"worker-2": 5}, ticket="TASK-61") == "worker-1"
    )  # without the setting: the least loaded
    for wrong in ({"by_slot": "yes"}, {"other": 1}, ["x"]):
        with pytest.raises(CockpitError, match="lanes takes"):
            load(
                _copy_pack(
                    pack_file, tmp_path / str(abs(hash(str(wrong)))), lambda data, _dir: data.update(lanes=wrong)
                )
            )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_page_uploads_bytes_and_verify_says_what_it_found(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-62"
    sent = (
        _client()
        .post(
            "/upload",
            json={"ticket": ticket, "name": "../shot 1.png", "b64": base64.b64encode(b"\x89PNG-bytes").decode()},
        )
        .json()
    )
    assert (
        sent["ok"]
        and sent["size"] == 10
        and open(sent["path"], "rb").read() == b"\x89PNG-bytes"
        and "/human/" in sent["path"]
        and sent["path"].endswith("shot 1.png")
    )
    assert (
        _client()
        .post("/upload", json={"ticket": ticket, "name": "n.txt", "b64": base64.b64encode(b"a note").decode()})
        .json()["ok"]
    )
    assert _client().post("/upload", json={"ticket": ticket, "b64": "!!"}).status_code in (200, 400)
    assert (
        _client()
        .post("/upload", json={"ticket": ticket, "name": "x", "b64": base64.b64encode(b"").decode()})
        .status_code
        == 400
    )
    monkeypatch.setattr("dashboard.cockpit.routes.pages._secret", lambda text: "secret" in text)
    assert (
        _client()
        .post("/upload", json={"ticket": ticket, "name": "s.txt", "b64": base64.b64encode(b"a secret").decode()})
        .status_code
        == 400
    )
    monkeypatch.setattr("dashboard.cockpit.routes.pages.MAX_BYTES", 3)
    assert (
        _client()
        .post("/upload", json={"ticket": ticket, "name": "big.bin", "b64": base64.b64encode(b"\xff" * 9).decode()})
        .status_code
        == 400
    )
    monkeypatch.setattr("cockpitlib.outbox.verify", lambda iid, pack=None: ["head moved"])
    assert "head moved" in _client().post("/verify", json={"id": "T-1/001-push-branch"}).json()["out"]
    monkeypatch.setattr("cockpitlib.outbox.verify", lambda iid, pack=None: [])
    assert _client().post("/verify", json={"id": "T-1/001-push-branch"}).json()["out"] == "verify ok"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_demo_login_without_a_password_stores_nothing_and_a_refusal_goes_back_to_its_lane_kind(
    env, pack_file, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib import refusals
    from cockpitlib.kanban import board_cards

    pack = load(pack_file)

    class Provider:
        def login(self, ticket, user):
            return {"user": user, "password": ""}

    monkeypatch.setattr("cockpitlib.slots.provider_for", lambda *a, **k: Provider())
    assert _client().post("/demo-login", json={"ticket": "T-1", "user": "u"}).status_code == 409
    ticket = f"{pack['tracker']['project']}-63"
    refusals.record(ticket, "tracker-comment", "", "tester-2", "no table")
    key = refusals.unresolved(pack)[0]["key"]
    answer = _client().post("/refusal-send-back", json={"key": key}).json()
    made = next(item for item in board_cards(pack["board"]) if item["id"] == answer["card_id"])
    assert made["assignee"].startswith("tester")


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_first_batchs_edges_fail_quietly_and_say_why(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import lend, test_flow
    from cockpitlib.acts import _diagnosis_of
    from cockpitlib.housekeeping import _send_back_testers
    from cockpitlib.slots import read_owner, write_owner

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-63"
    # an upload whose bytes are not base64
    assert _client().post("/upload", json={"ticket": ticket, "name": "n.bin", "b64": "abc"}).status_code == 400
    with monkeypatch.context() as patched:  # the analyst's diagnosis: a board that cannot be read is no diagnosis
        patched.setattr(
            "cockpitlib.kanban._index",
            lambda: {pack["board"]: {"t_x": {"kind": "ci", "ticket": ticket, "key": "abcdef123"}}},
        )
        patched.setattr("cockpitlib.kanban.db_path", lambda _board: str(tmp_path / "missing.db"))
        assert _diagnosis_of(pack, ticket, "abcdef1234567") == ""
        patched.setattr(
            test_flow, "_test_cards", lambda *_a, **_k: []
        )  # a human's go after the review: no tester card, or no readable board
        assert test_flow.human_go_after_review(pack, ticket) is False
        patched.setattr(test_flow, "_test_cards", lambda *_a, **_k: [("t_x", "", "tester-1")])
        assert test_flow.human_go_after_review(pack, ticket) is False
    with monkeypatch.context() as patched:  # the privileged rows: no pack to read gives none
        patched.setenv("COCKPIT_PACK", "/nonexistent/pack.yaml")
        assert lend.inbox_rows() == []
    card = put_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    line = lend.request_line(pack, "a step", "why")
    _block(pack["board"], card, line)
    assert lend.note_block(line, card) == "asked" and [row["card"] for row in lend.inbox_rows(pack)] == [
        card
    ]  # written twice, shown once
    with monkeypatch.context() as patched:  # an approve whose card cannot be answered still lends
        patched.setattr("cockpitlib.vault.sealed_to", lambda: "FP")
        patched.setattr(
            "cockpitlib.vault._items",
            lambda: [{"privileged": True, "email": "a@b.test", "origin": "https://x", "secret": "s", "label": "x"}],
        )
        patched.setattr("cockpitlib.lane_vault.place", lambda *a, **k: "item-1")
        patched.setattr("cockpitlib.scrub.rebuild", lambda *a, **k: None)
        patched.setattr(lend, "_drop_previous_lend", lambda _card: None)

        def refuse(*_a, **_k):
            raise CockpitError("no such card")

        patched.setattr("cockpitlib.acts.answer_card", refuse)
        assert lend.approve(card, "tester-1", 1, pack) == "lent"
    # an unfinished review is sent back only for a tester card with rows still open
    sent = _copy_pack(
        pack_file, tmp_path / "sent", lambda data, _dir: data.setdefault("testflow", {}).update(send_back=0)
    )
    sent_pack = load(sent)
    with monkeypatch.context() as patched:
        patched.setenv("COCKPIT_PACK", sent)
        _block(sent_pack["board"], put_card(sent_pack["board"], f"{ticket}: work", "worker-1", "ready"), "a question")
        from cockpitlib.paths import qa
        from cockpitlib.test_flow import run_pattern

        done = f"{sent_pack['tracker']['project']}-64"
        folder = os.path.join(qa(), done, run_pattern(sent_pack).format(n=1))
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "test-results.md"), "w").write(
            "# r\n\n## Summary\n\n| # | Scenario | Result | Evidence |\n|---|---|---|---|\n| 1 | 👤 email arrives | ✅ Pass | |\n"
        )
        _block(
            sent_pack["board"],
            put_card(sent_pack["board"], f"{done}: test", "tester-2", "ready"),
            words.worded(pack, "Run 001 ready for your review: all pass"),
        )
        assert _send_back_testers(sent_pack) == 0
    # the pack's state folder is only a mirror: a folder that cannot be made is skipped, the slot's own state still holds
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    broken = _copy_pack(
        pack_file,
        tmp_path / "broken",
        lambda data, _dir: data.setdefault("slots", {}).update(state_dir=f"{blocker}/slot-{{slot}}"),
    )
    with monkeypatch.context() as patched:
        patched.setenv("COCKPIT_PACK", broken)
        write_owner(1, "human")
        assert read_owner(1) == "human"
    with pytest.raises(CockpitError, match="send_back"):
        load(
            _copy_pack(
                pack_file,
                tmp_path / "wrong",
                lambda data, _dir: data.setdefault("testflow", {}).update(send_back="soon"),
            )
        )
