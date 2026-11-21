# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The gatekeeper sweeps the outbox, holds, digests and reconciles, and a sequence leaves one stage at a time."""

import json
import os
import re

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, ROOT, _client, _notified, _other


@pytest.mark.parametrize("pack_file", PACKS)
def test_one_gatekeeper_card_sweeps_and_holds_on_the_lanes_come_back(env, pack_file, monkeypatch):
    import sqlite3

    from cockpitlib.acts import sweep_state
    from cockpitlib.gate import recard, resweep_held, sweep
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import BoardWrites, board_cards, db_path, place_card
    from cockpitlib.outbox import create, hold
    from cockpitlib.paths import outbox
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1201"
    board = pack["board"]
    assert sweep(pack) == "0"
    first = create(pack, ticket, "pr-comment", "c", "note", {"repo": repo, "number": 1, "body": f"note {pack['name']}"})
    second = create(pack, ticket, "ci-rerun", "c", "rerun", {"repo": repo, "run_id": 7})
    assert sweep_state()["requested"] is True and sweep(pack) == "1"
    cards = [card for card in board_cards(board, pack) if card["flow"] == "sweep"]
    assert (
        len(cards) == 1
        and cards[0]["assignee"] == "gatekeeper"
        and cards[0]["ticket"] == f"{pack['tracker']['project']}-OUTBOX"
    )
    assert (
        first["id"] in cards[0]["body"] and second["id"] in cards[0]["body"] and "cockpit:outbox" in cards[0]["skills"]
    )
    assert sweep(pack) == "running" and sweep_state()["running"] is True
    create(pack, ticket, "ci-rerun", "c", "again", {"repo": repo, "run_id": 8})
    assert sweep(pack) == "running"
    writes = BoardWrites(board)
    writes.complete(cards[0]["id"], result="swept")
    writes.flush()
    assert sweep(pack) == "1"  # the request made while the first card ran gets a card of its own
    second_card = [card for card in board_cards(board, pack) if card["flow"] == "sweep" and card["status"] != "done"][0]
    connection = sqlite3.connect(db_path(board))
    connection.execute("update tasks set status = 'archived' where id = ?", (second_card["id"],))
    connection.commit()
    connection.close()
    assert sweep(pack) == "1"  # an unfinished card's request is served again
    for row in [first, second]:
        row = load_intent(row["id"])
        row["status"] = "endorsed"
        save(row)
    # A hold that waits on the lanes: back to pending once a card of the ticket completes; the human's when none is left.
    card = place_card(board, f"{ticket}: work", "worker-1", "ready")
    waiting = create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 9})
    waiting = hold(waiting["id"], f"tests still run for {pack['name']}", waits="lane", pack=pack)
    assert waiting["hold"]["waits"] == "lane" and resweep_held(pack) == "0"
    writes = BoardWrites(board)
    writes.complete(card, result="done")
    writes.flush()
    assert resweep_held(pack) == "1"
    back = load_intent(waiting["id"])
    assert back["status"] == "pending" and back["history"][-1]["card"] == card and "hold" not in back
    alone = hold(waiting["id"], "waits for nothing", waits="lane", pack=pack)
    assert alone["hold"]["waits"] == "human"
    lonely = create(pack, f"{ticket}9", "ci-rerun", "c", "x", {"repo": repo, "run_id": 10})
    lonely = hold(lonely["id"], "a lane hold", waits="lane")
    assert resweep_held(pack) == "0" and load_intent(lonely["id"])["hold"]["waits"] == "human"
    # A rework with no question goes straight back to the lane; a push also gets a tester and a reviewer behind it.
    branch = f"work/{ticket}"
    fake_gh.commit(repo, branch)
    push = create(pack, ticket, "push-branch", "c", "push", {"repo": repo, "branch": branch}, created_by="worker-1")
    sent = hold(push["id"], f"the diff misses {pack['name']} tests", rework="add the tests", chain=True, pack=pack)
    assert (
        sent["status"] == "returned"
        and sent["returned"]["lane"] == "worker-1"
        and sent["returned"]["by"] == "gatekeeper (rework)"
    )
    made = {card["id"]: card for card in board_cards(board, pack)}
    rework = made[sent["returned"]["card"]]
    assert (
        rework["flow"] == "rework"
        and "add the tests" in rework["body"]
        and f"cockpit outbox amend {push['id']}" in rework["body"]
    )
    assert [lane.split("-")[0] for lane, _card in sent["returned"]["chain"]] == ["tester", "reviewer"]
    skill = ((pack.get("skills") or {}).get("intent") or {})["pr-comment"][0]
    redo = create(pack, ticket, "pr-comment", "c", "n", {"repo": repo, "number": 1, "body": "x"}, created_by="reviewer")
    redone = hold(redo["id"], f"redo with skill {skill} loaded", pack=pack)
    assert (
        redone["status"] == "returned"
        and redone["returned"]["extra_skills"] == [skill]
        and redone["returned"]["chain"] == []
    )
    assert skill in {card["id"]: card for card in board_cards(board, pack)}[redone["returned"]["card"]]["skills"]
    asked = create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 11})
    asked = hold(
        asked["id"],
        "which run?",
        rework="pick the newer",
        ask="the newer or the older?",
        options=["newer", "older"],
        pack=pack,
    )
    assert (
        asked["status"] == "held"
        and asked["hold"]["options"] == ["newer", "older"]
        and asked["hold"]["waits"] == "human"
    )
    # A return whose card could not be made now gets it from the housekeeping step.
    from cockpitlib import kanban

    real = kanban.place_card

    def refused(*_args, **_kwargs):
        from cockpitlib.errors import CockpitError

        raise CockpitError(f"board busy for {pack['name']}")

    monkeypatch.setattr(kanban, "place_card", refused)
    later = create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 12})
    from cockpitlib.gate import return_intent

    late = return_intent(pack, later["id"], "use the other run")
    assert late["returned"]["card"] == "" and f"board busy for {pack['name']}" in late["returned"]["card_error"]
    assert recard(pack) == "0" and "board busy" in load_intent(later["id"])["returned"]["card_error"]
    monkeypatch.setattr(kanban, "place_card", real)
    assert recard(pack) == "1" and load_intent(later["id"])["returned"]["card"]
    from cockpitlib.errors import CockpitError

    shipped = load_intent(first["id"])
    shipped["status"] = "published"
    save(shipped)
    with pytest.raises(CockpitError, match="only an open intent is sent back"):
        return_intent(pack, first["id"], "x")
    assert os.path.isfile(os.path.join(outbox(), ticket, f"{later['id'].split('/')[1][:3]}-return.md"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_human_answers_the_digest_by_number(env, pack_file, monkeypatch, capsys):
    from cockpitlib.errors import CockpitError
    from cockpitlib.gate import digest, reply
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create, endorse
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1202"
    with pytest.raises(CockpitError, match="no digest numbering yet"):
        reply(pack, "publish all")
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    fake_gh.pull(full, 1, "work/x", "a" * 40)
    rows = []
    for run in (21, 22, 23, 24):
        rows.append(
            endorse(
                create(pack, ticket, "ci-rerun", "c", f"run {run}", {"repo": repo, "run_id": run})["id"],
                "low",
                "",
                "gatekeeper",
                "fixture-a",
                "fixture-large",
            )
        )
    review = endorse(
        create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 1, "sha": "a" * 40, "body": "ok"})[
            "id"
        ],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    pending = create(pack, ticket, "ci-rerun", "c", "later", {"repo": repo, "run_id": 25})
    numbered = digest()
    by_id = {row["id"]: row["number"] for row in numbered}
    assert by_id[pending["id"]] == len(numbered) and set(by_id) == {
        *[row["id"] for row in rows],
        review["id"],
        pending["id"],
    }
    number = lambda row: str(by_id[row["id"]])  # noqa: E731
    lines = reply(pack, f"publish {number(rows[0])}-{number(rows[1])}")
    assert len(lines) == 2 and all("/actions/runs/" in line for line in lines)
    assert reply(pack, f"hold {number(rows[2])}: not yet, {pack['name']}") == [f"held {rows[2]['id']}"]
    assert load_intent(rows[2]["id"])["hold"]["reason"] == f"human: not yet, {pack['name']}"
    assert reply(pack, f"drop {number(rows[3])}") == [f"dropped {rows[3]['id']}"]
    assert reply(pack, f"open {number(review)}")[0].endswith(f"{review['id'].split('/')[1]}.json")
    assert reply(pack, f"publish {number(review)}")[0].endswith(
        "#pullrequestreview-" + str(load_intent(review["id"])["review"]["id"])
    )
    assert "submitted only when you name" in reply(pack, "publish all")[0]
    assert (
        "submit" in json.dumps(reply(pack, f"publish {number(review)}"))
        or load_intent(review["id"])["status"] == "published"
    )
    stop = endorse(
        create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 26})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    stop["payload"]["run_id"] = 0
    save(stop)
    digest()
    fake_gh.fail("POST runs/0/", f"no run for {pack['name']}")
    stopped = reply(pack, "publish all")
    assert any("stopped here" in line and f"no run for {pack['name']}" in line for line in stopped)
    for bad, message in (
        ("merge 1", "starts with publish"),
        ("publish soon", "digest numbers"),
        ("publish 99", "no intent #99"),
        ("hold 1", "the number and the reason"),
        ("drop x", "a digest number"),
    ):
        with pytest.raises(CockpitError, match=message):
            reply(pack, bad)
    assert main(["outbox", "digest"]) == 0 and "Reply: cockpit reply" in capsys.readouterr().out
    assert main(["reply", "drop 1"]) == 0 and main(["reply"]) == 2
    client = _client()
    assert client.post("/digest").json()["count"] >= 1
    assert client.post("/reply", json={"text": "merge"}).status_code == 400
    listed = {row["id"]: row for row in client.get("/list").json()["rows"]}
    contract = json.load(open(os.path.join(ROOT, "tests", "contract", "outbox-list-fields.json"), encoding="utf-8"))
    for row in listed.values():
        assert set(contract["row_fields"]) - set(contract["optional"]) <= set(row), sorted(
            set(contract["row_fields"]) - set(row)
        )
    assert listed[review["id"]]["review"]["id"] and listed[rows[2]["id"]]["hold"]["waits"] == "human"
    assert listed[pending["id"]]["skills"]["ok"] in (True, False)


