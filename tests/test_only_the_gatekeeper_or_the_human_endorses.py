# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit outbox endorse` is the gatekeeper's or the human's: another lane is refused, and the endorsement names who
really gave it."""

import os

import pytest

from cockpitlib.cli import main
from cockpitlib.intents import load as load_intent
from cockpitlib.outbox import create
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
LANE = "COCKPIT_LANE"


def _pending(pack, number: int) -> str:
    repo = pack["repos"]["repos"][0]["name"]
    return create(
        pack, f"{pack['tracker']['project']}-{number}", "ci-rerun", "c", "rerun", {"repo": repo, "run_id": 7}
    )["id"]


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "lane", ("worker-1", "tester-1", "reviewer", "intake", "analyst", "advisor", "gatekeeper-2", "Gatekeeper", "human")
)
def test_a_lane_that_is_not_the_gatekeeper_cannot_endorse(env, pack_file, monkeypatch, capsys, lane):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    iid = _pending(load(pack_file), 4101)
    monkeypatch.setenv(LANE, lane)
    assert main(["outbox", "endorse", iid, "low", "looks fine"]) == 1
    assert "endorse is the gatekeeper's or the human's" in capsys.readouterr().err
    kept = load_intent(iid)
    assert kept["status"] == "pending" and "endorsement" not in kept


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_gatekeepers_endorsement_names_the_gatekeeper_and_its_model(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    iid = _pending(pack, 4102)
    monkeypatch.setenv(LANE, "gatekeeper")
    assert main(["outbox", "endorse", iid, "low", "checked"]) == 0
    assert capsys.readouterr().out.strip() == "endorsed"
    provider = pack["providers"][pack["roles"]["gatekeeper"]]
    endorsement = load_intent(iid)["endorsement"]
    assert load_intent(iid)["status"] == "endorsed"
    assert (endorsement["by"], endorsement["provider"], endorsement["model"]) == (
        "gatekeeper",
        provider["hermes_provider"],
        provider["model"],
    )
    assert (endorsement["risk"], endorsement["notes"]) == ("low", "checked")


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_humans_endorsement_names_the_human_and_no_model(env, pack_file, monkeypatch, capsys):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv(LANE, raising=False)
    iid = _pending(load(pack_file), 4103)
    assert main(["outbox", "endorse", iid, "low"]) == 0
    assert capsys.readouterr().out.strip() == "endorsed"
    endorsement = load_intent(iid)["endorsement"]
    assert load_intent(iid)["status"] == "endorsed"
    assert (endorsement["by"], endorsement["provider"], endorsement["model"], endorsement["notes"]) == (
        "human",
        "",
        "",
        "",
    )
