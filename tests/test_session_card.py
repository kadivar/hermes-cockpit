# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ticket pane's card while the human's manual session is open: the slot's app addresses and a login picker."""

import os
import shutil

import pytest
import yaml

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
CARD = {
    "apps": {"Shop": "https://app.example.test:{port.shop}", "API": "https://api.example.test:{port.https}/{ticket}"},
    "logins": [{"label": "admin", "user": "admin@example.test"}, {"label": "member", "user": "member@example.test"}],
    "default": "admin",
}


def _copy_pack(pack_file, tmp_path, change) -> str:
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(data)
    (copied / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(copied / "pack.yaml")


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _with_card(data):
    slots = data.setdefault("slots", {})
    slots["ports"] = {**(slots.get("ports") or {}), "shop": 8100, "https": 8200}
    slots["session_card"] = CARD


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_card_shows_while_the_humans_session_is_open_with_the_slots_addresses_and_logins(
    bare, pack_file, monkeypatch, tmp_path
):
    from cockpitlib.slots import write_owner, write_slot_secret, write_ticket

    path = _copy_pack(pack_file, tmp_path, _with_card)
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1801"
    assert _client().get(f"/session-card?ticket={ticket}").json() == {"open": False, "ticket": ticket}
    write_ticket(1, ticket)
    write_owner(1, "lane:worker-1")
    assert _client().get(f"/session-card?ticket={ticket}").json()["open"] is False  # a lane's slot is no manual session
    write_owner(1, "human")
    card = _client().get(f"/session-card?ticket={ticket}").json()
    assert card["open"] and card["slot"] == 1 and card["default"] == "admin" and card["current"] is None
    assert card["apps"] == [
        {"name": "Shop", "url": "https://app.example.test:8101"},
        {"name": "API", "url": f"https://api.example.test:8201/{ticket}"},
    ]
    assert [row["label"] for row in card["logins"]] == ["admin", "member"]
    write_slot_secret(1, {"username": "admin@example.test", "password": "s3cret"})
    assert _client().get(f"/session-card?ticket={ticket}").json()["current"] == {
        "username": "admin@example.test",
        "password": "s3cret",
    }
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert _client().get(f"/session-card?ticket={ticket}").json()["current"] == {"username": "admin@example.test"}
    monkeypatch.delenv("COCKPIT_LANE")
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert (
        _client().get(f"/session-card?ticket={ticket}").json()["open"] is False
    )  # no card in the pack, no card on the pane


@pytest.mark.parametrize("pack_file", PACKS)
def test_get_password_sets_one_for_the_picked_user_on_the_sessions_slot(bare, pack_file, monkeypatch, tmp_path):
    from cockpitlib.slots import read_slot_secret

    path = _copy_pack(pack_file, tmp_path, _with_card)
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    ticket = f"{pack['tracker']['project']}-1802"
    asked = []

    class Provider:
        def login(self, tkt, user):
            asked.append((tkt, user))
            return {"user": user, "password": "fresh" if user != "nobody@example.test" else ""}

    monkeypatch.setattr("cockpitlib.slots.provider_for", lambda *_a, **_k: Provider())
    sent = _client().post("/session-login", json={"ticket": ticket, "slot": 3, "user": "member@example.test"}).json()
    assert sent == {"ok": True, "slot": 3, "user": "member@example.test", "password": "fresh"} and asked == [
        (ticket, "member@example.test")
    ]
    assert read_slot_secret(3)["password"] == "fresh"
    assert (
        _client().post("/session-login", json={"ticket": ticket, "slot": 3, "user": "nobody@example.test"}).status_code
        == 409
    )
    assert _client().post("/session-login", json={"ticket": ticket}).status_code == 400


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_session_card_setting_is_checked(bare, pack_file, tmp_path):
    for number, bad in enumerate(
        (
            {"other": 1},
            {"apps": {"x": "ftp://y"}},
            {"logins": [{"label": "a"}]},
            {"logins": [{"label": "a", "user": "u"}], "default": "b"},
            ["x"],
        )
    ):
        with pytest.raises(CockpitError, match="slots.session_card"):
            load(
                _copy_pack(
                    pack_file,
                    tmp_path / str(number),
                    lambda data, bad=bad: data.setdefault("slots", {}).update(session_card=bad),
                )
            )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_login_the_packs_login_command_kept_in_its_state_folder_is_the_slots_login(
    bare, pack_file, monkeypatch, tmp_path
):
    import json

    from cockpitlib.slots import pack_state_dir, read_slot_secret

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    folder = pack_state_dir(2)
    assert folder
    os.makedirs(folder, exist_ok=True)
    json.dump({"username": "admin@example.test", "password": "kept"}, open(os.path.join(folder, "demo.json"), "w"))
    assert read_slot_secret(2)["password"] == "kept"


def test_the_tickets_list_is_newest_activity_first(bare, monkeypatch):
    from dashboard.cockpit.routes import pages as routes

    monkeypatch.setenv("COCKPIT_PACK", PACKS[0])
    monkeypatch.setattr(
        "cockpitlib.intents.all_intents",
        lambda *_a: [
            {"ticket": "TASK-1", "created_at": "2026-10-20T10:00:00+00:00"},
            {
                "ticket": "TASK-2",
                "created_at": "2026-10-20T10:00:00+00:00",
                "receipt": {"time": "2026-10-26T10:00:00Z"},
            },
        ],
    )
    monkeypatch.setattr(
        "cockpitlib.kanban.board_cards",
        lambda *_a, **_k: [
            {"ticket": "TASK-3", "status": "done", "created_at": 1_700_000_000, "completed_at": 1_800_000_000}
        ],
    )
    monkeypatch.setattr("cockpitlib.tracker.titles", lambda _p, keys: {key: "" for key in keys})
    monkeypatch.setattr(routes, "_ticket_row", lambda key, _i, _c, _pack=None: {"ticket": key})
    order = list(routes._ticket_index(load(PACKS[0])))
    assert order == ["TASK-3", "TASK-2", "TASK-1"]
    assert routes._when("x") == 0.0 and routes._when(None) == 0.0 and routes._when("12") == 12.0


def test_markdown_keeps_a_fences_language_and_wraps_a_table_to_scroll():
    from cockpitlib.render import markdown

    out = markdown("| a | b |\n|---|---|\n| 1 | 2 |\n\n```mermaid\nflowchart LR\n  A-->B\n```\n\n```\nplain\n```\n")
    assert '<div class="cockpit-table"><table><thead><tr><th>a</th><th>b</th></tr></thead>' in out
    assert '<pre><code class="language-mermaid">flowchart LR\n  A--&gt;B</code></pre>' in out
    assert "<pre><code>plain</code></pre>" in out


def _lane_db(path, rows):
    import sqlite3

    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "create table messages (id integer primary key, session_id text, role text, content text, tool_calls text, tool_name text, timestamp real)"
    )
    connection.executemany(
        "insert into messages (session_id, role, content, tool_calls, tool_name, timestamp) values (?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def test_a_cards_stream_carries_the_lanes_own_conversation_whatever_tool_it_drives(env, monkeypatch):
    from cockpitlib.lane_feed import lane_messages
    from cockpitlib.paths import hermes_home

    monkeypatch.setenv("COCKPIT_PACK", PACKS[0])
    import json

    calls = json.dumps(
        [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "terminal", "arguments": json.dumps({"command": "git status"})},
            }
        ]
    )
    _lane_db(
        os.path.join(hermes_home(), "profiles", "worker-1", "state.db"),
        [
            ("s1", "user", "Work on card t_abc: fix it", None, None, 100.0),
            ("s1", "assistant", "Looking at the diff", calls, None, 101.0),
            ("s1", "tool", "clean", None, "terminal", 102.0),
            ("s2", "user", "another card t_zzz", None, None, 103.0),
        ],
    )
    rows = lane_messages({"id": "t_abc", "assignee": "worker-1", "ticket": "T-1"})
    assert [row["kind"] for row in rows] == ["prompt", "text", "tool_use", "tool_result"] and rows[2][
        "name"
    ] == "terminal"
    assert all(row["card"] == "t_abc" and row["who"] == "worker-1" and row["ts"] for row in rows)
    assert lane_messages({"id": "t_abc", "assignee": "worker-1"}, since=rows[1]["ts"])[0]["kind"] == "tool_result"
    assert (
        lane_messages({"id": "t_abc", "assignee": "../x"}) == []
        and lane_messages({"id": "t_abc", "assignee": "tester-9"}) == []
    )
    _lane_db(os.path.join(hermes_home(), "profiles", "tester-8", "state.db"), [])
    assert lane_messages({"id": "t_abc", "assignee": "tester-8"}) == []
    open(os.path.join(hermes_home(), "profiles", "tester-8", "state.db"), "w").write("not a database")
    assert lane_messages({"id": "t_abc", "assignee": "tester-8"}) == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_jobs_are_newest_first_and_all_streams_the_packs_newest_jobs(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import lane_feed
    from cockpitlib.kanban import place_card

    path = _copy_pack(pack_file, tmp_path, lambda data: data.setdefault("desktop", {}).update(live_jobs=1))
    monkeypatch.setenv("COCKPIT_PACK", path)
    pack = load(path)
    place_card(pack["board"], f"{pack['tracker']['project']}-1901: work", "worker-1", "ready")
    place_card(pack["board"], f"{pack['tracker']['project']}-1902: work", "worker-1", "ready")
    listed = [row["ticket"] for row in lane_feed.jobs(pack)]
    lasts = [row["last"] for row in lane_feed.jobs(pack)]
    assert set(listed) >= {
        f"{pack['tracker']['project']}-1901",
        f"{pack['tracker']['project']}-1902",
    } and lasts == sorted(lasts, reverse=True)
    assert _client().get("/jobs").json()["jobs"][0]["ticket"] == listed[0]
    monkeypatch.setattr(
        "cockpitlib.activity.ticket_activity",
        lambda _p, name, _s="": [{"ts": "2026-10-27T10:00:00Z", "kind": "created", "text": name}],
    )
    streamed = {row["ticket"] for row in lane_feed.job_stream(pack, "all")["entries"]}
    assert streamed == {listed[0]}
    assert _client().get("/repos").json()["mermaid_url"] == ""
    for number, bad in enumerate(
        ({"live_jobs": 0}, {"mermaid_url": "http://x/m.mjs"}, {"mermaid_url": "https://x/'m"}, {"other": 1})
    ):
        with pytest.raises(CockpitError, match="desktop"):
            load(
                _copy_pack(
                    pack_file, tmp_path / str(number), lambda data, bad=bad: data.setdefault("desktop", {}).update(bad)
                )
            )
    good = load(
        _copy_pack(
            pack_file,
            tmp_path / "good",
            lambda data: data.setdefault("desktop", {}).update(mermaid_url="https://cdn.test/mermaid.esm.min.mjs"),
        )
    )
    assert good["desktop"]["mermaid_url"] == "https://cdn.test/mermaid.esm.min.mjs"


def test_one_parser_reads_two_coding_tools_lines_in_full(bare, tmp_path, monkeypatch):
    import json

    from cockpitlib import chat

    lines = [
        {"type": "system", "subtype": "init", "model": "m1", "tools": ["a", "b"], "timestamp": "t0"},
        {"type": "user", "timestamp": "t1", "message": {"role": "user", "content": "do it"}},
        {
            "type": "assistant",
            "timestamp": "t2",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "hmm"},
                    {"type": "text", "text": "ok"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "t3",
            "message": {
                "content": [{"type": "tool_result", "content": [{"type": "text", "text": "a.txt"}], "is_error": False}]
            },
        },
        {"type": "result", "result": "done", "total_cost_usd": 0.12, "num_turns": 3, "timestamp": "t4"},
        {"type": "summary", "summary": "the work"},
        {
            "role": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "cursor says"},
                    {"type": "tool_result", "content": "out", "is_error": True},
                ]
            },
        },
        {"other": 1},
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    monkeypatch.setattr(chat, "_allowed", lambda _p: True)
    kinds = [(row["kind"], row.get("text", "")[:12]) for row in chat.coding_tail(str(path))["entries"]]
    assert kinds[:9] == [
        ("system", "session star"),
        ("prompt", "do it"),
        ("thinking", "hmm"),
        ("text", "ok"),
        ("tool_use", ""),
        ("tool_result", "a.txt"),
        ("result", "done"),
        ("system", "summary: the"),
        ("text", "cursor says"),
    ]
    assert kinds[9] == ("tool_result", "out") and kinds[10][0] == "text"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_human_may_approve_despite_ci_unless_the_pack_forbids_it_for_that_commit_only(
    env, pack_file, monkeypatch, tmp_path
):
    from cockpitlib import sequence
    from cockpitlib.cli import main
    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import save
    from cockpitlib.outbox import ci_overridden, ci_override, create

    path = _copy_pack(pack_file, tmp_path, lambda data: data.setdefault("outbox", {}).update(ci_override=False))
    monkeypatch.setenv("COCKPIT_PACK", pack_file)  # no setting: offered
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    forbidden = load(path)
    repo = pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-1950"
    approve = create(
        pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 5, "sha": "a" * 40, "event": "APPROVE"}
    )
    comment = create(
        pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 6, "sha": "b" * 40, "event": "COMMENT"}
    )
    with pytest.raises(CockpitError, match="say why"):
        ci_override(pack, approve["id"], " ")
    with pytest.raises(CockpitError, match="no approval"):
        ci_override(pack, comment["id"], "x")
    monkeypatch.setenv("COCKPIT_LANE", "reviewer")
    with pytest.raises(CockpitError, match="stay with the human"):
        ci_override(pack, approve["id"], "x")
    monkeypatch.delenv("COCKPIT_LANE")
    with pytest.raises(CockpitError, match="does not allow"):
        ci_override(forbidden, approve["id"], "x")  # the pack switched it off
    assert main(["outbox", "ci-override", approve["id"], "--reason", "the e2e job is flaky today"]) == 0
    given = load_intent(approve["id"])
    assert given["ci_override"]["reason"] == "the e2e job is flaky today" and ci_overridden(given, pack)
    assert not ci_overridden(given, forbidden)  # switched off: a given override no longer counts
    staged = {**given, "payload": {**given["payload"], "waits_for": "X/001-push-branch"}}
    monkeypatch.setattr("cockpitlib.ci_watch.state_for", lambda *_a, **_k: {"state": "failure"})
    assert sequence._ci(staged, pack) == {}  # the sequence wait is skipped
    assert sequence._ci({**staged, "ci_override": None}, pack)["id"] == "CI"
    moved = {**given, "payload": {**given["payload"], "sha": "c" * 40}}
    assert not ci_overridden(moved, pack)  # another commit: CI counts again
    done = load_intent(approve["id"])
    done["status"] = "published"
    save(done)
    with pytest.raises(CockpitError, match="only an open approval"):
        ci_override(pack, approve["id"], "x")
    row = _client().post("/ci-override", json={"id": comment["id"], "reason": "x"})
    assert row.status_code == 400 and "no approval" in row.text


@pytest.mark.parametrize("pack_file", PACKS)
def test_submitting_an_overridden_approval_skips_the_live_check_read(bare, pack_file, monkeypatch, tmp_path):
    from cockpitlib import publish

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    asked = []

    class Forge:
        def checks(self, repo, sha):
            asked.append(sha)
            return ["e2e: failure"]

        def repo(self, name):
            return f"org/{name}"

        def get(self, path):
            return {"state": "APPROVED"}

    intent = {
        "id": "T-1/001-pr-review-submit",
        "status": "posted",
        "review": {"id": 9, "proposed_event": "APPROVE"},
        "payload": {"repo": "api", "number": 5, "sha": "a" * 40, "event": "APPROVE"},
    }
    with pytest.raises(CockpitError, match="waits for green checks"):
        publish.submit_review(dict(intent), Forge(), event="APPROVE", pack=pack, dry_run=True)
    overridden = {**intent, "ci_override": {"by": "human", "reason": "x", "sha": "a" * 40}}
    try:
        publish.submit_review(overridden, Forge(), event="APPROVE", pack=pack, dry_run=True)
    except CockpitError as exc:
        assert "green checks" not in str(exc)
    assert asked == ["a" * 40]  # the override skipped the read
