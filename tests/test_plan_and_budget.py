# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intake's plan and what holds a kickoff: the go, the advisor, the plan gate, the budget and the plan window."""

import json
import os
import re

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, _client, _other, _parents


@pytest.mark.parametrize("pack_file", PACKS)
def test_intake_finish_writes_the_proposal_and_blocks_for_go(env, pack_file, monkeypatch):
    from cockpitlib.intents import all_intents
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.paths import qa
    from cockpitlib.slots import read_owner, read_ticket
    from cockpitlib.worktree import dest

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = "TASK-990"
    product = os.path.join(dest(ticket, "api"), "README")
    os.makedirs(os.path.dirname(product), exist_ok=True)
    open(product, "w", encoding="utf-8").write("product\n")
    client = _client()
    opened = client.post("/kickoff", json={"ticket": ticket, "mode": "intake"})
    assert opened.status_code == 200
    card = opened.json()["card_id"]
    assert read_ticket(1) == ticket and read_owner(1) == "intake"
    empty = client.post("/intake-finish", json={"id": card, "proposal": "  "})
    assert empty.status_code == 409 and "empty" in empty.text
    worker = place_card(pack["board"], f"{ticket}: worker", "worker-1", "ready")
    refused = client.post("/intake-finish", json={"id": worker, "proposal": "ship it"})
    assert refused.status_code == 409 and "not an intake" in refused.text
    nameless = place_card(pack["board"], "intake notes", "intake", "ready")
    assert client.post("/intake-finish", json={"id": nameless, "proposal": "a plan"}).status_code == 409
    done = client.post("/intake-finish", json={"id": card, "proposal": "change the report"})
    assert done.status_code == 200
    body = done.json()
    assert body["blocked"] is True and body["published"] == ""
    assert open(os.path.join(qa(), ticket, "proposal.md"), encoding="utf-8").read() == "change the report\n"
    assert any(item["id"] == card and item["status"] == "blocked" for item in board_cards(pack["board"]))
    assert all_intents(ticket) == []
    assert open(product, encoding="utf-8").read() == "product\n"
    assert client.post("/intake-finish", json={"id": "missing", "proposal": "a plan"}).status_code == 409
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.acts import archive_card
    from cockpitlib.plan import require_decision, show
    from cockpitlib.slots import write_owner, write_ticket

    archive_card(pack, worker)
    write_owner(1, "free")
    write_ticket(1, "")
    with pytest.raises(CockpitError, match="no decision"):
        require_decision(ticket)
    blocked = client.post("/kickoff", json={"ticket": ticket, "mode": "rework"})
    assert blocked.status_code == 409 and "waiting for go" in blocked.text
    assert client.post("/answer", json={"id": card, "text": "go"}).status_code == 200
    plan = show(ticket)
    assert "change the report" in plan and "## Decision" in plan and "\ngo (" in plan
    assert other["name"] not in plan
    require_decision(ticket)
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = 'blocked' where id = ?", (card,))
    connection.commit()
    connection.close()
    assert client.post("/answer", json={"id": card, "text": "go"}).status_code == 200
    assert "change the report" in show(ticket)
    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = 'blocked' where id = ?", (card,))
    connection.commit()
    connection.close()
    proposal = os.path.join(qa(), ticket, "proposal.md")
    changed = client.post(
        "/answer", json={"id": card, "text": f"go with changes: add {pack['name']} path: {proposal} read change"}
    )
    assert changed.status_code == 200
    kept = show(ticket)
    assert "change the report" in kept and f"add {pack['name']}" in kept and other["name"] not in kept


