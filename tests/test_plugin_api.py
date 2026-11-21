# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Another plugin's cards, modes, Inbox rows and requests go through cockpit's own policy."""

import json
import os
import re

import pytest

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.boards import put_card
from tests.support.both_packs import PACKS, PLUGIN_MODES, ROOT, _client, _plugged


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugin_card_records_its_repos(env, pack_file, tmp_path, monkeypatch):
    """api.start_card(repos=...) records the repos on the one card it starts: a rework (worker) card does not fan out
    per repo and keeps its run limit; a short name resolves to its repos.yaml name; without repos nothing changes. The
    repos its card names never open a repo's own checkout to the worker."""
    import shutil
    import sqlite3
    import subprocess

    import yaml

    from cockpitlib import plugin_api
    from cockpitlib.egress import check_bound, explained
    from cockpitlib.errors import PackError
    from cockpitlib.kanban import card_entry, db_path
    from cockpitlib.plugin_api import _resolve_repos

    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    pack = load(str(copied / "pack.yaml"))
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings

    save_settings(
        pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}}
    )  # two tickets' worker cards: a slot each
    board = str(pack["board"])
    own, other = [repo["name"] for repo in pack["repos"]["repos"]][:2]

    def limit_of(card):
        connection = sqlite3.connect(f"file:{db_path(board)}?mode=ro", uri=True)
        try:
            return connection.execute("select max_runtime_seconds from tasks where id = ?", (card,)).fetchone()[0]
        finally:
            connection.close()

    for bad in ("api", [1], {own: True}, b"api"):
        with pytest.raises(CockpitError, match="repos is a list of repo names"):
            plugin_api.start_card("rework", f"{pack['tracker']['project']}-1400", policy="release", repos=bad)
    # a name that resolves to no repo is refused, not dropped (the fence would fail open), and starts no card
    with pytest.raises(CockpitError, match="no-such-repo is not a repo of this pack"):
        plugin_api.start_card(
            "rework", f"{pack['tracker']['project']}-1403", policy="release", repos=[own, "no-such-repo"]
        )
    assert plugin_api.board_cards(f"{pack['tracker']['project']}-1403") == []
    # without repos: one card, no repos recorded, as before
    plain = plugin_api.start_card("rework", f"{pack['tracker']['project']}-1401", body="unit 0", policy="release")
    assert "repos" not in card_entry(board, plain["card_id"]) and "cards" not in plain and "repos" not in plain
    ticket = f"{pack['tracker']['project']}-1402"
    started = plugin_api.start_card(
        "rework", ticket, body="unit 1", policy="release", max_runtime_seconds=900, repos=(name for name in [own])
    )  # a generator is read once, then checked
    assert "cards" not in started and len(plugin_api.board_cards(ticket)) == 1  # one card, not one per repo
    assert started["repos"] == [own]  # the resolved names come back
    assert card_entry(board, started["card_id"])["repos"] == [own]
    assert limit_of(started["card_id"]) == 900  # the run limit stays on it
    # a short name: a repos.yaml label, else the one name it prefixes with a dot
    shaped = {
        "repos": {
            "repos": [
                {"name": "core.shop.example.test"},
                {"name": "web.shop.example.test", "label": "front"},
                {"name": "ops.a.example.test"},
                {"name": "ops.b.example.test"},
                {"name": "api"},
            ]
        }
    }
    assert _resolve_repos(["core", "front", "web.shop.example.test", "api", "core", ""], shaped) == [
        "core.shop.example.test",
        "web.shop.example.test",
        "api",
    ]
    with pytest.raises(CockpitError, match="nope is not a repo of this pack"):
        _resolve_repos(["core", "nope"], shaped)
    with pytest.raises(CockpitError, match=r"ops is ambiguous \(ops.a.example.test, ops.b.example.test\)"):
        _resolve_repos(["ops"], shaped)
    repos_yaml = yaml.safe_load((copied / "repos.yaml").read_text(encoding="utf-8"))
    repos_yaml["repos"][0]["label"] = ""
    (copied / "repos.yaml").write_text(yaml.safe_dump(repos_yaml, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match="label is the repo's short name"):
        load(str(copied / "pack.yaml"))
    repos_yaml["repos"][1]["label"] = "short"  # two repos, one label
    repos_yaml["repos"][0]["label"] = "short"
    (copied / "repos.yaml").write_text(yaml.safe_dump(repos_yaml, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match="label short is on more than one repo"):
        load(str(copied / "pack.yaml"))
    repos_yaml["repos"][1].pop("label")
    repos_yaml["repos"][0]["label"] = other  # a label that is another repo's name
    (copied / "repos.yaml").write_text(yaml.safe_dump(repos_yaml, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match=f"label {other} is another repo's name"):
        load(str(copied / "pack.yaml"))
    repos_yaml["repos"][0]["label"] = "short"
    (copied / "repos.yaml").write_text(yaml.safe_dump(repos_yaml, sort_keys=False), encoding="utf-8")
    assert load(str(copied / "pack.yaml"))["repos"]["repos"][0]["label"] == "short"
    # the repos a card names open nothing: a worker never writes in the repos' own checkouts
    for name in (own, other):
        subprocess.run(
            ["git", "-C", str(env["root"] / "repos" / name), "checkout", "-B", f"{pack['branch_prefix']}/{ticket}"],
            check=True,
            capture_output=True,
        )
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    monkeypatch.setenv("HERMES_KANBAN_TASK", started["card_id"])
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    note = {name: env["root"] / "repos" / name / "note" for name in (own, other)}
    assert check_bound(f"echo hi > {note[own]}") == "blocked" and check_bound(f"echo hi > {note[other]}") == "blocked"
    assert "outside your ticket checkouts" in explained("blocked")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugin_mode_is_offered_and_lands_on_the_seat_the_pack_names(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import plugin_api
    from cockpitlib.errors import PackError
    from cockpitlib.pack import plugin_block

    plugged = _plugged(pack_file, tmp_path)
    monkeypatch.setenv("COCKPIT_PACK", plugged)
    pack = load(plugged)
    plugin, kind, title, flow, bucket, lane = PLUGIN_MODES[pack["name"]]
    assert "card_kinds" not in plugin_block(pack, plugin) and "kickoff_modes" not in plugin_block(pack, plugin)
    client = _client()
    modes = {row["mode"]: row for row in client.get("/kickoff-modes").json()["modes"]}
    assert modes[kind] == {
        "mode": kind,
        "label": f"{kind} → {lane}",
        "text": f"{plugin} starts {kind}",
        "lane_kind": lane,
        "owner": plugin,
    }
    assert modes["intake"]["owner"] == "" and modes["rework"]["lane_kind"] == "worker"
    ticket = f"{pack['tracker']['project']}-501"
    started = client.post("/kickoff", json={"ticket": ticket, "mode": kind})
    assert started.status_code == 200, started.text
    assert started.json()["lane"].startswith(lane) and started.json()["title"] == title.format(ticket=ticket)
    [card] = plugin_api.board_cards(ticket, pack)
    assert card["kind"] == kind and card["flow"] == flow and card["assignee"] == started.json()["lane"]
    refused = client.post("/kickoff", json={"ticket": ticket, "mode": "no-such-mode"})
    assert refused.status_code == 409 and "unknown kickoff mode no-such-mode" in refused.json()["detail"]
    assert client.post("/kickoff", json={"ticket": ticket, "mode": kind}).status_code == 409  # its twin is open
    with pytest.raises(PackError, match="is cockpit's own"):
        plugin_api.register_kickoff_mode("intake", "analyst")
    with pytest.raises(PackError, match="is cockpit's own"):
        plugin_api.register_card_kind("rework", "{ticket}: rework")
    import yaml

    raw = yaml.safe_load(open(plugged, encoding="utf-8"))
    for broken, message in (
        (
            {"kickoff": {"lanes": {kind: "gatekeeper"}}},
            f"kickoff.lanes.{kind}: gatekeeper is not a seat a kickoff starts",
        ),
        ({"kickoff": {"lanes": {"absent": "analyst"}}}, "kickoff.lanes.absent: no such kickoff mode"),
        ({"kickoff": ["analyst"]}, "kickoff takes lanes"),
    ):
        open(plugged, "w", encoding="utf-8").write(
            yaml.safe_dump({**raw, **broken}, sort_keys=False, allow_unicode=True)
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(plugged)
    raw["plugins"][plugin]["kickoff_modes"][kind]["preflight"] = ["teleport"]
    open(plugged, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    with pytest.raises(PackError, match="preflight steps are"):
        load(plugged)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugin_card_reads_with_its_flow_and_one_key_makes_one_card(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import plugin_api
    from cockpitlib.kanban import card_title, place_card

    plugged = _plugged(pack_file, tmp_path)
    monkeypatch.setenv("COCKPIT_PACK", plugged)
    pack = load(plugged)
    plugin, kind, title, flow, bucket, lane = PLUGIN_MODES[pack["name"]]
    ticket = f"{pack['tracker']['project']}-502"
    assert card_title(kind, ticket, pack=pack) == title.format(ticket=ticket)
    key = f"{pack['name']}-unit-1"
    first = place_card(
        pack["board"],
        card_title(kind, ticket, pack=pack),
        "analyst",
        kind=kind,
        ticket=ticket,
        pack=pack,
        idempotency_key=key,
    )
    again = place_card(
        pack["board"],
        card_title(kind, ticket, pack=pack),
        "analyst",
        kind=kind,
        ticket=ticket,
        pack=pack,
        idempotency_key=key,
    )
    assert first == again and [card["id"] for card in plugin_api.board_cards(ticket, pack)] == [first]
    assert plugin_api.board_cards(ticket, pack)[0]["flow"] == flow
    board = _client().get("/board").json()["cards"]
    assert [(card["ticket"], card["flow"]) for card in board if card["id"] == first] == [(ticket, flow)]
    tickets = {row["ticket"]: row for row in _client().get("/tickets").json()["tickets"]}
    assert tickets[ticket]["last_card"]["id"] == first and tickets[ticket]["last_card"]["flow"] == flow
    assert tickets[ticket]["phase"] == "running"


@pytest.mark.parametrize("pack_file", PACKS)
def test_housekeeping_leaves_a_plugins_card_to_that_plugin_and_wakes_it(env, pack_file, monkeypatch, tmp_path):
    import sqlite3

    from cockpitlib import plugin_api
    from cockpitlib.housekeeping import (
        RATE_LIMITED,
        STALE_RATE_LIMIT,
        return_unfinished,
        settle_reviews,
        stamp_rate_limit,
        unstrand,
    )
    from cockpitlib.kanban import BoardWrites, board_cards, db_path, place_card
    from cockpitlib.paths import qa

    plugged = _plugged(pack_file, tmp_path)
    monkeypatch.setenv("COCKPIT_PACK", plugged)
    pack = load(plugged)
    plugin, kind, title, flow, bucket, lane = PLUGIN_MODES[pack["name"]]
    board = pack["board"]
    ticket = f"{pack['tracker']['project']}-503"
    owned = place_card(board, title.format(ticket=ticket), "reviewer", kind=kind, ticket=ticket, pack=pack)
    mine = put_card(board, f"{ticket}: review", "reviewer", "review")
    db = sqlite3.connect(db_path(board))
    db.execute(
        "update tasks set status = 'review', result = ? where id in (?, ?)", (f"report {pack['name']}", owned, mine)
    )
    db.commit()
    db.close()
    marker = plugin_api.wake_marker(plugin)
    assert settle_reviews(pack) == "1"
    statuses = {card["id"]: card["status"] for card in board_cards(board)}
    assert statuses[owned] == "review" and statuses[mine] == "done"
    assert open(marker, encoding="utf-8").read().split()[-1] == owned
    blocked = place_card(
        board,
        title.format(ticket=f"{ticket}9"),
        "reviewer",
        "blocked",
        reason=f"{RATE_LIMITED} {pack['name']}",
        kind=kind,
        ticket=f"{ticket}9",
        pack=pack,
    )
    stamp_rate_limit(pack, blocked, ticket, now=1_000)
    os.makedirs(os.path.join(qa(), f"{ticket}9"), exist_ok=True)
    open(os.path.join(qa(), f"{ticket}9", "test-results.md"), "w", encoding="utf-8").write("| 1 | open row |\n")
    return_unfinished(pack)
    assert unstrand(pack, now=1_000 + STALE_RATE_LIMIT) == "0"
    assert {card["id"]: card["status"] for card in board_cards(board)}[blocked] == "blocked"
    woken = open(marker, encoding="utf-8").read().splitlines()
    assert [line.split()[-1] for line in woken].count(blocked) == 2  # returned-unfinished and unstrand each asked
    writes = BoardWrites(board)
    writes.unblock(blocked)
    writes.flush()
    assert {card["id"]: card["status"] for card in board_cards(board)}[blocked] == "ready"
    stamp_rate_limit(pack, blocked, ticket, now=2_000)
    assert (
        unstrand(pack, now=2_000 + STALE_RATE_LIMIT) == "0"
    )  # a stale stamp on a plugin's card is dropped, not counted
    other = PACKS[0] if pack["name"] == "bravo" else PACKS[1]
    assert PLUGIN_MODES[load(other)["name"]][0] not in marker


# What the analyst of each fixture asks, and the row each fixture's plugin puts on the Inbox.
INBOX_ASKS = {
    "acme": (
        "which ledger window should the plan use?",
        {
            "id": "close week 41",
            "icon": "📒",
            "what": "ledger week 41 closed",
            "action_label": "open ledger",
            "href": "/ledger",
            "tone": "warn",
        },
    ),
    "bravo": (
        "may the sample include the north cdn?",
        {
            "id": "rate-drop",
            "icon": "📉",
            "what": "sampling fell to a quarter",
            "action_label": "open traces",
            "href": "/traces",
            "tone": "danger",
        },
    ),
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_inbox_lists_cards_that_wait_on_the_human_and_other_plugins_rows(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import plugin_api
    from cockpitlib.errors import CockpitError
    from cockpitlib.inbox import rows
    from cockpitlib.kanban import BoardWrites, board_cards, place_card

    plugged = _plugged(pack_file, tmp_path)
    monkeypatch.setenv("COCKPIT_PACK", plugged)
    pack = load(plugged)
    plugin, kind, title, flow, bucket, lane = PLUGIN_MODES[pack["name"]]
    ask, row = INBOX_ASKS[pack["name"]]
    board = pack["board"]
    ticket = f"{pack['tracker']['project']}-504"
    plan = place_card(
        board, f"{ticket}: analyst", "analyst", "blocked", reason=ask, kind="analyst", ticket=ticket, pack=pack
    )
    looped = place_card(board, title.format(ticket=ticket), "analyst", kind=kind, ticket=ticket, pack=pack)
    plugin_api.block(looped, ask, "needs_input", pack=pack)
    writes = BoardWrites(board)
    writes.unblock(looped)
    writes.flush()
    plugin_api.block(
        looped, ask, "needs_input", pack=pack
    )  # the same ask again: Hermes's loop guard sends it to triage
    running = place_card(board, f"{ticket}: rework", "worker-1", kind="rework", ticket=ticket, pack=pack)
    client = _client()
    cards = {card["id"]: card for card in client.get("/needs-you").json()["cards"]}
    assert cards[plan]["status"] == "blocked" and cards[plan]["block_reason"] == ask and cards[plan]["question"] == ask
    assert cards[plan]["blocked_at"] and cards[plan]["ticket"] == ticket and cards[plan]["owner"] == ""
    assert (
        cards[looped]["status"] == "triage"
        and cards[looped]["block_reason"] == ask
        and cards[looped]["owner"] == plugin
    )
    assert (
        cards[looped]["flow"] == flow and cards[running]["block_reason"] == "" and cards[running]["blocked_at"] is None
    )
    answered = client.post("/answer", json={"id": looped, "text": f"use {pack['name']} defaults"})
    assert answered.status_code == 200, answered.text
    assert {card["id"]: card["status"] for card in board_cards(board)}[looped] == "ready"
    assert client.post("/answer", json={"id": plan, "text": "the last full week"}).status_code == 200
    assert plan not in {card["id"] for card in client.get("/needs-you").json()["cards"] if card["status"] == "blocked"}

    ident = plugin_api.inbox_row(plugin, row)
    listed = client.get("/needs-you").json()["plugins"]
    assert [(item["plugin"], item["id"], item["what"], item["tone"], item["href"]) for item in listed] == [
        (plugin, ident, row["what"], row["tone"], row["href"])
    ]
    assert ident == row["id"].replace(" ", "_") and listed[0]["at"]
    assert (
        plugin_api.inbox_row(plugin, {"id": row["id"], "what": row["what"], "tone": "info"}) == ident
        and rows()[0]["tone"] == "info"
    )
    folder = os.path.dirname(os.path.join(plugin_api.records_root(), "inbox", plugin, "x"))
    open(os.path.join(folder, "broken.json"), "w", encoding="utf-8").write("{not json")
    open(os.path.join(folder, "notes.txt"), "w", encoding="utf-8").write("not a row")
    open(os.path.join(folder, "empty.json"), "w", encoding="utf-8").write("{}")
    open(os.path.join(plugin_api.records_root(), "inbox", "stray"), "w", encoding="utf-8").write(
        "a file, not a plugin's folder"
    )
    assert [item["id"] for item in rows()] == [ident]
    for bad, message in (
        ({"what": "no id"}, "has an id"),
        ({"id": "x"}, "says what it is"),
        ({"id": "x", "what": "y", "tone": "loud"}, "tone is one of"),
    ):
        with pytest.raises(CockpitError, match=message):
            plugin_api.inbox_row(plugin, bad)
    assert plugin_api.drop_inbox_row(plugin, row["id"]) and not plugin_api.drop_inbox_row(plugin, row["id"])
    assert client.get("/needs-you").json()["plugins"] == []


@pytest.mark.parametrize("pack_file", PACKS[:1])
def test_a_pane_button_queues_the_rows_own_request_back_to_its_plugin(env, pack_file, monkeypatch, tmp_path):
    """The page names the row and which of its actions; the payload comes off the row the plugin wrote.

    So a page cannot put a request into a plugin's queue that the plugin never offered, and cockpit
    neither runs nor reads what it relays.
    """
    from cockpitlib import plugin_api
    from cockpitlib.errors import CockpitError
    from cockpitlib.inbox import acts_dir, queue_act

    monkeypatch.setenv("COCKPIT_PACK", _plugged(pack_file, tmp_path))
    client = _client()
    ident = plugin_api.inbox_row(
        "supervisor",
        {
            "id": "stuck:U1/check",
            "what": "check is stuck on U1",
            "tone": "danger",
            "ticket": "ACME-1",
            "detail": {
                "title": "check is stuck on U1",
                "brief": "it stopped",
                "actions": [
                    {"label": "Requeue", "act": {"release": "V1-0-0", "action": "requeue"}},
                    {"label": "Open the release", "href": "/supervisor"},
                ],
            },
        },
    )
    listed = client.get("/needs-you").json()["plugins"][0]
    assert listed["ticket"] == "ACME-1" and listed["detail"]["actions"][0]["label"] == "Requeue"

    answered = client.post("/plugin-act", json={"plugin": "supervisor", "id": ident, "index": 0})
    assert answered.status_code == 200, answered.text
    queued = sorted(os.listdir(acts_dir("supervisor")))
    assert len(queued) == 1
    entry = json.load(open(os.path.join(acts_dir("supervisor"), queued[0]), encoding="utf-8"))
    assert entry["row"] == ident and entry["act"] == {"release": "V1-0-0", "action": "requeue"} and entry["at"]

    # an action with no `act` is a link, not a request; an index off the end is nothing at all
    for index, message in ((1, "not one this row asks for"), (2, "has no action"), (-1, "has no action")):
        with pytest.raises(CockpitError, match=message):
            queue_act("supervisor", ident, index)
    with pytest.raises(CockpitError, match="no Inbox row"):
        queue_act("supervisor", "not-a-row", 0)
    assert client.post("/plugin-act", json={"plugin": "supervisor", "id": ident, "index": 9}).status_code == 400
    assert len(os.listdir(acts_dir("supervisor"))) == 1, "nothing else was queued"


@pytest.mark.parametrize("pack_file", PACKS[:1])
def test_a_button_pressed_twice_is_one_request_and_the_row_says_it_is_queued(env, pack_file, monkeypatch, tmp_path):
    """The pane forgot a press when it was drawn again (closed and reopened, the Inbox polled), so the same button
    could be pressed twice and its plugin ran it twice. A press waiting for its plugin is now one request however
    often it is pressed, and the row itself says which of its buttons are queued, so the pane can show it."""
    from cockpitlib import plugin_api
    from cockpitlib.inbox import acts_dir, queue_act

    monkeypatch.setenv("COCKPIT_PACK", _plugged(pack_file, tmp_path))
    client = _client()
    ident = plugin_api.inbox_row(
        "supervisor",
        {
            "id": "stuck:U1/check",
            "what": "check is stuck on U1",
            "tone": "danger",
            "detail": {
                "title": "t",
                "brief": "b",
                "actions": [
                    {"label": "Requeue", "act": {"release": "V1-0-0", "action": "requeue"}},
                    {"label": "Waive", "act": {"release": "V1-0-0", "action": "waive"}},
                ],
            },
        },
    )
    first = queue_act("supervisor", ident, 0)
    again = client.post("/plugin-act", json={"plugin": "supervisor", "id": ident, "index": 0}).json()
    assert first["queued"] and again.get("already") is True
    assert len(os.listdir(acts_dir("supervisor"))) == 1, "one request, not two"
    assert client.get("/needs-you").json()["plugins"][0]["queued"] == [0]
    queue_act("supervisor", ident, 1)
    assert client.get("/needs-you").json()["plugins"][0]["queued"] == [0, 1], "another button is its own request"
    for name in os.listdir(acts_dir("supervisor")):  # the plugin takes them
        os.remove(os.path.join(acts_dir("supervisor"), name))
    assert client.get("/needs-you").json()["plugins"][0]["queued"] == []
    assert queue_act("supervisor", ident, 0)["queued"], "taken: a new press is a new request"


@pytest.mark.parametrize("pack_file", PACKS[:1])
def test_a_pages_link_is_pack_data_and_a_pack_without_one_offers_none(env, pack_file, monkeypatch, tmp_path):
    """plugins.<name>.page is how a plugin beside cockpit gets a link at the right of the tab row.

    Cockpit learns nothing about the plugin by offering it — the label and the route are the plugin's
    own words — and a pack that declares none gets an empty list, which renders nothing at all.
    """
    from cockpitlib.errors import PackError
    from cockpitlib.registry import plugin_pages

    plugged = _plugged(pack_file, tmp_path)
    monkeypatch.setenv("COCKPIT_PACK", plugged)
    pack = load(plugged)
    assert plugin_pages(pack) == [], "nothing declares a page, so there is nothing to cross to"
    assert _client().get("/plugin-pages").json() == {"pages": []}

    named = {
        **pack,
        "plugins": {
            "supervisor": {"page": {"label": "Supervisor", "path": "/supervisor"}},
            "ledger": {"page": {"label": "Ledger", "path": "/ledger"}},
        },
    }
    assert plugin_pages(named) == [
        {"plugin": "ledger", "label": "Ledger", "path": "/ledger"},
        {"plugin": "supervisor", "label": "Supervisor", "path": "/supervisor"},
    ]

    for bad in (
        {"label": "X"},
        {"path": "/x"},
        {"label": "X", "path": "x"},
        {"label": "X", "path": "/x", "extra": 1},
        "x",
    ):
        with pytest.raises(PackError, match="takes label and path"):
            plugin_pages({**pack, "plugins": {"supervisor": {"page": bad}}})


def test_the_cockpit_api_matches_its_pinned_contract():
    import inspect

    from cockpitlib import plugin_api

    pinned = json.load(open(os.path.join(ROOT, "tests", "contract", "cockpit-api.json"), encoding="utf-8"))
    found = {
        name: str(inspect.signature(fn))
        for name, fn in vars(plugin_api).items()
        if not name.startswith("_") and inspect.isfunction(fn) and fn.__module__ == plugin_api.__name__
    }
    assert pinned["api_version"] == plugin_api.API_VERSION and found == pinned["functions"], (
        "a changed signature raises API_VERSION"
    )
    assert callable(plugin_api.halt.write) and callable(plugin_api.halt.clear)
    plugin_api.require(plugin_api.API_VERSION)
    with pytest.raises(CockpitError, match=f"cockpit API {plugin_api.API_VERSION}, not {plugin_api.API_VERSION + 1}"):
        plugin_api.require(plugin_api.API_VERSION + 1)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugin_starts_and_follows_cards_through_cockpits_policy(env, pack_file, monkeypatch, tmp_path):
    import sqlite3

    from cockpitlib import plugin_api
    from cockpitlib.errors import Conflict
    from cockpitlib.kickoff import RELEASE_GO, start
    from cockpitlib.paths import records
    from cockpitlib.plan import show

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert plugin_api.records_root() == records() and plugin_api.plugin_block("absent") == {}
    ticket = f"{pack['tracker']['project']}-505"
    with pytest.raises(CockpitError, match="plan has no decision"):
        plugin_api.start_card("rework", ticket)
    with pytest.raises(CockpitError, match="unknown kickoff policy"):
        plugin_api.start_card("rework", ticket, policy="whenever")
    started = plugin_api.start_card(
        "rework",
        ticket,
        body=f"unit 1 of {pack['name']}",
        policy="release",
        idempotency_key=f"{pack['name']}-505-rework",
        model_override=f"model-{pack['name']}",
    )
    assert started["lane"].startswith("worker") and RELEASE_GO in show(ticket)
    [card] = plugin_api.board_cards(ticket)
    assert card["id"] == started["card_id"] and card["kind"] == "rework" and card["flow"] == "rework"
    assert f"unit 1 of {pack['name']}" in card["body"] and "policy: release" in card["body"]
    with pytest.raises(Conflict, match="already open"):
        plugin_api.start_card("rework", ticket, policy="release")
    plugin_api.halt.write(ticket, f"stop {pack['name']}")
    with pytest.raises(Conflict):
        start(pack, "analyst", ticket=ticket)
    assert plugin_api.halt.clear(ticket)

    plugin_api.comment(started["card_id"], f"note from {pack['name']}", author="ledger")
    plugin_api.block(started["card_id"], f"waiting for {pack['name']} data", pack=pack)
    assert [c["status"] for c in plugin_api.board_cards(ticket)] == ["blocked"]
    plugin_api.unblock(started["card_id"], pack=pack)
    assert [c["status"] for c in plugin_api.board_cards(ticket)] == ["ready"]
    from cockpitlib.kanban import db_path

    db = sqlite3.connect(db_path(pack["board"]))
    assert db.execute("select author, body from task_comments where task_id = ?", (started["card_id"],)).fetchall() == [
        ("ledger", f"note from {pack['name']}")
    ]
    assert plugin_api.runs(started["card_id"]) == []
    db.execute(
        "create table if not exists task_runs (id integer primary key autoincrement, task_id text not null, profile text, "
        "status text not null, started_at integer not null, ended_at integer, outcome text, summary text, metadata text)"
    )
    db.execute(
        "insert into task_runs (task_id, profile, status, started_at, ended_at, outcome, summary, metadata) values "
        "(?, 'worker-1', 'done', 10, 20, 'completed', 'built', ?)",
        (started["card_id"], json.dumps({"claims": {"tests": pack["name"]}})),
    )
    db.execute(
        "insert into task_runs (task_id, profile, status, started_at, metadata) values (?, 'worker-1', 'running', 30, 'not json')",
        (started["card_id"],),
    )
    db.commit()
    db.close()
    first, second = plugin_api.runs(started["card_id"])
    assert (
        first["metadata"] == {"claims": {"tests": pack["name"]}}
        and first["outcome"] == "completed"
        and second["metadata"] == {}
    )
    plugin_api.block(started["card_id"], f"waiting for {pack['name']} sign-off", pack=pack)
    assert plugin_api.answer(started["card_id"], f"carry on, {pack['name']}")["ok"]
    assert [c["status"] for c in plugin_api.board_cards(ticket)] == ["ready"]
    intent = plugin_api.outbox_create(
        ticket,
        "tracker-comment",
        started["card_id"],
        f"summary {pack['name']}",
        {"body": "done"},
        created_by="worker-1",
    )
    assert intent["ticket"] == ticket and intent["created_by"] == "worker-1"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_review_or_test_of_work_the_pipeline_never_planned_starts_and_says_so(env, pack_file, monkeypatch):
    """A colleague's pull request has no plan: its review starts, and its new plan records why. A plan that waits for the
    human's go is still refused, and a rework still needs a plan."""
    from cockpitlib import plugin_api
    from cockpitlib.kickoff import OUTSIDE_GO, _decide_for_outside
    from cockpitlib.plan import decided, plan_path, show

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    outside = f"{pack['tracker']['project']}-606"
    assert not os.path.isfile(plan_path(outside))
    started = plugin_api.start_card("review", outside, pack=pack)
    assert started["lane"].startswith("reviewer") and OUTSIDE_GO in show(outside) and "did not plan" in show(outside)
    from cockpitlib.acts import archive_card

    archive_card(pack, started["card_id"])  # the fixture's one review seat is free again

    waiting = f"{pack['tracker']['project']}-607"
    os.makedirs(os.path.dirname(plan_path(waiting)), exist_ok=True)
    with open(plan_path(waiting), "w", encoding="utf-8") as handle:
        handle.write(f"# Plan {waiting}\n\nthe proposal, before the go\n")
    with pytest.raises(CockpitError, match="plan has no decision"):
        plugin_api.start_card("review", waiting, pack=pack)
    with pytest.raises(CockpitError, match="plan has no decision"):
        plugin_api.start_card("rework", f"{pack['tracker']['project']}-608", pack=pack)
    assert not os.path.isfile(plan_path(f"{pack['tracker']['project']}-608"))

    tested = f"{pack['tracker']['project']}-609"
    _decide_for_outside(tested, "test")
    assert decided(tested) and "this test was kicked off" in show(tested)
    _decide_for_outside(f"{pack['tracker']['project']}-610", "analyst")
    assert not os.path.isfile(plan_path(f"{pack['tracker']['project']}-610"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugin_registers_its_kind_and_mode_in_process_and_bad_ones_are_refused(
    env, pack_file, monkeypatch, tmp_path
):
    import yaml

    from cockpitlib import plugin_api, registry
    from cockpitlib.errors import PackError

    monkeypatch.setattr(registry, "_kinds", {})
    monkeypatch.setattr(registry, "_modes", {})
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    plugin, kind, title, flow, bucket, lane = PLUGIN_MODES[pack["name"]]
    plugin_api.register_card_kind(kind, title, flow=flow, role="analyst", owner=plugin)
    plugin_api.register_kickoff_mode(kind, "analyst", capacity_bucket=bucket, text=f"{plugin} in process", owner=plugin)
    ticket = f"{pack['tracker']['project']}-506"
    started = plugin_api.start_card(kind, ticket)
    assert started["lane"].startswith("analyst") and started["title"] == title.format(ticket=ticket)
    from cockpitlib.kanban import place_card

    other = place_card(pack["board"], f"{pack['tracker']['project']}-507: analyst", "analyst", kind="analyst")
    assert [card["id"] for card in plugin_api.board_cards(ticket)] == [started["card_id"]] != [other]
    assert plugin_api.board_cards(ticket)[0]["flow"] == flow and registry.owned_kinds() == {kind: plugin}
    for bad, message in (
        (("x", "no ticket here"), "card kind x: {title (with {ticket}), flow, role}"),
        (("x", "{ticket}: x", "", "pilot"), "card kind x: role is a seat kind"),
    ):
        with pytest.raises(PackError, match=re.escape(message)):
            plugin_api.register_card_kind(*bad)
    with pytest.raises(PackError, match="lane_kind is one of"):
        plugin_api.register_kickoff_mode("y", "gatekeeper")
    plugged = _plugged(pack_file, tmp_path)
    raw = yaml.safe_load(open(plugged, encoding="utf-8"))
    block = raw["plugins"][plugin]
    for change, message in (
        ({"kickoff_modes": {kind: {"lane": "analyst"}}}, f"kickoff mode {kind}: {{lane_kind"),
        (
            {"kickoff_modes": {"intake": {"lane_kind": "analyst"}}},
            f"plugins.{plugin}.kickoff_modes: intake is cockpit's own",
        ),
        ({"card_kinds": {kind: "a title"}}, f"card kind {kind}: {{title"),
        ({"card_kinds": {kind: {"title": "{ticket}: x", "role": "pilot"}}}, "role is a seat kind"),
    ):
        open(plugged, "w", encoding="utf-8").write(
            yaml.safe_dump(
                {**raw, "kickoff": None, "plugins": {plugin: {**block, **change}}}, sort_keys=False, allow_unicode=True
            )
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(plugged)
    open(plugged, "w", encoding="utf-8").write(yaml.safe_dump({**raw, "plugins": {plugin: ["pages"]}}, sort_keys=False))
    with pytest.raises(PackError, match=re.escape(f"plugins.{plugin} is a mapping")):
        load(plugged)
    validator = os.path.join(os.path.dirname(plugged), "plugins", plugin, "cockpit_pack.py")
    open(validator, "w", encoding="utf-8").write(
        "from cockpitlib.errors import PackError\n\n\ndef validate(block, pack_dir):\n"
        "    raise PackError('the plugin refuses in cockpit\\'s words')\n"
    )
    open(plugged, "w", encoding="utf-8").write(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    with pytest.raises(PackError, match="the plugin refuses in cockpit's words"):
        load(plugged)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_real_ci_failure_on_a_ticket_a_plugin_runs_opens_no_intake_waiting_for_the_human(env, pack_file, monkeypatch):
    """A release supervisor runs its units' tickets and sends their CI fixes itself. Cockpit's CI verdict on one of
    them leaves it there: no intake card holding the intake seat for the human's go. Any other ticket is as before,
    and a plugin that stops refreshing its list gives its tickets back."""
    import time

    from cockpitlib import plugin_api
    from cockpitlib.acts import mark_ci
    from cockpitlib.kanban import board_cards
    from cockpitlib.owners import LAPSE_SECONDS, owner_of

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    owned, other = f"{pack['tracker']['project']}-601", f"{pack['tracker']['project']}-602"
    assert plugin_api.ticket_owner(owned) == ""
    assert (
        plugin_api.own_tickets("supervisor", [owned, owned, " "]) == 1
        and plugin_api.ticket_owner(owned) == "supervisor"
    )
    marked = mark_ci(pack, owned, "abc1234def", "real")
    assert marked == {
        "ok": True,
        "verdict": "real",
        "owner": "supervisor",
        "card_id": "",
        "waiting": "",
        "created": False,
    }
    assert not [card for card in board_cards(pack["board"]) if card["ticket"] == owned]
    assert mark_ci(pack, other, "abc1234def", "real")["created"] is True, "a ticket no plugin runs: intake, as always"
    assert owner_of(owned, now=time.time() + LAPSE_SECONDS + 1) == "", "a list nobody refreshes lapses"
    plugin_api.own_tickets("supervisor", [])
    assert plugin_api.ticket_owner(owned) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugins_prs_get_a_merge_row_when_ready_and_their_tickets_a_done_ack_after_the_merge(
    env, pack_file, monkeypatch
):
    """A release supervisor registers its tickets' PRs. The PR watch follows them; once the plugin marks one ready, the
    human gets a merge row (one per PR, every ticket it carries); after the merge each ticket gets its ticket-done row,
    which the plugin can acknowledge for a whole release at once."""
    from cockpitlib import plugin_api
    from cockpitlib.outbox import create
    from cockpitlib.outbox import load as load_intent
    from cockpitlib.pr_watch import merge_ready, record_path, watched

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    one, two = f"{pack['tracker']['project']}-701", f"{pack['tracker']['project']}-702"
    prs = [
        {"ticket": one, "repo": "orders", "number": 119, "url": "https://x/orders/pull/119", "ready": False},
        {"ticket": two, "repo": "orders", "number": 119, "url": "https://x/orders/pull/119", "ready": False},
        {"ticket": two, "repo": "core", "number": 166, "ready": False},
        {"ticket": "bad"},
    ]
    assert plugin_api.watch_prs("supervisor", prs) == 3
    assert {(one, "orders", 119), (two, "orders", 119), (two, "core", 166)} <= set(watched())
    for ticket, repo, number in ((one, "orders", 119), (two, "orders", 119), (two, "core", 166)):
        os.makedirs(os.path.dirname(record_path(ticket, repo, number)), exist_ok=True)
        json.dump(
            {"repo": repo, "number": number, "state": "open", "title": "the work"},
            open(record_path(ticket, repo, number), "w", encoding="utf-8"),
        )
    assert merge_ready() == [], "not ready yet: no row"
    plugin_api.watch_prs("supervisor", [{**item, "ready": True} for item in prs[:3]])
    rows = merge_ready()
    assert [(row["repo"], row["number"], row["tickets"]) for row in rows] == [
        ("core", 166, [two]),
        ("orders", 119, [one, two]),
    ]
    assert _client().get("/needs-you").json()["merge_ready"][1]["tickets"] == [one, two]
    json.dump(
        {"repo": "core", "number": 166, "state": "merged", "merged": True},
        open(record_path(two, "core", 166), "w", encoding="utf-8"),
    )
    assert [row["number"] for row in merge_ready()] == [119], "merged: its row leaves"
    # the final stage: their ticket-done rows, acknowledged for the whole release in one go
    done_one = create(pack, one, "ticket-done", "pr-watch", "every PR merged", {"repo": "orders", "number": 119})
    done_two = create(pack, two, "ticket-done", "pr-watch", "every PR merged", {"repo": "orders", "number": 119})
    other = create(
        pack, f"{pack['tracker']['project']}-703", "ticket-done", "pr-watch", "elsewhere", {"repo": "web", "number": 1}
    )
    assert {row["id"] for row in plugin_api.done_waiting([one, two])} == {done_one["id"], done_two["id"]}
    assert sorted(plugin_api.ack_tickets([one, two])) == sorted([done_one["id"], done_two["id"]])
    assert load_intent(done_one["id"])["status"] == "acknowledged" and load_intent(other["id"])["status"] == "pending"
    assert plugin_api.done_waiting([one, two]) == [] and plugin_api.ack_tickets([one, two]) == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_plugin_reads_a_cards_thread_and_decides_held_items_on_the_humans_behalf(env, pack_file, monkeypatch):
    """A plugin answering for the human reads a blocked card's report, lists its tickets' held items, and confirms one
    (endorsed as the plugin, so its scope's auto-publish may send it), sends one back or drops one."""
    from cockpitlib import plugin_api
    from cockpitlib.errors import CockpitError
    from cockpitlib.outbox import create, hold
    from cockpitlib.outbox import load as load_intent

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-801"
    started = plugin_api.start_card("rework", ticket, body="x", policy="release")
    plugin_api.comment(started["card_id"], "## Report\\nthe cause is X", author="analyst")
    plugin_api.block(started["card_id"], "waiting for go", pack=pack)
    thread = plugin_api.card_thread(started["card_id"])
    assert (
        thread["status"] == "blocked"
        and thread["blocked_at"]
        and thread["comments"][-1]["body"].startswith("## Report")
    )
    first = create(pack, ticket, "tracker-comment", started["card_id"], "a note", {"body": "x"})
    second = create(pack, ticket, "tracker-comment", started["card_id"], "another", {"body": "y"})
    for row in (first, second):
        hold(row["id"], "the pushed range has commits by someone@x: confirm they belong", waits="human")
    listed = plugin_api.held_intents([ticket])
    assert {row["id"] for row in listed} == {first["id"], second["id"]} and listed[0]["hold"]["reason"].startswith(
        "the pushed range"
    )
    confirmed = plugin_api.decide_intent(first["id"], "confirm", "both authors are the owner's", by="supervisor-brain")
    assert confirmed["status"] == "endorsed" and confirmed["endorsement"]["by"] == "supervisor-brain"
    assert plugin_api.decide_intent(second["id"], "drop", "superseded", by="supervisor-brain")["status"] == "dropped"
    with pytest.raises(CockpitError, match="only a held item"):
        plugin_api.decide_intent(first["id"], "drop", by="supervisor-brain")
    assert plugin_api.held_intents([ticket]) == [] and load_intent(second["id"])["status"] == "dropped"
    # a held PR into another base (a release PR, a retarget) is the human's alone: listed as protected, refused to a plugin
    repo = pack["repos"]["repos"][0]
    own = repo.get("base") or pack.get("base_branch") or "main"
    release = create(
        pack,
        ticket,
        "open-pr",
        started["card_id"],
        "release PR",
        {"repo": repo["name"], "title": "Release 1.0.0", "head": "elsewhere", "base": f"{own}-release"},
    )
    hold(release["id"], "a PR into another base", waits="human")
    shown = next(row for row in plugin_api.held_intents([ticket]) if row["id"] == release["id"])
    assert shown["protected"] is True and shown["payload"]["base"] == f"{own}-release"
    with pytest.raises(CockpitError, match="only the human confirms it"):
        plugin_api.decide_intent(release["id"], "confirm", by="supervisor-brain")
    assert plugin_api.decide_intent(release["id"], "confirm", by="owner")["status"] == "endorsed"
    # an answered card that cites a PR resumes on another seat of its kind
    from cockpitlib.lane_feed import card as card_view
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings

    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}})
    before = card_view(pack, started["card_id"])["assignee"]
    moved = plugin_api.hand_over_card(started["card_id"])
    assert moved and moved != before and card_view(pack, started["card_id"])["assignee"] == moved
