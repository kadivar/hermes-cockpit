# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lane is told where a run's screenshots and videos go in the pack's own word for that folder
(testflow.evidence_dir): the soul's {{EVIDENCE}} is filled in when the seat is rendered, for every seat kind."""

import pytest

from cockpitlib import setup, test_flow
from cockpitlib.pack import load
from tests.support.both_packs import PACKS


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_tester_is_told_the_packs_evidence_folder(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    kept = test_flow.evidence_dir(pack)
    soul = setup._soul(pack, "tester-1", "tester")
    assert f"<run>/{kept}/videos/<scenario>-<slug>-repro.mp4" in soul and f"`{kept}/videos/README.md`" in soul
    assert f"into the run's `{kept}/`" in soul
    for lane, kind in (("worker-1", "worker"), ("reviewer", "reviewer"), ("intake", "intake")):
        assert "{{EVIDENCE}}" not in setup._soul(pack, lane, kind)


def test_the_two_fixture_packs_name_two_folders():
    names = {test_flow.evidence_dir(load(pack_file)) for pack_file in PACKS}
    assert len(names) == 2 and test_flow.EVIDENCE_DIR in names
