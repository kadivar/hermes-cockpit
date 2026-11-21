# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""tracker.kind jira is Jira's REST API with the pack's two credential variables. It is the kind's one name: both
fixture packs say it, and a pack that says another word for it does not load."""

import os
import shutil

import pytest
import yaml

from cockpitlib import pack_keys, tracker, trackers
from cockpitlib.errors import PackError
from cockpitlib.pack import TRACKER_KINDS, load
from cockpitlib.pack_effective import effective
from tests.support.both_packs import PACKS


def _with_kind(pack_file, tmp_path, kind) -> str:
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / kind / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw["tracker"]["kind"] = kind
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(copied / "pack.yaml")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_that_says_jira_gets_the_tracker_on_jiras_rest_api(pack_file):
    pack = load(pack_file)
    assert yaml.safe_load(open(pack_file, encoding="utf-8"))["tracker"]["kind"] == "jira"
    assert type(tracker.tracker_for(pack, dry_run=True)) is tracker.JiraTracker
    assert tracker.tracker_kind(tracker._config(pack)) == "jira" == effective(pack)["tracker.kind"]


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("kind", ("rest", "Jira", "jira-rest"))
def test_a_pack_that_says_another_word_for_it_does_not_load(pack_file, tmp_path, kind):
    with pytest.raises(PackError, match="tracker.kind is one of connector, jira, command, local, github-issues"):
        load(_with_kind(pack_file, tmp_path, kind))
    with pytest.raises(PackError, match="tracker.kind is one of connector, jira, command, local, github-issues"):
        trackers.implementation(kind)


def test_the_registry_lists_the_kinds_the_loader_takes():
    entry = pack_keys.find("tracker.kind")
    assert entry["example"] == "jira" and set(entry["enum"]) == set(TRACKER_KINDS) == set(trackers.NAMES)
    assert "rest" not in TRACKER_KINDS
