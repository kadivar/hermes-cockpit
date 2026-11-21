# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""finding_labels is a list of short tags, and a pack that names none has none. A pack that wrote something else
loads and is read as written; doctor says so in a warning, which fails nothing."""

import os
import shutil

import pytest
import yaml

from cockpitlib import doctor, pack_keys, pr_watch
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
STARTER = os.path.join(ROOT, "starter")
NO_TAGS = None  # a pack with no tags is read by a pattern no line matches


def _with(pack_file, tmp_path, value) -> dict:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    data = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    data["finding_labels"] = value
    (folder / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load(str(folder / "pack.yaml"))


def _tags(pack):
    pattern = pr_watch._tag_pattern(pack)
    if pattern is pr_watch.NO_TAG:
        assert not pattern.search("B: a finding\nQ: a question\n")
        return NO_TAGS
    return pattern.pattern.rsplit("(?:", 2)[1].rsplit(")", 1)[0]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_shipped_pack_names_its_tags_or_has_none_and_neither_is_warned(pack_file):
    pack = load(pack_file)
    named = pack.get("finding_labels")
    assert (pack_file == PACKS[0]) == bool(named), "one fixture pack names its tags and the other has none"
    assert pr_watch.finding_labels_problem(pack) == "" and _tags(pack) == ("|".join(named) if named else NO_TAGS)
    for base, _dirs, files in os.walk(STARTER):
        for name in files:
            if name.endswith(".yaml"):
                assert "finding_labels" not in open(os.path.join(base, name), encoding="utf-8").read()
    assert pr_watch.finding_labels_problem(None) == ""


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "value, tags, said",
    [
        (["B", "Q"], "B|Q", ""),
        ([], NO_TAGS, ""),
        (None, NO_TAGS, ""),
        (
            "B, Q",
            NO_TAGS,
            "is str 'B, Q', not a list, so no tag marks a finding (only a suggestion block asks for work)",
        ),
        ({"B": "blocker"}, NO_TAGS, "is dict"),
        (7, NO_TAGS, "is int '7', not a list"),
        (["B", 7], "B|7", "has an item that is not a tag: '7'"),
        (["B", ""], "B|", "has an item that is not a tag: ''"),
        (["B", " Q"], r"B|\ Q", "has an item that is not a tag: ' Q'"),
        (["a tag far too long to be one"], "skip", "(a tag is a text of 1 to 16 characters"),
    ],
)
def test_a_value_of_another_shape_loads_and_is_read_as_before_and_doctor_says_what_it_is(
    env, pack_file, tmp_path, value, tags, said
):
    pack = _with(pack_file, tmp_path, value)  # it loads, whatever the shape
    if tags != "skip":
        assert _tags(pack) == tags
    problem = pr_watch.finding_labels_problem(pack)
    assert (said in problem and problem != "") if said else problem == ""
    found = [item for item in doctor.findings(pack) if item["id"] == "pack.finding-labels"]
    assert [item["message"] for item in found] == ([f"finding_labels {problem}"] if said else [])
    for item in found:
        assert (
            item["severity"] == "warning"
            and item["subject"] == "finding_labels"
            and "finding_labels: [B, Q]" in item["fix"]
        )
    assert not [line for line in doctor.run(pack) if line.startswith("finding_labels")], (
        "a warning born with the tiers fails nothing"
    )


def test_the_registry_says_what_an_empty_list_means():
    entry = pack_keys.find("finding_labels")
    assert entry["when"] == pack_keys.NOT_LIST and "only a suggestion block asks for work" in entry["doc"]
    assert pack_keys.default_of(entry) == []
    assert (
        pack_keys.defaulted(entry, True, [])
        and pack_keys.defaulted(entry, True, "B")
        and not pack_keys.defaulted(entry, True, ["B"])
    )
    assert doctor.CHECKS["pack.finding-labels"] == {
        "severity": "warning",
        "security": False,
        "born": True,
        "fix": doctor.CHECKS["pack.finding-labels"]["fix"],
    }
