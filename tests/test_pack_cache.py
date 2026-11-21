# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack whose files have not changed is loaded once per process; anything it was loaded from changing loads it again
(parsing it again is most of a view's time). And a board's kinds are read once per read."""

import os
import shutil
import sqlite3

import pytest
import yaml

from cockpitlib import kanban, registry
from cockpitlib import pack as packmod
from cockpitlib.errors import PackError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme"), os.path.join(ROOT, "packs", "bravo"))


@pytest.fixture
def parses(monkeypatch):
    """How many YAML files the loader has parsed."""
    seen = []
    real = yaml.safe_load
    monkeypatch.setattr(packmod.yaml, "safe_load", lambda stream: seen.append(1) or real(stream))
    return seen


def _copy(env, source, tmp_path):
    folder = tmp_path / "packs" / os.path.basename(source)
    shutil.copytree(source, folder)
    return str(folder / "pack.yaml")


@pytest.mark.parametrize("source", PACKS)
def test_an_unchanged_pack_is_parsed_once_and_every_caller_gets_its_own_copy(env, source, tmp_path, parses):
    path = _copy(env, source, tmp_path)
    first = packmod.load(path)
    parsed = len(parses)
    assert parsed > 1
    second = packmod.load(path)
    assert len(parses) == parsed and second == first and second is not first
    second["seats"].clear()
    second["name"] = "someone else's change"
    third = packmod.load(path)
    assert third == first and third["seats"] and len(parses) == parsed


@pytest.mark.parametrize("source", PACKS)
def test_a_change_to_any_file_of_the_pack_folder_loads_it_again(env, source, tmp_path, parses):
    path = _copy(env, source, tmp_path)
    first = packmod.load(path)
    parsed = len(parses)
    beside = os.path.join(os.path.dirname(path), "repos.yaml")
    with open(beside, "a", encoding="utf-8") as handle:
        handle.write("\n# a comment more\n")
    again = packmod.load(path)
    assert len(parses) > parsed and again == first
    parsed = len(parses)
    (tmp_path / "packs" / os.path.basename(source) / "a-validator-reads-this.txt").write_text("x", encoding="utf-8")
    packmod.load(path)
    assert len(parses) > parsed  # another plugin's validator may read any file of the folder: a new one counts too


def test_a_pack_that_fails_to_load_is_not_kept_and_a_fixed_one_loads(env, tmp_path, parses):
    path = _copy(env, PACKS[0], tmp_path)
    good = open(path, encoding="utf-8").read()
    open(path, "w", encoding="utf-8").write(good + "\nno_such_key: 1\n")
    for _ in range(2):
        with pytest.raises(PackError, match="unknown key no_such_key"):
            packmod.load(path)
    open(path, "w", encoding="utf-8").write(good)
    assert packmod.load(path)["name"] == "acme"
    with pytest.raises(PackError, match="missing pack"):
        packmod.load(str(tmp_path / "nowhere" / "pack.yaml"))


def test_what_the_load_asked_outside_the_folder_and_where_the_home_is_count_too(env, tmp_path, parses, monkeypatch):
    path = _copy(env, PACKS[0], tmp_path)
    packmod.load(path)
    parsed = len(parses)
    kept = packmod._LOADED[os.path.realpath(path)]
    outside = [item for item, how in kept[1] if not item.startswith(os.path.dirname(os.path.realpath(path)))]
    assert outside  # the home's plugins, the skills beside cockpit: asked about, so part of what the pack depends on
    monkeypatch.setenv("COCKPIT_HERMES_HOME", str(tmp_path / "another-home"))
    packmod.load(path)
    assert len(parses) > parsed
    parsed = len(parses)
    monkeypatch.setitem(registry._kinds, "late-kind", {"owner": "late", "flow": "late", "title": "{ticket}: late"})
    packmod.load(path)
    assert len(parses) > parsed  # a kind another plugin registered since may clash with the pack's: checked again


def test_a_pack_folder_too_large_to_stamp_is_loaded_every_time(env, tmp_path, parses, monkeypatch):
    path = _copy(env, PACKS[0], tmp_path)
    packmod.load(path)
    monkeypatch.setattr(packmod, "TREE_LIMIT", 1)
    parsed = len(parses)
    packmod.load(path)
    packmod.load(path)
    assert len(parses) > parsed * 2 and os.path.realpath(path) not in packmod._LOADED


def test_a_state_asked_only_as_a_folder_ignores_what_the_folder_holds(tmp_path):
    folder = tmp_path / "records"
    folder.mkdir()
    before = packmod._state(str(folder), "dir")
    (folder / "new.json").write_text("{}", encoding="utf-8")
    assert (
        before is True
        and packmod._state(str(folder), "dir") is True
        and packmod._state(str(folder / "new.json"), "dir") is False
    )
    assert (
        packmod._state(str(tmp_path / "gone"), "dir") is None and packmod._state(str(tmp_path / "gone"), "file") is None
    )
    listed = packmod._state(str(folder), "list")
    assert packmod._listdir(str(folder)) == ["new.json"] and len(listed) == 3
    packmod.consulted(str(folder))  # outside a load: nothing to note, nothing raised


def test_a_board_reads_its_kinds_once_however_many_cards_it_has(bare, monkeypatch, tmp_path):
    database = tmp_path / "board.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "create table tasks (id text, title text, status text, assignee text, created_at text, body text, skills text)"
    )
    for number in range(40):
        connection.execute(
            "insert into tasks values (?, ?, 'running', 'worker-1', '', '', '')",
            (f"t_{number}", f"TASK-{number}: implement"),
        )
    connection.commit()
    connection.close()
    monkeypatch.setattr(kanban, "db_path", lambda _slug: str(database))
    monkeypatch.setattr(
        kanban,
        "_index",
        lambda: {"acme": {f"t_{number}": {"kind": "release-step" if number % 2 else "worker"} for number in range(40)}},
    )
    calls = []
    real = registry.card_kinds
    monkeypatch.setattr(registry, "card_kinds", lambda pack=None: calls.append(1) or real(pack))
    pack = {"plugins": {"supervisor": {"card_kinds": {"release-step": {"flow": "release", "title": "{ticket}: step"}}}}}
    cards = kanban.board_cards("acme", pack)
    assert (
        len(cards) == 40
        and len(calls) == 1
        and {card["flow"] for card in cards if card["id"] in ("t_1", "t_3")} == {"release"}
    )
    calls.clear()
    rows = kanban.open_card_rows("acme", pack)
    assert (
        len(rows) == 40
        and len(calls) == 1
        and rows[1]["owner"] == "supervisor"
        and rows[1]["flow"] == "release"
        and rows[0]["owner"] == ""
    )
    assert kanban._flow_of("release-step", "TASK-1: step", pack) == "release"  # one card, no kinds handed in: read then


def test_a_list_reads_the_record_of_a_pr_once_for_all_the_intents_that_name_it(monkeypatch):
    from cockpitlib import outbox
    from dashboard.cockpit import router as web

    reads = []
    record = {"repo": "api", "number": 12, "state": "open", "merged": False, "title": "Fix", "approvals": ["lead"]}
    monkeypatch.setattr(
        outbox,
        "_pr_state",
        lambda ticket, repo, number: reads.append((ticket, repo, number)) or (record if number == 12 else None),
    )
    first = {"ticket": "TASK-100", "type": "pr-comment", "payload": {"repo": "api", "number": 12}}
    stored = {
        "ticket": "TASK-100",
        "type": "pr-comment",
        "payload": {"repo": "api", "number": 13},
        "pr": {"title": "as it was written"},
    }
    seen = {}
    inbox = [{"ticket": "TASK-100", "repo": "api", "number": 12, "new": [{"id": 1}]}]
    rows = [web._with_new_comments(item, inbox, seen) for item in (first, first, stored, stored)]
    assert reads == [("TASK-100", "api", 12), ("TASK-100", "api", 13)]
    assert (
        rows[0] == rows[1] == web._with_new_comments(first, inbox)
        and rows[0] is not rows[1]
        and rows[0]["new_count"] == 1
    )
    rows[0]["title"] = "changed by one row"
    assert (
        rows[1]["title"] == "Fix"
        and rows[2]["title"] == rows[3]["title"] == "as it was written"
        and rows[2]["number"] == 13
    )
