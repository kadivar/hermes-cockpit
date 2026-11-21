# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/replay: a snapshot of a workspace is cut reading only; one kernel captured twice over it answers the same,
byte for byte; a changed record shows as exactly the views that read it; the receipt holds hashes and counts and nothing
of the records."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
SUPPORT = os.path.join(ROOT, "scripts", "replay_support")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from replay_support import tool  # noqa: E402

CLOCK = "2030-01-02T09:00:00Z"
RESULTS = """# Test run 001

**Date:** 2029-12-30, 15:00
**Under test:** the export at abc123

## Summary

| # | Scenario | Verdict | Evidence |
|---|---|---|---|
| 1 | the box renders | ✅ pass | [shot](evidences/one.png) |
| 2 | the empty case | ❌ fail | |

## Notes

All **fine** otherwise.
"""


def _hashes(folder: str) -> dict:
    """Every file under a folder: its content's hash and its time."""
    found = {}
    for top, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(top, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            found[os.path.relpath(path, folder)] = (
                hashlib.sha256(open(path, "rb").read()).hexdigest(),
                os.stat(path).st_mtime_ns,
            )
    return found


def _seed(pack) -> dict:
    """A small installation's records: intents in several states, a QA run, a watched PR, a CI record, a standup draft
    and a board with cards. Every identifier comes from the pack."""
    from cockpitlib import ci_watch, pr_watch
    from cockpitlib.kanban import BoardWrites, db_path, place_card
    from cockpitlib.outbox import create, drop, endorse, hold
    from cockpitlib.paths import platform_dir, qa

    def put_card(title: str, lane: str, status: str) -> str:
        """A card in a state only a run gives it: made the way cockpit makes one, then moved (test setup only)."""
        card = place_card(slug, title, lane, "ready")
        connection = sqlite3.connect(db_path(slug))
        connection.execute("update tasks set status = ? where id = ?", (status, card))
        connection.commit()
        connection.close()
        return card

    project = (pack.get("tracker") or {}).get("project") or "TASK"
    one, two = f"{project}-100", f"{project}-101"
    repo = pack["repos"]["repos"][0]["name"]
    slug = pack["board"]
    blocked = place_card(slug, f"{one}: implement the fix", "worker-1", "ready")
    writes = BoardWrites(slug)
    writes.block(blocked, "Which colour: the old one or the brand one?")
    writes.comment(blocked, "worker-1", "I need the colour.")
    writes.flush()
    put_card(f"{one}: test the fix", "tester-1", "done")
    put_card(f"{two}: review the PR", "reviewer", "running")
    pending = create(pack, one, "push-branch", blocked, "ship the fix", {"repo": repo, "branch": "main", "number": 7})
    held = create(
        pack, one, "infra-note", blocked, "a note for the platform", {"repo": repo, "body": "raise the limit"}
    )
    hold(held["id"], "needs a look")
    dropped = create(pack, two, "infra-note", "c", "not needed after all", {"repo": repo, "body": "nothing"})
    drop(dropped["id"], "not needed")
    endorsed = create(pack, two, "push-branch", "c", "ship the second", {"repo": repo, "branch": "main"})
    endorse(endorsed["id"], "low", "fine **as is**", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    folder = os.path.join(qa(), one)
    from cockpitlib import test_flow

    run, kept = test_flow.next_run_dir(pack, folder), test_flow.evidence_dir(pack)  # by the pack's own names
    os.makedirs(os.path.join(run, kept), exist_ok=True)
    open(os.path.join(run, "test-results.md"), "w", encoding="utf-8").write(RESULTS.replace("evidences/", kept + "/"))
    open(os.path.join(run, kept, "one.png"), "wb").write(b"\x89PNG\r\n\x1a\n")
    open(os.path.join(run, kept, "long.webm"), "wb").write(b"\0" * (3 << 20))  # over the test's sparse limit
    open(os.path.join(folder, test_flow.plan_file(pack)), "w", encoding="utf-8").write(
        "# Plan\n\n## Brief\n\nthe box\n\n1. box\n"
    )
    record = {
        "ticket": one,
        "repo": repo,
        "number": 7,
        "state": "open",
        "role": "author",
        "author": "human",
        "title": "the fix",
        "url": f"https://example.test/{pack['forge']['org']}/{repo}/pull/7",
        "head": "work/fix",
        "head_sha": "a" * 40,
        "base": "main",
        "ids": ["issue:1"],
        "new": [
            {
                "id": "issue:2",
                "kind": "comment",
                "author": "peer",
                "body": "B: please rename",
                "at": "2029-12-31T10:00:00Z",
            }
        ],
        "first_sight": "2029-12-30T10:00:00Z",
        "last_check": "2030-01-01T10:00:00Z",
        "last_activity": 1893492000.0,
    }
    path = pr_watch.record_path(one, repo, 7)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(record, open(path, "w", encoding="utf-8"))
    ci = ci_watch.record_path(one, repo, "a" * 40)
    os.makedirs(os.path.dirname(ci), exist_ok=True)
    json.dump(
        {"repo": repo, "sha": "a" * 40, "state": "failed", "summary": "1 failed", "branch": "work/fix", "runs": []},
        open(ci, "w", encoding="utf-8"),
    )
    os.makedirs(platform_dir(), exist_ok=True)
    open(os.path.join(platform_dir(), "standup.md"), "w", encoding="utf-8").write(
        f"# Standup 2030-01-02\n\nSince yesterday\n\n- {one}: the fix\n"
    )
    return {
        "tickets": [one, two],
        "repo": repo,
        "intents": [pending["id"], held["id"], dropped["id"], endorsed["id"]],
        "results": os.path.join(run, "test-results.md"),
    }


def _snapshot(env, pack_file: str, out) -> dict:
    return tool.snapshot(ROOT, str(env["workspace"]), pack_file, str(env["home"]), str(out), clock=CLOCK, sparse_mb=1)


RECEIPT_WORDS = {
    "tool",
    "version",
    "date",
    "baseline",
    "candidate",
    "commit",
    "edited",
    "tree",
    "pack_digest",
    "snapshot_digest",
    "records",
    "intents",
    "outbox_tickets",
    "qa_tickets",
    "pr_records",
    "watch_files",
    "cards",
    "effective",
    "result",
    "replay",
    "files",
    "different",
    "differences",
    "allowed",
    "skipped_a",
    "skipped_b",
    "replay_errors",
    "forge_writes_refused",
    "allow_file",
    "pack_tests",
    "exit",
    "counts",
    "passed",
    "skipped",
    "verdict",
}


def _keys(value) -> set:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    return set()


def _leaves(value) -> list:
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    return [] if value is None or isinstance(value, bool) else [str(value)]


def _files_that_differ(found: dict) -> set:
    return {line.split(":", 1)[0] for line in found["lines"] if not line.startswith(" ")}


@pytest.mark.parametrize("pack_file", PACKS)
def test_one_kernel_captured_twice_answers_the_same_and_a_changed_record_shows_as_its_views(
    env, pack_file, monkeypatch, tmp_path
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    seeded = _seed(pack)
    before = {
        "workspace": _hashes(str(env["workspace"])),
        "home": _hashes(str(env["home"])),
        "pack": _hashes(os.path.dirname(pack_file)),
    }
    meta = _snapshot(env, pack_file, tmp_path / "snap")
    assert meta["records"] == pack["records_dir"] and meta["board"] == pack["board"] and meta["board_copy"] == "copied"
    assert (
        meta["counts"]["intents"] == 4
        and meta["counts"]["pr_records"] == 1
        and meta["counts"]["cards"] == 3
        and meta["counts"]["qa_tickets"] == 1
    )
    assert meta["copied"]["sparse"] == 1  # the video is there by size only
    one = tool.capture(ROOT, str(tmp_path / "snap"), str(tmp_path / "a"))
    two = tool.capture(ROOT, str(tmp_path / "snap"), str(tmp_path / "b"))
    # reading only: not a byte nor a time of the workspace, the runtime's home or the pack moved
    assert before == {
        "workspace": _hashes(str(env["workspace"])),
        "home": _hashes(str(env["home"])),
        "pack": _hashes(os.path.dirname(pack_file)),
    }
    assert one["files"] == two["files"] and one["views"] > 40
    same = tool.compare(str(tmp_path / "a"), str(tmp_path / "b"))
    assert same["result"] == "identical" and same["lines"] == [] and same["files"] == one["views"]
    assert one["errors"] == [] and one["forge_writes_refused"] == 0 and one["kernel"]["tree"] == two["kernel"]["tree"]
    # what was captured: the list as the Desktop gets it, each intent, the Inbox, the board, the QA views, the PR pass, the fences
    names = set(one["files"])
    for wanted in (
        "outbox/list",
        "inbox/needs-you",
        "standup/stored",
        "standup/draft",
        "board/board",
        "tickets/index",
        "qa/index",
        f"qa/ticket/{seeded['tickets'][0]}",
        f"tickets/ticket/{seeded['tickets'][0]}",
        "skills/required",
        "skills/missing",
        f"pr_watch/read/{seeded['tickets'][0]}/{seeded['repo']}-7",
        f"pr/state/{seeded['tickets'][0]}/{seeded['repo']}-7",
        "digest/numbered",
        "digest/morning",
        "pack/loaded",
        "effects/written",
        "effects/outward",
        *[f"fence/{seat}" for seat, _lane in tool.SEATS],
        *[f"outbox/intent/{iid}" for iid in seeded["intents"]],
    ):
        assert os.path.join("views", wanted + ".json") in names, wanted
    listed = json.load(open(tmp_path / "a" / "views" / "outbox" / "list.json", encoding="utf-8"))["result"]
    assert sorted(listed["intents"]) == sorted(seeded["intents"]) and listed["counts"] == {
        "pending": 1,
        "held": 1,
        "dropped": 1,
        "endorsed": 1,
    }
    text = "".join(open(tmp_path / "a" / name, encoding="utf-8").read() for name in names)
    assert str(tmp_path) not in text and "{WORKSPACE}" in text  # no path of the sandbox survives in an answer
    read = json.load(
        open(
            tmp_path / "a" / "views" / "pr_watch" / "read" / seeded["tickets"][0] / f"{seeded['repo']}-7.json",
            encoding="utf-8",
        )
    )["result"]
    assert (
        read["last_check"] == CLOCK and read["title"] == "the fix" and [row["id"] for row in read["new"]] == ["issue:2"]
    )
    fences = json.load(open(tmp_path / "a" / "views" / "fence" / "worker.json", encoding="utf-8"))["result"]
    decided = {row["command"]: row["decision"] for row in fences}
    assert decided["git push"].startswith("blocked") and decided["git status"] == "" and len(fences) >= 80
    host = pack["egress"]["production_hosts"][0].replace("\\", "")
    assert decided[f"curl https://{host}/"].startswith("blocked")
    # one record changed: the same kernel over the changed records differs in the views that read it, and in no other
    changed = open(seeded["results"], encoding="utf-8").read().replace("❌ fail", "✅ pass")
    stamp = os.stat(seeded["results"])
    open(seeded["results"], "w", encoding="utf-8").write(changed)
    os.utime(seeded["results"], ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    _snapshot(env, pack_file, tmp_path / "snap2")
    tool.capture(ROOT, str(tmp_path / "snap2"), str(tmp_path / "c"))
    with pytest.raises(tool.ReplayError, match="not of the same replay"):
        tool.compare(str(tmp_path / "a"), str(tmp_path / "c"))
    moved = tool.compare(str(tmp_path / "a"), str(tmp_path / "c"), across=True)
    ticket = seeded["tickets"][0]
    assert moved["result"] == "different"
    assert _files_that_differ(moved) == {"views/qa/index.json", f"views/qa/ticket/{ticket}.json"}
    assert any("fail" in line and "pass" in line for line in moved["lines"])
    # the receipt: hashes and counts, and not one name out of the records
    made = tool.receipt(
        str(tmp_path / "a"),
        str(tmp_path / "b"),
        f"{sys.executable} -c \"print('3 passed, 1 skipped in 0.1s')\"",
        out=str(tmp_path / "receipt.json"),
    )
    assert (
        made["verdict"] == "accept"
        and made["replay"]["result"] == "identical"
        and made["pack_tests"] == {"result": "passed", "exit": 0, "counts": {"passed": 3, "skipped": 1}}
    )
    assert made["baseline"]["commit"] == made["candidate"]["commit"] and made["records"]["intents"] == 4
    slip = json.load(open(tmp_path / "receipt.json", encoding="utf-8"))
    assert slip == made
    # its words are the tool's own, the same on every machine; what it says in them is verdicts, hashes, counts and a date
    assert _keys(slip) == RECEIPT_WORDS
    said = " ".join(_leaves(slip))
    private = {
        *seeded["tickets"],
        seeded["repo"],
        pack["name"],
        pack["forge"]["org"],
        str(tmp_path),
        str(env["workspace"]),
        ROOT,
        "rename",
        "colour",
    }
    for _top, dirs, files in os.walk(tmp_path / "snap"):
        private.update(name for name in [*dirs, *files] if len(name) > 3)
    assert len(private) > 40 and [word for word in sorted(private) if word in said] == []
    assert all(
        re.fullmatch(r"[0-9a-f]{40,64}|\d{4}-\d\d-\d\d|identical|unavailable|passed|accept|replay|unknown|\d+", word)
        for word in said.split()
    ), said
    refused = tool.receipt(str(tmp_path / "a"), str(tmp_path / "c"), "exit 3", across=True)
    assert refused["verdict"] == "refuse" and refused["pack_tests"]["exit"] == 3 and refused["replay"]["different"] == 2


def test_a_capture_from_the_command_line_cuts_its_own_snapshot_and_says_what_it_did(env, tmp_path, capsys, monkeypatch):
    pack = load(os.environ["COCKPIT_PACK"])
    _seed(pack)
    monkeypatch.setattr(tool, "SEATS", (("worker", "worker-1"),))
    argv = [
        "capture",
        "--kernel",
        ROOT,
        "--workspace",
        str(env["workspace"]),
        "--pack",
        os.environ["COCKPIT_PACK"],
        "--hermes-home",
        str(env["home"]),
        "--clock",
        CLOCK,
        "--out",
        str(tmp_path / "a"),
    ]
    assert tool.main(argv) == 0
    assert "views, " in capsys.readouterr().out
    assert tool.main(argv) == 2 and "is not empty" in capsys.readouterr().err  # a capture never writes over one
    assert tool.main(["compare", str(tmp_path / "a"), str(tmp_path / "a")]) == 0
    assert capsys.readouterr().out.startswith("identical: ")
    assert (
        tool.main(
            [
                "receipt",
                "--baseline",
                str(tmp_path / "a"),
                "--candidate",
                str(tmp_path / "a"),
                "--out",
                str(tmp_path / "r.json"),
            ]
        )
        == 1
    )
    assert "pack tests not run: incomplete" in capsys.readouterr().out
    assert tool.main(["capture", "--kernel", ROOT, "--out", str(tmp_path / "b")]) == 2
    assert "--snapshot" in capsys.readouterr().err


def test_a_snapshot_is_never_written_inside_what_it_reads(env, tmp_path):
    pack_file = os.environ["COCKPIT_PACK"]
    for inside in (env["workspace"] / "snap", env["home"] / "snap"):
        with pytest.raises(tool.ReplayError, match="writes nothing there"):
            tool.snapshot(ROOT, str(env["workspace"]), pack_file, str(env["home"]), str(inside))
        assert not inside.exists()
    with pytest.raises(tool.ReplayError, match="the workspace has no such folder"):  # a workspace with no records yet
        tool.snapshot(ROOT, str(env["workspace"]), pack_file, str(env["home"]), str(tmp_path / "empty"))
    with pytest.raises(tool.ReplayError, match="no pack at"):
        tool.snapshot(ROOT, str(env["workspace"]), str(tmp_path / "none.yaml"), str(env["home"]), str(tmp_path / "s"))
    with pytest.raises(tool.ReplayError, match="not a kernel checkout"):
        tool.capture(str(tmp_path), str(tmp_path), str(tmp_path / "out"))


def test_a_copy_keeps_times_empties_a_large_file_and_drops_a_link_that_leads_out(tmp_path):
    source = tmp_path / "source"
    (source / "deep").mkdir(parents=True)
    (source / "deep" / "small.json").write_text("{}", encoding="utf-8")
    (source / "big.bin").write_bytes(b"x" * 5000)
    (source / "big.json").write_text(
        json.dumps({"rows": ["x" * 5000]}), encoding="utf-8"
    )  # a record is copied whole, whatever its size
    (source / "node_modules").mkdir()
    (source / "node_modules" / "heavy.js").write_text("x", encoding="utf-8")
    os.utime(source / "big.bin", ns=(10**18, 10**18))
    os.symlink("deep/small.json", source / "near")
    os.symlink(str(tmp_path), source / "away")
    os.symlink("../..", source / "deep" / "up")
    counts = tool.copy_tree(str(source), str(tmp_path / "copy"), limit=1000, skip=tool.HEAVY)
    assert counts == {"files": 3, "bytes": 2 + 5014, "sparse": 1, "links_skipped": 2}
    copied = tmp_path / "copy"
    assert copied.joinpath("big.json").read_text(encoding="utf-8") == source.joinpath("big.json").read_text(
        encoding="utf-8"
    )
    assert not copied.joinpath("node_modules").exists()
    shutil.rmtree(source / "node_modules")
    assert copied.joinpath("big.bin").read_bytes() == b"\0" * 5000 and os.stat(copied / "big.bin").st_mtime_ns == 10**18
    assert (
        os.readlink(copied / "near") == "deep/small.json"
        and not os.path.lexists(copied / "away")
        and not os.path.lexists(copied / "deep" / "up")
    )
    assert os.stat(copied / "deep").st_mtime_ns == os.stat(source / "deep").st_mtime_ns
    assert tool.tree_digest(str(source), 1000, times=True) == tool.tree_digest(str(copied), 1000, times=True)


def test_a_snapshot_takes_of_the_home_only_what_a_pack_load_reads(tmp_path):
    home = tmp_path / "home"
    (home / "plugins" / "model-providers" / "fixture-c").mkdir(parents=True)
    (home / "plugins" / "ledger-view" / "node_modules").mkdir(parents=True)
    (home / "plugins" / "ledger-view" / "plugin.yaml").write_text("name: ledger-view\n", encoding="utf-8")
    (home / "plugins" / "ledger-view" / "cockpit_pack.py").write_text(
        "def validate(block, folder):\n    return block\n", encoding="utf-8"
    )
    (home / "plugins" / "ledger-view" / "node_modules" / "x.js").write_text("x", encoding="utf-8")
    (home / "plugins" / "own" / "kernel" / "cockpitlib").mkdir(parents=True)
    (home / "plugins" / "own" / "plugin.yaml").write_text("name: own\n", encoding="utf-8")
    (home / "plugins" / "own" / "kernel" / "cockpitlib" / "cli.py").write_text("", encoding="utf-8")
    (home / "plugins" / "loose").mkdir()
    (home / "known-providers").write_text("fixture-a\n# a note\n", encoding="utf-8")
    (home / "config.yaml").write_text(
        "model:\n  default: large\n  provider: fixture-b\nkeys:\n  token: s3cret-value\n", encoding="utf-8"
    )
    (home / "auth.json").write_text("{}", encoding="utf-8")
    tool.copy_home_bits(str(home), str(tmp_path / "copy"), 1 << 20)
    copied = sorted(
        os.path.relpath(os.path.join(top, name), tmp_path / "copy")
        for top, dirs, files in os.walk(tmp_path / "copy")
        for name in [*files, *[d for d in dirs if not os.listdir(os.path.join(top, d))]]
    )
    assert copied == [
        "known-providers",
        "plugins/ledger-view/cockpit_pack.py",
        "plugins/ledger-view/plugin.yaml",
        "plugins/model-providers/fixture-c",
        "plugins/own/plugin.yaml",
    ]
    assert (tmp_path / "copy" / "known-providers").read_text(
        encoding="utf-8"
    ) == "fixture-a\nfixture-b\n"  # the provider, not the keys beside it


def test_differences_name_the_json_path_and_an_allow_file_excuses_only_what_it_names(tmp_path):
    left = {"rows": [{"id": 1, "status": "pending"}, {"id": 2}], "name": "x", "only": 1}
    right = {"rows": [{"id": 1, "status": "held"}], "name": "x", "more": True}
    assert tool.differences(left, right) == [
        ("$.more", "only in B: true"),
        ("$.only", "only in A: 1"),
        ("$.rows.length", "2 -> 1"),
        ("$.rows[0].status", '"pending" -> "held"'),
    ]
    assert tool.differences(1, True) == [("$", "1 -> true")] and tool.differences({"a": [1, 2]}, {"a": [1, 2]}) == []
    rules = [{"file": "views/outbox/*.json", "path": "$.rows[*].status", "reason": "the new status name"}]
    assert tool.allowed(rules, "views/outbox/list.json", "$.rows[0].status") and not tool.allowed(
        rules, "views/outbox/list.json", "$.name"
    )
    assert not tool.allowed(rules, "views/board/board.json", "$.rows[0].status")
    for index, capture_name in enumerate(("a", "b")):
        folder = tmp_path / capture_name / "views"
        folder.mkdir(parents=True)
        (folder / "one.json").write_text(
            json.dumps({"result": {"status": ["pending", "held"][index], "n": index}}), encoding="utf-8"
        )
        (folder / "same.json").write_text("{}", encoding="utf-8")
        if index:
            (folder / "new.json").write_text("{}", encoding="utf-8")
        files = {
            os.path.relpath(path, tmp_path / capture_name): tool.sha256_file(path)
            for path in tool.walk_files(str(folder))
        }
        tool.write_json(
            str(tmp_path / capture_name / "manifest.json"),
            {
                "version": tool.VERSION,
                "snapshot_digest": "s",
                "clock": 1.0,
                "pack_digest": "p",
                "files": files,
                "skipped": {"route /x": "why"} if index else {},
            },
        )
    found = tool.compare(str(tmp_path / "a"), str(tmp_path / "b"))
    assert found["result"] == "different" and found["different"] == 2 and found["differences"] == 3
    assert found["lines"] == [
        "views/new.json: 1 difference(s)",
        "  $: only in B",
        "views/one.json: 2 difference(s)",
        "  $.result.n: 0 -> 1",
        '  $.result.status: "pending" -> "held"',
        "skipped only in B: route /x (why)",
    ]
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps([{"file": "views/one.json", "path": "$.result.*", "reason": "expected"}]), encoding="utf-8"
    )
    partly = tool.compare(str(tmp_path / "a"), str(tmp_path / "b"), str(allow))
    assert partly["result"] == "different" and partly["allowed"] == 2 and partly["different"] == 1
    allow.write_text(
        json.dumps([{"file": "views/*.json", "path": "$*", "reason": "all of it, reviewed"}]), encoding="utf-8"
    )
    assert tool.compare(str(tmp_path / "a"), str(tmp_path / "b"), str(allow))["result"] == "allowed"
    assert (
        tool.main(["compare", str(tmp_path / "a"), str(tmp_path / "b")]) == 1
        and tool.main(["compare", str(tmp_path / "a"), str(tmp_path / "b"), "--allow", str(allow)]) == 0
    )
    allow.write_text(json.dumps([{"file": "views/*.json", "path": "$*"}]), encoding="utf-8")
    with pytest.raises(tool.ReplayError, match="a reason"):
        tool.compare(str(tmp_path / "a"), str(tmp_path / "b"), str(allow))
    (tmp_path / "a" / "views" / "same.json").write_text("{ }", encoding="utf-8")
    with pytest.raises(tool.ReplayError, match="not the file its manifest names"):
        tool.compare(str(tmp_path / "a"), str(tmp_path / "b"))


def _gh(tmp_path, *argv, reads=None):
    (tmp_path / "reads.json").write_text(json.dumps(reads or {}), encoding="utf-8")
    env = {
        "PATH": os.environ["PATH"],
        "REPLAY_FORGE_READS": str(tmp_path / "reads.json"),
        "REPLAY_CALLS": str(tmp_path / "calls.jsonl"),
        "REPLAY_VIEW": "v",
    }
    return subprocess.run(
        [sys.executable, os.path.join(SUPPORT, "standin_gh.py"), *argv],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_the_replay_forge_answers_recorded_reads_and_refuses_every_write(tmp_path):
    reads = {"login": "dev", "pulls": {"example/api#7": {"number": 7, "title": "the fix"}, "*/web#2": {"number": 2}}}
    assert json.loads(_gh(tmp_path, "api", "repos/example/api/pulls/7", reads=reads).stdout)["title"] == "the fix"
    assert json.loads(_gh(tmp_path, "api", "repos/other/web/pulls/2", reads=reads).stdout) == {"number": 2}
    assert json.loads(_gh(tmp_path, "api", "user", reads=reads).stdout) == {"login": "dev"}
    assert json.loads(_gh(tmp_path, "api", "repos/example/api/issues/7/comments?per_page=100").stdout) == []
    assert json.loads(_gh(tmp_path, "api", "repos/example/api/commits/abc/check-runs").stdout) == {
        "check_runs": [],
        "total_count": 0,
    }
    assert _gh(tmp_path, "api", "-i", "repos/example/api/pulls/7", reads=reads).stdout.startswith("HTTP/2.0 200 OK")
    missing = _gh(tmp_path, "api", "repos/example/api/pulls/9")
    assert missing.returncode == 1 and "no recorded read" in missing.stderr
    (tmp_path / "body.json").write_text(
        json.dumps({"query": "query($o:String!){repository{pullRequest{reviewThreads{nodes{id}}}}}"}), encoding="utf-8"
    )
    assert (
        json.loads(_gh(tmp_path, "api", "graphql", "--input", str(tmp_path / "body.json")).stdout)["data"][
            "repository"
        ]["pullRequest"]["reviewThreads"]["nodes"]
        == []
    )
    (tmp_path / "body.json").write_text(
        json.dumps({"query": "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}"}),
        encoding="utf-8",
    )
    for argv in (
        ["api", "graphql", "--input", str(tmp_path / "body.json")],
        ["api", "repos/example/api/pulls/7", "--method", "PATCH"],
        ["api", "repos/example/api/issues/7/comments", "-f", "body=done"],
        ["pr", "merge", "7"],
        ["release", "create", "v1"],
    ):
        done = _gh(tmp_path, *argv)
        assert done.returncode == 1 and "refused" in done.stderr and done.stdout == "", argv
    assert _gh(tmp_path, "pr", "list", "--json", "number").stdout.strip() == "[]"
    calls = [json.loads(line) for line in open(tmp_path / "calls.jsonl", encoding="utf-8")]
    assert sum(1 for call in calls if call["kind"] == "write") == 5 and all(call["view"] == "v" for call in calls)
    refused = subprocess.run(
        [sys.executable, os.path.join(SUPPORT, "standin_refuse.py"), "kanban", "list"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"], "REPLAY_STANDIN": "hermes", "REPLAY_CALLS": str(tmp_path / "calls.jsonl")},
    )
    assert refused.returncode == 1 and "hermes is not run during a replay" in refused.stderr
    assert json.loads(open(tmp_path / "calls.jsonl", encoding="utf-8").read().splitlines()[-1]) == {
        "tool": "hermes",
        "kind": "refused",
        "what": "kanban list",
        "view": "",
    }


PROBE = """
import json, os, sys
sys.path.insert(0, {support!r})
import driver
clock = driver.Clock(1893574800.0)
tried = []
driver.libraries()
driver.freeze(clock)
driver.deny_network(tried)
driver.sorted_folders()
import datetime, socket, time, urllib.request
found = {{"time": time.time(), "now": datetime.datetime.now(datetime.timezone.utc).isoformat(), "today": datetime.date.today().isoformat(),
         "is": isinstance(datetime.datetime.now(), datetime.date) and isinstance(datetime.datetime.fromisoformat("2001-01-01") + datetime.timedelta(1), datetime.datetime)
               and isinstance(datetime.datetime.now().astimezone(), datetime.datetime) and "yaml" in sys.modules,
         "strftime": time.strftime("%Y-%m-%d"), "listed": os.listdir({folder!r}), "scanned": [entry.name for entry in os.scandir({folder!r})],
         "walked": [name for _top, _dirs, files in os.walk({folder!r}) for name in files]}}
time.sleep(30)
found["after_sleep"] = time.time()
clock.reset()
found["after_reset"] = time.time()
for attempt in (lambda: urllib.request.urlopen("http://example.test/", timeout=2), lambda: socket.create_connection(("127.0.0.1", 9), 1),
                lambda: socket.socket().connect(("127.0.0.1", 9))):
    try:
        attempt()
        found["left"] = True
    except OSError as exc:
        found.setdefault("refused", []).append(type(exc).__name__)
found["tried"] = tried
print(json.dumps(found))
"""


def test_the_driver_freezes_the_clock_denies_the_network_and_lists_folders_in_order(tmp_path):
    for name in ("b.json", "c.json", "a.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", PROBE.format(support=SUPPORT, folder=str(tmp_path))],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"], "TZ": "UTC"},
    )
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout)
    assert (
        found["time"] == 1893574800.0
        and found["now"] == "2030-01-02T09:00:00+00:00"
        and found["today"] == "2030-01-02"
        and found["is"] is True
    )
    assert (
        found["strftime"] == "2030-01-02"
        and found["after_sleep"] == 1893574830.0
        and found["after_reset"] == 1893574800.0
    )
    assert found["listed"] == found["scanned"] == found["walked"] == ["a.json", "b.json", "c.json"]
    assert "left" not in found and len(found["refused"]) == 3 and found["tried"]


def test_the_command_corpus_covers_each_kind_of_command_and_fills_in_the_packs_hosts(tmp_path):
    sys.path.insert(0, SUPPORT)
    import driver

    assert (
        driver.literal_host("app\\.acme\\.example") == "app.acme.example"
        and driver.literal_host("^\\bdb\\.example\\.test$") == "db.example.test"
    )
    pack = tmp_path / "pack"
    shutil.copytree(os.path.join(ROOT, "packs", "acme"), pack)
    egress = pack / "egress.yaml"
    egress.write_text(
        egress.read_text(encoding="utf-8").replace(
            '  - "app\\\\.acme\\\\.example"', '  - "app\\\\.acme\\\\.example"\n  - "db\\\\.acme\\\\.example"'
        ),
        encoding="utf-8",
    )
    job = {
        "pack": str(pack / "pack.yaml"),
        "commands": os.path.join(SUPPORT, "commands.txt"),
        "env": {
            "COCKPIT_WORKSPACE": "/ws",
            "COCKPIT_HERMES_HOME": "/home",
            "COCKPIT_WT": "/wt",
            "COCKPIT_VOLUMES": "/vol",
        },
    }
    found = driver.corpus(job)
    commands = [command for _key, command in found]
    assert len({key for key, _command in found}) == len(found) >= 100 and not [
        command
        for command in commands
        if "{" in command
        and "}" in command
        and '{"' not in command
        and "{ " not in command
        and "{threadId" not in command
    ]
    assert (
        "curl https://app.acme.example/" in commands
        and "curl https://db.acme.example/" in commands
        and "cat /home/vault/passwords.json" in commands
    )
    assert "gh api repos/acme/api/pulls/7" in commands and "git push" in commands and "ls" in commands
    lines = [
        line
        for line in open(os.path.join(SUPPORT, "commands.txt"), encoding="utf-8")
        if line.strip() and not line.startswith("#")
    ]
    assert 80 <= len(lines)
