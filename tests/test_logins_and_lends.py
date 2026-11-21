# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lane's logins: the vault fills them, a lend is approved once and taken back, and no secret reaches a tool."""

import io
import json
import os
import sys

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, ROOT, _client


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_hermes_login_block_is_answered_once_per_block(env, pack_file):
    """Each block is answered once. A second block of the same kind is Hermes's loop guard: triage, for a human."""
    from cockpitlib.housekeeping import unblock_logins
    from cockpitlib.kanban import BoardWrites, block_reason, board_cards, place_card
    from cockpitlib.paths import watch_dir
    from tests.support.boards import raw

    pack = load(pack_file)
    board = pack["board"]
    reason = f"CREDENTIALS NEEDED · {pack['privileged']['environment']}"

    def block(card, why, kind=None):
        writes = BoardWrites(board)
        writes.block(card, why, kind)
        assert writes.flush() == [True]

    def status(card):
        return {item["id"]: item["status"] for item in board_cards(board)}[card]

    def put(card, value):
        connection = raw(board)
        connection.execute("update tasks set status = ? where id = ?", (value, card))
        connection.commit()
        connection.close()

    card = place_card(board, f"{pack['tracker']['project']}-330: test", "tester-1")
    block(card, reason)
    assert unblock_logins(pack) == "1" and status(card) == "ready"
    put(card, "blocked")
    assert unblock_logins(pack) == "0" and status(card) == "blocked"
    put(card, "ready")
    block(card, f"{reason} · 2FA: no authenticator key stored")
    assert status(card) == "triage"
    assert unblock_logins(pack) == "0"
    reader = raw(board)
    assert block_reason(reader, card).endswith("2FA: no authenticator key stored")
    reader.close()

    other = place_card(board, f"{pack['tracker']['project']}-332: test", "tester-1")
    block(other, f"waiting for {pack['name']}")
    put(other, "ready")
    block(other, reason)
    assert status(other) == "blocked"
    assert unblock_logins(pack) == "1" and status(other) == "ready"

    earlier = place_card(board, f"{pack['tracker']['project']}-331: test", "tester-1")
    block(earlier, reason)
    path = os.path.join(watch_dir(), "login-unblocked.json")
    kept = json.load(open(path, encoding="utf-8"))
    open(path, "w", encoding="utf-8").write(json.dumps(kept + [f"{earlier}#0"]))
    assert unblock_logins(pack) == "0" and status(earlier) == "blocked"
    rewritten = json.load(open(path, encoding="utf-8"))
    assert f"{earlier}#0" not in rewritten and any(key.startswith(f"{earlier}#0#e") for key in rewritten)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_login_block_is_answered_once_per_block(env, pack_file):
    import time

    from cockpitlib.acts import _comment, _open, fail_login
    from cockpitlib.housekeeping import unblock_logins
    from cockpitlib.kanban import board_cards, place_card

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    environment = pack["privileged"]["environment"]
    assert environment != other["privileged"]["environment"]
    ticket = "TASK-8880"
    waiting = place_card(pack["board"], f"{ticket}: test", "tester-1", "ready")
    time.sleep(0.01)
    other_card = place_card(pack["board"], f"{ticket}: other", "tester-1", "blocked")
    reason = f"CREDENTIALS NEEDED · {environment}"
    assert fail_login(pack, waiting, reason)["blocked"] is True
    connection = _open(pack["board"])
    _comment(connection, other_card, "tester-1", "missing the switch")
    connection.commit()
    connection.close()
    assert unblock_logins(pack) == "1"
    cards = {card["id"]: card["status"] for card in board_cards(pack["board"])}
    assert cards[waiting] == "ready"
    assert cards[other_card] == "blocked"
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'blocked' where id = ?", (waiting,))
    connection.commit()
    connection.close()
    assert unblock_logins(pack) == "0"
    assert any(card["id"] == waiting and card["status"] == "blocked" for card in board_cards(pack["board"]))

    connection = _open(pack["board"])
    _comment(connection, waiting, "tester-1", f"{reason} · second step")
    connection.commit()
    connection.close()
    assert unblock_logins(pack) == "1"
    cards = {card["id"]: card["status"] for card in board_cards(pack["board"])}
    assert cards[waiting] == "ready"
    assert cards[other_card] == "blocked"
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'blocked' where id = ?", (waiting,))
    connection.commit()
    connection.close()
    assert unblock_logins(pack) == "0"
    assert {card["id"]: card["status"] for card in board_cards(pack["board"])}[waiting] == "blocked"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_refused_complete_keeps_the_lane_login(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import qa
    from cockpitlib.slots import state_dir, write_ticket

    ticket = f"{pack['tracker']['project']}-1042"
    write_ticket(1, ticket)
    write_ticket(2, f"{other['tracker']['project']}-1")
    for slot, body in ((1, f"stay {pack['name']}"), (2, f"other {other['name']}")):
        folder = state_dir(slot)
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "login.json"), "w", encoding="utf-8").write(body + "\n")
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "blocked")
    with pytest.raises(CockpitError, match="unfinished"):
        answer_card(pack, card, "complete")
    own = os.path.join(state_dir(1), "login.json")
    theirs = os.path.join(state_dir(2), "login.json")
    assert open(own, encoding="utf-8").read() == f"stay {pack['name']}\n"
    assert open(theirs, encoding="utf-8").read() == f"other {other['name']}\n"
    shot = os.path.join(qa(), ticket, "evidences")
    os.makedirs(shot, exist_ok=True)
    open(os.path.join(shot, "row.png"), "wb").write(b"png")
    open(os.path.join(qa(), ticket, "test-results.md"), "w", encoding="utf-8").write("1 ✅ evidences/row.png\n")
    open(os.path.join(qa(), ticket, "plan.md"), "w", encoding="utf-8").write("1\n")
    assert answer_card(pack, card, f"complete: proved {pack['name']}")["out"] == "completed"
    assert not os.path.isfile(own)
    assert open(theirs, encoding="utf-8").read() == f"other {other['name']}\n"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_lane_logs_out_of_the_ticket_slot(env, pack_file):
    import time

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["stores"][0]["name"] != other["stores"][0]["name"]
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card
    from cockpitlib.slots import state_dir, write_ticket

    shaped = dict(pack)
    shaped["seats"] = dict(pack["seats"])
    shaped["seats"]["slots"] = 2
    ticket = "TASK-8890"
    write_ticket(2, ticket)
    write_ticket(1, "TASK-1")
    for slot, body in ((1, f"keep {pack['name']}"), (2, f"drop {pack['name']}")):
        folder = state_dir(slot)
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "login.json"), "w", encoding="utf-8").write(body + "\n")
    card = place_card(shaped["board"], f"{ticket}: test", "tester-1", "blocked")
    assert answer_card(shaped, card, "block missing the switch. who: the human")["ok"]
    assert not os.path.isfile(os.path.join(state_dir(2), "login.json"))
    assert open(os.path.join(state_dir(1), "login.json"), encoding="utf-8").read() == f"keep {pack['name']}\n"
    time.sleep(0.01)
    plain = place_card(shaped["board"], "note", "tester-1", "blocked")
    assert answer_card(shaped, plain, "block missing the form. who: the human")["ok"]
    assert not os.path.isfile(os.path.join(state_dir(1), "login.json"))
    from cockpitlib.acts import _slots_holding, handover_human_rows
    from cockpitlib.paths import volumes

    assert _slots_holding("") == []
    os.makedirs(os.path.join(volumes(), "notes"), exist_ok=True)
    os.makedirs(os.path.join(volumes(), "slot-x"), exist_ok=True)
    write_ticket(2, ticket)
    for slot, body in ((1, f"keep {pack['name']}"), (2, f"drop {pack['name']}")):
        open(os.path.join(state_dir(slot), "login.json"), "w", encoding="utf-8").write(body + "\n")
    link = f"https://{pack['name']}.test/row"
    handed = handover_human_rows(
        ticket,
        [
            {"n": 1},
            {"n": 2, "human": True, "links": [link], "steps": ["sign in"]},
        ],
    )
    assert handed["rows"][-1]["logged_out"] is True
    assert handed["rows"][-1]["links"] == [link]
    assert other["name"] not in link
    assert not os.path.isfile(os.path.join(state_dir(2), "login.json"))
    assert open(os.path.join(state_dir(1), "login.json"), encoding="utf-8").read() == f"keep {pack['name']}\n"
    shaped["seats"]["slots"] = 1
    write_ticket(2, ticket)
    write_ticket(1, "TASK-1")
    for slot, body in ((1, f"keep {pack['name']}"), (2, f"drop {pack['name']}")):
        open(os.path.join(state_dir(slot), "login.json"), "w", encoding="utf-8").write(body + "\n")
    time.sleep(0.01)
    narrowed = place_card(shaped["board"], f"{ticket}: test again", "tester-1", "blocked")
    assert answer_card(shaped, narrowed, "block missing the form. who: the human")["ok"]
    assert not os.path.isfile(os.path.join(state_dir(2), "login.json"))
    assert open(os.path.join(state_dir(1), "login.json"), encoding="utf-8").read() == f"keep {pack['name']}\n"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_tool_result_does_not_contain_the_code(env, pack_file, monkeypatch):
    import importlib.util

    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.vault import current_code, scrub_result, store_login
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    staging = yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    email = f"lane@{pack['name']}.test"
    secret = f"secret-{pack['privileged']['label']}"
    seed = "JBSWY3DPEHPK3PXP"
    assert pack["privileged"]["label"] != other["privileged"]["label"]
    assert store_login(origin, email, secret, otp=seed, lane="tester-1") == "vault stored"
    from tests.support.hermes_contract import as_hermes_process

    as_hermes_process(monkeypatch)
    monkeypatch.setattr("time.time", lambda: 1_700_000_000)
    code = current_code(origin, email)
    assert code
    shown = scrub_result(f"tool said {code} and {secret} seed {seed}")
    assert code not in shown and secret not in shown and seed not in shown
    assert scrub_result("") == ""
    spec = importlib.util.spec_from_file_location("cockpit_plugin_scrub", os.path.join(ROOT, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Ctx:
        def __init__(self):
            self.hooks = {}

        def register_skill(self, *_args):
            return None

        def register_hook(self, event, fn):
            self.hooks[event] = fn

    ctx = Ctx()
    module.register(ctx)
    from tests.support.hermes_contract import call

    assert call(ctx.hooks["transform_tool_result"], "transform_tool_result", result=f"page {code}") is not None
    assert code not in call(ctx.hooks["transform_tool_result"], "transform_tool_result", result=f"page {code}")
    assert call(ctx.hooks["transform_terminal_output"], "transform_terminal_output", output=f"log {secret}") is not None
    assert secret not in call(
        ctx.hooks["transform_terminal_output"], "transform_terminal_output", output=f"log {secret}"
    )
    assert call(ctx.hooks["transform_tool_result"], "transform_tool_result", result="plain text") is None
    assert call(ctx.hooks["transform_tool_result"], "transform_tool_result", result=None) is None
    assert (
        call(ctx.hooks["pre_tool_call"], "pre_tool_call", tool_name="terminal", args={"command": "git status"}) is None
    )
    from cockpitlib import vault

    monkeypatch.setattr(vault, "_items", lambda: (_ for _ in ()).throw(CockpitError("vault is unreadable")))
    assert scrub_result("kept") == "kept"
    # Locked: the index still masks what it knows, without the key.
    assert secret not in scrub_result(f"log {secret}") and seed not in scrub_result(f"seed {seed}")


@pytest.mark.parametrize("pack_file", PACKS)
def test_automatic_two_factor_submits_without_showing_the_code(env, pack_file, monkeypatch):
    import yaml

    from cockpitlib.vault import current_code, fill_login, store_login
    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    staging = yaml.safe_load(open(os.path.join(os.path.dirname(pack_file), "staging.yaml"), encoding="utf-8"))
    other_staging = yaml.safe_load(
        open(
            os.path.join(os.path.dirname(PACKS[0] if pack["name"] == "bravo" else PACKS[1]), "staging.yaml"),
            encoding="utf-8",
        )
    )
    origin = staging["origins"]["app"]
    assert origin != other_staging["origins"]["app"]
    seal_ephemeral(monkeypatch, str(env["home"]))
    email = f"qa@{pack['name']}.test"
    store_login(origin, email, f"secret-{pack['name']}", otp="JBSWY3DPEHPK3PXP", lane="tester-1")
    store_login(origin, f"plain@{pack['name']}.test", "secret", lane="tester-1")
    code = current_code(origin, email, moment=1_700_000_000)
    filled = fill_login("tester-1", origin, email, 1)
    visible = json.dumps(filled)
    # Hermes's browser_vault fills the password and enters the code; the lane gets the handle, never either.
    assert filled["fill"] == f"browser_vault action=fill handle={filled['handle']}"
    assert filled["code"] == f"browser_vault action=enter_code handle={filled['handle']}"
    assert code not in visible
    assert f"secret-{pack['name']}" not in visible
    plain = fill_login("tester-1", origin, f"plain@{pack['name']}.test", 1)
    assert "code" not in plain and plain["handle"] != filled["handle"]
    from cockpitlib.slots import state_dir

    assert not os.path.exists(os.path.join(state_dir(1), "login.json"))
    assert other["name"] != pack["name"]


def test_lifted_rule_and_two_factor_stay_out_of_the_tool(env, monkeypatch):
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.pack import load
    from cockpitlib.vault import current_code, scrub_result, store_login
    from tests.test_vault import seal_ephemeral

    pack = load(os.environ["COCKPIT_PACK"])
    card = place_card(pack["board"], "TASK-950: test", "tester-1", "blocked")
    with pytest.raises(CockpitError, match="restatement"):
        answer_card(pack, card, "go with changes: allow the row")
    assert any(item["id"] == card and item["status"] == "blocked" for item in board_cards(pack["board"]))
    asked = answer_card(pack, card, "go with changes: path /orders read 1")
    assert asked["ok"] is False and asked["blocked"] is True
    assert asked["text"].startswith("PRIVILEGED LOGIN NEEDED · lab ·")
    assert any(item["id"] == card and item["status"] == "blocked" for item in board_cards(pack["board"]))

    seal_ephemeral(monkeypatch, str(env["home"]))
    import yaml

    origin = yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    email = "qa@example.test"
    store_login(
        origin, email, "pw-lane-77", otp="JBSWY3DPEHPK3PXP", lane="tester-1"
    )  # a lane's login lives in its seat store
    code = current_code(origin, email, moment=1_700_000_000)
    assert code.isdigit() and len(code) == 6
    live = current_code(origin, email)
    from tests.support.hermes_contract import as_hermes_process

    as_hermes_process(monkeypatch)  # the result hook runs inside Hermes, where the seat store's seeds are read
    assert live not in scrub_result(f"tool said {live}") and "pw-lane-77" not in scrub_result("tool said pw-lane-77")
    assert current_code(origin, "missing@example.test") == ""
    # Hermes's own parsing: a bad key is refused; an otpauth link keeps its digits, period, and algorithm.
    with pytest.raises(CockpitError, match="vault: authenticator key must be"):
        store_login(origin, "bad@example.test", "secret", otp="!!!!")
    link = "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP&digits=8&period=60&algorithm=SHA256"
    store_login(origin, "long@example.test", "secret", otp=link)
    import base64
    import hashlib
    import hmac
    import struct

    digest = hmac.new(
        base64.b32decode("JBSWY3DPEHPK3PXP"), struct.pack(">Q", 1_700_000_000 // 60), hashlib.sha256
    ).digest()
    offset = digest[-1] & 0x0F
    expected = str((struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**8).zfill(8)
    assert current_code(origin, "long@example.test", moment=1_700_000_000) == expected


def test_each_lane_fills_only_its_own_origin(env, monkeypatch):
    import yaml

    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import place_card
    from cockpitlib.pack import load
    from cockpitlib.slots import state_dir
    from cockpitlib.vault import fill_login, lane_logins, logout, scrub_result, store_login
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    origins = {}
    for pack_file in PACKS:
        data = load(pack_file)
        staging = yaml.safe_load(open(os.path.join(data["_dir"], "staging.yaml"), encoding="utf-8"))
        origins[data["name"]] = staging["origins"]["app"]
    assert origins["acme"] != origins["bravo"]
    acme = load(PACKS[0])
    bravo = load(PACKS[1])
    assert (
        store_login(origins["acme"], "acme@example.test", "acme-secret", lane="tester-1", pack=acme) == "vault stored"
    )
    assert (
        store_login(origins["bravo"], "bravo@example.test", "bravo-secret", lane="reviewer", pack=bravo)
        == "vault stored"
    )
    emails = lambda lane, origin, pack: [row["email"] for row in lane_logins(lane, origin, pack=pack)]
    assert emails("tester-1", origins["acme"], acme) == ["acme@example.test"]
    assert emails("tester-1", origins["bravo"], bravo) == [] and emails("reviewer", origins["bravo"], bravo) == [
        "bravo@example.test"
    ]
    # A shared login reaches only the seats the pack names as its readers.
    assert store_login(origins["acme"], "shared@acme.test", "shared-secret", pack=acme) == "vault stored"
    assert store_login(origins["bravo"], "shared@north.test", "north-shared", pack=bravo) == "vault stored"
    assert lane_logins("tester-1", origins["acme"], pack=acme)[1]["lane"] == "shared"
    assert emails("reviewer", origins["acme"], acme) == []
    assert "shared@north.test" in emails("tester-1", origins["bravo"], bravo) and "shared@north.test" in emails(
        "reviewer", origins["bravo"], bravo
    )
    store_login(origins["acme"], "shared@acme.test", "shared-secret-2", pack=acme)
    assert emails("tester-1", origins["acme"], acme).count("shared@acme.test") == 1
    # A login no seat owns stays the human's; a foreign origin is not placed at all.
    assert (
        store_login(origins["acme"], "nobody@acme.test", "x-secret", pack=acme)
        == "vault stored for the human: no lane owns this login"
    )
    assert "nobody@acme.test" not in emails("tester-1", origins["acme"], acme)
    with pytest.raises(CockpitError, match="https://elsewhere.test is not a staging or slot origin"):
        store_login("https://elsewhere.test", "x@acme.test", "x", lane="tester-1", pack=acme)
    assert (
        store_login("http://127.0.0.1:8101", "slot@acme.test", "slot-secret", lane="tester-1", pack=acme)
        == "vault stored"
    )
    with pytest.raises(CockpitError, match="no login"):
        fill_login("tester-1", origins["bravo"], "bravo@example.test", 1)
    shared = fill_login("tester-1", origins["bravo"], "shared@north.test", 2, pack=bravo)
    assert (
        shared["email"] == "shared@north.test"
        and shared["origin"] == origins["bravo"]
        and "secret" not in json.dumps(shared)
    )
    filled = fill_login("tester-1", origins["acme"], "acme@example.test", 1)
    assert "acme-secret" not in json.dumps(filled) and filled["handle"].startswith("vault_")
    assert not os.path.exists(os.path.join(state_dir(1), "login.json"))
    assert "acme-secret" not in scrub_result("saw acme-secret")
    # A plaintext copy an older cockpit left beside a slot goes at logout.
    os.makedirs(state_dir(1), exist_ok=True)
    open(os.path.join(state_dir(1), "login.json"), "w", encoding="utf-8").write("{}")
    assert logout(1) == "logged out"
    assert not os.path.isfile(os.path.join(state_dir(1), "login.json"))
    pack = load(PACKS[0])
    card = place_card(pack["board"], "TASK-960: test", "tester-1", "blocked")
    assert answer_card(pack, card, "block missing the row. who: the human")["ok"]
    from cockpitlib.acts import fail_login
    from cockpitlib.kanban import board_cards

    missing = place_card(pack["board"], "TASK-961: test", "tester-1", "ready")
    first = fill_login("tester-1", origins["bravo"], "bravo@example.test", 1, pack=pack, card=missing)
    assert first["blocked"] is True and first["reason"] == "no login for this lane"
    assert any(item["id"] == missing and item["status"] == "blocked" for item in board_cards(pack["board"]))
    again = fill_login("tester-1", origins["bravo"], "bravo@example.test", 1, pack=pack, card=missing)
    assert again["blocked"] is False
    seed = place_card(pack["board"], "TASK-962: test", "tester-1", "ready")
    blocked_seed = fail_login(pack, seed, "2FA: no seed")
    assert blocked_seed["blocked"] is True and blocked_seed["reason"].startswith("2FA:")
    assert fail_login(pack, seed, "2FA: no seed")["blocked"] is False
    rejected = place_card(pack["board"], "TASK-963: test", "tester-1", "ready")
    assert fail_login(pack, rejected, "login rejected")["blocked"] is True
    assert fail_login(pack, rejected, "login rejected")["blocked"] is False
    from cockpitlib.housekeeping import clear_own_session, note_other_session
    from cockpitlib.paths import watch_dir

    own = note_other_session("tester-1", "acme@example.test", "acme@example.test")
    assert own["pending"] is True and own["question"] is False
    assert clear_own_session(pack) == "1"
    assert note_other_session("tester-1", "acme@example.test", "acme@example.test")["once"] is True
    assert clear_own_session(pack) == "0"
    other = note_other_session("tester-1", "other@example.test", "acme@example.test")
    assert other["question"] is True
    assert clear_own_session(pack) == "0"
    questions = json.loads(open(os.path.join(watch_dir(), "session-questions.json"), encoding="utf-8").read())
    assert questions[0]["account"] == "other@example.test"
    watch = watch_dir()
    open(os.path.join(watch, "own-session-once.json"), "w", encoding="utf-8").write("{")
    assert note_other_session("worker-1", "acme@example.test", "acme@example.test")["pending"] is True
    open(os.path.join(watch, "session-questions.json"), "w", encoding="utf-8").write("{")
    assert note_other_session("tester-1", "second@example.test", "acme@example.test")["question"] is True
    open(os.path.join(watch, "own-session.json"), "w", encoding="utf-8").write("[]")
    assert clear_own_session(pack) == "1"
    open(os.path.join(watch, "own-session.json"), "w", encoding="utf-8").write("{")
    assert clear_own_session(pack) == "1"
    open(os.path.join(watch, "own-session-once.json"), "w", encoding="utf-8").write(json.dumps(["tester-1"]))
    open(os.path.join(watch, "own-session.json"), "w", encoding="utf-8").write(
        json.dumps({"lane": "tester-1", "account": "a"})
    )
    assert clear_own_session(pack) == "0"
    open(os.path.join(watch, "own-session-once.json"), "w", encoding="utf-8").write("{")
    open(os.path.join(watch, "own-session.json"), "w", encoding="utf-8").write(
        json.dumps({"lane": "reviewer", "account": "a"})
    )
    assert clear_own_session(pack) == "1"
    from cockpitlib.housekeeping import return_lends

    open(os.path.join(watch, "admin-lends.json"), "w", encoding="utf-8").write(
        json.dumps([{"card": "missing-card", "lane": "tester-1", "at": 1}])
    )
    assert return_lends(pack) == "1"


@pytest.mark.parametrize("pack_file", PACKS)
def test_another_session_on_the_lanes_account_is_cleared_once(env, pack_file, monkeypatch):
    import time

    import yaml

    from cockpitlib.acts import _comment, _open
    from cockpitlib.housekeeping import clear_own_session
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.paths import watch_dir
    from cockpitlib.vault import store_login
    from tests.support.boards import set_body
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    staging = yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    own = f"lane@{pack['name']}.test"
    foreign = f"lane@{other['name']}.test"
    assert own != foreign
    store_login(origin, own, "secret", lane="tester-1", pack=pack)
    assert clear_own_session({"board": "missing-board"}) == "0"
    watch = watch_dir()
    os.makedirs(watch, exist_ok=True)
    open(os.path.join(watch, "session-cleared.json"), "w", encoding="utf-8").write("{")
    open(os.path.join(watch, "session-questions.json"), "w", encoding="utf-8").write("{")

    def status_of(card):
        for item in board_cards(pack["board"]):
            if item["id"] == card:
                return item["status"]
        return ""

    def comment(card, text):
        connection = _open(pack["board"])
        _comment(connection, card, "tester-1", text)
        connection.commit()
        connection.close()

    project = pack["tracker"]["project"]
    quiet = place_card(pack["board"], f"{project}-441: test", "tester-1", "blocked")
    assert clear_own_session(pack) == "0"
    assert status_of(quiet) == "blocked"
    time.sleep(0.01)
    named = place_card(pack["board"], f"{project}-442: test", "tester-1", "blocked")
    comment(named, f"already in another session {own}")
    assert clear_own_session(pack) == "1"
    assert status_of(named) == "ready"
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute("update tasks set status = 'blocked' where id = ?", (named,))
    connection.commit()
    connection.close()
    assert clear_own_session(pack) == "0"
    assert status_of(named) == "blocked"
    time.sleep(0.01)
    stranger = place_card(pack["board"], f"{project}-443: test", "tester-1", "blocked")
    comment(stranger, f"Already in another session {foreign}")
    assert clear_own_session(pack) == "0"
    assert status_of(stranger) == "blocked"
    questions = json.loads(open(os.path.join(watch, "session-questions.json"), encoding="utf-8").read())
    assert {"lane": "tester-1", "account": foreign} in questions
    assert own not in [row.get("account") for row in questions]
    assert clear_own_session(pack) == "0"
    again = json.loads(open(os.path.join(watch, "session-questions.json"), encoding="utf-8").read())
    assert again == questions
    time.sleep(0.01)
    mixed = place_card(pack["board"], f"{project}-447: test", "tester-1", "blocked")
    extra = f"other@{pack['name']}.test"
    assert extra not in (own, foreign)
    comment(mixed, f"already in another session {own} {extra}")
    assert clear_own_session(pack) == "0"
    assert status_of(mixed) == "blocked"
    mixed_questions = json.loads(open(os.path.join(watch, "session-questions.json"), encoding="utf-8").read())
    assert {"lane": "tester-1", "account": extra} in mixed_questions
    assert {"lane": "tester-1", "account": own} not in mixed_questions
    time.sleep(0.01)
    bare = place_card(pack["board"], f"{project}-444: test", "tester-1", "blocked")
    set_body(pack["board"], bare, "already in another session")
    assert clear_own_session(pack) == "1"
    assert status_of(bare) == "ready"
    time.sleep(0.01)
    unnamed = place_card(pack["board"], f"{project}-445: test", "reviewer", "blocked")
    set_body(pack["board"], unnamed, "already in another session")
    assert clear_own_session(pack) == "0"
    assert status_of(unnamed) == "blocked"
    connection = _open(pack["board"])
    columns = {row[1] for row in connection.execute("pragma table_info(tasks)")}
    if "result" not in columns:
        connection.execute("alter table tasks add column result text")
    time.sleep(0.01)
    connection.close()
    reported = place_card(pack["board"], f"{project}-446: test", "tester-1", "blocked")
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute(
        "update tasks set result = ? where id = ?",
        (f"already in another session {own}", reported),
    )
    connection.commit()
    connection.close()
    assert clear_own_session(pack) == "1"
    assert status_of(reported) == "ready"


@pytest.mark.parametrize("pack_file", PACKS)
def test_approve_lends_the_pack_label_not_another_privileged_login(env, pack_file, monkeypatch):
    import yaml

    from cockpitlib.lend import _labelled_login, approve
    from cockpitlib.vault import entry_records, store_login
    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["privileged"]["label"] != other["privileged"]["label"]
    assert _labelled_login([]) == {}
    assert _labelled_login(["skip", {"privileged": True, "email": "plain@test"}])["email"] == "plain@test"
    seal_ephemeral(monkeypatch, str(env["home"]))
    staging = yaml.safe_load(open(os.path.join(os.path.dirname(pack_file), "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    store_login(origin, other["privileged"]["label"], "other-secret", otp="OTHERSEED2", privileged=True)
    store_login(origin, pack["privileged"]["label"], f"secret-{pack['name']}", otp="JBSWY3DPEHPK3PXP", privileged=True)
    assert approve("card-label", "tester-1") == "lent"
    from cockpitlib.lane_vault import items
    from cockpitlib.lanes import profile_dir
    from tests.support.hermes_contract import seat_secret

    assert [item["label"] for item in items("tester-1")] == [f"cockpit lent card-label {pack['privileged']['label']}"]
    lent = seat_secret(profile_dir("tester-1"), f"cockpit lent card-label {pack['privileged']['label']}")
    assert lent["otp_secret"] == "JBSWY3DPEHPK3PXP" and lent["password"] == f"secret-{pack['name']}"
    assert lent["identifier"] != other["privileged"]["label"]
    assert not [item for item, _path in entry_records() if item.get("lent")]
    from cockpitlib.kanban import place_card
    from cockpitlib.lend import _card_lane

    card_id = place_card(pack["board"], f"{pack['tracker']['project']}-1047: test", "tester-1", "blocked")
    assert _card_lane(None, card_id) == ""
    assert _card_lane(pack, "missing") == ""
    assert _card_lane(pack, card_id) == "tester-1"
    posted = _client().post("/privileged-approve", json={"card": card_id})
    assert posted.status_code == 200
    copied = [item for item in items("tester-1") if item["label"].startswith(f"cockpit lent {card_id} ")]
    assert len(copied) == 1
    assert copied[0]["identifier"] == pack["privileged"]["label"] != other["privileged"]["label"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_second_approval_removes_the_previous_lend(env, pack_file, monkeypatch):
    import time

    import yaml

    from cockpitlib.lend import _drop_previous_lend, approve, deny, take_back
    from cockpitlib.pack import policy
    from cockpitlib.vault import _encrypt, _entry_dir, _items, entry_records, login_metadata, sealed_to, store_login
    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    seal_ephemeral(monkeypatch, str(env["home"]))
    _drop_previous_lend("none")
    staging = yaml.safe_load(open(os.path.join(os.path.dirname(pack_file), "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    other_origin = yaml.safe_load(
        open(
            os.path.join(os.path.dirname(PACKS[0] if pack["name"] == "bravo" else PACKS[1]), "staging.yaml"),
            encoding="utf-8",
        )
    )["origins"]["app"]
    assert origin != other_origin
    email = f"admin@{pack['name']}.test"
    assert (
        store_login(origin, email, f"secret-{pack['privileged']['label']}", otp="JBSWY3DPEHPK3PXP", privileged=True)
        == "vault stored"
    )
    scope = policy(pack)["privileged_scope"]
    assert scope == pack["privileged"]["scope"]
    note = os.path.join(_entry_dir(scope), "000.gpg")
    _encrypt(sealed_to(), b"[]", note)
    card = "card-lend"
    from cockpitlib.lane_vault import items

    lent_here = lambda lane: [item for item in items(lane) if item["label"].startswith(f"cockpit lent {card} ")]
    assert approve(card, "tester-1") == "lent"
    assert len(lent_here("tester-1")) == 1
    assert approve(card, "worker-1") == "lent"
    assert lent_here("tester-1") == [] and len(lent_here("worker-1")) == 1
    from cockpitlib.paths import watch_dir

    returned_log = open(os.path.join(watch_dir(), "admin-lends.log"), encoding="utf-8").read()
    assert "RETURN card-lend ← tester-1: replaced" in returned_log
    assert "LEND card-lend → worker-1" in returned_log
    assert other_origin not in returned_log
    assert os.path.isfile(note)
    assert lent_here("worker-1")[0]["origin"] == origin
    assert any(item.get("privileged") and item.get("email") == email for item, _path in entry_records())
    returned = take_back(now=time.time(), status_of=lambda _card: (None, 0))
    assert any(row[2] == "the card is gone" for row in returned)
    assert lent_here("worker-1") == []
    assert any(item.get("privileged") and item.get("email") == email for item, _path in entry_records())
    assert os.path.isfile(note)
    assert all(row.get("email") != email for row in login_metadata("worker-1"))
    assert all(row.get("email") != email for row in login_metadata("tester-1"))
    before = len(_items())
    assert deny(card) == "denied"
    assert len(_items()) == before
    _encrypt(sealed_to(), b"not-json", os.path.join(_entry_dir(scope), "bad.gpg"))
    with pytest.raises(CockpitError, match="unreadable"):
        entry_records()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_demo_password_is_set_on_the_slot_copy(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.paths import qa
    from cockpitlib.slots import read_slot_secret

    ticket = "TASK-1013"
    user = f"qa@{pack['name']}.test"
    link = pack["logins"]["shared"][0]["origin"]
    other_link = other["logins"]["shared"][0]["origin"]
    assert link != other_link
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    demo = os.path.join(folder, "demo.json")
    json.dump(
        {
            "account": user,
            "slot": 1,
            "env": pack["name"],
            "links": [link, {"url": link + "/row", "label": "row"}, "", {"label": "skip"}],
            "steps": ["sign in"],
        },
        open(demo, "w", encoding="utf-8"),
    )
    # The pack's own login command sets the demo password on the slot copy; only the human page shows it.
    password, login_user = {"acme": ("demo-acme-1", user), "bravo": ("demo-north-1", f"north-{ticket}")}[pack["name"]]
    posted = _client().post("/demo-login", json={"ticket": ticket, "user": user, "slot": 1})
    assert posted.status_code == 200
    body = posted.json()
    assert body["out"] == "set on the slot"
    assert "password" not in body and password not in json.dumps(body)
    stored = read_slot_secret(1)
    assert stored["password"] == password
    assert stored["email"] == login_user
    assert other["name"] not in stored["email"]
    assert password not in open(demo, encoding="utf-8").read()
    page = _client().get("/demo", params={"ticket": ticket}).json()
    assert page["login"]["password"] == password
    assert page["login"]["username"] == user
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    hidden = _client().get("/demo", params={"ticket": ticket}).json()
    assert hidden["login"]["username"] == user
    assert "password" not in hidden["login"]
    assert password not in json.dumps(hidden)
    assert other["name"] not in json.dumps(hidden["login"])
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    assert page["account"] == user
    assert page["slot"] == 1
    assert page["steps"] == ["sign in"]
    assert page["links"] == [{"url": link, "label": link}, {"url": link + "/row", "label": "row"}]
    assert other_link not in [item["url"] for item in page["links"]]
    assert any(app["name"] == "app" and app["url"] == link and app["up"] is False for app in page["apps"])
    assert "slot-local" not in open(demo, encoding="utf-8").read()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_lane_writes_the_demo_record_without_a_secret(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.paths import qa
    from cockpitlib.slots import read_slot_secret

    ticket = f"{pack['tracker']['project']}-1034"
    secret = f"secret-{pack['privileged']['label']}"
    account = f"qa@{pack['name']}.test"
    link = pack["logins"]["shared"][0]["origin"]
    assert _client().post("/demo", json={"env": pack["name"]}).status_code == 400
    posted = _client().post(
        "/demo",
        json={
            "ticket": ticket,
            "env": pack["privileged"]["environment"],
            "account": account,
            "links": [link],
            "steps": [f"open {pack['name']}"],
            "password": secret,
            "slot": 1,
        },
    )
    assert posted.status_code == 200
    body = posted.json()
    assert body["record"]["account"] == account
    assert secret not in json.dumps(body)
    assert other["name"] not in json.dumps(body)
    text = open(os.path.join(qa(), ticket, "demo.json"), encoding="utf-8").read()
    assert secret not in text
    assert "password" not in text
    assert other["name"] not in text
    assert pack["privileged"]["environment"] in text
    assert read_slot_secret(1)["password"] == secret
    page = _client().get("/demo", params={"ticket": ticket}).json()
    assert page["login"]["password"] == secret
    assert other["name"] not in page["login"]["password"]
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    hidden = _client().get("/demo", params={"ticket": ticket}).json()
    assert "password" not in hidden["login"]
    assert secret not in json.dumps(hidden)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_lane_types_the_identifier_and_the_vault_fills_the_secret(env, pack_file, monkeypatch):
    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["name"] != other["name"]
    from cockpitlib.slots import state_dir
    from cockpitlib.vault import store_login
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    origin = str(
        yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    ).rstrip("/")
    other_origin = str(
        yaml.safe_load(open(os.path.join(other["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    ).rstrip("/")
    assert origin != other_origin
    secret = f"secret-{pack['privileged']['label']}"
    other_secret = f"secret-{other['privileged']['label']}"
    email = f"lane@{pack['name']}.test"
    other_email = f"lane@{other['name']}.test"
    assert store_login(origin, email, secret, lane="tester-1")
    assert store_login(other_origin, other_email, other_secret, lane="reviewer", pack=other)
    assert _client().post("/login-fill", json={"origin": origin, "email": email}).status_code == 400
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    assert _client().post("/login-fill", json={"email": email}).status_code == 400
    posted = _client().post("/login-fill", json={"origin": origin, "email": email, "slot": 1})
    assert posted.status_code == 200
    assert posted.json()["fill"] == f"browser_vault action=fill handle={posted.json()['handle']}"
    assert secret not in posted.text
    assert other_secret not in posted.text
    assert not os.path.exists(os.path.join(state_dir(1), "login.json"))
    foreign = _client().post("/login-fill", json={"origin": origin, "email": other_email, "slot": 1})
    assert foreign.status_code == 400
    assert other_secret not in foreign.text


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_demo_login_copies_the_vault_secret_onto_the_slot(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.paths import qa
    from cockpitlib.slots import read_slot_secret
    from cockpitlib.vault import store_login
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    origin = pack["logins"]["shared"][0]["origin"]
    other_origin = other["logins"]["shared"][0]["origin"]
    assert origin != other_origin
    user = f"qa@{pack['name']}.test"
    secret = f"secret-{pack['name']}"
    store_login(origin, user, secret)
    store_login(other_origin, user, f"secret-{other['name']}")
    ticket = f"{pack['tracker']['project']}-1014"
    folder = os.path.join(qa(), ticket)
    os.makedirs(folder, exist_ok=True)
    demo = os.path.join(folder, "demo.json")
    json.dump(
        {"account": user, "slot": 1, "env": pack["name"], "links": [], "steps": ["sign in"]},
        open(demo, "w", encoding="utf-8"),
    )
    posted = _client().post("/demo-login", json={"ticket": ticket, "user": user, "slot": 1})
    assert posted.status_code == 200
    assert "password" not in posted.json()
    assert secret not in json.dumps(posted.json())
    stored = read_slot_secret(1)
    assert stored["password"] == secret
    assert other["name"] not in stored["password"]
    assert secret not in open(demo, encoding="utf-8").read()
    page = _client().get("/demo", params={"ticket": ticket}).json()
    assert page["login"]["password"] == secret
    assert other["name"] not in page["login"]["password"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_deny_leaves_the_row_blocked(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["privileged"]["environment"] != other["privileged"]["environment"]
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.lend import deny, inbox_rows, note_block, request_line
    from cockpitlib.paths import watch_dir

    ticket = "TASK-1014"
    card = place_card(pack["board"], f"{ticket}: test", "tester-1", "blocked")
    line = request_line(pack, "open the row", "the value is not on a lane path")
    assert pack["privileged"]["environment"] in line
    assert other["privileged"]["environment"] not in line
    assert note_block(line, card) == "asked"
    assert inbox_rows()
    assert deny(card, pack) == "denied"
    assert inbox_rows() == []
    stayed = [item for item in board_cards(pack["board"]) if item["id"] == card]
    assert stayed and stayed[0]["status"] == "blocked"
    recorded = json.load(open(os.path.join(watch_dir(), "denies.json"), encoding="utf-8"))
    assert recorded[-1]["undo"] == "a new request"
    assert recorded[-1]["environment"] == pack["privileged"]["environment"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_lane_returns_to_its_own_login_after_the_privileged_step(env, pack_file, monkeypatch):
    import time

    import yaml

    from cockpitlib.lend import approve, take_back
    from cockpitlib.vault import login_metadata, store_login
    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    seal_ephemeral(monkeypatch, str(env["home"]))
    staging = yaml.safe_load(open(os.path.join(os.path.dirname(pack_file), "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    assert (
        origin
        != yaml.safe_load(
            open(
                os.path.join(os.path.dirname(PACKS[0] if pack["name"] == "bravo" else PACKS[1]), "staging.yaml"),
                encoding="utf-8",
            )
        )["origins"]["app"]
    )
    own = f"lane@{pack['name']}.test"
    admin = f"admin@{pack['name']}.test"
    assert store_login(origin, own, f"own-{pack['privileged']['label']}", lane="tester-1") == "vault stored"
    assert store_login(origin, admin, f"secret-{pack['privileged']['label']}", privileged=True) == "vault stored"
    from cockpitlib.lane_vault import items
    from cockpitlib.vault import fill_login

    assert fill_login("tester-1", origin, own, 1)["handle"]
    card = "card-step"
    assert approve(card, "tester-1", 1) == "lent"
    # During the step the lane's store holds its own login and the lent one, side by side.
    during = sorted(item["identifier"] for item in items("tester-1"))
    assert during == sorted([own, admin]) and other["name"] not in "".join(during)
    lent = fill_login("tester-1", origin, admin, 1)
    assert lent["handle"] and all(
        row["email"] != admin for row in login_metadata("tester-1") if row["lane"] == "shared"
    )
    returned = take_back(now=time.time(), status_of=lambda _card: ("done", 0))
    assert any(row[0] == card for row in returned)
    assert [item["identifier"] for item in items("tester-1")] == [own]
    with pytest.raises(CockpitError, match="no login for this lane"):
        fill_login("tester-1", origin, admin, 1)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_new_block_takes_the_lend_back(env, pack_file):
    import time

    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["privileged"]["label"] != other["privileged"]["label"]
    from cockpitlib.acts import _comment, _open
    from cockpitlib.housekeeping import return_lends
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import watch_dir

    card = place_card(pack["board"], "TASK-9962: work", "tester-1", "blocked")
    moment = int(time.time())
    connection = _open(pack["board"])
    _comment(connection, card, "human", f"waiting {pack['privileged']['label']}")
    connection.commit()
    connection.close()
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute("update task_comments set created_at = ? where task_id = ?", (moment - 50, card))
    connection.commit()
    connection.close()
    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    lend = {"card": card, "lane": "tester-1", "at": moment, "slot": 1, "previous": {}}
    open(os.path.join(folder, "admin-lends.json"), "w", encoding="utf-8").write(json.dumps([lend]))
    assert return_lends(pack) == "0"
    connection = _open(pack["board"])
    _comment(connection, card, "human", "blocked again")
    connection.commit()
    connection.close()
    from tests.support.boards import raw

    connection = raw(pack["board"])
    connection.execute(
        "update task_comments set created_at = ? where id = (select max(id) from task_comments where task_id = ?)",
        (moment + 5, card),
    )
    connection.commit()
    connection.close()
    assert return_lends(pack) == "1"
    left = json.loads(open(os.path.join(folder, "admin-lends.json"), encoding="utf-8").read())
    assert left == []
    log = open(os.path.join(folder, "admin-lends.log"), encoding="utf-8").read()
    assert "blocked again" in log
    assert other["privileged"]["label"] not in log
    connection = raw(pack["board"])
    connection.execute("update task_comments set created_at = ? where task_id = ?", ("soon", card))
    connection.commit()
    connection.close()
    open(os.path.join(folder, "admin-lends.json"), "w", encoding="utf-8").write(json.dumps([lend]))
    assert return_lends(pack) == "0"
    import sqlite3

    from cockpitlib.kanban import db_path

    bare = dict(pack)
    bare["board"] = f"bare-{pack['name']}"
    path = db_path(bare["board"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fresh = {"card": card, "lane": "tester-1", "at": moment, "slot": 1, "previous": {}}

    def lend_again():
        open(os.path.join(folder, "admin-lends.json"), "w", encoding="utf-8").write(json.dumps([fresh]))

    connection = sqlite3.connect(path)
    connection.execute("create table tasks (id text, title text)")
    connection.execute("insert into tasks values (?, ?)", (card, "t"))
    connection.commit()
    connection.close()
    lend_again()
    return_lends(bare)
    connection = sqlite3.connect(path)
    connection.execute("drop table tasks")
    connection.execute("create table tasks (id text, status text)")
    connection.execute("insert into tasks values (?, 'blocked')", (card,))
    connection.commit()
    connection.close()
    lend_again()
    assert return_lends(bare) == "0"
    connection = sqlite3.connect(path)
    connection.execute("create table task_comments (id integer, task_id text, body text)")
    connection.execute("insert into task_comments values (1, ?, 'note')", (card,))
    connection.commit()
    connection.close()
    lend_again()
    assert return_lends(bare) == "0"
    connection = sqlite3.connect(path)
    connection.execute("drop table task_comments")
    connection.execute("create table task_comments (id integer, task_id text, body text, created_at text)")
    connection.commit()
    connection.close()
    lend_again()
    assert return_lends(bare) == "0"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_missing_seed_blocks_once(env, pack_file, monkeypatch):
    import yaml

    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.slots import state_dir
    from cockpitlib.vault import fill_login, store_login
    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    seal_ephemeral(monkeypatch, str(env["home"]))
    staging = yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))
    other_staging = yaml.safe_load(open(os.path.join(other["_dir"], "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    assert origin != other_staging["origins"]["app"]
    email = f"qa@{pack['name']}.test"
    secret = f"secret-{pack['name']}"
    # Hermes's own parsing refuses a bad authenticator key when it is stored, so nothing is placed.
    with pytest.raises(CockpitError, match="vault: authenticator key must be"):
        store_login(origin, email, secret, otp="!!!!", lane="tester-1")
    card = place_card(pack["board"], "TASK-9960: test", "tester-1", "ready")
    with pytest.raises(CockpitError, match="no login for this lane"):
        fill_login("tester-1", origin, email, 1)
    blocked = fill_login("tester-1", origin, email, 1, pack=pack, card=card)
    visible = json.dumps(blocked)
    assert blocked["blocked"] is True
    assert blocked["reason"] == "no login for this lane"
    assert secret not in visible
    assert any(item["id"] == card and item["status"] == "blocked" for item in board_cards(pack["board"]))
    assert not os.path.isfile(os.path.join(state_dir(1), "login.json"))
    again = fill_login("tester-1", origin, email, 1, pack=pack, card=card)
    assert again["blocked"] is False
    assert secret not in json.dumps(again)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_lane_is_allowed_that_step_only(env, pack_file, monkeypatch):
    import yaml

    from cockpitlib.lend import approve, note_block, request_line, use_step
    from cockpitlib.vault import fill_login, store_login
    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    assert pack["privileged"]["environment"] != other["privileged"]["environment"]
    assert pack["privileged"]["label"] != other["privileged"]["label"]
    seal_ephemeral(monkeypatch, str(env["home"]))
    staging = yaml.safe_load(open(os.path.join(os.path.dirname(pack_file), "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    own = f"lane@{pack['name']}.test"
    admin = f"admin@{pack['name']}.test"
    secret = f"secret-{pack['privileged']['label']}"
    assert store_login(origin, own, f"own-{pack['privileged']['label']}", lane="tester-1") == "vault stored"
    assert store_login(origin, admin, secret, privileged=True) == "vault stored"
    assert fill_login("tester-1", origin, own, 1)["handle"]
    step = f"open the {pack['privileged']['environment']} row"
    other_step = f"open the {other['privileged']['environment']} row"
    assert step != other_step
    card = "card-one-step"
    assert note_block(request_line(pack, step, "the value is not on a lane path"), card) == "asked"
    assert approve(card, "tester-1", 1) == "lent"
    from cockpitlib.lane_vault import items
    from cockpitlib.paths import watch_dir

    held = lambda: sorted(item["identifier"] for item in items("tester-1"))
    assert held() == sorted([own, admin])
    recorded = json.load(open(os.path.join(watch_dir(), "admin-lends.json"), encoding="utf-8"))
    assert recorded[-1]["step"] == step
    assert other["privileged"]["environment"] not in recorded[-1]["step"]
    with pytest.raises(CockpitError, match="not allowed"):
        use_step(card, other_step)
    assert held() == sorted([own, admin])
    refused = _client().post("/privileged-step", json={"card": card, "step": other_step})
    assert refused.status_code == 400
    assert secret not in refused.text
    done = _client().post("/privileged-step", json={"card": card, "step": step})
    assert done.status_code == 200 and done.json()["out"] == "done"
    assert secret not in done.text
    assert held() == [own]
    with pytest.raises(CockpitError, match="already done"):
        use_step(card, step)
    with pytest.raises(CockpitError, match="no privileged lend"):
        use_step("missing-card", step)
    bare = "card-no-step"
    assert approve(bare, "tester-1", 1) == "lent"
    with pytest.raises(CockpitError, match="not allowed"):
        use_step(bare, "")
    with pytest.raises(CockpitError, match="not allowed"):
        use_step(bare, step)


@pytest.mark.parametrize("pack_file", PACKS)
def test_login_unblock_happens_once(env, pack_file):
    import sqlite3

    from cockpitlib.housekeeping import unblock_logins
    from cockpitlib.kanban import db_path
    from cockpitlib.paths import watch_dir

    pack = load(pack_file)
    path = db_path(pack["board"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("create table tasks (id text, title text, status text, result text)")
    connection.execute(
        "insert into tasks (id, title, status, result) values ('login', 'TASK-1: test', 'blocked', 'CREDENTIALS NEEDED · app')"
    )
    connection.execute(
        "insert into tasks (id, title, status, result) values ('other', 'TASK-1: test', 'blocked', 'CREDENTIALS NEEDED · other')"
    )
    connection.commit()
    connection.close()
    assert unblock_logins(pack) == "2"
    connection = sqlite3.connect(path)
    connection.execute("update tasks set status = 'blocked', result = 'CREDENTIALS NEEDED · app' where id = 'login'")
    connection.commit()
    connection.close()
    assert unblock_logins(pack) == "0"
    connection = sqlite3.connect(path)
    login = connection.execute("select status from tasks where id = 'login'").fetchone()
    other = connection.execute("select status from tasks where id = 'other'").fetchone()
    connection.close()
    assert login[0] == "blocked"
    assert other[0] == "ready"
    open(os.path.join(watch_dir(), "login-unblocked.json"), "w", encoding="utf-8").write("{")
    connection = sqlite3.connect(path)
    connection.execute(
        "insert into tasks (id, title, status, result) values ('third', 'TASK-1: test', 'blocked', 'CREDENTIALS NEEDED · third')"
    )
    connection.commit()
    connection.close()
    assert unblock_logins(pack) == "2"
    open(os.path.join(watch_dir(), "login-unblocked.json"), "w", encoding="utf-8").write("{}")
    assert unblock_logins(pack) == "0"
    assert unblock_logins({"board": "missing-board"}) == "0"


@pytest.mark.parametrize("pack_file", PACKS)
def test_vault_export_keeps_four_copies_for_both_fixtures(env, pack_file, monkeypatch):
    import shutil

    import yaml

    from cockpitlib.vault import backup_vault, current_code, login_metadata, restore_vault, store_login
    from tests.test_vault import seal_ephemeral

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.pack import policy

    parsed = policy(pack)
    assert parsed["privileged_scope"] != parsed["login_scope"]
    seal_ephemeral(monkeypatch, str(env["home"]))
    staging = yaml.safe_load(open(os.path.join(os.path.dirname(pack_file), "staging.yaml"), encoding="utf-8"))
    origin = staging["origins"]["app"]
    email = f"qa@{pack['name']}.test"
    admin = f"admin@{pack['name']}.test"
    password = f"secret-{pack['privileged']['label']}"
    seed = "JBSWY3DPEHPK3PXP"
    assert "secret" not in store_login(origin, email, password, otp=seed, lane="tester-1")
    assert store_login(origin, admin, password, otp=seed, privileged=True) == "vault stored"
    from cockpitlib.vault import _entry_paths, _items

    pairs = list(zip(_entry_paths(), _items()))
    lane_path = next(path for path, item in pairs if item.get("email") == email)
    admin_path = next(path for path, item in pairs if item.get("privileged"))
    assert f"{os.sep}scopes{os.sep}{parsed['login_scope']}{os.sep}" in lane_path
    assert f"{os.sep}scopes{os.sep}{parsed['privileged_scope']}{os.sep}" in admin_path
    os.makedirs(os.path.join(str(env["home"]), "vault", "entries"), exist_ok=True)
    assert lane_path in _entry_paths()
    code = current_code(origin, email, moment=1_700_000_000)
    assert len(code) == 6
    assert backup_vault().startswith("vault backup")
    root = os.path.join(str(env["home"]), "backups", "vault")
    first = sorted(os.listdir(root))[0]
    for _ in range(4):
        backup_vault()
    names = sorted(name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name)))
    assert len(names) == 4
    assert first not in names
    assert os.path.realpath(root).startswith(os.path.realpath(str(env["home"])))
    assert not os.path.realpath(root).startswith(os.path.realpath(os.environ["COCKPIT_WORKSPACE"]))
    for dirpath, _dirs, files in os.walk(root):
        assert "vault.key" not in files
        for name in files:
            if name.endswith(".gpg") or name.endswith(".enc"):
                continue
            text = open(os.path.join(dirpath, name), "rb").read()
            assert password.encode() not in text
            assert seed.encode() not in text
    second = os.path.join(str(env["home"]), "second")
    shutil.copytree(root, os.path.join(second, "backups", "vault"))
    monkeypatch.setenv("COCKPIT_HERMES_HOME", second)
    assert restore_vault() == "vault restored"
    meta = login_metadata("tester-1")
    assert any(
        row["origin"] == origin and row["email"] == email and row["two_factor"] is True and row["lane"] == "tester-1"
        for row in meta
    )
    assert all(row["email"] != admin for row in meta)
    assert current_code(origin, email, moment=1_700_000_000) == code
    restored = list(zip(_entry_paths(), _items()))
    assert any(
        item.get("email") == email and f"{os.sep}scopes{os.sep}{parsed['login_scope']}{os.sep}" in path
        for path, item in restored
    )
    assert any(
        item.get("privileged")
        and item.get("email") == admin
        and f"{os.sep}scopes{os.sep}{parsed['privileged_scope']}{os.sep}" in path
        for path, item in restored
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_seat_login_lives_in_its_hermes_store_and_never_leaves_in_a_tool_call(env, pack_file, monkeypatch):
    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib import vault
    from cockpitlib.egress import check_tool
    from cockpitlib.lanes import profile_dir
    from cockpitlib.scrub import index_path, scrub
    from cockpitlib.vault import lane_logins, scrub_result, store_login
    from tests.support.hermes_contract import as_hermes_process
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    origin = yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    secret = f"pw-{pack['name']}-{pack['privileged']['label']}"
    seed = "JBSWY3DPEHPK3PXP"
    store_login(origin, f"qa@{pack['name']}.test", secret, otp=seed, lane="tester-1", pack=pack)

    # The seat's own Hermes store holds it; no plaintext copy anywhere; another seat cannot list it.
    store = os.path.join(profile_dir("tester-1"), "vault", "vault.json.enc")
    assert os.path.isfile(store) and secret.encode() not in open(store, "rb").read()
    for dirpath, _dirs, files in os.walk(str(env["root"])):
        for name in files:
            assert secret.encode() not in open(os.path.join(dirpath, name), "rb").read()
    assert lane_logins("reviewer", origin, pack) == []
    index = open(index_path(), encoding="utf-8").read()
    assert secret not in index and seed not in index and oct(os.stat(index_path()).st_mode & 0o777) == "0o600"

    # A tool call that carries it is refused; Hermes's browser_vault, which takes the handle, is not.
    monkeypatch.setenv("COCKPIT_LANE", "tester-1")
    assert (
        check_tool("terminal", {"command": f"curl -u qa:{secret} {origin}"}) == "a secret may not leave in a tool call"
    )
    assert check_tool("browser_type", {"ref": "e3", "text": secret}) == "a secret may not leave in a tool call"
    assert (
        check_tool("browser_vault", {"action": "fill", "handle": lane_logins("tester-1", origin, pack)[0]["handle"]})
        == ""
    )
    assert check_tool("terminal", {"command": f"echo {secret[:-1]}"}) == ""

    # A result is masked while cockpit's key is locked; the index needs no key.
    monkeypatch.setattr(vault, "_items", lambda: (_ for _ in ()).throw(CockpitError("locked")))
    assert scrub_result(f"page shows {secret} and {seed}") == "page shows [secret] and [secret]"

    # A login a lane saves itself through Hermes's save_login is masked from the next call on.
    as_hermes_process(monkeypatch)
    from agent.vault_store import VaultStore

    saved = f"own-{pack['name']}-pass"
    VaultStore(base_dir=os.path.join(profile_dir("tester-1"), "vault")).add_item(
        "login",
        "saved by the lane",
        {"identifier_type": "email", "identifier": "me@x.test", "password": saved},
        origin=origin,
    )
    assert scrub(f"typed {saved}") == "typed [secret]"
    assert check_tool("terminal", {"command": f"echo {saved}"}) == "a secret may not leave in a tool call"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_vault_audit_finds_and_fixes_what_cockpit_did_not_place(env, pack_file, monkeypatch, capsys):
    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.housekeeping import staging_audit
    from cockpitlib.lane_vault import audit, items, label
    from cockpitlib.lanes import profile_dir
    from cockpitlib.vault import store_login
    from tests.support.hermes_contract import as_hermes_process
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    origin = yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]
    shared = next(row for row in pack["logins"]["shared"])
    store_login(origin, f"qa@{pack['name']}.test", "own-secret-1", lane="tester-1", pack=pack)
    store_login(shared["origin"], shared["email"], "shared-secret-1", pack=pack)
    assert audit(pack) == [] and staging_audit(pack) == "0"

    # Plant what cockpit would not: a duplicate, a login it never placed, and one for a foreign origin.
    as_hermes_process(monkeypatch)
    from agent.vault_store import VaultStore

    store = VaultStore(base_dir=os.path.join(profile_dir("tester-1"), "vault"))
    secret = lambda word: {
        "identifier_type": "email",
        "identifier": f"{word}@{pack['name']}.test",
        "password": f"{word}-secret",
    }
    store.add_item(
        "login",
        label("lane", f"qa@{pack['name']}.test"),
        {**secret("qa"), "identifier": f"qa@{pack['name']}.test"},
        origin=origin,
    )
    store.add_item("login", label("lane", f"ghost@{pack['name']}.test"), secret("ghost"), origin=origin)
    store.add_item("login", "saved by the lane", secret("away"), origin="https://elsewhere.test")
    found = audit(pack)
    assert f"duplicate: tester-1 {origin} qa@{pack['name']}.test" in found
    assert f"not placed by cockpit: tester-1 {origin} ghost@{pack['name']}.test" in found
    assert "foreign origin: tester-1 https://elsewhere.test away@" + pack["name"] + ".test" in found
    with pytest.raises(CockpitError, match="vault audit: 3 findings"):
        staging_audit(pack)
    assert main(["vault", "audit"]) == 1
    assert main(["vault", "audit", "--fix"]) == 0
    assert "vault audit: clean" in capsys.readouterr().out
    assert sorted(item["identifier"] for item in items("tester-1")) == sorted(
        [f"qa@{pack['name']}.test", shared["email"]]
    )
    assert staging_audit(pack) == "0"

    # The credentials form names its lane, or the card's.
    from cockpitlib.kanban import place_card

    refused = _client().post("/staging-credentials", json={"email": "new@x.test", "password": "pw-123456"})
    assert refused.status_code == 400 and "name the lane that owns this login" in refused.text
    card = place_card(pack["board"], f"{pack['tracker']['project']}-95: test", "tester-1", "blocked")
    stored = _client().post("/staging-credentials", json={"id": card, "email": "new@x.test", "password": "pw-123456"})
    assert stored.status_code == 200 and "new@x.test" in [item["identifier"] for item in items("tester-1")]


# Each fixture's manifest: an account per seat it is meant for, and one renewal window.
ACCOUNTS = {
    "acme": {"owned": ("qa-one@acme.test", ["tester-1"]), "shared": ("desk@acme.test", ["reviewer"]), "renew_days": 30},
    "bravo": {"shared": ("north-qa@north.test", ["analyst", "tester-1"]), "renew_days": 14},
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_staging_accounts_are_created_placed_verified_and_renewed(env, pack_file, monkeypatch, capsys):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    own = ACCOUNTS[pack["name"]]
    from cockpitlib import accounts
    from cockpitlib.lane_vault import items, place
    from cockpitlib.lanes import profile_dir
    from tests.support.hermes_contract import seat_secret
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    declared = [own[kind] for kind in ("owned", "shared") if kind in own]
    assert accounts.plan(pack) == [f"add {who} for {', '.join(seats)}" for who, seats in declared]
    assert main(["vault", "accounts", "apply"]) == 0
    out = capsys.readouterr().out
    assert (
        all(f"added {who}" in out for who, _seats in declared)
        and "password" not in out
        and pack["name"] + "-" not in out
    )
    assert accounts.verify(pack) == [] and main(["vault", "accounts", "verify"]) == 0
    assert accounts.plan(pack) == [f"ok {who}" for who, _seats in declared]
    # A placement that went missing is planned, named by verify, and put back by apply.
    from cockpitlib.lane_vault import remove

    first, first_seats = declared[0]
    gone = next(item for item in items(first_seats[0]) if item["identifier"] == first)
    remove(first_seats[0], gone["id"])
    assert accounts.plan(pack)[0] == f"place {first} for {', '.join(first_seats)}"
    assert f"missing on {first_seats[0]}: {first}" in accounts.verify(pack)
    assert accounts.apply(pack) == [f"placed {first}"] and accounts.verify(pack) == []

    # A reader seat sees only the accounts shared with it.
    from cockpitlib.lanes import seats_from

    every = [lane for names in seats_from(pack).values() for lane in names]
    for lane in every:
        meant = sorted(who for who, seats in declared if lane in seats)
        assert sorted(item["identifier"] for item in items(lane)) == meant, lane

    # Renewal waits for its window, then gives every holder the new password.
    who, seats = declared[0]
    label = f"cockpit {'lane' if 'owned' in own else 'shared'} {who}"
    before = seat_secret(profile_dir(seats[0]), label)["password"]
    assert accounts.renew(pack) == ["nothing due"]
    later = time.time() + (own["renew_days"] + 1) * 86400
    assert accounts.plan(pack, now=later)[0] == f"renew {who}"
    assert accounts.renew(pack, now=later)[0] == f"renewed {who}"
    for lane in seats:
        assert seat_secret(profile_dir(lane), label)["password"] not in (before, "")
    assert main(["vault", "accounts", "renew", "--force"]) == 0
    assert main(["vault", "accounts", "list"]) == 0 and who in capsys.readouterr().out

    # A placement nobody declared is found.
    stray = next(lane for lane in every if lane not in seats)
    origin = next(row["origin"] for row in accounts.manifest(pack)["accounts"] if row["identifier"] == who)
    place(stray, origin, who, "pw-stray-1", kind="shared")
    assert f"extra on {stray}: {who}" in accounts.verify(pack)
    assert main(["vault", "accounts", "verify"]) == 1

    # The human's own privileged login, from stdin; it never reaches a seat.
    monkeypatch.setattr(sys, "stdin", io.StringIO("human-pw-77\n\n"))
    assert main(["vault", "human-add", "https://app.example.test", f"boss@{pack['name']}.test"]) == 0
    assert all(item["identifier"] != f"boss@{pack['name']}.test" for lane in every for item in items(lane))
    assert main(["vault", "accounts", "nope"]) == 2
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["vault", "human-add", "https://app.example.test", "x@x.test"]) == 2
    assert main(["vault", "human-add", "https://app.example.test"]) == 2


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_failed_account_command_stores_nothing_and_shows_no_secret(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    pack = load(pack_file)
    from cockpitlib import accounts
    from tests.test_vault import seal_ephemeral

    seal_ephemeral(monkeypatch, str(env["home"]))
    copied = tmp_path / "packs" / pack["name"]
    shutil.copytree(os.path.dirname(pack_file), copied)
    data = yaml.safe_load((copied / "accounts.yaml").read_text(encoding="utf-8"))
    script = copied / "bin" / "broken"
    script.write_text('#!/bin/sh\necho \'{"password": "leaked-pw"\' ; echo nope >&2; exit 4\n', encoding="utf-8")
    script.chmod(0o755)
    data["command"] = ["bin/broken"]
    (copied / "accounts.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    broken = load(str(copied / "pack.yaml"))
    with pytest.raises(CockpitError) as caught:
        accounts.apply(broken)
    assert "exit 4 nope" in str(caught.value) and "leaked-pw" not in str(caught.value)
    assert accounts.verify(broken)[0].startswith("not created: ")
    for answer, message in (("not json", "printed no JSON"), ('{"user": "x"}', "printed no password")):
        script.write_text(f"#!/bin/sh\necho '{answer}'\n", encoding="utf-8")
        with pytest.raises(CockpitError, match=message):
            accounts.apply(broken)
    seedless = dict(data["accounts"][0], totp=True)
    script.write_text('#!/bin/sh\necho \'{"password": "pw-1234567"}\'\n', encoding="utf-8")
    with pytest.raises(CockpitError, match="printed no seed"):
        accounts._run_command(broken, "create", seedless)
    data["command"] = []
    (copied / "accounts.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(CockpitError, match="names no command"):
        accounts.apply(load(str(copied / "pack.yaml")))


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_unreachable_lift_asks_for_the_privileged_login(env, pack_file, monkeypatch):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.acts import answer_card
    from cockpitlib.kanban import board_cards, place_card
    from cockpitlib.lend import inbox_rows
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import accept_block, lane_reaches, named_path

    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    environment = pack["privileged"]["environment"]
    assert environment and environment != other["privileged"]["environment"]
    assert pack["privileged"]["label"] != other["privileged"]["label"]
    with pytest.raises(CockpitError, match="undo"):
        accept_block("missing the switch. who: the human step: open it")
    assert "undo:" in accept_block("missing the switch. who: the human step: open it undo: close it")
    assert named_path("go with changes: path: qa/TASK-970/state read open") == "qa/TASK-970/state"
    assert named_path("go with changes: path, read 1") == ""
    from cockpitlib.test_flow import expected_read, require_restatement

    assert (
        expected_read("go with changes: path: qa/TASK-970/state read open") == "open"
        and expected_read("go with changes") == ""
    )
    assert (
        require_restatement("go with changes: rerun the failed rows", "as said") == "as said"
        and require_restatement("go with changes: rerun", "") == ""
    )
    scratch = str(env["root"] / "scratch")
    os.makedirs(scratch, exist_ok=True)
    copied = dict(pack)
    copied["scratch"] = scratch
    assert lane_reaches(copied, os.path.join(scratch, "value")) is True
    assert lane_reaches(pack, "") is False
    repo_name = pack["repos"]["repos"][0]["name"]
    other_name = other["repos"]["repos"][0]["name"]
    assert repo_name != other_name
    source = pack["repos"]["repos"][0]["path"]
    if not os.path.isabs(source):
        source = os.path.join(os.environ["COCKPIT_ROOT"], source)
    other_source = other["repos"]["repos"][0]["path"]
    if not os.path.isabs(other_source):
        other_source = os.path.join(os.environ["COCKPIT_ROOT"], other_source)
    os.makedirs(source, exist_ok=True)
    os.makedirs(other_source, exist_ok=True)
    from cockpitlib.paths import wt

    os.makedirs(os.path.join(wt(), "TASK-970", repo_name), exist_ok=True)
    held = os.path.join(wt(), "TASK-970", repo_name, f"held-{pack['name']}.txt")
    foreign = os.path.join(other_source, f"foreign-{other['name']}.txt")
    open(held, "w", encoding="utf-8").write("open\n")
    open(foreign, "w", encoding="utf-8").write("open\n")
    assert lane_reaches(pack, held) is True
    assert lane_reaches(pack, foreign) is False
    assert lane_reaches(pack, os.path.join(source, "x")) is False  # a repo's own checkout is not the lane's
    time.sleep(0.01)
    checkout_card = place_card(pack["board"], "TASK-976: test", "tester-1", "blocked")
    reached_checkout = answer_card(pack, checkout_card, f"go with changes: path: {held} read open")
    assert reached_checkout["ok"] is True
    assert environment not in reached_checkout.get("text", "")
    card = place_card(pack["board"], "TASK-970: test", "tester-1", "blocked")
    asked = answer_card(pack, card, "go with changes: path /orders read 1")
    assert asked["ok"] is False and environment in asked["text"]
    assert any(row.get("card") == card for row in inbox_rows())
    assert any(item["id"] == card and item["status"] == "blocked" for item in board_cards(pack["board"]))
    time.sleep(0.01)
    bare = place_card(pack["board"], "TASK-972: test", "tester-1", "blocked")
    bare_ask = answer_card(pack, bare, "go with changes: path, read 1")
    assert "no path to the value" in bare_ask["text"]
    time.sleep(0.01)
    reached = place_card(pack["board"], "TASK-971: test", "tester-1", "blocked")
    folder = os.path.join(qa(), "TASK-971")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, "state")
    open(target, "w", encoding="utf-8").write("open\n")
    done = answer_card(pack, reached, f"go with changes: path: {target} read open")
    assert done["ok"] is True
    assert any(item["id"] == reached and item["status"] == "ready" for item in board_cards(pack["board"]))
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    comments = [
        row[0] for row in connection.execute("select body from task_comments where task_id = ?", (reached,)).fetchall()
    ]
    connection.close()
    assert comments == [f"path: {target} read open"]
    assert other["name"] not in comments[0]
    time.sleep(0.01)
    missing = place_card(pack["board"], "TASK-973: test", "tester-1", "blocked")
    wrong = os.path.join(folder, "closed")
    open(wrong, "w", encoding="utf-8").write("closed\n")
    held = answer_card(pack, missing, f"go with changes: path: {wrong} read open")
    assert held["ok"] is False and held["text"] == "read back open"
    assert other["privileged"]["environment"] not in held["text"]
    assert any(item["id"] == missing and item["status"] == "blocked" for item in board_cards(pack["board"]))
    time.sleep(0.01)
    absent = place_card(pack["board"], "TASK-974: test", "tester-1", "blocked")
    missing_file = answer_card(pack, absent, f"go with changes: path: {os.path.join(folder, 'missing')} read open")
    assert missing_file["text"] == "read back open"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_rejected_login_blocks_once_in_the_pack_environment(env, pack_file, monkeypatch):
    import time

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.kanban import place_card
    from cockpitlib.vault import block_text, reject_login

    email = f"lane@{pack['name']}.test"
    text = block_text(pack, email, "login rejected")
    assert text.startswith("CREDENTIALS NEEDED · " + pack["privileged"]["environment"])
    assert other["privileged"]["environment"] not in text
    assert "secret" not in text
    card = place_card(pack["board"], f"{pack['tracker']['project']}-1011: test", "tester-1", "ready")
    time.sleep(0.01)
    from cockpitlib.slots import state_dir, write_ticket

    write_ticket(1, f"{pack['tracker']['project']}-1011")
    write_ticket(2, f"{other['tracker']['project']}-9")
    kept_email = f"keep@{other['name']}.test"
    for slot, account in ((1, email), (2, kept_email)):
        folder = state_dir(slot)
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, "login.json"), "w", encoding="utf-8").write(json.dumps({"email": account}))
    first = reject_login(pack, card, email)
    assert first["blocked"] is True
    assert first["reason"] == text
    assert "secret" not in json.dumps(first)
    assert not os.path.isfile(os.path.join(state_dir(1), "login.json"))
    kept = open(os.path.join(state_dir(2), "login.json"), encoding="utf-8").read()
    assert kept_email in kept
    assert pack["name"] not in kept
    assert reject_login(pack, card, email)["blocked"] is False
    assert os.path.isfile(os.path.join(state_dir(2), "login.json"))
    again = place_card(pack["board"], f"{pack['tracker']['project']}-1012: test", "tester-1", "ready")
    posted = _client().post("/login-rejected", json={"card": again, "email": email})
    assert posted.status_code == 200
    assert posted.json()["blocked"] is True
    assert pack["privileged"]["environment"] in posted.json()["reason"]
    assert other["name"] not in posted.json()["reason"]
