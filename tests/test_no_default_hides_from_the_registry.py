# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A default the kernel gives a pack key where it reads it is on a reviewed list: a new one cannot appear unseen.

`cockpit pack effective` can only say what a key comes to when the registry knows every place that fills an unset key
in. The scan reads kernel/cockpitlib for `x.get("key") or DEFAULT` and `x.get("key", DEFAULT)` over the pack and its
blocks; each (file, key) it finds must be in tests/contract/pack-defaults.json. The list only shrinks (a default that
moved into pack.load) or changes with review (a new default, registered in pack_keys with its reader and its rule).
"""

import json
import os

from cockpitlib import pack_keys
from tests.guards.pack_default_scan import scan, scan_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED = os.path.join(ROOT, "tests", "contract", "pack-defaults.json")


def _allowed() -> set:
    return {(row["file"], row["key"]) for row in json.load(open(ALLOWED, encoding="utf-8"))["defaults"]}


def test_every_default_given_at_a_reading_place_is_on_the_reviewed_list():
    hits = scan()
    found = {(hit["file"], hit["key"]) for hit in hits}
    new = sorted(
        f"{hit['file']}:{hit['line']} {hit['key']} ({hit['form']} {hit['fallback']})"
        for hit in hits
        if (hit["file"], hit["key"]) not in _allowed()
    )
    assert new == [], (
        "a pack key gets a default here that the list does not know: register the default in pack_keys (default, when, "
        "site) with its probe, then add the pair to tests/contract/pack-defaults.json"
    )
    assert sorted(_allowed() - found) == [], (
        "a listed default is gone: take the pair out of tests/contract/pack-defaults.json"
    )


def test_the_reviewed_list_is_sorted_names_registry_keys_and_no_pair_twice():
    rows = json.load(open(ALLOWED, encoding="utf-8"))["defaults"]
    pairs = [(row["file"], row["key"]) for row in rows]
    assert pairs == sorted(set(pairs))
    assert all(
        set(row) == {"file", "key"} and pack_keys.label(pack_keys.find(row["key"])) == row["key"] for row in rows
    )


SAMPLE = """
def reader(pack, row, repo):
    forge = (pack or {}).get("forge") or {}
    bots = forge.get("bots") or ["example-bot"]
    tracker = dict(pack.get("tracker") or {})
    kind = tracker.get("kind", "rest")
    for item in pack["repos"]["repos"]:
        item.get("base") or "trunk"
    first = [entry.get("name") or "?" for entry in (pack.get("stores") or [])]
    return [bots, kind, first, repo.get("watched", True), pack.get("board") or "board", pack["hours"].get("retry_seconds") or 3,
            pack.get("grooming") or [], forge.get("org") or "", (pack.get("slots") or {}).get("ports") or {},
            pack.get("not_a_key") or 1, row.get("bots") or 2, row.get("name", "x"), pack.get("egress") or 4]


class Reader:
    def run(self, pack):
        def inner():
            return pack.get("base_branch") or "trunk"
        return (pack.get("budget") or {}).get("monthly_usd", 5), inner
"""


def test_the_scan_finds_a_default_over_the_pack_and_its_blocks_and_nothing_else():
    found = [(hit["function"], hit["key"], hit["form"], hit["fallback"]) for hit in scan_source("sample.py", SAMPLE)]
    assert found == [
        ("reader", "forge.bots", "or", "['example-bot']"),
        ("reader", "tracker.kind", "get", "'rest'"),
        ("reader", "repos.yaml:repos[].base", "or", "'trunk'"),
        ("reader", "stores[].name", "or", "'?'"),
        ("reader", "board", "or", "'board'"),
        ("reader", "hours.retry_seconds", "or", "3"),
        ("reader", "repos.yaml:repos[].watched", "get", "True"),
        ("Reader.inner", "base_branch", "or", "'trunk'"),  # a function inside a method is named after the class
        ("Reader.run", "budget.monthly_usd", "get", "5"),
    ]
    # an empty fallback is no default: it is listed only when asked for
    trivial = {hit["key"] for hit in scan_source("sample.py", SAMPLE, trivial=True)} - {key for _, key, _, _ in found}
    assert trivial == {"grooming", "forge.org", "slots.ports", "forge", "tracker", "stores", "slots", "budget"}
