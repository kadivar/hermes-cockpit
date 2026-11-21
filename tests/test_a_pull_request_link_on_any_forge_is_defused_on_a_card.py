# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pull-request link in a card comment becomes `repo#n` whatever forge it points at: the built-in forges' own hosts,
the host the pack names (`forge.host`, a self-hosted forge) and the file-backed forge's `local://` links are handled as
a github.com link always was. A link to anything else stays a link."""

import pytest

from cockpitlib import kanban
from cockpitlib.pack import load
from tests.support.both_packs import PACKS


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_link_to_the_packs_own_forge_host_is_defused_like_a_github_one(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    hosted = {**pack, "forge": {**(pack.get("forge") or {}), "host": f"forge.{pack['name']}.example.test"}}
    link = f"https://forge.{pack['name']}.example.test/team/{repo}/pull/41#discussion_r9"
    assert kanban.defuse_pr_links(f"see {link}", hosted) == f"see {repo}#41 (discussion_r9)"
    assert kanban.defuse_pr_links(f"see https://github.com/x/{repo}/pull/7", hosted) == f"see {repo}#7", (
        "the built-in host still counts"
    )
    assert kanban.defuse_pr_links(f"see {link}", pack) == f"see {link}", (
        "a host no forge of this pack lives at is not a forge link"
    )
    assert kanban.defuse_pr_links(f"see {link.replace('/pull/', '/issues/')}", hosted).endswith(
        "/issues/41#discussion_r9"
    )
    assert kanban.defuse_pr_links(
        f"see https://forge.{pack['name']}.example.test.evil.example.test/team/{repo}/pull/41", hosted
    ).startswith("see https://")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_link_of_the_file_backed_forge_is_defused(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    repo = pack["repos"]["repos"][0]["name"]
    assert (
        kanban.defuse_pr_links(f"opened local://{pack['forge']['org']}/{repo}/pull/3 today", pack)
        == f"opened {repo}#3 today"
    )
    assert (
        kanban.defuse_pr_links(f"local://{pack['forge']['org']}/{repo}", pack)
        == f"local://{pack['forge']['org']}/{repo}"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_with_no_pack_given_the_bound_packs_host_is_read_and_a_missing_pack_leaves_the_built_in_hosts(
    bare, pack_file, monkeypatch, tmp_path
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert kanban.defuse_pr_links("https://github.com/x/y/pull/7#a-b and local://x/y/pull/8") == "y#7 (a-b) and y#8"
    assert kanban.defuse_pr_links("") == "" and kanban.defuse_pr_links(None) == ""
    monkeypatch.setenv("COCKPIT_PACK", str(tmp_path / "no-pack.yaml"))
    assert kanban.defuse_pr_links("https://github.com/x/y/pull/7") == "y#7"
    assert kanban.pr_url_pattern({"forge": "not a table"}).search("https://github.com/x/y/pull/7")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_comment_queued_for_a_card_carries_no_forge_link(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    writes = kanban.BoardWrites(load(pack_file)["board"])
    writes.comment("t_1", "cockpit", "opened local://x/api/pull/3 and https://github.com/x/api/pull/4")
    assert writes.ops[-1]["body"] == "opened api#3 and api#4"
    assert kanban.PR_URL.search("https://github.com/x/y/pull/7"), "the older name still reads a github.com link"