@pytest.mark.parametrize("pack_file", PACKS)
def test_over_budget_refuses_kickoff_and_names_the_window_or_the_spend(env, pack_file, monkeypatch):
    import sqlite3
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    assert pack["budget"] != other["budget"]
    from cockpitlib.paths import hermes_home, watch_dir
    from cockpitlib.settings import budget_state
    from cockpitlib.usage import WINDOWS_FRESH, plan_windows, providers_in_use

    used = sorted(providers_in_use(pack))
    assert used
    ceiling = pack["budget"]["plan_window_max_pct"]
    client = _client()
    fresh = budget_state(pack, now=1_000)
    assert fresh["over"] is False and fresh["error"] == "" and fresh["window"] is None
    assert fresh["unmetered"] == used  # no reader for a provider is a fact, not a failed read
    usage = os.path.join(os.environ["COCKPIT_ROOT"], "fake-usage.json")
    soon = "2099-01-01T00:00:00+00:00"
    json.dump(
        {
            used[0]: {
                "windows": [
                    {"label": f"session {pack['name']}", "used_percent": ceiling + 1, "resets_at": soon},
                    {"label": "one model", "used_percent": 100, "scope": "model"},
                ]
            },
            "not-a-lane-provider": {"windows": [{"label": "elsewhere", "used_percent": 100}]},
        },
        open(usage, "w", encoding="utf-8"),
    )
    assert budget_state(pack, now=1_000 + WINDOWS_FRESH - 1)["over"] is False  # still the kept read
    state = budget_state(pack, now=1_000 + WINDOWS_FRESH)
    assert state["over"] is True and state["why"] == f"window session {pack['name']} is {ceiling + 1}%"
    assert state["window"]["name"] == f"session {pack['name']}" and state["window"]["resets_in"].endswith("d")
    assert {window["name"] for window in state["windows"]} == {f"session {pack['name']}", "one model"}
    os.remove(os.path.join(watch_dir(), "plan-windows.json"))
    refused = client.post(
        "/kickoff", json={"mode": "intake", "ticket": f"{pack['tracker']['project']}-41", "prompt": "go"}
    )
    assert refused.status_code == 409 and f"session {pack['name']}" in refused.json()["detail"]
    caps = client.get("/capacity").json()
    assert caps["dev"] == 0 and caps["review"] == 0 and f"session {pack['name']}" in caps["why"]
    shown = client.get("/settings").json()["budget"]
    assert shown["over"] is True and shown["window"]["used"] == ceiling + 1 and shown["families"] == used
    assert client.get("/usage").json()["windows"][0]["provider"] == used[0]
    json.dump(
        {used[0]: {"windows": [{"label": "session", "used_percent": ceiling - 1}]}}, open(usage, "w", encoding="utf-8")
    )
    os.remove(os.path.join(watch_dir(), "plan-windows.json"))
    assert budget_state(pack)["over"] is False
    database = os.path.join(hermes_home(), "profiles", "worker-1", "state.db")
    os.makedirs(os.path.dirname(database), exist_ok=True)
    connection = sqlite3.connect(database)
    connection.execute(
        "create table sessions (title text, model text, started_at real, estimated_cost_usd real, actual_cost_usd real)"
    )
    connection.execute("insert into sessions values ('old', 'm', 1000, null, 999)")
    connection.execute("insert into sessions values ('now', 'm', ?, 41.5, null)", (time.time(),))
    connection.commit()
    connection.close()
    spent = budget_state(pack)
    assert spent["month_usd"] == 41.5
    assert (
        spent["over"] is bool(pack["budget"]["monthly_usd"])
        and (spent["why"] == f"spent 41.50 of {pack['budget']['monthly_usd']:.2f}") is spent["over"]
    )
    json.dump({used[0]: {"raise": "reader exploded"}}, open(usage, "w", encoding="utf-8"))
    assert "reader exploded" in plan_windows(pack, now=10**9)["error"]
    monkeypatch.setattr(
        "cockpitlib.hermes_runtime.run_helper", lambda name, request: (_ for _ in ()).throw(CockpitError("no hermes"))
    )
    assert plan_windows(pack, now=2 * 10**9)["error"] == "no hermes"
    from cockpitlib.usage import _resets_in

    assert _resets_in("bad", 0) == "" and _resets_in("1970-01-01T00:00:00+00:00", 10) == "now"
    assert _resets_in("1970-01-01T00:30:00+00:00", 0) == "30m" and _resets_in("1970-01-01T05:00:00+00:00", 0) == "5h"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plan_window_gates_only_the_seats_that_bill_on_the_plan_not_seats_on_an_api_key(env, pack_file, monkeypatch):
    # The usage reader measures a provider's subscription (the root home's OAuth login). A seat whose own credential is
    # an API key is billed by the dollar: that window says nothing about it, so the spend cap is its only budget.
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert pack["budget"] != _other(pack)["budget"]
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.paths import watch_dir
    from cockpitlib.settings import budget_state
    from cockpitlib.settings import load as load_settings

    ceiling = pack["budget"]["plan_window_max_pct"]
    judged = pack["providers"][pack["roles"]["reviewer"]]["hermes_provider"]
    worked = pack["providers"][pack["roles"]["worker"]]["hermes_provider"]
    assert judged != worked
    json.dump(
        {
            judged: {"windows": [{"label": f"session {pack['name']}", "used_percent": 100}]},
            worked: {"windows": [{"label": f"week {pack['name']}", "used_percent": ceiling}]},
        },
        open(os.path.join(os.environ["COCKPIT_ROOT"], "fake-usage.json"), "w", encoding="utf-8"),
    )
    shaped = dict(pack)
    shaped["seats"] = load_settings(pack)["seats"]
    lanes = {
        provider: [
            lane
            for kind, names in seats_from(shaped).items()
            if kind in pack["roles"] and pack["providers"][pack["roles"][kind]]["hermes_provider"] == provider
            for lane in names
        ]
        for provider in (judged, worked)
    }
    assert lanes[judged] and lanes[worked]

    def env_key(provider):
        return provider.upper().replace("-", "_") + "_API_KEY"

    def seat(lane, env="", pool=None):
        folder = profile_dir(lane)
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, ".env"), "w", encoding="utf-8").write(f"COCKPIT_LANE={lane}\n{env}")
        if pool is not None:
            json.dump(
                {"version": 1, "credential_pool": pool}, open(os.path.join(folder, "auth.json"), "w", encoding="utf-8")
            )

    def state():
        cached = os.path.join(watch_dir(), "plan-windows.json")
        if os.path.exists(cached):
            os.remove(cached)
        return budget_state(pack)

    # No seat names its credential (as in the fixtures and cockpit-only packs): every window counts, exactly as before.
    before = state()
    assert before["over"] is True
    assert before["why"] == f"window session {pack['name']} is 100%; window week {pack['name']} is {ceiling}%"
    assert before["metered_by_key"] == []
    # Every seat of the worker's provider carries that provider's API key (in its .env, or as the only credentials in
    # its pool): that provider's plan window no longer stops a card. The other provider's still does.
    for index, lane in enumerate(lanes[worked]):
        if index % 2:
            seat(lane, pool={worked: [{"auth_type": "api_key", "source": "manual", "access_token": "sk-live-1"}]})
        else:
            seat(lane, env=f'export {env_key(worked)}="sk-live-{pack["name"]}"\n')
    keyed = state()
    assert keyed["over"] is True and keyed["why"] == f"window session {pack['name']} is 100%"
    assert keyed["window"]["name"] == f"session {pack['name']}"
    assert keyed["metered_by_key"] == [worked] and worked in keyed["ignored"]
    assert {window["name"] for window in keyed["windows"]} == {
        f"session {pack['name']}",
        f"week {pack['name']}",
    }  # still shown
    # One seat still on the plan keeps the window: an OAuth token under the key's name, a pool that also holds the
    # OAuth login, another provider's key, a login token beside the key, or no credential at all (it falls back to the account's login).
    plan_seats = (
        dict(env=f"{env_key(judged)}=sk-ant-oat01-{pack['name']}\n"),
        dict(
            pool={
                judged: [
                    {"auth_type": "api_key", "access_token": "sk-live-2"},
                    {"auth_type": "oauth", "source": "claude_code"},
                ]
            }
        ),
        dict(env="ANTHROPIC_API_KEY=sk-ant-api03-elsewhere\n"),
        dict(
            env=f"{env_key(judged)}=sk-live-{pack['name']}\n{judged.upper().replace('-', '_')}_TOKEN=sk-ant-oat01-login\n"
        ),
        dict(),
    )
    for shape in plan_seats:
        for lane in lanes[judged]:
            seat(lane, env=f"{env_key(judged)}=sk-live-{pack['name']}\n")
        seat(lanes[judged][0], **shape)
        if os.path.exists(os.path.join(profile_dir(lanes[judged][0]), "auth.json")) and "pool" not in shape:
            os.remove(os.path.join(profile_dir(lanes[judged][0]), "auth.json"))
        assert state()["why"] == f"window session {pack['name']} is 100%", shape
    # Every seat on an API key: no plan window gates a card; the dollar cap still does.
    seat(lanes[judged][0], env=f"{env_key(judged)}=sk-live-{pack['name']}\n")
    free = state()
    assert free["over"] is False and free["why"] == "" and free["window"] is None
    assert free["metered_by_key"] == sorted({judged, worked}) and free["families"] == sorted({judged, worked})
    client = _client()
    caps = client.get("/capacity").json()
    assert caps["dev"] > 0 and caps["review"] > 0 and "window" not in (caps.get("why") or "")


