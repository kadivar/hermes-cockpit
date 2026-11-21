# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A write that does not go through store is on a reviewed list: a new one cannot appear unseen, and the list only shrinks.

Records are plain files that crons, lanes, the routes and the human's CLI write at the same time. `store` writes one
whole or not at all (a temp file beside it, then a replace); any other write can be read half done. The scan reads
kernel/cockpitlib and dashboard/cockpit for every write; each one that is not store's must be in
tests/contract/record-writes.json, with the reason it stays as it is: no write of a shared record is on it.
"""

import json
import os

from tests.guards.record_write_scan import key, scan, scan_source, unlisted

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTED = os.path.join(ROOT, "tests", "contract", "record-writes.json")


def _rows() -> list:
    with open(LISTED, encoding="utf-8") as handle:
        return json.load(handle)["writes"]


def _listed() -> dict:
    return {(row["file"], row["function"], row["form"], row["target"]): row["count"] for row in _rows()}


def test_every_write_outside_the_store_is_on_the_reviewed_list():
    found, listed = unlisted(scan()), _listed()
    new = sorted(
        f"{file} {function}: {form} {target} (x{count}, listed x{listed.get((file, function, form, target), 0)})"
        for (file, function, form, target), count in found.items()
        if count > listed.get((file, function, form, target), 0)
    )
    assert new == [], (
        "a file is written here without store: use store.write_json, store.dump_json, store.write_text or "
        "store.append_line; only a file that is not a shared record goes on tests/contract/record-writes.json, "
        "with its reason"
    )


def test_the_reviewed_list_only_shrinks():
    found, listed = unlisted(scan()), _listed()
    gone = sorted(
        f"{' '.join(row)} (listed x{count}, found x{found.get(row, 0)})"
        for row, count in listed.items()
        if found.get(row, 0) < count
    )
    assert gone == [], "a listed write is gone or moved onto store: take it out of tests/contract/record-writes.json"


def test_the_reviewed_list_is_sorted_and_says_why_each_write_stays_as_it_is():
    rows = _rows()
    keys = [(row["file"], row["function"], row["form"], row["target"]) for row in rows]
    assert keys == sorted(set(keys))
    for row in rows:
        assert set(row) == {"file", "function", "form", "target", "count", "reason"}
        assert row["count"] >= 1 and len(row["reason"]) > 20, (
            f"{row['file']} {row['function']}: a write that stays says why"
        )


SAMPLE = """
import json, os, shutil
from pathlib import Path
from .store import write_json, log
from . import store


def plain(path, data, other):
    open(path, "w", encoding="utf-8").write("x")
    json.dump(data, open(path, "w"), indent=1)
    with open(path, "a") as handle:
        handle.write("line")
    open(path).read()
    open(path, "rb").read()
    open(path, mode="x").close()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.open(path, os.O_RDONLY)
    with os.fdopen(fd, "w") as stream:
        stream.write("y")
    Path(path).write_text("z")
    os.replace(path, other)
    os.rename(path, other)
    shutil.copyfile(path, other)
    shutil.rmtree(other)


class Keeper:
    def keep(self, path, data):
        def inner():
            write_json(path, data)
        store.write_text(path, "text")
        store.append_line(path, "line")
        log("LINE")
        data.write_text("not a file")
        return inner
"""


def test_the_scan_finds_each_way_of_writing_and_knows_the_store():
    hits = scan_source("sample.py", SAMPLE)
    assert [(hit["function"], hit["form"], hit["target"], hit["mode"], hit["atomic"]) for hit in hits] == [
        ("plain", "open", "path", "w", False),
        ("plain", "open", "path", "w", False),
        ("plain", "open", "path", "a", False),
        ("plain", "open", "path", "x", False),
        ("plain", "os.open", "path", "os.O_WRONLY | os.O_CREAT", False),
        ("plain", "os.fdopen", "fd", "w", False),
        ("plain", "Path.write_text", "Path(path)", "", False),
        ("plain", "os.replace", "other", "", False),
        ("plain", "os.rename", "other", "", False),
        ("plain", "shutil.copyfile", "other", "", False),
        ("Keeper.keep.inner", "store.write_json", "path", "", True),
        ("Keeper.keep", "store.write_text", "path", "", True),
        ("Keeper.keep", "store.append_line", "path", "", True),
        ("Keeper.keep", "store.log", "'LINE'", "", True),
        ("Keeper.keep", "Path.write_text", "data", "", False),
    ]
    counts = unlisted(hits)
    assert counts[("sample.py", "plain", "open", "path")] == 4 and key(hits[0]) == (
        "sample.py",
        "plain",
        "open",
        "path",
    )
    assert not any(row[1].startswith("Keeper") and row[2].startswith("store.") for row in counts)


def test_a_mode_that_is_not_a_literal_counts_as_a_write_and_the_store_file_is_the_helper():
    assert [hit["mode"] for hit in scan_source("x.py", "def f(p, m):\n    open(p, m)\n    open(p, mode=m)\n")] == [
        "m",
        "m",
    ]
    assert [hit["atomic"] for hit in scan_source("kernel/cockpitlib/store.py", "def f(p):\n    open(p, 'w')\n")] == [
        True
    ]
    assert scan_source("x.py", "open(p, 'w')\n")[0]["function"] == "<module>"
