# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A watch record an earlier pipeline wrote names its comments by that pipeline's prefixes. The mapping is the pack's
(migrate.yaml records.watch_id_prefixes); a pack that names none has none. A migrate.yaml that is
there and cannot be read stops the watcher pass with a health line: a pass run with no mapping would announce every
comment such a record knows as new."""

import json
import os
import shutil

import pytest
import yaml

from cockpitlib import ops, pack_keys, pack_migration, pr_watch
from cockpitlib.errors import PackError
from cockpitlib.pack import load
from cockpitlib.paths import watch_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
OWN = (("rc", "inline:"), ("ic", "issue:"), ("rv", "review:"))
RECORD = {"ids": ["inline:1", "rv2", "old4"], "baseline": ["ic3"]}


def _copy(pack_file, tmp_path, monkeypatch, change=None, text=None) -> dict:
    """A copy of the fixture pack whose migrate.yaml is changed (or replaced by a text), bound and loaded."""
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    path = folder / "migrate.yaml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    elif change is not None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(folder / "pack.yaml"))
    return load(str(folder / "pack.yaml"))


def test_a_pack_that_names_its_prefixes_has_an_earlier_pipelines_ids_read_by_them():
    pack = load(PACKS[0])
    assert pack_migration.load_spec(pack)["records"]["watch_id_prefixes"] == dict(OWN)
    prefixes = pr_watch.watch_id_prefixes(pack)
    assert prefixes == OWN
    assert [
        pr_watch.own_id(value, prefixes) for value in ("rc123", "ic7", "rv9", "inline:5", "rsABC", "", "rc", "rcx1")
    ] == ["inline:123", "issue:7", "review:9", "inline:5", "rsABC", "", "rc", "rcx1"]
    assert pr_watch.known_ids(RECORD, prefixes) == {"inline:1", "review:2", "issue:3", "old4"}
    assert pr_watch.first_baseline(RECORD, ["inline:1"], False, 0.0, 10.0, prefixes) == {
        "inline:1",
        "review:2",
        "issue:3",
        "old4",
    }


def test_a_pack_that_names_no_mapping_reads_every_id_as_it_is_written():
    pack = load(PACKS[1])
    assert "watch_id_prefixes" not in (pack_migration.load_spec(pack).get("records") or {})
    assert pr_watch.watch_id_prefixes(pack) == ()
    assert pack_keys.default_of(pack_keys.find("migrate.yaml:records.watch_id_prefixes")) == {}
    assert [pr_watch.own_id(value) for value in ("rc123", "inline:5", "")] == ["rc123", "inline:5", ""]
    assert pr_watch.known_ids(RECORD) == {"inline:1", "rv2", "old4", "ic3"}
    assert pr_watch.first_baseline(RECORD, ["inline:1"], False, 0.0, 10.0) == {"inline:1", "rv2", "old4", "ic3"}
    # a pack with no folder, and one with no migrate.yaml, have nothing to read a mapping from
    assert pr_watch.watch_id_prefixes(None) == () == pr_watch.watch_id_prefixes({})


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_without_a_migrate_file_has_no_prefix(pack_file, tmp_path, monkeypatch):
    pack = _copy(pack_file, tmp_path, monkeypatch)
    os.remove(os.path.join(pack["_dir"], "migrate.yaml"))
    assert pr_watch.watch_id_prefixes(pack) == ()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_packs_mapping_is_the_one_read_and_an_empty_one_means_none(pack_file, tmp_path, monkeypatch):
    pack = _copy(
        pack_file,
        tmp_path,
        monkeypatch,
        lambda data: data.setdefault("records", {}).update(watch_id_prefixes={"old": "inline:", "rv": "review:"}),
    )
    prefixes = pr_watch.watch_id_prefixes(pack)
    assert prefixes == (("old", "inline:"), ("rv", "review:")) and pack_migration.load_spec(pack)["records"][
        "watch_id_prefixes"
    ] == dict(prefixes)
    assert pr_watch.known_ids(RECORD, prefixes) == {"inline:1", "review:2", "ic3", "inline:4"}
    none = _copy(
        pack_file, tmp_path / "n", monkeypatch, lambda data: data.setdefault("records", {}).update(watch_id_prefixes={})
    )
    assert pr_watch.watch_id_prefixes(none) == () and pr_watch.known_ids(RECORD, ()) == {
        "inline:1",
        "rv2",
        "old4",
        "ic3",
    }
    null = _copy(
        pack_file,
        tmp_path / "z",
        monkeypatch,
        lambda data: data.setdefault("records", {}).update(watch_id_prefixes=None),
    )
    assert pr_watch.watch_id_prefixes(null) == (), "a key named with no value is an unset key"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_file_is_read_once_until_it_changes(pack_file, tmp_path, monkeypatch):
    pack = _copy(pack_file, tmp_path, monkeypatch)
    first = pr_watch.watch_id_prefixes(pack)
    pr_watch._PREFIXES.clear()
    reads = []
    real = yaml.safe_load
    monkeypatch.setattr(yaml, "safe_load", lambda stream: reads.append(1) or real(stream))
    for _ in range(3):
        assert pr_watch.watch_id_prefixes(pack) == first
    assert len(reads) == 1
    path = os.path.join(pack["_dir"], "migrate.yaml")
    data = real(open(path, encoding="utf-8"))
    data.setdefault("records", {})["watch_id_prefixes"] = {"old": "issue:"}
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(data))
    assert (
        pr_watch.watch_id_prefixes(pack) == (("old", "issue:"),) == pr_watch.watch_id_prefixes(pack) and len(reads) == 2
    )


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "text, said",
    [
        ("legacy: [unclosed\n", "cannot be read ("),
        ("- a list\n", "is not a mapping with a records block"),
        ("records: [a, b]\n", "is not a mapping with a records block"),
        (
            "records: {watch_id_prefixes: [rc]}\n",
            "records.watch_id_prefixes maps a prefix of letters to one of inline:, issue:, review:",
        ),
        ("records: {watch_id_prefixes: {rc: comment}}\n", "records.watch_id_prefixes maps a prefix of letters"),
        ("records: {watch_id_prefixes: {'r1': 'inline:'}}\n", "records.watch_id_prefixes maps a prefix of letters"),
    ],
)
def test_a_file_that_cannot_be_read_stops_the_pass_with_a_health_line_and_no_record_is_touched(
    bare, pack_file, tmp_path, monkeypatch, text, said
):
    pack = _copy(pack_file, tmp_path, monkeypatch, text=text)
    with pytest.raises(pr_watch.SpecUnreadable) as refused:
        pr_watch.watch_id_prefixes(pack)
    assert said in str(refused.value) and "migrate.yaml" in str(refused.value)
    built = []
    from cockpitlib import publish

    monkeypatch.setattr(publish, "forge_for", lambda pack: built.append(1))
    with pytest.raises(pr_watch.SpecUnreadable):
        pr_watch.watch(pack, now=1000.0)
    with pytest.raises(pr_watch.SpecUnreadable):
        pr_watch.read(pack, object(), "TASK-100", "api", 1, 1000.0)
    said_by_job = ops.watch_pr(pack, now=1000.0)
    assert said_by_job.startswith("pr-watch did not run: ") and said in said_by_job and built == [], (
        "no forge was asked"
    )
    health = json.load(open(os.path.join(watch_dir(), "pr-watch.json"), encoding="utf-8"))
    assert health["ok"] is False and health["summary"] == said_by_job and health["fails"] == 1
    # once the file reads again the next pass runs by its mapping
    open(os.path.join(pack["_dir"], "migrate.yaml"), "w", encoding="utf-8").write(
        "records: {watch_id_prefixes: {old: 'inline:'}}\n"
    )
    assert pr_watch.watch_id_prefixes(pack) == (("old", "inline:"),)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_file_the_machine_cannot_open_is_unreadable_too(pack_file, tmp_path, monkeypatch):
    pack = _copy(pack_file, tmp_path, monkeypatch)
    real = os.stat
    path = os.path.join(pack["_dir"], "migrate.yaml")

    def stat(target, *args, **kwargs):
        if str(target) == path:
            raise PermissionError(13, "Permission denied")
        return real(target, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    with pytest.raises(pr_watch.SpecUnreadable, match="cannot be read"):
        pr_watch.watch_id_prefixes(pack)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_migration_spec_refuses_a_mapping_of_the_wrong_shape(pack_file, tmp_path, monkeypatch):
    for index, wrong in enumerate((["rc"], {"rc": "comment"}, {"r-1": "inline:"}, {7: "inline:"})):
        pack = _copy(
            pack_file,
            tmp_path / str(index),
            monkeypatch,
            lambda data: data.setdefault("records", {}).update(watch_id_prefixes=wrong),
        )
        with pytest.raises(
            PackError, match="records.watch_id_prefixes maps a prefix of letters to one of inline:, issue:, review:"
        ):
            pack_migration.load_spec(pack)
