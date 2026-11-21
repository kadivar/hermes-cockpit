# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Live page lists a ticket's lanes in the order of the pack's own seats, which the job stream sends: by kind, each
kind's seats by number. A pack whose seats are the ones the page once listed by name gets the same order; a pack with
more seats gets them in their place and no longer at the end."""

import os

import pytest

from cockpitlib import lanes
from cockpitlib.lane_feed import job_stream
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
# The list the page had, without the three names that are no seat of a pack (two Hermes profiles and a session label).
ONCE = [
    "intake",
    "worker-1",
    "worker-2",
    "worker-3",
    "tester-1",
    "tester-2",
    "tester-3",
    "reviewer",
    "gatekeeper",
    "analyst",
    "advisor",
]


def _seated(pack, slots=3, intake=1, reviewer=1, analyst=1, advisor=True) -> dict:
    made = {**pack, "seats": {"slots": slots, "intake": intake, "reviewer": reviewer, "analyst": analyst}}
    made["advisor"] = {"checkpoints": {"C0": {"answers": ["APPROVED"]}}} if advisor else {}
    return made


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_seats_the_page_once_listed_by_name_come_in_the_same_order(pack_file):
    pack = _seated(load(pack_file))
    assert lanes.live_order(pack) == ONCE
    assert lanes.live_order(_seated(pack, advisor=False)) == ONCE[:-1]
    assert lanes.LIVE_KINDS == ("intake", "worker", "tester", "reviewer", "gatekeeper", "analyst", "advisor")
    assert set(lanes.LIVE_KINDS) == set(__import__("cockpitlib.pack", fromlist=["ROLES"]).ROLES)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_with_more_seats_gets_each_in_its_place(pack_file):
    pack = _seated(load(pack_file), slots=5, intake=2, reviewer=3, analyst=2)
    assert lanes.live_order(pack) == [
        "intake",
        "intake-2",
        *(f"worker-{n}" for n in range(1, 6)),
        *(f"tester-{n}" for n in range(1, 6)),
        "reviewer",
        "reviewer-2",
        "reviewer-3",
        "gatekeeper",
        "analyst",
        "analyst-2",
        "advisor",
    ]
    assert lanes.live_order(_seated(pack, slots=0, advisor=False)) == ["intake", "reviewer", "gatekeeper", "analyst"]
    assert lanes.live_order(None) == [] == lanes.live_order({})


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_job_stream_sends_the_seats_in_force_in_that_order(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    found = job_stream(pack, "TASK-100")
    from cockpitlib.settings import load as settings

    in_force = lanes.seats_from(pack, settings(pack)["seats"])
    assert found["lane_order"] == [lane for kind in lanes.LIVE_KINDS for lane in in_force.get(kind) or []] != []
    assert found["lanes"] == [] or set(found) >= {
        "lanes",
        "lane_order",
    }  # the lanes that spoke are sent as before, beside the order


@pytest.mark.parametrize("pack_file", PACKS)
def test_without_a_workspace_the_packs_own_counts_are_the_seats(pack_file, monkeypatch):
    from cockpitlib import settings
    from cockpitlib.errors import CockpitError

    pack = load(pack_file)

    def no_workspace(pack):
        raise CockpitError("no workspace")

    monkeypatch.setattr(settings, "load", no_workspace)
    own = lanes.seats_from(pack)
    assert lanes.live_order(pack) == [lane for kind in lanes.LIVE_KINDS for lane in own.get(kind) or []]
