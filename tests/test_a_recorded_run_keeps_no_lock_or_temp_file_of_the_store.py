# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The forge transcript (tests/forge_transcript.py) keeps records, never the store's own lock and temp files: a lock
holds the id of the process that took it, so with them two runs of the same code never compared equal. The rule for
what is the store's own is store.scratch, read in one place; a run recorded before still compares."""

import json

from cockpitlib import store
from tests.support import forge_transcript as recorder


def _workspace(tmp_path, pid: str):
    watch = tmp_path / "hermes" / "watch"
    watch.mkdir(parents=True)
    (watch / "cards.json").write_text('{"t_00000001": {"kind": "work"}}', encoding="utf-8")
    (watch / ".cards.json.lock").write_text(json.dumps({"pid": pid}), encoding="utf-8")
    (watch / ".cards.json.1234.tmp").write_text("{", encoding="utf-8")
    ci = tmp_path / "hermes" / "qa" / "TASK-100" / "ci"
    ci.mkdir(parents=True)
    (ci / "api-0123abc.json").write_text('{"state": "green"}', encoding="utf-8")
    (ci / ".api-0123abc.json.lock").write_text(json.dumps({"pid": pid}), encoding="utf-8")
    return str(tmp_path)


def test_the_recorder_asks_the_store_what_is_its_own():
    for name in (".cards.json.lock", "watch/.cards.json.1234.tmp", "cards.json", ".hidden.json", "notes.lock"):
        assert recorder.scratch(name) is store.scratch(name)


def test_a_workspaces_records_are_kept_without_its_locks_and_temp_files(tmp_path):
    kept = recorder.records(_workspace(tmp_path, "4242"))
    assert sorted(kept) == ["hermes/qa/TASK-100/ci/api-0123abc.json", "hermes/watch/cards.json"]


def test_two_runs_that_differ_only_in_the_process_that_held_a_lock_compare_equal(tmp_path):
    for run, pid in (("before", "4242"), ("after", "9191")):
        folder = tmp_path / run
        folder.mkdir()
        kept = recorder.records(_workspace(tmp_path / f"{run}-workspace", pid))
        (folder / "tests_x.py..test_a.records.json").write_text(
            json.dumps({"meta": {}, "records": kept}), encoding="utf-8"
        )
    assert recorder.compare(recorder.load(str(tmp_path / "before")), recorder.load(str(tmp_path / "after"))) == []


def test_a_run_recorded_with_its_locks_still_compares_with_one_recorded_without(tmp_path):
    record = {"hermes/watch/cards.json": "{}"}
    for run, kept in (
        ("before", {**record, "hermes/watch/.cards.json.lock": '{"pid": "4242"}'}),
        ("after", {**record, "hermes/watch/.cards.json.lock": '{"pid": "9191"}'}),
        ("clean", record),
    ):
        folder = tmp_path / run
        folder.mkdir()
        (folder / "tests_x.py..test_a.records.json").write_text(
            json.dumps({"meta": {}, "records": kept}), encoding="utf-8"
        )
    before, after, clean = (recorder.load(str(tmp_path / run)) for run in ("before", "after", "clean"))
    assert recorder.compare(before, after) == [] and recorder.compare(before, clean) == []
    # a record that differs is still a difference
    (tmp_path / "clean" / "tests_x.py..test_a.records.json").write_text(
        json.dumps({"meta": {}, "records": {"hermes/watch/cards.json": '{"x": 1}'}}), encoding="utf-8"
    )
    assert recorder.compare(before, recorder.load(str(tmp_path / "clean"))) != []
