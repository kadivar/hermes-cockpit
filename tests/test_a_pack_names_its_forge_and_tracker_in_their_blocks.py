# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The forge organisation is forge.org, the tracker's address tracker.url and its project tracker.project: each is
required where it is read, a key of any other name is an unknown key, and a key written with no value is read as an
absent one (the text "None" is never a URL, a project or an organisation)."""

import os
import shutil

import pytest
import yaml

from cockpitlib import pack as packs
from cockpitlib import tracker
from cockpitlib.errors import PackError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS


def _copy(pack_file, tmp_path, change) -> str:
    """A copy of the fixture whose pack.yaml is rewritten by `change`, under a folder named packs as its @anchors need."""
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    change(raw)
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(copied / "pack.yaml")


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("block,field", packs.REQUIRED_IN_A_BLOCK)
def test_a_pack_that_leaves_one_out_does_not_load_and_is_told_which(tmp_path, pack_file, block, field):
    def change(raw):
        raw[block].pop(field)

    with pytest.raises(PackError, match=f"^missing {block}\\.{field}$"):
        load(_copy(pack_file, tmp_path, change))


@pytest.mark.parametrize("block,field", (("forge", "org"), ("tracker", "url")))
def test_a_pack_without_the_block_is_told_the_first_key_it_lacks(tmp_path, block, field):
    def change(raw):
        raw.pop(block)

    file = _copy(PACKS[0], tmp_path, change)
    with pytest.raises(PackError, match=f"^missing {block}\\.{field}$"):
        load(file)
    assert packs.problems(file)[0] == f"missing {block}.{field}"


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("name", ("forge_org", "tracker_url", "tracker_project", "org"))
def test_a_top_level_key_of_another_name_is_an_unknown_key(tmp_path, pack_file, name):
    def change(raw):
        raw[name] = "example"

    file = _copy(pack_file, tmp_path, change)
    with pytest.raises(PackError, match=f"^unknown key {name}$"):
        load(file)
    assert packs.problems(file) == [f"unknown key {name}"]


@pytest.mark.parametrize("block", ("forge", "tracker"))
def test_a_block_that_is_not_a_mapping_is_refused_by_its_own_check(tmp_path, block):
    def change(raw):
        raw[block] = ["not", "a", "block"]

    with pytest.raises(PackError, match=f"^{block} "):
        load(_copy(PACKS[0], tmp_path, change))


@pytest.mark.parametrize("pack_file", PACKS)
def test_both_fixture_packs_are_read_where_they_wrote_the_three_values(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    written = yaml.safe_load(open(pack_file, encoding="utf-8"))
    config = tracker._config(pack)
    assert packs.forge_org(pack) == written["forge"]["org"]
    assert packs.tracker_url(pack) == written["tracker"]["url"] == config["url"]
    assert packs.tracker_project(pack) == written["tracker"]["project"] == config["project"]
    assert packs.batch_project(pack) == written["tracker"]["project"]


@pytest.mark.parametrize("empty", (None, ""))
def test_a_value_written_empty_is_empty_and_never_the_text_none(empty):
    config = tracker._config({"tracker": {"url": empty, "project": empty}})
    assert config == {"url": "", "project": ""}
    assert tracker._config({}) == {"url": "", "project": ""} and tracker._config(None) == {"url": "", "project": ""}
    assert packs.forge_org({"forge": {"org": empty}}) == "" and packs.forge_org({"forge": empty}) == ""
    assert packs.tracker_url({"tracker": {"url": empty}}) == "" and packs.tracker_url(None) == ""
    assert packs.tracker_project({"tracker": {"project": empty}}) == "" and packs.tracker_project({}) == ""


def test_a_value_the_pack_gives_is_kept_but_for_the_addresses_last_slash():
    given = {"tracker": {"url": "https://tracker.example.test//", "project": "TASK", "kind": "jira"}}
    assert tracker._config(given) == {"url": "https://tracker.example.test", "project": "TASK", "kind": "jira"}
    assert packs.tracker_url(given) == "https://tracker.example.test//", "the accessor answers what the pack wrote"


def test_a_batch_is_named_under_the_tracker_project_and_under_BATCH_without_one():
    assert packs.batch_project({"tracker": {"project": "TASK"}}) == "TASK"
    assert packs.batch_project({"tracker": {"project": ""}}) == "BATCH" and packs.batch_project(None) == "BATCH"
