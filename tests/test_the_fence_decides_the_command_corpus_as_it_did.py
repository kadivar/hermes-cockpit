# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every command of the replay's corpus gets, from each seat's fence, the decision it got before the forge seam.

The forge CLI's deny rules come from the forge implementations now, as a union over every built-in forge. This pins
what the fence said for each line of scripts/replay_support/commands.txt, for each seat of both fixture packs, when the
rules were still spelled in egress.py: a rule that moved must still refuse what it refused and allow what it allowed,
with the same words. A corpus line is only ever appended, so a new line adds a decision and changes none.

To pin a new corpus line (after reading its decisions): FENCE_CORPUS_WRITE=1 scripts/test tests/<this file>
"""

import json
import os
import sys

import pytest

from tests.support.both_packs import PACKS, ROOT

SUPPORT = os.path.join(ROOT, "scripts", "replay_support")
PINNED = os.path.join(ROOT, "tests", "contract", "fence-corpus.json")
SEATS = (
    ("human", ""),
    ("worker", "worker-1"),
    ("tester", "tester-1"),
    ("reviewer", "reviewer"),
    ("intake", "intake"),
    ("analyst", "analyst"),
    ("gatekeeper", "gatekeeper"),
)


def _decisions(pack_file: str, lane: str, made: dict, monkeypatch) -> dict:
    from cockpitlib import egress

    sys.path.insert(0, SUPPORT)
    try:
        import driver
    finally:
        sys.path.remove(SUPPORT)
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    if lane:
        monkeypatch.setenv("COCKPIT_LANE", lane)
        monkeypatch.delenv("COCKPIT_HUMAN", raising=False)
    job = {
        "pack": pack_file,
        "commands": os.path.join(SUPPORT, "commands.txt"),
        "env": {
            name: os.environ[name]
            for name in ("COCKPIT_WORKSPACE", "COCKPIT_HERMES_HOME", "COCKPIT_WT", "COCKPIT_VOLUMES")
        },
    }
    places = sorted(
        (
            (os.path.realpath(str(made["workspace"].parent)), "<tmp>"),
            (str(made["workspace"].parent), "<tmp>"),
            (ROOT, "<plugin>"),
        ),
        key=lambda pair: -len(pair[0]),
    )

    def plain(text: str) -> str:
        for place, name in places:
            text = text.replace(place, name)
        return text

    return {
        key: plain(egress.explained(egress.check_tool("terminal", {"command": command})))
        for key, command in driver.corpus(job)
    }


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("seat,lane", SEATS)
def test_a_seat_gets_the_pinned_decision_for_every_corpus_command(bare, pack_file, seat, lane, monkeypatch):
    name = os.path.basename(os.path.dirname(pack_file))
    found = _decisions(pack_file, lane, bare, monkeypatch)
    pinned = json.load(open(PINNED, encoding="utf-8")) if os.path.isfile(PINNED) else {}
    if os.environ.get("FENCE_CORPUS_WRITE"):
        pinned.setdefault(name, {})[seat] = found
        with open(PINNED, "w", encoding="utf-8") as handle:
            json.dump(pinned, handle, indent=1, sort_keys=True)
            handle.write("\n")
    want = pinned[name][seat]
    assert len(found) >= 100
    changed = {key: (want.get(key), said) for key, said in found.items() if key in want and want[key] != said}
    assert changed == {}, "the fence decides a corpus command differently than it did"
    assert sorted(set(want) - set(found)) == [], "a pinned corpus line is gone: lines are only appended"
    assert sorted(set(found) - set(want)) == [], (
        "a new corpus line has no pinned decision: read it, then pin it (FENCE_CORPUS_WRITE=1)"
    )


def test_the_forge_cli_writes_are_refused_for_a_lane_and_its_reads_are_not():
    pinned = json.load(open(PINNED, encoding="utf-8"))
    for name, seats in pinned.items():
        worker = seats["worker"]
        refused = [said for said in worker.values() if said.startswith("blocked: a denied command (rule \\bgh\\s")]
        assert len(refused) >= 10, name
        assert any(said == "" for said in worker.values()), name
