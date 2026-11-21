# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The CI watch lists a ticket's ci/ folder to count flaky runs, to dismiss, re-arm and forget a commit. The store keeps
its own files in a records folder for a moment (a temp file beside the record it is writing, a lock beside one it
holds): a temp file holds a whole record under another name. None of the listings reads one as a record, writes one
back or removes one."""

import json
import os

from cockpitlib import ci_watch, store

TICKET, REPO, SHA = "TASK-100", "api", "abcdef0123456789"
RECORD = {
    "repo": REPO,
    "sha": SHA,
    "state": "failed",
    "settled": True,
    "runs": [{"id": 7, "name": "tests", "passed_after_rerun": True}],
}


def _folder_with_store_files() -> tuple:
    """The commit's record, a temp file holding the same record, and a lock beside it: (record, temp, lock)."""
    path = ci_watch.record_path(TICKET, REPO, SHA)
    store.dump_json(path, RECORD, indent=1)
    folder, name = os.path.split(path)
    temp = os.path.join(folder, f".{name}.4242.0.abcdef.tmp")
    lock = store.lock_file(path)
    for other in (temp, lock):
        with open(other, "w", encoding="utf-8") as handle:
            json.dump(RECORD, handle)
        assert store.scratch(other)
    return path, temp, lock


def test_a_flaky_run_is_counted_once_however_many_store_files_lie_beside_its_record(bare):
    _folder_with_store_files()
    assert ci_watch._flaky(TICKET, REPO, "tests") == 1
    assert ci_watch._repo_flaky(REPO, "tests") == [(TICKET, 1)]


def test_dismissing_a_commit_marks_its_record_and_leaves_the_store_files_as_they_were(bare):
    path, temp, lock = _folder_with_store_files()
    before = {other: open(other, encoding="utf-8").read() for other in (temp, lock)}
    done = ci_watch.dismiss({}, TICKET, REPO, SHA[:12])
    assert done["records"] == [os.path.basename(path)]
    assert json.load(open(path, encoding="utf-8"))["dismissed"] is True
    assert {other: open(other, encoding="utf-8").read() for other in (temp, lock)} == before


def test_a_rerun_rearms_the_record_and_not_a_temp_file_that_sorts_before_it(bare):
    path, temp, lock = _folder_with_store_files()
    assert sorted(os.listdir(os.path.dirname(path)))[0] != os.path.basename(path), (
        "the store's files sort first: an unfiltered listing meets them first"
    )
    assert ci_watch.rearm(TICKET, REPO, 7) == os.path.basename(path)
    assert json.load(open(path, encoding="utf-8"))["settled"] is False
    assert json.load(open(temp, encoding="utf-8"))["settled"] is True


def test_forgetting_a_commit_removes_its_record_and_no_lock(bare):
    path, temp, lock = _folder_with_store_files()
    assert ci_watch.forget(TICKET, SHA)["removed"] == [os.path.basename(path)]
    assert not os.path.exists(path) and os.path.exists(lock) and os.path.exists(temp)


def test_a_folder_that_is_not_there_has_no_records(bare):
    assert ci_watch._records(os.path.join(str(bare["workspace"]), "nowhere")) == []
    assert ci_watch._flaky("TASK-200", REPO, "tests") == 0
