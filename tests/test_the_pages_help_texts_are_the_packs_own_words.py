# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Desktop's help texts that name a team's way of working (its review skill, its bump routine) are pack keys
(desktop.hints). The page prints what the /repos route sends; a pack that sets none gets the words the page always
printed, which the page also keeps for a kernel that sends none."""

import json
import os
import shutil

import pytest
import yaml

from cockpitlib import pack_keys
from cockpitlib.errors import PackError
from cockpitlib.pack import DESKTOP_HINTS, desktop_hints, load
from tests.support.both_packs import _client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
PAGE = open(os.path.join(ROOT, "desktop", "src", "lib", "packwords.js"), encoding="utf-8").read()


def _with(pack_file, tmp_path, monkeypatch, hints) -> dict:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    data = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    data["desktop"] = {**(data.get("desktop") or {}), "hints": hints}
    (folder / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(folder / "pack.yaml"))
    return load(str(folder / "pack.yaml"))


def test_the_page_keeps_the_same_words_for_a_kernel_that_sends_none():
    for name, text in DESKTOP_HINTS.items():
        assert f"{json.dumps(name)}: {json.dumps(text, ensure_ascii=False)}" in PAGE, name
        assert "\n" not in text and pack_keys.default_of(pack_keys.find(f"desktop.hints.{name}")) is text
    listed = {
        pack_keys.segments(entry["path"])[-1]
        for entry in pack_keys.ENTRIES
        if entry["path"].startswith("desktop.hints.")
    }
    assert listed == set(DESKTOP_HINTS)
    assert repr(pack_keys.find("desktop.hints.review")["default"]) == "Ref('pack:DESKTOP_HINTS', item='review')"
    # the kernel's own words name no skill of a pack
    assert DESKTOP_HINTS["bumps_tab"] == "Bumps → reviewer"
    assert not any("skill" in text for text in DESKTOP_HINTS.values())


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_that_sets_none_is_sent_the_words_the_page_always_printed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert "hints" not in pack["desktop"] and desktop_hints(pack) == DESKTOP_HINTS == desktop_hints(None)
    assert _client().get("/repos").json()["hints"] == DESKTOP_HINTS


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_packs_own_text_replaces_one_hint_and_leaves_the_others(env, pack_file, tmp_path, monkeypatch):
    pack = _with(
        pack_file,
        tmp_path,
        monkeypatch,
        {"review": "The reviewer reviews each pull request.", "bumps": None, "rereview": ""},
    )
    wanted = {**DESKTOP_HINTS, "review": "The reviewer reviews each pull request."}
    assert (
        desktop_hints(pack) == wanted
        and pack["desktop"]["hints"]["review"] == "The reviewer reviews each pull request."
    )
    assert _client().get("/repos").json()["hints"] == wanted
    for name in DESKTOP_HINTS:  # the registry's rule for an unset key is the reader's
        entry = pack_keys.find(f"desktop.hints.{name}")
        for value in (None, "", "Mine."):
            resolved = pack_keys.default_of(entry) if pack_keys.defaulted(entry, True, value) else value
            assert desktop_hints({"desktop": {"hints": {name: value}}})[name] == resolved


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "hints, said",
    [
        (
            ["review"],
            "desktop.hints takes bumps_tab, review, bumps, rereview, bumps_start, each a help text of the pages",
        ),
        ({"reviews": "x"}, "desktop.hints takes bumps_tab, review, bumps, rereview, bumps_start"),
        ({"review": 7}, "desktop.hints.review is one line of text of at most 600 characters"),
        ({"bumps": "two\nlines"}, "desktop.hints.bumps is one line of text"),
        ({"rereview": "x" * 601}, "desktop.hints.rereview is one line of text of at most 600 characters"),
    ],
)
def test_a_hint_of_the_wrong_shape_is_refused_with_the_right_one(pack_file, tmp_path, monkeypatch, hints, said):
    with pytest.raises(PackError) as refused:
        _with(pack_file, tmp_path, monkeypatch, hints)
    assert said in str(refused.value)
