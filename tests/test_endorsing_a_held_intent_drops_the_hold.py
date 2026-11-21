# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Endorsing a held intent is that pass, so the hold does not stay on the record beside it."""

from cockpitlib.intents import load
from cockpitlib.outbox import create, endorse, hold
from cockpitlib.pack import load as load_pack
from tests.support.both_packs import PACKS

TICKET = "TASK-100"


def test_endorsing_a_held_intent_drops_the_hold(bare):
    made = create(load_pack(PACKS[0]), TICKET, "infra-note", "card", "note", {"body": "x"})
    held = hold(made["id"], "wait")
    assert held["status"] == "held" and "hold" in held
    endorsed = endorse(made["id"], "low", "pass", "gatekeeper", "", "")
    assert endorsed["status"] == "endorsed" and endorsed["endorsement"]["notes"] == "pass"
    assert "hold" not in endorsed and "hold" not in load(made["id"])
