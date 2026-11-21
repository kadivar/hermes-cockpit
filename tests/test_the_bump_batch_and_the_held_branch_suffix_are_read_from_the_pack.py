# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two names are read from the pack. The standup note knows a bump batch by the pack's forge.bump_batch template (and
by the BUMPS- prefix); the diff pane takes the repo's own branch_suffix_when_held off a branch name and, for a repo
that names none, the pack's desktop.diff_held_suffix, which is empty unless the pack names one."""

import os
import shutil

import pytest
import yaml

from cockpitlib import diffs, pack_keys, standup_note
from cockpitlib.errors import PackError
from cockpitlib.kickoff import batch_key
from cockpitlib.pack import load, tracker_project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _copy(pack_file, tmp_path, change, repos=None) -> dict:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    for name, edit in (("pack.yaml", change), ("repos.yaml", repos)):
        if edit is not None:
            data = yaml.safe_load((folder / name).read_text(encoding="utf-8"))
            edit(data)
            (folder / name).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load(str(folder / "pack.yaml"))


def _acts(pack, ticket) -> dict:
    """The acts of one window in which the ticket had a push published and a pull request of ours merged."""
    return (
        {ticket: {"bumps": [{"what": "api#1", "url": "", "at": 1.0}]}}
        if standup_note.is_bumps(pack, ticket)
        else {ticket: {"developed": [{"what": "branch pushed", "url": "", "at": 1.0}]}}
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_whose_template_starts_with_the_old_prefix_reads_as_it_always_did(pack_file, tmp_path):
    pack = _copy(pack_file, tmp_path, lambda data: data["forge"].update(bump_batch="BUMPS-{week}"))
    project = tracker_project(pack)
    for ticket, batch in (
        ("BUMPS-2026W42", True),
        ("BUMPS-anything", True),
        (f"{project}-100", False),
        (f"{project}-BUMPS", False),
        ("", False),
    ):
        assert standup_note.is_bumps(pack, ticket) is batch is ticket.startswith("BUMPS-"), ticket


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_packs_own_batch_ticket_is_a_bump_batch_whatever_its_template(pack_file):
    pack = load(pack_file)
    ticket = batch_key(pack, 0)
    assert not ticket.startswith("BUMPS-") and standup_note.is_bumps(pack, ticket), (
        "before, only the BUMPS- prefix was one"
    )
    assert standup_note.is_bumps(pack, "BUMPS-2026W42"), "the prefix the note always read still is"
    assert not standup_note.is_bumps(pack, f"{tracker_project(pack)}-100")
    lines = standup_note.sections(pack, _acts(pack, ticket), {})
    assert lines[0] == "**Dependency bumps:**" and lines[1].startswith("- [" + ticket + "]("), (
        "its own ticket is a tracker ticket: linked"
    )
    assert (
        standup_note.sections(pack, {"BUMPS-2026W42": {"bumps": [{"what": "api#1", "url": "", "at": 1.0}]}}, {})[1]
        == "- BUMPS-2026W42 — api#1"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_kernels_own_template_names_a_batch_the_note_never_knew(pack_file, tmp_path):
    """Before, no ticket of a pack on the default template ({project}-BUMPS) was ever a bump batch to the note: the
    prefix BUMPS- is not what that template makes. Now its batch is one."""
    pack = _copy(pack_file, tmp_path, lambda data: data["forge"].pop("bump_batch"))
    ticket = batch_key(pack, 0)
    assert ticket == f"{tracker_project(pack)}-BUMPS".upper() and not ticket.startswith(standup_note.BUMPS)
    assert standup_note.is_bumps(pack, ticket) and not standup_note.is_bumps(pack, f"{tracker_project(pack)}-BUMPSX")
    assert standup_note.is_bumps(None, "BATCH-BUMPS") and not standup_note.is_bumps(None, "TASK-100")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_batch_tickets_acts_are_collected_under_bumps_and_it_is_no_open_work(bare, pack_file, monkeypatch):
    import json

    from cockpitlib.paths import qa

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket, plain = batch_key(pack, 0), f"{tracker_project(pack)}-100"
    for key in (ticket, plain):
        os.makedirs(os.path.join(qa(), key, "pr"))
        json.dump(
            {"repo": "api", "number": 5, "merged": True, "merged_at": 50.0, "role": "author", "url": ""},
            open(os.path.join(qa(), key, "pr", "api-5.json"), "w", encoding="utf-8"),
        )
    found = standup_note.collect(0.0, 100.0, pack)
    assert list(found[ticket]) == ["bumps"] and list(found[plain]) == ["merged"]
    monkeypatch.setattr(
        "cockpitlib.kanban.board_cards",
        lambda board, pack=None: [{"ticket": ticket, "flow": "dev"}, {"ticket": plain, "flow": "dev"}],
    )
    assert [row["ticket"] for row in standup_note.open_work(pack)] == [plain]


# ---------- the held-branch suffix ----------


def _repo(pack) -> dict:
    return pack["repos"]["repos"][0]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_repo_that_names_a_suffix_loses_it_once_and_a_published_name_wins(pack_file, tmp_path):
    pack = _copy(pack_file, tmp_path, None, lambda data: data["repos"][0].update(branch_suffix_when_held="-wt"))
    name = _repo(pack)["name"]
    for branch in ("work/x-wt", "work/x", "work/x-wt-wt", "-wt"):
        assert diffs.remote_branch_of(branch, "", pack, name) == (branch[:-3] if branch.endswith("-wt") else branch)
        assert diffs.remote_branch_of(branch) == branch, "with no pack in reach nothing comes off"
    assert diffs.remote_branch_of("work/x-wt", "pub", pack, name) == "pub" == diffs.remote_branch_of("work/x-wt", "pub")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_repo_with_its_own_suffix_loses_that_one_and_no_other(pack_file):
    pack = load(pack_file)
    held = [repo for repo in pack["repos"]["repos"] if repo.get("branch_suffix_when_held")]
    assert held, "each fixture pack has a repo that names a suffix"
    name, suffix = held[0]["name"], held[0]["branch_suffix_when_held"]
    assert suffix != "-wt" and diffs.remote_branch_of("work/x" + suffix, "", pack, name) == "work/x"
    assert diffs.remote_branch_of("work/x-wt", "", pack, name) == "work/x-wt", (
        "the pack's own suffix is not this repo's"
    )
    assert diffs.remote_branch_of("work/x" + suffix) == "work/x" + suffix  # with no pack in reach nothing comes off


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_repo_that_names_no_suffix_loses_the_packs_own_and_none_when_the_pack_names_none(pack_file, tmp_path):
    strip = lambda data: [repo.pop("branch_suffix_when_held", None) for repo in data["repos"]]
    pack = _copy(pack_file, tmp_path / "a", None, strip)
    name = _repo(pack)["name"]
    given = (yaml.safe_load(open(pack_file, encoding="utf-8")).get("desktop") or {}).get("diff_held_suffix")
    assert diffs.held_suffix(pack) == (given or "") and diffs.held_suffix(None) == ""
    assert (pack_file == PACKS[0]) == bool(given), "one fixture pack names a suffix and the other takes none"
    assert (
        diffs.remote_branch_of("work/x" + (given or "-wt"), "", pack, name) == ("work/x" if given else "work/x-wt")
        and diffs.remote_branch_of("work/x-lane", "", pack, name) == "work/x-lane"
    )
    assert diffs.remote_branch_of("work/x" + (given or ""), "", pack, "not-a-repo") == "work/x", (
        "a repo the pack does not list has no suffix of its own"
    )
    own = _copy(
        pack_file, tmp_path / "b", lambda data: data.setdefault("desktop", {}).update(diff_held_suffix=".held"), strip
    )
    assert (
        diffs.remote_branch_of("work/x.held", "", own, name) == "work/x"
        and diffs.remote_branch_of("work/x-wt", "", own, name) == "work/x-wt"
    )
    none = _copy(
        pack_file, tmp_path / "c", lambda data: data.setdefault("desktop", {}).update(diff_held_suffix=""), strip
    )
    assert diffs.held_suffix(none) == "" and diffs.remote_branch_of("work/x-wt", "", none, name) == "work/x-wt"
    unset = _copy(
        pack_file, tmp_path / "d", lambda data: data.setdefault("desktop", {}).update(diff_held_suffix=None), strip
    )
    assert diffs.held_suffix(unset) == "" and "diff_held_suffix" not in unset["desktop"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_registry_resolves_the_suffix_as_the_diff_pane_reads_it(pack_file, tmp_path):
    entry = pack_keys.find("desktop.diff_held_suffix")
    assert pack_keys.default_of(entry) == "" and entry["when"] == pack_keys.NONE
    for value in (None, "", "-held"):
        resolved = pack_keys.default_of(entry) if pack_keys.defaulted(entry, True, value) else value
        assert diffs.held_suffix({"desktop": {"diff_held_suffix": value}}) == resolved
    for index, wrong in enumerate((7, "a/b", "two words", ["-wt"])):
        with pytest.raises(PackError, match="desktop.diff_held_suffix is the end of a branch name"):
            _copy(
                pack_file,
                tmp_path / str(index),
                lambda data: data.setdefault("desktop", {}).update(diff_held_suffix=wrong),
            )