@pytest.mark.parametrize("pack_file", PACKS)
def test_go_with_changes_keeps_every_section_and_append_stamps_one_heading(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.plan import CHANGES, append, decided, init, plan_path, sections, show

    ticket = f"{pack['tracker']['project']}-77"
    with pytest.raises(CockpitError, match=f"no plan for {ticket}"):
        append(ticket, "Delivered", "x")
    init(ticket, f"# Plan {pack['name']}\n\nscope {pack['name']}\n\n## Steps\n\n1. build", "go")
    assert decided(ticket) and sections(ticket) == ["Steps", "Decision"]
    append(ticket, "Delivered", f"shipped {pack['name']}")
    append(ticket, "Tested", "row 1 passed")
    append(ticket, "Delivered", "second part")
    text = show(ticket)
    assert text.count("## Delivered") == 1 and "second part" in text and re.search(r"_\d{4}-\d\d-\d\dT", text)
    assert init(ticket, "ignored", "go") == plan_path(ticket) and show(ticket) == text  # a later plain go keeps it
    init(ticket, "ignored", f"go with changes: also cover {pack['name']} exports")
    changed = show(ticket)
    assert sections(changed and ticket) == ["Steps", "Decision", "Delivered", "Tested", CHANGES]
    assert f"shipped {pack['name']}" in changed and "row 1 passed" in changed and f"scope {pack['name']}" in changed
    assert f"also cover {pack['name']} exports" in changed and "ignored" not in changed and other["name"] not in changed
    assert changed.count("## Decision") == 1 and f"go with changes: also cover {pack['name']} exports (" in changed
    init(ticket, "", "go with changes: one more")
    assert show(ticket).count(f"## {CHANGES}") == 1 and "one more" in show(ticket) and "also cover" in show(ticket)
    open(plan_path(ticket), "w", encoding="utf-8").write("## Tested\n\na\n\n## Notes\n\nn\n\n## Tested\n\nb\n")
    assert sections(ticket) == ["Tested", "Notes"]
    append(ticket, "Notes", "c")
    assert show(ticket).count("## Tested") == 1 and "a\n\nb" in show(ticket)
    fresh = f"{pack['tracker']['project']}-78"
    init(fresh, "", "go")
    assert show(fresh).startswith(f"# Plan {fresh}") and sections(fresh) == ["Decision"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_advisor_answers_in_the_packs_grammar_is_limited_and_blocks_on_failure(
    env, pack_file, monkeypatch, tmp_path
):
    import shutil
    import sqlite3

    import yaml

    from cockpitlib.errors import PackError

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.acts import answer_card
    from cockpitlib.advise import advise, calls, parse, report_refusal
    from cockpitlib.egress import check_tool
    from cockpitlib.kanban import board_cards, db_path, place_card
    from cockpitlib.lanes import advisor_seat, seats_from
    from cockpitlib.plan import init, show

    cfg = pack["advisor"]
    assert set(cfg["checkpoints"]["C0"]["answers"]) != set(other["advisor"]["checkpoints"]["C0"]["answers"])
    assert "advisor" not in seats_from(pack)  # a command or an in-tool advisor needs no seat
    ticket = f"{pack['tracker']['project']}-81"
    init(ticket, f"plan {pack['name']}", "go")
    card = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready")
    with pytest.raises(CockpitError, match="no checkpoint C9"):
        advise(pack, "C9", ticket=ticket)
    with pytest.raises(CockpitError, match="needs the ticket"):
        advise(pack, "C0")
    if cfg.get("in_tool"):
        with pytest.raises(CockpitError, match="inside the coding tool"):
            advise(pack, "C0", ticket=ticket)
        good = "\n".join(
            [
                "delivered",
                f"north-advice: C0 {cfg['checkpoints']['C0']['answers'][0]} / C2 {cfg['checkpoints']['C2']['answers'][0]}",
            ]
        )
        assert report_refusal(pack, good) == "" and "lacks the advisor line" in report_refusal(pack, "delivered")
        monkeypatch.setenv("COCKPIT_LANE", "worker-1")
        assert "lacks the advisor line" in check_tool("kanban_complete", {"summary": "done", "result": ""})
        assert check_tool("kanban_complete", {"summary": good}) == ""
        monkeypatch.setenv("COCKPIT_LANE", "reviewer")
        assert check_tool("kanban_complete", {"summary": "done"}) == ""
        monkeypatch.delenv("COCKPIT_LANE")
        blocked = place_card(pack["board"], f"{ticket}: work two", "worker-1", "blocked")
        init(ticket, "plan", "go")
        assert answer_card(pack, blocked, "complete: shipped")[
            "ok"
        ]  # the human completing a card is not the worker's report
        assert main(["advise", "C0", "--ticket", ticket]) == 1
    else:
        assert report_refusal(pack, "anything") == ""
        monkeypatch.setenv("COCKPIT_LANE", "worker-1")
        assert check_tool("kanban_complete", {"summary": "done"}) == ""
        monkeypatch.delenv("COCKPIT_LANE")
        approved = advise(pack, "C0", f"note {pack['name']}", ticket=ticket, card=card)
        assert approved["ok"] and approved["verdict"] == "APPROVED"
        logged = open(os.path.join(os.environ["COCKPIT_ROOT"], "advise.log"), encoding="utf-8").read()
        assert "You advise the acme lanes" in logged and "APPROVED, DEVIATES" in logged
        monkeypatch.setenv("ACME_ADVICE", "DEVIATES")
        assert advise(pack, "C0", ticket=ticket)["verdict"] == "DEVIATES"
        assert "## Advisor" in show(ticket) and "C0: DEVIATES" in show(ticket)
        monkeypatch.setenv("ACME_ADVICE", "MAYBE")
        unparsed = advise(pack, "C2", ticket=ticket, card=card)
        assert unparsed["ok"] is False and "names none of APPROVED, CHANGES" in unparsed["reason"]
        assert {item["id"]: item["status"] for item in board_cards(pack["board"])}[card] == "blocked"
        connection = sqlite3.connect(db_path(pack["board"]))
        said = [
            row[0]
            for row in connection.execute(
                "select body from task_comments where task_id = ? and author = 'advisor'", (card,)
            )
        ]
        connection.close()
        assert said[0].startswith("C0: APPROVED") and len(said) == 2
        assert len(calls(ticket)) == 3
        with pytest.raises(CockpitError, match="advisor limit: 3 calls"):
            advise(pack, "C0", ticket=ticket)
        assert main(["advise", "C0", "--ticket", ticket]) == 1
        ticket2 = f"{pack['tracker']['project']}-82"
        monkeypatch.setenv("ACME_ADVICE", "fail")
        failed = advise(pack, "C0", ticket=ticket2)
        assert failed["ok"] is False and "acme advisor offline" in failed["reason"]
        monkeypatch.setenv("ACME_ADVICE", "APPROVED")
        monkeypatch.setenv("HERMES_KANBAN_TASK", card)
        assert main(["advise", "C2", "fine", "--ticket", ticket2]) == 0
        monkeypatch.delenv("HERMES_KANBAN_TASK")
    assert main(["advise"]) == 2 and main(["advise", "C0", "--nope"]) == 2
    assert parse(["OK", "FIX"], "## OK, fine") == "OK" and parse(["OK"], "OKAY") == "" and parse(["OK"], "") == ""
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    seated = {"checkpoints": {"C0": {"answers": ["YES", "NO"]}}, "max_calls": 2}
    (copied / "pack.yaml").write_text(yaml.safe_dump({**raw, "advisor": seated}, sort_keys=False), encoding="utf-8")
    seat_pack = load(str(copied / "pack.yaml"))
    assert advisor_seat(seat_pack) and seats_from(seat_pack)["advisor"] == ["advisor"]
    from cockpitlib.setup import _seat_settings, _soul

    assert _seat_settings(seat_pack, "advisor", "advisor")["platform_toolsets"] == {"cli": []}
    assert "You have no tools" in _soul(seat_pack, "advisor", "advisor")
    from cockpitlib.advise import DEFAULT_COMMAND, _run

    assert DEFAULT_COMMAND[:2] == ["hermes", "--profile"]
    report = tmp_path / "report.json"
    fake = tmp_path / "fake-advisor"
    fake.write_text(
        '#!/bin/sh\nprintf \'{"pid": 1, "exit_code": 0, "error": "", "reply": "YES from report"}\' > "$HERMES_QUIET_TURN_REPORT_FILE"\n'
        "env | grep -q HERMES_KANBAN_ && exit 9\necho ignored\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("HERMES_KANBAN_TASK", "leaks")
    reply, error = _run({**seat_pack, "advisor": {**seated, "command": [str(fake)]}}, "q", str(report), "C0", "T-1")
    assert (reply, error) == ("YES from report", "")
    fake.write_text(
        '#!/bin/sh\nprintf \'{"exit_code": 2, "error": "model refused"}\' > "$HERMES_QUIET_TURN_REPORT_FILE"\nexit 0\n',
        encoding="utf-8",
    )
    assert (
        _run({**seat_pack, "advisor": {**seated, "command": [str(fake)]}}, "q", str(report), "C0", "T-1")[1]
        == "advisor failed: model refused"
    )
    assert (
        "did not answer"
        in _run(
            {**seat_pack, "advisor": {**seated, "command": [str(tmp_path / "missing")]}},
            "q",
            str(tmp_path / "r2"),
            "C0",
            "T-1",
        )[1]
    )
    for value, message in (
        ({"checkpoints": {}}, "advisor.checkpoints names"),
        ({"checkpoints": {"C0": {"answers": ["low"]}}}, "upper-case words"),
        ({**seated, "bogus": 1}, "advisor takes"),
        ({**seated, "command": "x"}, "advisor.command must be a command"),
        ({**seated, "prompt": ""}, "advisor.prompt is a file path"),
        ({**seated, "max_calls": 0}, "max_calls is a whole number"),
        ({**seated, "in_tool": "y"}, "in_tool is true or false"),
        ({**seated, "in_tool": True}, "needs advisor.report_line"),
        ({**seated, "report_line": "("}, "advisor.report_line:"),
    ):
        (copied / "pack.yaml").write_text(yaml.safe_dump({**raw, "advisor": value}, sort_keys=False), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_after_go_intake_breaks_the_ticket_into_the_packs_linked_cards_and_the_plan_gate_holds_pushes(
    env, pack_file, monkeypatch, tmp_path, capsys
):
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.decompose import chain, check, decompose
    from cockpitlib.kanban import BoardWrites, board_cards, place_card
    from cockpitlib.outbox import create
    from cockpitlib.plan import init
    from cockpitlib.plan_gate import declared, gate, waits

    assert chain(pack) != chain(other)
    repos = [repo["name"] for repo in pack["repos"]["repos"]][:2]
    ticket = f"{pack['tracker']['project']}-91"
    breakdown = {
        "repos": [
            {"repo": repos[0], "slot": "1", "prs": ["#4"], "plan_gate": "human"},
            {"repo": repos[-1], "plan_gate": "auto", "note": f"careful {pack['name']}"},
        ]
    }
    with pytest.raises(CockpitError, match="has no go"):
        check(pack, ticket, breakdown)
    init(ticket, "plan", "go")
    for bad, message in (
        ({}, "the breakdown lists repos"),
        ({"repos": [{"repo": "moon"}]}, "not a repo of this pack"),
        ({"repos": [{"repo": repos[0], "x": 1}]}, "each breakdown row takes"),
        ({"repos": [{"repo": repos[0]}, {"repo": repos[0]}]}, "listed twice"),
        ({"repos": [{"repo": repos[0], "plan_gate": "maybe"}]}, "plan_gate is auto or human"),
        ({"repos": [{"repo": repos[0], "prs": "#1"}]}, "prs is a list"),
    ):
        with pytest.raises(CockpitError, match=re.escape(message)):
            check(pack, ticket, bad)
    intake = place_card(pack["board"], f"{ticket}: intake", "intake", "ready")
    monkeypatch.setenv("HERMES_KANBAN_TASK", intake)
    made = decompose(pack, ticket, breakdown)["cards"]
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    per_repo = len(chain(pack))
    assert len(made) == per_repo * len(breakdown["repos"])
    cards = {card["id"]: card for card in board_cards(pack["board"])}
    first = [row for row in made if row["repo"] == repos[0]]
    assert [row["kind"] for row in first] == chain(pack) and first[0]["parent"] == intake
    for before, after in zip(first, first[1:]):
        assert _parents(pack, after["card"]) == [before["card"]]
    body = cards[first[0]["card"]]["body"]
    assert "Plan gate: human" in body and "Slot: 1" in body and "PRs: #4" in body and repos[0] in body
    assert ("Read the plan at" in body) is (pack["name"] == "acme") and ("Plan file:" in body) is (
        pack["name"] == "bravo"
    )
    assert decompose(pack, ticket, breakdown)["cards"][0]["card"] == first[0]["card"]  # made once
    worker = first[0]["card"]
    assert declared(body) == "human" and gate(pack, worker) == "human" and gate(pack, "nope") == "auto"
    monkeypatch.setenv("HERMES_KANBAN_TASK", worker)
    held = create(pack, ticket, "push-branch", worker, "ship", {"repo": repos[0], "branch": "main"})
    assert held["status"] == "held" and any("plan gate" in item for item in str(held.get("hold") or held).split("'"))
    writes = BoardWrites(pack["board"])
    writes.comment(worker, "human", "Human: plan ok")
    writes.flush()
    assert waits(pack, worker) == ""
    free = create(pack, ticket, "push-branch", worker, "ship again", {"repo": repos[0], "branch": f"work/{ticket}"})
    assert free["status"] == "pending"
    auto = next(row for row in made if row["repo"] == repos[-1] and row["kind"] == "work")["card"]
    monkeypatch.setenv("HERMES_KANBAN_TASK", auto)
    assert waits(pack, auto) == ""
    if pack["advisor"].get("command"):
        from cockpitlib.advise import advise

        monkeypatch.setenv("ACME_ADVICE", "DEVIATES")
        advise(pack, "C0", ticket=ticket, card=auto)
        assert gate(pack, auto) == "human" and "plan gate" in waits(pack, auto)  # a deviation at C0 asks the human
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    breakdown_file = tmp_path / "breakdown.json"
    breakdown_file.write_text(json.dumps({"repos": [{"repo": repos[0]}]}), encoding="utf-8")
    second = f"{pack['tracker']['project']}-92"
    init(second, "plan", "go")
    assert main(["flow", "decompose", second, str(breakdown_file)]) == 0
    assert len(json.loads(capsys.readouterr().out)["cards"]) == per_repo
    assert main(["flow", "decompose", second, str(tmp_path / "none.json")]) == 2
    assert main(["flow", "nope", second, "x"]) == 2
    monkeypatch.setenv("COCKPIT_LANE", "intake")
    monkeypatch.setenv("COCKPIT_TICKET", ticket)
    assert main(["flow", "reopen", second, "x"]) == 1  # a lane acts on its own ticket only
    assert main(["flow", "reopen", ticket, f"again {pack['name']}"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == f"{ticket}: reopened"
    from cockpitlib.paths import wt

    os.makedirs(os.path.join(wt(), ticket, repos[0]), exist_ok=True)
    assert main(["outbox", "rework", ticket, "--instruction", f"fix {pack['name']}"]) == 0
    reworked = json.loads(capsys.readouterr().out)["cards"]
    assert [row["repo"] for row in reworked] == [repos[0]] and [lane for lane, _card in reworked[0]["chain"]][
        0
    ].startswith("tester")
    assert main(["outbox", "rework", ticket]) == 2
    assert main(["outbox", "chain", ticket, worker, "--instruction", "check it"]) == 0
    assert len(json.loads(capsys.readouterr().out)["chain"]) == 2
    assert main(["ci", "rework", ticket, "a" * 40, "--repo", repos[-1]]) == 0
    assert json.loads(capsys.readouterr().out)["cards"][0]["repo"] == repos[-1]
    monkeypatch.delenv("COCKPIT_LANE")
    monkeypatch.delenv("COCKPIT_TICKET")
    from cockpitlib.acts import continue_ticket

    both = continue_ticket(pack, ticket, "two repos", kind="rework", repos=repos)
    titles = {card["title"] for card in board_cards(pack["board"])}
    assert len(both["cards"]) == len(repos) == 2 and all(f"{ticket}: rework ({repo})" in titles for repo in repos)
    with pytest.raises(CockpitError, match="moon is not a repo"):
        continue_ticket(pack, ticket, "x", kind="rework", repos=["moon"])
    client = _client()
    assert (
        client.post("/kickoff", json={"ticket": ticket, "mode": "rework", "repos": [repos[0]]}).status_code == 409
    )  # a rework is open
    third = f"{pack['tracker']['project']}-93"
    init(third, "plan", "go")
    closing = BoardWrites(pack["board"])
    for card in board_cards(pack["board"]):
        if str(card.get("lane") or card.get("assignee") or "").startswith("intake") and card["status"] not in (
            "done",
            "archived",
        ):
            closing.complete(card["id"], result="done")  # the intake seat is free again
    closing.flush()
    routed = client.post(
        "/kickoff", json={"ticket": third, "mode": "rework", "repos": [repos[0]], "prompt": "via kickoff"}
    )
    assert routed.status_code == 200, routed.text
    assert routed.json()["cards"][0]["repo"] == repos[0] and len(routed.json()["cards"][0]["chain"]) == 2
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    skills = yaml.safe_load((copied / "skills.yaml").read_text(encoding="utf-8"))
    for value, message in (
        ({"decompose": ["review"]}, "cards.decompose is the chain"),
        ({"decompose": ["work", "moon"]}, "cards.decompose is the chain"),
        ({"body": "cards/none.md"}, "cards.body: no file"),
        ({"body": "cards/bad.md"}, "cards.body: 'oops'"),
        ({"other": 1}, "cards takes skills, titles, body and decompose"),
    ):
        (copied / "cards" / "bad.md").write_text("{oops}", encoding="utf-8")
        (copied / "skills.yaml").write_text(
            yaml.safe_dump({**skills, "cards": {**skills["cards"], **value}}, sort_keys=False), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_advisor_and_plan_gate_read_damaged_records_as_empty(env, pack_file, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.advise import _folder, _run, calls
    from cockpitlib.plan_gate import said_ok

    ticket = f"{pack['tracker']['project']}-95"
    os.makedirs(_folder(ticket), exist_ok=True)
    open(os.path.join(_folder(ticket), "calls.jsonl"), "w", encoding="utf-8").write('{bad\n[1]\n{"checkpoint": "C0"}\n')
    assert calls(ticket) == [{"checkpoint": "C0"}]
    fake = tmp_path / "advisor"
    fake.write_text(
        "#!/bin/sh\nprintf '{bad' > \"$HERMES_QUIET_TURN_REPORT_FILE\"\necho STDOUT-ANSWER\n", encoding="utf-8"
    )
    fake.chmod(0o755)
    assert _run({**pack, "advisor": {"command": [str(fake)]}}, "q", str(tmp_path / "r.json"), "C0", ticket) == (
        "STDOUT-ANSWER\n",
        "",
    )
    assert said_ok({"board": f"no-board-{pack['name']}"}, "t_1") is False
    import sqlite3

    real = sqlite3.connect
    monkeypatch.setattr(
        "cockpitlib.plan_gate.sqlite3.connect",
        lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
    )
    assert said_ok(pack, "t_1") is False
    monkeypatch.setattr("cockpitlib.plan_gate.sqlite3.connect", real)


def test_a_seat_env_that_is_not_utf8_reads_as_no_key_and_keeps_the_gate_working(tmp_path):
    from cockpitlib.usage import _env_values

    bad = tmp_path / ".env"
    bad.write_bytes(b"ANTHROPIC_API_KEY=\xff\xfe\n")
    assert _env_values(str(bad)) == {}
