# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The update pre-flight refuses a kernel that prints a pack value the installed one does not, unless the release
declares the key (UPDATE-CHANGES.json). A key this release adds, a key whose default it changes and a key it removes
are declared there: each is a registry key, or a name a pack may no longer write."""

import json
import os

import pytest

from cockpitlib import pack_keys, self_update
from cockpitlib.pack import load
from cockpitlib.pack_effective import rows_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def test_the_declared_keys_are_read_as_the_pre_flight_reads_them():
    declared = self_update._declared(ROOT)
    assert declared == sorted(set(declared)) != []
    assert json.load(open(os.path.join(ROOT, self_update.CHANGES_FILE), encoding="utf-8")) == {
        "effective_changes": declared
    }


# The keys this release takes away: a pack that writes one does not load, and the row it had is gone from the dump.
REMOVED = ("github_org", "jira_project", "jira_url", "standup_hour")
# The keys whose default this release changes; a pack that wrote its value out reads the same before and after.
MOVED = (
    "desktop.diff_held_suffix",
    "desktop.hints.bumps",
    "desktop.hints.bumps_start",
    "desktop.hints.bumps_tab",
    "desktop.hints.rereview",
    "desktop.hints.review",
    "finding_labels",
    "forge.rereview_job",
    "migrate.yaml:records.watch_id_prefixes",
    "standup.chat_file",
    "standup.sections.created",
    "standup.sections.developments",
    "standup.sections.opened",
    "standup.sections.reviews",
    "standup.sections.testings",
    "standup.sections.waiting",
    "testflow.banners.not_ok",
    "testflow.banners.ok",
    "testflow.evidence_dir",
    "testflow.plan_file",
    "testflow.review_mark",
    "testflow.title",
)


def _covered(key: str, declared) -> bool:
    """As the pre-flight reads a declaration: a key covers what is under it."""
    return any(key == name or key.startswith(name + ".") for name in declared)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_declared_key_is_a_registry_key_or_one_a_pack_may_no_longer_write(pack_file, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    rows = rows_of(load(pack_file))
    for name in self_update._declared(ROOT):
        if name in REMOVED:
            assert pack_keys.find(name) is None and name not in rows
            folder = tmp_path / name / "packs" / os.path.basename(os.path.dirname(pack_file))
            shutil.copytree(os.path.dirname(pack_file), folder)
            raw = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
            raw[name] = "example"
            (folder / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            with pytest.raises(PackError, match=f"^unknown key {name}$"):
                load(str(folder / "pack.yaml"))
            continue
        assert pack_keys.find(name) is not None, f"{name} is no registry key"
        assert [key for key in rows if key == name or key.startswith(name + ".")], name


def test_every_removed_key_and_every_changed_default_is_declared():
    declared = self_update._declared(ROOT)
    assert [name for name in (*REMOVED, *MOVED) if not _covered(name, declared)] == []
    for name in MOVED:
        entry = pack_keys.find(name)
        assert entry is not None and "default" in entry, name