@pytest.mark.parametrize("pack_file", PACKS)
def test_reconcile_records_what_the_forge_already_has_and_ready_prs_are_announced_once(
    env, pack_file, monkeypatch, capsys
):
    from cockpitlib.gate import announce, reconcile, ticket_ready
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.kanban import BoardWrites, place_card
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import qa
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1203"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    branch = f"work/{ticket}"
    sha = fake_gh.commit(repo, branch)
    push = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": branch})
    import subprocess

    subprocess.run(
        ["git", "-C", str(env["root"] / "repos" / repo), "push", "-q", "origin", f"{branch}:{branch}"], check=True
    )
    fake_gh.pull(full, 3, branch, sha)
    opened = create(pack, ticket, "open-pr", "c", "o", {"repo": repo, "branch": branch, "title": "t", "body": "b"})
    posted = create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 3, "sha": sha})
    posted = endorse(posted["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    execute(posted, pack=pack)
    data = fake_gh.state()
    next(iter(data["repos"][full]["pulls"]["3"]["reviews"].values()))["state"] = "COMMENTED"
    fake_gh.save(data)
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    lines = reconcile(pack, ticket)
    assert lines == [
        f"{push['id']}: published-manually",
        f"{opened['id']}: published-manually",
        f"{posted['id']}: published-manually",
    ]
    assert (
        load_intent(opened["id"])["receipt"]["url"].endswith(f"{full}/pull/3")
        and load_intent(opened["id"])["payload"]["number"] == 3
    )
    assert (
        reconcile(pack, ticket) == []
        and main(["outbox", "reconcile", ticket]) == 0
        and "nothing to reconcile" in capsys.readouterr().out
    )
    gone = create(pack, f"{ticket}9", "push-branch", "c", "p", {"repo": repo, "branch": "work/gone"})
    gone["payload"]["repo"] = "nowhere"
    save(gone)
    assert reconcile(pack, f"{ticket}9") == [f"{gone['id']}: unknown repo nowhere"]
    # Ready: the PR is out but a card still runs; once it is done the message goes out once.
    reopened = load_intent(opened["id"])
    reopened["status"] = "published"
    save(reopened)
    assert "card " in announce(pack, ticket) and "not ready" in announce(pack, ticket)
    writes = BoardWrites(pack["board"])
    writes.complete(card, result="done")
    writes.flush()
    assert ticket_ready(pack) == "1" and ticket_ready(pack) == "0"
    sent = _notified()
    assert (
        sent.count("|ready_for_review|") == 1
        and f"https://github.com/{full}/pull/3" in sent
        and pack["name"] in sent.split("|")[0]
    )
    assert json.load(open(os.path.join(qa(), ticket, "ready-for-review.json"), encoding="utf-8"))["prs"] == [
        f"https://github.com/{full}/pull/3"
    ]
    assert "no published PR yet" in announce(pack, f"{ticket}7")
    # A patch apply that pushed tells the reviewers once per commit; it waits while the PR has comments newer than the plan.
    fake_gh.thread(full, 3, 6001, "reviewer-x")
    plan = env["workspace"] / "plan.json"
    plan.write_text(json.dumps([{"comment_id": 6001, "thread": "PRRT_6001", "type": "Code"}]), encoding="utf-8")
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder, exist_ok=True)
    state = os.path.join(folder, f"{repo}-3.json")
    open(state, "w", encoding="utf-8").write(
        json.dumps({"role": "author", "state": "open", "new": [{"id": 1}, {"id": 2}]})
    )
    fake_gh.commit(repo, branch, name="fix.txt")
    apply = create(
        pack,
        ticket,
        "pr-patch-apply",
        "c",
        "a",
        {"repo": repo, "number": 3, "branch": branch, "threads_file": str(plan)},
    )
    assert apply["status"] == "held" and "2 new comment(s) since the plan" in apply["hold"]["reason"]
    apply = endorse(apply["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large")
    assert "2 new comment(s)" in pytest.raises(CockpitError, execute, apply, pack=pack).value.args[0]
    open(state, "w", encoding="utf-8").write(json.dumps({"role": "author", "state": "open", "new": []}))
    assert execute(load_intent(apply["id"]), pack=pack)["ok"]
    assert _notified().count("|updated_after_review|") == 1
    with pytest.raises(CockpitError, match="confirm must echo the id"):
        execute(load_intent(apply["id"]), pack=pack, confirm="something else")


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_gate_commands_and_their_edges(env, pack_file, monkeypatch, capsys):
    from cockpitlib import gate, kanban
    from cockpitlib.errors import CockpitError
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import create, endorse
    from cockpitlib.paths import outbox, qa, workspace
    from cockpitlib.publish import execute
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-1204"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    row = create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 31})
    assert main(["outbox", "hold", row["id"]]) == 2 and "hold needs --reason" in capsys.readouterr().err
    assert main(["outbox", "hold", row["id"], "--reason", "x", "--waits", "never"]) == 2
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert (
        main(["outbox", "hold", row["id"], "--reason", "x"]) == 1
        and "the gatekeeper's or the human's" in capsys.readouterr().err
    )
    assert main(["outbox", "sweep"]) == 0 and "sweep requested" in capsys.readouterr().out
    monkeypatch.setenv("COCKPIT_LANE", "gatekeeper")
    assert (
        main(
            [
                "outbox",
                "hold",
                row["id"],
                "--reason",
                f"which run, {pack['name']}?",
                "--ask",
                "old or new?",
                "--option",
                "old",
                "--option",
                "new",
            ]
        )
        == 0
    )
    assert load_intent(row["id"])["hold"]["options"] == ["old", "new"]
    monkeypatch.delenv("COCKPIT_LANE")
    assert main(["outbox", "return", row["id"]]) == 2 and "return needs --instruction" in capsys.readouterr().err
    assert (
        main(["outbox", "return", row["id"], "--instruction", "use run 32", "--no-chain", "--assignee", "analyst"]) == 0
    )
    assert "→ analyst" in capsys.readouterr().out and load_intent(row["id"])["returned"]["lane"] == "analyst"
    assert (
        main(["outbox", "drop", row["id"], "--note", "superseded"]) == 0
        and load_intent(row["id"])["human"]["note"] == "superseded"
    )
    # publish --all: every endorsed intent in digest order, stopping at the first refusal.
    ready = [
        endorse(
            create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": run})["id"],
            "low",
            "",
            "gatekeeper",
            "fixture-a",
            "fixture-large",
        )
        for run in (41, 42)
    ]
    assert main(["publish", "--all"]) == 0 and "published 2 of 2" in capsys.readouterr().out
    refused = endorse(
        create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 43})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    fake_gh.fail("POST runs/43/", "nope")
    assert main(["publish", "--all"]) == 1 and "refused: " in capsys.readouterr().out
    assert main(["publish", "--all", "--id", refused["id"]]) == 2 and main(["publish", "--all", "--all"]) == 2
    assert all(load_intent(item["id"])["status"] == "published" for item in ready)
    # A sweep whose card cannot be made keeps its request.
    gate.request_sweep(ticket)
    create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 44})

    def busy(*_args, **_kwargs):
        raise CockpitError("board busy")

    real = kanban.place_card
    monkeypatch.setattr(kanban, "place_card", busy)
    with pytest.raises(CockpitError, match="board busy"):
        gate.sweep(pack)
    assert os.path.exists(os.path.join(outbox(), "_sweep.requested")) and not os.path.exists(
        os.path.join(outbox(), "_sweep.serving")
    )
    # A return whose tester card cannot be made keeps the rework card; a posted review goes back only by the human, discarded first.
    branch = f"work/{ticket}"
    fake_gh.commit(repo, branch)
    push = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": branch})
    calls = {"n": 0}

    def first_only(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise CockpitError("board busy")
        return real(*args, **kwargs)

    monkeypatch.setattr(kanban, "place_card", first_only)
    returned = gate.return_intent(pack, push["id"], "rebase first")
    assert returned["returned"]["card"] and returned["returned"]["chain"] == []
    monkeypatch.setattr(kanban, "place_card", real)
    fake_gh.pull(full, 2, branch, "b" * 40)
    review = endorse(
        create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 2, "sha": "b" * 40})["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    execute(review, pack=pack)
    with pytest.raises(CockpitError, match="only the human discards it"):
        gate.return_intent(pack, review["id"], "x", actor="gatekeeper")
    back = gate.return_intent(pack, review["id"], f"re-review for {pack['name']}")
    assert back["status"] == "returned" and back["history"][-1]["event"] == "discarded pending review"
    assert fake_gh.state()["repos"][full]["pulls"]["2"]["reviews"] == {}
    # recard: a return with no body file left is skipped; one with a body gets its card and, for a push, its chain.
    lost = create(pack, ticket, "ci-rerun", "c", "x", {"repo": repo, "run_id": 45})
    lost["status"] = "returned"
    lost["returned"] = {"card": "", "body_file": "nowhere.md", "lane": "worker-1"}
    save(lost)
    fake_gh.commit(repo, f"{branch}-z")
    later = create(pack, ticket, "push-branch", "c", "p", {"repo": repo, "branch": f"{branch}-z"})
    body = os.path.join(outbox(), ticket, "later-return.md")
    open(body, "w", encoding="utf-8").write("rework\n")
    later["status"] = "returned"
    later["returned"] = {
        "card": "",
        "body_file": os.path.relpath(body, workspace()),
        "lane": "worker-1",
        "instruction": "rework",
    }
    save(later)
    assert gate.recard(pack) == "1" and len(load_intent(later["id"])["returned"]["chain"]) == 2
    # The digest's publish backfills the sibling links of the PRs it opened.
    fake_gh.head(full, branch, fake_gh.remote(repo, branch) or "c" * 40)
    opened = endorse(
        create(pack, ticket, "open-pr", "c", "o", {"repo": repo, "branch": f"{branch}-z", "title": "t", "body": "b"})[
            "id"
        ],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
    )
    load_intent(opened["payload"]["after"])
    first = load_intent(opened["payload"]["after"])
    first["status"] = "endorsed"
    first["endorsement"] = {"by": "gatekeeper"}
    save(first)
    numbered = {row["id"]: row["number"] for row in gate.digest()}
    published = gate.reply(pack, f"publish {numbered[opened['id']]}")
    assert any(re.search(r"/pull/\d+$", line) for line in published), published
    # The rows the page reads: files by field, and a review whose PR head moved since it was written.
    note = env["workspace"] / "n.md"
    note.write_text("x", encoding="utf-8")
    shot = env["workspace"] / pack["records_dir"] / "qa" / ticket / "s.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"s")
    filed = create(pack, ticket, "tracker-comment", "c", "x", {"body_file": str(note), "attach": [str(shot)]})
    stale = create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 5, "sha": "d" * 40})
    folder = os.path.join(qa(), ticket, "pr")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, f"{repo}-5.json"), "w", encoding="utf-8").write(json.dumps({"head_sha": "e" * 40}))
    rows = {row["id"]: row for row in _client().get("/list").json()["rows"]}
    assert set(rows[filed["id"]]["files"]) == {"body_file", "attach_0"} and rows[filed["id"]]["files"][
        "attach_0"
    ].endswith("s.png")
    assert rows[stale["id"]]["stale_head"] == {"reviewed": "d" * 9, "now": "e" * 9}
    # A review of the commit one of the ticket's own pushes still has to send is not stale: the head has not got there yet.
    from dashboard.cockpit.router import _awaiting_push, _stale_head

    unsent = {"ticket": ticket, "type": "push-branch", "status": "held", "payload": {"repo": repo, "sha": "d" * 40}}
    assert _stale_head(stale, _awaiting_push([unsent, {"type": "push-branch", "status": "held"}])) is None
    assert _stale_head(stale, _awaiting_push([{**unsent, "status": "published"}])) == {
        "reviewed": "d" * 9,
        "now": "e" * 9,
    }
    # The push is out and the watch still shows the head it replaced: not stale. Another head is a move.
    sent = {**unsent, "status": "published", "payload": {**unsent["payload"], "remote_sha": "e" * 40}}
    assert _stale_head(stale, _awaiting_push([sent])) is None
    assert _stale_head(stale, _awaiting_push([{**sent, "payload": {**sent["payload"], "remote_sha": "f" * 40}}])) == {
        "reviewed": "d" * 9,
        "now": "e" * 9,
    }
    from cockpitlib.health import reason as why

    assert why({"ok": False, "output": "forge x: For more on scraping GitHub ... (HTTP 403)"}).startswith(
        "GitHub refused a burst"
    )
    assert why({"ok": False, "output": "forge x: Bad credentials (HTTP 401)"}) == "the forge rejected the token"
    assert _stale_head(stale, _awaiting_push([{**unsent, "ticket": "OTHER-1"}])) == {
        "reviewed": "d" * 9,
        "now": "e" * 9,
    }
    assert gate._since("not a time") == 0.0
    open(kanban.db_path(pack["board"]), "w", encoding="utf-8").write("not a database")
    assert gate._ticket_cards(pack, ticket) == []
    monkeypatch.setattr(gate, "announce", busy)
    from cockpitlib import publish

    pr_work = {"id": push["id"], "type": "push-branch", "ticket": ticket, "payload": {"sha": "a"}}
    publish._announce(pack, pr_work, "u")
    assert pr_work["announced"] == "board busy"


