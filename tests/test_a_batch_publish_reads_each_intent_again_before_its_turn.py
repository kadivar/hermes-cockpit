# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit publish --all` holds the rows it read when it started. Publishing one row may publish another row of the same
batch first: a move the tracker only reaches through an earlier move sends that earlier move, from the file. The batch
then reads each row again just before its turn, so the row that already left is not sent twice and is not refused as
changed underneath; a row someone held meanwhile is refused for what it says now."""

import pytest

from cockpitlib.pack import load
from tests.support.both_packs import PACKS


def _two_moves(pack, jira, number: int) -> tuple:
    """Two endorsed moves of one issue, the second only reachable through the first: (issue, first, second)."""
    from cockpitlib.outbox import create, endorse

    ticket = f"{pack['tracker']['project']}-{number}"
    jira.issue(ticket)
    made = []
    for to in ("In Progress", "In Review"):
        row = create(pack, ticket, "tracker-transition", "c", f"move to {to}", {"issue": ticket, "to": to})
        made.append(endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large"))
    return ticket, made[0], made[1]


def _moves_sent(jira, ticket: str) -> int:
    return sum(
        1 for request in jira.requests if "POST" in str(request) and f"/issue/{ticket}/transitions" in str(request)
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_move_published_as_another_moves_first_step_is_not_sent_again_at_its_own_turn(
    env, pack_file, monkeypatch, jira
):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.publish import forge_for, publish_all

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket, first, second = _two_moves(pack, jira, 4101)
    rows = [
        load_intent(second["id"]),
        load_intent(first["id"]),
    ]  # the later move first: it needs the earlier one, and sends it
    for row in rows:
        row["payload"]["after"] = ""  # no pairing: the tracker's own routes decide what goes first
    before = _moves_sent(jira, ticket)
    receipts = publish_all(rows, forge_for(pack), {row["id"]: row["id"] for row in rows}, pack=pack)
    assert [receipt.get("ok") for receipt in receipts] == [True, True], receipts
    assert receipts[0]["output"].startswith(f"after {first['id']}: ")
    assert jira.issues[ticket]["status"] == "In Review"
    assert _moves_sent(jira, ticket) - before == 2, "each move went out once"
    kept = load_intent(first["id"])
    assert kept["status"] == "published" and receipts[1] == kept["receipt"], (
        "the receipt is the one it was published with"
    )
    assert rows[1]["status"] == "published", "the batch's own row says what the file says"
    assert load_intent(second["id"])["status"] == "published"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_row_held_after_the_batch_was_read_is_refused_for_what_it_says_now(env, pack_file, monkeypatch, jira):
    from cockpitlib.intents import load as load_intent
    from cockpitlib.outbox import hold
    from cockpitlib.publish import forge_for, publish_all

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket, first, _second = _two_moves(pack, jira, 4102)
    rows = [load_intent(first["id"])]
    hold(first["id"], "wait")
    receipts = publish_all(rows, forge_for(pack), {first["id"]: first["id"]}, pack=pack)
    assert receipts == [{"ok": False, "error": f"{first['id']} is held, not endorsed", "id": first["id"]}]
    assert jira.issues[ticket]["status"] == "Backlog" and load_intent(first["id"])["status"] == "held"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_row_whose_file_is_gone_is_refused_and_a_row_built_in_memory_is_published_as_given(
    env, pack_file, monkeypatch, jira
):
    import os

    from cockpitlib.intents import load as load_intent
    from cockpitlib.intents import path_of
    from cockpitlib.publish import forge_for, publish_all

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    ticket, first, second = _two_moves(pack, jira, 4103)
    plain = dict(load_intent(first["id"]))  # no file bytes go with it: nothing to compare, it is sent as it is
    assert publish_all([plain], forge_for(pack), {first["id"]: first["id"]}, pack=pack)[0]["ok"]
    assert jira.issues[ticket]["status"] == "In Progress"
    gone = load_intent(second["id"])
    os.remove(path_of(second["id"]))
    receipts = publish_all([gone], forge_for(pack), {second["id"]: second["id"]}, pack=pack)
    assert receipts[0]["ok"] is False and jira.issues[ticket]["status"] == "In Progress"