AUTO_TYPES = {
    "acme": ["push-branch", "open-pr", "pr-comment", "tracker-transition", "pr-review-submit"],
    "bravo": ["push-branch", "pr-edit", "tracker-transition", "pr-review-submit"],
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_release_scope_intent_publishes_with_no_click_and_nothing_else_does(
    env, pack_file, monkeypatch, tmp_path, jira
):
    import shutil

    import yaml

    from cockpitlib import plugin_api
    from cockpitlib.errors import PackError
    from cockpitlib.gate import auto_publish
    from cockpitlib.intents import load as load_intent
    from cockpitlib.kanban import card_scope, place_card
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw["outbox"] = {"auto": [{"scope": "release", "types": AUTO_TYPES[name]}]}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(str(copied / "pack.yaml"))
    assert auto_publish(load(pack_file)) == "0"  # the fixtures do not opt in; only this copy does
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    ticket = f"{pack['tracker']['project']}-1301"
    jira.issue(ticket)
    started = plugin_api.start_card("rework", ticket, policy="release", pack=pack)
    assert card_scope(pack["board"], started["card_id"]) == "release"
    branch = f"work/{ticket}"
    sha = fake_gh.commit(repo, branch)
    push = create(
        pack,
        ticket,
        "push-branch",
        started["card_id"],
        "push",
        {"repo": repo, "branch": branch},
        created_by=started["lane"],
    )
    from cockpitlib.skill_log import append

    append(ticket, started["lane"], "jira-tickets")
    move = create(
        pack,
        ticket,
        "tracker-transition",
        started["card_id"],
        "start",
        {"issue": ticket, "to": "In Progress", "assignee": "me"},
        created_by=started["lane"],
    )
    elsewhere = place_card(pack["board"], f"{pack['tracker']['project']}-1302: work", "worker-1", "ready", kind="work")
    fake_gh.commit(repo, f"{branch}-x")
    waits = create(
        pack,
        f"{pack['tracker']['project']}-1302",
        "push-branch",
        elsewhere,
        "push",
        {"repo": repo, "branch": f"{branch}-x"},
    )
    fake_gh.pull(full, 4, branch, sha)
    approve = create(
        pack,
        ticket,
        "pr-review-submit",
        started["card_id"],
        "r",
        {"repo": repo, "number": 4, "sha": sha, "event": "APPROVE"},
    )
    base = create(pack, ticket, "push-branch", started["card_id"], "base", {"repo": repo, "branch": "main"})
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert auto_publish(pack) == "skipped: a lane does not publish"
    monkeypatch.delenv("COCKPIT_LANE")
    assert auto_publish(pack) == "2", [
        load_intent(row["id"]).get("auto") or load_intent(row["id"])["status"] for row in (push, move)
    ]
    assert load_intent(push["id"])["status"] == "published" and fake_gh.remote(repo, branch) == sha
    assert (
        load_intent(push["id"])["endorsement"]["by"] == "auto-publish"
        and load_intent(push["id"])["auto"]["scope"] == "release"
    )
    assert load_intent(move["id"])["status"] == "published" and jira.issues[ticket]["status"] == "In Progress"
    assert jira.issues[ticket]["fields"]["assignee"] == {"accountId": jira.account}
    assert load_intent(waits["id"])["status"] == "pending" and "auto" not in load_intent(waits["id"])
    assert (
        load_intent(approve["id"])["status"] == "pending"
        and "the human's" in load_intent(approve["id"])["auto"]["waits"]
    )
    assert (
        load_intent(base["id"])["status"] == "pending"
        and "is a protected branch" in load_intent(base["id"])["auto"]["waits"]
    )
    # A body holding a secret waits; a check that fails keeps the intent for the gatekeeper and records why.
    secret = f"token-{pack['name']}-1"
    monkeypatch.setattr("cockpitlib.scrub.holds_secret", lambda texts: any(secret in text for text in texts))
    if "pr-comment" in AUTO_TYPES[name]:
        leaked = create(
            pack, ticket, "pr-comment", started["card_id"], "c", {"repo": repo, "number": 4, "body": f"see {secret}"}
        )
    else:
        leaked = create(
            pack, ticket, "pr-edit", started["card_id"], "e", {"repo": repo, "number": 4, "title": f"see {secret}"}
        )
    auto_publish(pack)
    assert (
        load_intent(leaked["id"])["auto"]["waits"] == "it holds a secret"
        and load_intent(leaked["id"])["status"] == "pending"
    )
    fake_gh.commit(repo, f"{branch}-y")
    broken = create(pack, ticket, "push-branch", started["card_id"], "push", {"repo": repo, "branch": f"{branch}-y"})
    hook = env["root"] / "remotes" / f"{repo}.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    assert auto_publish(pack) == "0"
    shown = load_intent(broken["id"])
    assert shown["status"] == "endorsed" and shown["auto"]["ok"] is False and "protected" in shown["auto"]["error"]
    for bad, message in (
        ({"auto": [{"scope": "release", "types": ["ticket-done"]}]}, "intent types that publish"),
        ({"auto": [{"scope": "", "types": []}]}, "lists {scope, types}"),
        ({"always": True}, "outbox takes auto"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, "outbox": bad}, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_sequence_offers_and_publishes_one_stage_at_a_time(env, pack_file, monkeypatch, jira, capsys):
    from cockpitlib.ci_watch import record_path
    from cockpitlib.cli import main
    from cockpitlib.errors import CockpitError
    from cockpitlib.gate import _auto_refusal, digest
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import amend, create, drop, endorse, relink
    from cockpitlib.publish import execute
    from cockpitlib.sequence import waits
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    org, repo = pack["forge"]["org"], pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1201"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[f"{org}/{repo}"])
    fake_gh.pull(f"{org}/{repo}", 5, f"bump/{pack['name']}", "a" * 40, title=f"bump {pack['name']}")

    def ready(kind, payload):
        return endorse(
            create(pack, ticket, kind, "c", kind, payload)["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large"
        )

    with pytest.raises(CockpitError, match=re.escape("a title with {key} needs --issue-from")):
        create(pack, ticket, "pr-edit", "c", "x", {"repo": repo, "number": 5, "title_append": "[{key}]"})
    with pytest.raises(CockpitError, match="--waits-for: no intent"):
        create(
            pack,
            ticket,
            "pr-edit",
            "c",
            "x",
            {"repo": repo, "number": 5, "add_labels": ["x"], "waits_for": f"{ticket}/099-tracker-create"},
        )
    made = ready("tracker-create", {"summary": f"bump {pack['name']}"})
    retarget = ready(
        "pr-edit",
        {"repo": repo, "number": 5, "title_append": "[{key}]", "issue_from": made["id"], "waits_for": made["id"]},
    )
    labels = ready(
        "pr-edit", {"repo": repo, "number": 5, "add_labels": [f"{pack['name']}-deps"], "waits_for": retarget["id"]}
    )
    assert retarget["payload"]["after"] == "" and labels["payload"]["waits_for"] == retarget["id"]
    assert [row["id"] for row in digest()] == [made["id"]]  # only the first stage is offered
    with pytest.raises(
        CockpitError,
        match=re.escape(f"waits for {made['id']} (tracker-create), which is endorsed: publish that stage first"),
    ):
        execute(load_intent(retarget["id"]), pack=pack)
    assert execute(load_intent(made["id"]), pack=pack)["ok"]
    assert [row["id"] for row in digest()] == [retarget["id"]]
    assert waits(load_intent(labels["id"]), pack) == {"id": retarget["id"], "type": "pr-edit", "status": "endorsed"}
    assert execute(load_intent(retarget["id"]), pack=pack)["ok"]
    key = load_intent(made["id"])["receipt_steps"]["key"]["value"]
    assert fake_gh.state()["repos"][f"{org}/{repo}"]["pulls"]["5"]["title"] == f"bump {pack['name']} [{key}]"
    assert execute(load_intent(labels["id"]), pack=pack)["ok"] and not digest()
    # Relink: an open intent joins a sequence after the fact; the endorsement stays and a pairing goes.
    first = ready("pr-edit", {"repo": repo, "number": 5, "add_labels": ["one"]})
    second = ready("pr-edit", {"repo": repo, "number": 5, "add_labels": ["two"]})
    paired = load_intent(second["id"])
    paired["payload"]["after"] = first["id"]
    save(paired)
    moved = relink(second["id"], first["id"])
    assert moved["status"] == "endorsed" and moved["endorsement"] and moved["payload"]["after"] == ""
    assert moved["history"][-1]["event"] == f"relinked: waits for {first['id']} (was paired after {first['id']})"
    again = relink(second["id"], first["id"])
    assert again["history"][-1]["event"].endswith(f"(was waiting for {first['id']})")
    for wid, message in ((second["id"], "would close a loop"), (first["id"], "would close a loop")):
        with pytest.raises(CockpitError, match=message):
            relink(first["id"] if wid == second["id"] else first["id"], wid)
    with pytest.raises(CockpitError, match="would close a loop"):
        amend(first["id"], payload={"waits_for": second["id"]}, pack=pack)
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    with pytest.raises(CockpitError, match="relink is the human's"):
        relink(second["id"], first["id"])
    monkeypatch.setenv("COCKPIT_LANE", "gatekeeper")
    assert relink(second["id"], first["id"])["history"][-1]["by"] == "gatekeeper"
    monkeypatch.delenv("COCKPIT_LANE")
    with pytest.raises(CockpitError, match="only an open intent waits"):
        relink(labels["id"], first["id"])
    assert "it holds" not in _auto_refusal(pack, load_intent(second["id"])) and "waits for" in _auto_refusal(
        pack, load_intent(second["id"])
    )
    # A dropped stage before breaks the sequence: the human decides; a dropped intent is never named.
    drop(first["id"])
    assert waits(load_intent(second["id"]))["status"] == "dropped"
    with pytest.raises(CockpitError, match="is dropped; name the stage"):
        create(
            pack,
            ticket,
            "pr-edit",
            "c",
            "x",
            {"repo": repo, "number": 5, "add_labels": ["x"], "waits_for": first["id"]},
        )
    gone = load_intent(second["id"])
    gone["payload"]["waits_for"] = f"{ticket}/098-pr-edit"
    assert waits(gone)["status"] == "missing"
    # An approval in a sequence also waits for green CI at its commit.
    sha = "c" * 40
    approve = {
        "id": f"{ticket}/097-pr-review-submit",
        "type": "pr-review-submit",
        "status": "endorsed",
        "ticket": ticket,
        "payload": {"repo": repo, "number": 5, "sha": sha, "event": "APPROVE", "waits_for": made["id"]},
    }
    assert waits(approve, pack) == {"id": "CI", "type": "ci", "status": "not seen yet"}
    path = record_path(ticket, repo, sha)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for state, expected in (
        ("running", {"id": "CI", "type": "ci", "status": "running"}),
        ("success", None),
        ("none", None),
    ):
        json.dump({"state": state, "sha": sha, "repo": repo}, open(path, "w", encoding="utf-8"))
        assert waits(approve, pack) == expected
    json.dump({"state": "failed", "sha": sha, "repo": repo}, open(path, "w", encoding="utf-8"))
    assert (
        waits({**approve, "payload": {**approve["payload"], "waits_for": ""}}, pack) is None
    )  # not a stage: the live check at publish decides
    assert waits({**approve, "status": "published"}, pack) is None
    from cockpitlib.sequence import said

    assert "CI at its commit is failed" in said(approve, waits(approve, pack))
    # The command line and the page.
    third = ready("pr-edit", {"repo": repo, "number": 5, "add_labels": ["three"]})
    orphan = ready("pr-edit", {"repo": repo, "number": 5, "add_labels": ["orphan"]})
    stray = load_intent(orphan["id"])
    stray["payload"]["waits_for"] = f"{ticket}/097-pr-edit"  # its own stage before was never written
    save(stray)
    assert relink(third["id"], orphan["id"])["payload"]["waits_for"] == orphan["id"]
    assert main(["outbox", "relink", third["id"], "--waits-for", made["id"]]) == 0
    assert "that stage is out, so it is offered now" in capsys.readouterr().out
    assert main(["outbox", "relink", third["id"], "--waits-for", second["id"]]) == 0
    assert "offered once it is out (endorsed now)" in capsys.readouterr().out
    assert main(["outbox", "relink", third["id"]]) == 2
    listed = {row["id"]: row for row in _client().get("/list").json()["rows"]}
    assert listed[third["id"]]["waits"] == {"id": second["id"], "type": "pr-edit", "status": "endorsed"}
    assert listed[made["id"]]["waits"] is None
    assert _other(pack)["name"] not in json.dumps(listed[third["id"]])


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_bump_batch_keeps_the_packs_stage_order_and_its_barrier(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import CockpitError, PackError
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import next_seq, save
    from cockpitlib.kickoff import batch_key
    from cockpitlib.outbox import create, relink
    from cockpitlib.sequence import is_batch, said, waits

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    sequence = pack["bump_sequence"]
    assert sequence != _other(pack)["bump_sequence"]
    ticket, repo = batch_key(pack), pack["repos"]["repos"][0]["name"]
    assert (
        is_batch(pack, ticket)
        and not is_batch(pack, f"{pack['tracker']['project']}-1301")
        and not is_batch(_other(pack), ticket)
    )
    values = {"base": "main", "title_append": "[deps]", "add_labels": ["deps"], "assignee": "me", "labels": ["deps"]}

    def payload_for(stage, number):
        pr = {"repo": repo, "number": number}
        return {
            "tracker-create": {"summary": f"bump {number}"},
            "tracker-transition": {"to": "In Review", "issue": ticket},
            "push-branch": {"repo": repo, "branch": f"bump/{number}", "sha": "a" * 40},
            "pr-review-submit": {**pr, "sha": "a" * 40, "event": stage["event"] or "COMMENT"},
            "pr-edit": {**pr, stage["fields"][0]: values[stage["fields"][0]]} if stage["fields"] else pr,
        }[stage["intent"]]

    def put(stage, number, waits_for="", status="pending", **over):
        iid = f"{ticket}/{next_seq(ticket)}-{stage['intent']}"
        save(
            {
                "id": iid,
                "type": stage["intent"],
                "ticket": ticket,
                "status": status,
                "payload": {**payload_for(stage, number), "waits_for": waits_for, **over},
            }
        )
        return iid

    names = [stage["name"] for stage in sequence["stages"]]
    limit = names.index(sequence["barrier"])
    filed = {}
    for number in (7, 8):
        previous = ""
        for stage in sequence["stages"]:
            previous = filed[(number, stage["name"])] = put(stage, number, previous)
    after = sequence["stages"][limit + 1]
    late = load_intent(filed[(7, after["name"])])
    for stage in sequence["stages"][: limit + 1]:  # PR 7 is through the barrier; PR 8 is not
        done = load_intent(filed[(7, stage["name"])])
        done["status"] = "published"
        save(done)
    wait = waits(late, pack)
    assert wait["type"] == "batch" and f"of the {repo} batch up to {sequence['barrier']} not out yet" in wait["status"]
    assert "is past the batch barrier" in said(late, wait)
    pre = [
        filed[(8, stage["name"])]
        for stage in sequence["stages"][: limit + 1]
        if (load_intent(filed[(8, stage["name"])])["payload"]).get("repo") == repo
    ]
    for index, iid in enumerate(pre):  # one published, the rest dropped: the batch is through
        row = load_intent(iid)
        row["status"] = "published" if index == 0 else "dropped"
        save(row)
    assert (waits(load_intent(filed[(7, after["name"])]), pack) or {}).get(
        "type"
    ) != "batch"  # an approval still waits for CI
    assert waits(load_intent(filed[(7, names[0])]), pack) is None  # a stage up to the barrier never waits for the batch
    for row in pre:  # PR 8 not through again: a ticket that is no batch has no barrier
        back = load_intent(row)
        back["status"] = "pending"
        save(back)
    assert (
        waits(late, pack)["type"] == "batch"
        and (waits({**late, "ticket": f"{pack['tracker']['project']}-1302"}, pack) or {}).get("type") != "batch"
    )
    assert (waits(load_intent(filed[(8, names[0])]), pack) or {}).get(
        "type"
    ) != "batch"  # an open stage up to the barrier
    # Writing a stage: it names the stage before it, on the same PR, and does one stage only.
    edits = [stage for stage in sequence["stages"] if stage["intent"] == "pr-edit" and stage["after"]]
    stage = edits[0]
    with pytest.raises(CockpitError, match=f"the {stage['name']} stage needs --waits-for"):
        create(pack, ticket, "pr-edit", "c", "x", payload_for(stage, 9))
    wrong = next(
        found for found in sequence["stages"] if found["name"] not in stage["after"] and found["name"] != stage["name"]
    )
    with pytest.raises(
        CockpitError, match=f"the {stage['name']} stage waits for a {' or '.join(stage['after'])} stage"
    ):
        create(pack, ticket, "pr-edit", "c", "x", {**payload_for(stage, 9), "waits_for": put(wrong, 9)})
    before = next(found for found in sequence["stages"] if found["name"] == stage["after"][0])
    with pytest.raises(CockpitError, match="is another PR's stage"):
        create(
            pack,
            ticket,
            "pr-edit",
            "c",
            "x",
            {**payload_for(stage, 9), "waits_for": put(before, 10, repo=f"{repo}-other")},
        )
    made = create(pack, ticket, "pr-edit", "c", "x", {**payload_for(stage, 9), "waits_for": put(before, 9)})
    assert made["payload"]["waits_for"]
    both = {**payload_for(edits[0], 9), **payload_for(edits[1], 9)} if len(edits) > 1 else None
    if both is None:
        both = {
            **payload_for(stage, 9),
            **{
                field: values[field]
                for found in sequence["stages"]
                if found["intent"] == "pr-edit"
                for field in found["fields"][:1]
            },
        }
    with pytest.raises(CockpitError, match="are separate stages"):
        create(pack, ticket, "pr-edit", "c", "x", {**both, "waits_for": put(before, 9)})
    assert create(pack, f"{pack['tracker']['project']}-1303", "pr-edit", "c", "x", payload_for(stage, 9))["status"] in (
        "pending",
        "held",
    )
    with pytest.raises(CockpitError, match="waits for a"):
        relink(made["id"], put(wrong, 9), pack=pack)
    from cockpitlib.acts import kickoff_text

    told = kickoff_text(pack, ticket, "bumps", "")
    assert (
        " → ".join(names[: limit + 1]) + " → [the repo's whole batch] → " in told
        and kickoff_text(pack, ticket, "intake", "").count("→") == 0
    )
    # The pack's grammar.
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    one = {"name": "a", "intent": "push-branch"}
    for value, message in (
        ([], "bump_sequence takes stages"),
        ({"stages": []}, "bump_sequence takes stages"),
        ({"stages": [{"name": "a", "intent": "deploy"}]}, "with an intent type"),
        ({"stages": [{**one, "field": "nope"}]}, "field names payload fields"),
        ({"stages": [{**one, "event": "MERGE"}]}, "event is one of"),
        ({"stages": [one, {"name": "b", "intent": "pr-edit", "after": "z"}]}, "after names earlier stages"),
        ({"stages": [one, one]}, "is named twice"),
        ({"stages": [one], "barrier": "z"}, "barrier z is not a stage"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, "bump_sequence": value}, sort_keys=False), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_hold_on_another_authors_commits_is_confirmed_by_the_human_then_published_by_them(
    env, pack_file, monkeypatch
):
    """The gatekeeper holds a push with commits by another author and asks nothing. The human confirms it from the
    Inbox (endorsed as theirs); auto-publish leaves it to their own Publish. A pack that lists the human's other
    addresses does not hold their own commits at all."""
    from cockpitlib.errors import CockpitError
    from cockpitlib.gate import auto_publish
    from cockpitlib.outbox import OWNER, confirm, create
    from cockpitlib.outbox import load as load_intent
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    name = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1110"
    shared = f"work/{ticket}"
    fake_gh.commit(name, shared, name="mine.txt")
    fake_gh.commit(name, shared, name="theirs.txt", email=f"me-at-work@{pack['name']}.test")
    held = create(pack, ticket, "push-branch", "c", "push", {"repo": name, "branch": shared})
    assert held["status"] == "held" and not held["hold"].get("ask")
    with pytest.raises(CockpitError, match="only a hold that waits for you"):
        confirm(
            create(
                pack,
                f"{pack['tracker']['project']}-1111",
                "push-branch",
                "c",
                "push",
                {"repo": name, "branch": f"work/{pack['tracker']['project']}-1111"},
            )["id"],
            pack=pack,
        )
    done = _client().post("/confirm", json={"id": held["id"]}).json()
    assert done == {"ok": True, "id": held["id"], "status": "endorsed"}
    assert load_intent(held["id"])["endorsement"]["by"] == OWNER
    scoped = {
        **pack,
        "outbox": {**(pack.get("outbox") or {}), "auto": [{"scope": "standalone", "types": ["push-branch"]}]},
    }
    monkeypatch.setattr("cockpitlib.kanban.card_scope", lambda *_a, **_k: "standalone")
    auto_publish(scoped)
    assert load_intent(held["id"])["status"] == "endorsed", "confirmed by the human: their Publish, not auto-publish's"
    assert _client().post("/confirm", json={"id": held["id"]}).status_code == 400, "only a held intent is confirmed"
    # the human's other address is theirs: nothing to confirm
    mine = {**pack, "forge": {**(pack.get("forge") or {}), "human_emails": [f"me-at-work@{pack['name']}.test"]}}
    other = f"{pack['tracker']['project']}-1112"
    fake_gh.commit(name, f"work/{other}", name="a.txt")
    fake_gh.commit(name, f"work/{other}", name="b.txt", email=f"me-at-work@{pack['name']}.test")
    clean = create(mine, other, "push-branch", "c", "push", {"repo": name, "branch": f"work/{other}"})
    assert clean["payload"]["foreign"] == [] and clean["status"] == "pending"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_lane_never_asks_to_push_a_protected_branch_and_a_rerun_the_forge_calls_gone_is_dropped(
    env, pack_file, monkeypatch, tmp_path, jira
):
    """An analyst card asked to push a coordination repo's master (over a thousand local record commits) and it waited in
    the Inbox as a held push; a CI rerun of a run GitHub would no longer retry stayed endorsed, failing every pass."""
    import shutil

    import yaml

    from cockpitlib import plugin_api
    from cockpitlib.errors import CockpitError
    from cockpitlib.gate import auto_publish
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw["outbox"] = {"auto": [{"scope": "release", "types": AUTO_TYPES[name] + ["ci-rerun"]}]}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(str(copied / "pack.yaml"))
    repo = pack["repos"]["repos"][0]["name"]
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[f"{pack['forge']['org']}/{repo}"])
    ticket = f"{pack['tracker']['project']}-1351"
    jira.issue(ticket)
    started = plugin_api.start_card("rework", ticket, policy="release", pack=pack)
    base = sorted(__import__("cockpitlib.git_push", fromlist=["protected"]).protected(pack, repo))[0]
    with pytest.raises(CockpitError, match="a lane pushes a feature branch"):
        create(
            pack,
            ticket,
            "push-branch",
            started["card_id"],
            "push",
            {"repo": repo, "branch": base},
            created_by=started["lane"],
        )
    from cockpitlib.refusals import _load as refusals

    assert any("protected branch" in row["reason"] for row in refusals()), "the refusal is on record for the Inbox"
    rerun = create(
        pack,
        ticket,
        "ci-rerun",
        started["card_id"],
        "rerun",
        {"repo": repo, "run_id": 39090822803},
        created_by=started["lane"],
    )
    monkeypatch.setattr(
        "cockpitlib.publish.execute",
        lambda intent, pack=None: {"ok": False, "error": "gh: This workflow run cannot be retried (HTTP 403)"},
    )
    auto_publish(pack)
    gone = load_intent(rerun["id"])
    assert gone["status"] == "dropped" and "what it acts on is gone" in gone["dropped"]["reason"]
    again = create(
        pack, ticket, "ci-rerun", started["card_id"], "rerun", {"repo": repo, "run_id": 1}, created_by=started["lane"]
    )
    monkeypatch.setattr("cockpitlib.publish.execute", lambda intent, pack=None: {"ok": False, "error": "HTTP 502"})
    auto_publish(pack)
    assert load_intent(again["id"])["status"] == "endorsed", "a passing forge error keeps it for the next pass"
