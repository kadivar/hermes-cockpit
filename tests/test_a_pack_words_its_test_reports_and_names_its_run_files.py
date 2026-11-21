# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack may word a test report its own way (testflow.title, testflow.banners) and name a run's files its own way
(testflow.evidence_dir, plan_file, results_file). The report is written and read back by the same words. A pack that
sets none of them is read by the kernel's own."""

import os
import shutil

import pytest
import yaml

from cockpitlib import acts, qa_view, record, test_flow
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load
from cockpitlib.paths import qa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
OWN = {
    "title": "Check report",
    "banners": {"ok": "Passed", "not_ok": "Passed with failures", "in_progress": "Running"},
    "evidence_dir": "proof",
    "plan_file": "plan.md",
    "results_file": "results.md",
}
TICKET = "TASK-100"


def _with(pack_file, tmp_path, monkeypatch, block) -> dict:
    """A copy of the fixture pack whose testflow block also has these keys, bound and loaded."""
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    data = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    data["testflow"] = {**data["testflow"], **block}
    (folder / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(folder / "pack.yaml"))
    return load(str(folder / "pack.yaml"))


def _run(pack, text, proof=()) -> str:
    """The ticket's first run folder by the pack's own names, with a results file and proof files; its path."""
    folder = test_flow.next_run_dir(pack, os.path.join(qa(), TICKET))
    os.makedirs(os.path.join(folder, test_flow.evidence_dir(pack)))
    open(os.path.join(folder, test_flow.results_file(pack)), "w", encoding="utf-8").write(text)
    for name in proof:
        open(os.path.join(folder, test_flow.evidence_dir(pack), name), "w", encoding="utf-8").write("x")
    return folder


def _table(pack, *rows) -> str:
    lines = ["# Results", "", "## Summary", "", "| # | Scenario | Result | Evidence | Notes |", "|---|---|---|---|---|"]
    for number, result in enumerate(rows, 1):
        lines.append(
            f"| {number} | Scenario {number} | {result} | [shot]({test_flow.evidence_dir(pack)}/{number}-shot.png) | |"
        )
    return "\n".join(lines) + "\n"


def _post(body, **payload) -> dict:
    return {"type": "tracker-comment", "ticket": TICKET, "payload": {"body": body, **payload}}


def test_a_pack_that_sets_none_of_them_is_read_by_the_kernels_own_words(bare, monkeypatch):
    pack_file = PACKS[1]  # the fixture pack that names none of them
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    assert not set(pack["testflow"]) & set(OWN)
    assert test_flow.title(pack) == test_flow.title(None) == "Test run"
    assert (
        test_flow.banners(pack)
        == test_flow.banners(None)
        == {"ok": "Passed", "not_ok": "Failed", "in_progress": "In progress"}
    )
    assert (test_flow.evidence_dir(pack), test_flow.plan_file(pack), test_flow.results_file(pack)) == (
        "evidence",
        "test-plan.md",
        "test-results.md",
    )
    assert test_flow.BANNERS == ("Failed", "Passed", "In progress")
    passed = [{"n": 1, "result": "✅ Pass", "evidence": "evidence/1.png"}]
    failed = [*passed, {"n": 2, "result": "❌ Fail", "evidence": "evidence/2.png"}]
    for rows, said in (
        (passed, "Passed"),
        (failed, "Failed"),
        ([{"n": 1, "result": "Not run"}], "In progress"),
        ([{"n": 1, "result": "✅ Pass", "evidence": "proof/1.png"}], "In progress"),
    ):
        assert test_flow.banner(rows) == test_flow.banner(rows, pack) == said
    assert test_flow.complete(failed) == test_flow.complete(failed, pack) == "Failed"
    for payload, final in (
        ({"body": "h2. Test run 1\nPassed"}, True),
        ({"body": "## Test run\nFailed"}, True),
        ({"body": "Passed", "probe_title": "Test run"}, True),
        ({"body": "Passed", "comment_from": "TASK-100/001"}, True),
        ({"body": "Test run\nIn progress"}, False),
        ({"body": "Test runner\nPassed"}, False),
        ({"body": "Check report\nAll good", "probe_title": "Check report"}, False),
    ):
        assert test_flow.results_post(payload) is test_flow.results_post(payload, pack) is final, payload
    _run(pack, _table(pack, "✅ Pass", "❌ Fail"), ("1-shot.png", "2-shot.png"))
    assert test_flow.post_problems(pack, _post("Test run\nPassed")) == [
        "the post says 'Passed' but the rows call for 'Failed'"
    ]
    assert test_flow.post_problems(pack, _post("Test run\nFailed")) == []
    assert (
        test_flow.post_problems(pack, _post("Test run\nIn progress"))
        == []
        == test_flow.post_problems(pack, _post("Done with failures"))
    )
    shown = qa_view.ticket(TICKET, pack)
    assert shown["names"] == {
        "title": "Test run",
        "results": "test-results.md",
        "evidence": "evidence",
        "plan": "test-plan.md",
    }
    assert [file["rel"] for file in shown["runs"][0]["files"]] == ["1-shot.png", "2-shot.png"] and shown["runs"][0][
        "results"
    ]["rows"]


def test_a_fixture_pack_that_names_its_own_words_is_read_by_them(bare, monkeypatch):
    pack_file = PACKS[0]
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    written = yaml.safe_load(open(pack_file, encoding="utf-8"))["testflow"]
    assert test_flow.title(pack) == written["title"] != test_flow.title(None)
    assert test_flow.banners(pack) == {**test_flow.banners(None), **written["banners"]} != test_flow.banners(None)
    assert (test_flow.evidence_dir(pack), test_flow.plan_file(pack)) == (written["evidence_dir"], written["plan_file"])
    assert written["review_mark"] != test_flow.REVIEW_MARK
    rows = [{"n": 1, "result": "✅ Pass", "evidence": f"{written['evidence_dir']}/1.png"}]
    assert test_flow.banner(rows, pack) == written["banners"]["ok"] and test_flow.banner(rows) == "In progress"
    post = _post(f"{written['title']}\n{written['banners']['ok']}")
    assert test_flow.results_post(post["payload"], pack) is True and test_flow.results_post(post["payload"]) is False


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_report_is_written_and_read_back_by_the_packs_own_words(bare, pack_file, tmp_path, monkeypatch):
    pack = _with(pack_file, tmp_path, monkeypatch, OWN)
    assert test_flow.title(pack) == "Check report" and test_flow.banners(pack) == OWN["banners"]
    proof = lambda number: {"n": number, "result": "✅ Pass", "evidence": f"proof/{number}.png"}
    assert test_flow.banner([proof(1)], pack) == "Passed"
    assert (
        test_flow.banner([proof(1), {"n": 2, "result": "❌ Fail", "evidence": "proof/2.png"}], pack)
        == "Passed with failures"
    )
    assert test_flow.banner([{"n": 1, "result": "✅ Pass", "evidence": "evidences/1.png"}], pack) == "Running", (
        "the proof is in the pack's folder"
    )
    with pytest.raises(CockpitError, match="unfinished 1·screenshot"):
        test_flow.complete([{"n": 1, "result": "✅ Pass", "evidence": "evidences/1.png"}], pack)
    for payload, final in (
        ({"body": "h2. Check report 1\nPassed"}, True),
        ({"body": "# Check report\nPassed with failures"}, True),
        ({"body": "Passed", "probe_title": "Check report"}, True),
        ({"body": "Check report\nRunning"}, False),
        ({"body": "Check reports\nPassed"}, False),
        ({"body": "Test Run\nTested and Ok", "probe_title": "Test Run"}, False),
        ({"body": "Test Run\nPassed"}, False),
    ):
        assert test_flow.results_post(payload, pack) is final, payload
    _run(pack, _table(pack, "✅ Pass", "❌ Fail"), ("1-shot.png", "2-shot.png"))
    # one banner is the other's first words: the post is read by the longer one it gives
    assert test_flow.post_problems(pack, _post("Check report\nPassed with failures")) == []
    assert test_flow.post_problems(pack, _post("Check report\nPassed")) == [
        "the post says 'Passed' but the rows call for 'Passed with failures'"
    ]
    assert test_flow.post_problems(pack, _post("Check report\nRunning")) == []
    assert test_flow.post_problems(pack, _post("Test Run\nTested and Ok")) == [], (
        "the kernel's own words are no banner of this pack"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_runs_files_are_found_under_the_packs_own_names(bare, pack_file, tmp_path, monkeypatch):
    pack = _with(pack_file, tmp_path, monkeypatch, OWN)
    folder = os.path.join(qa(), TICKET)
    run = _run(pack, _table(pack, "✅ Pass", "❌ Fail"), ("1-shot.png", "2-shot.png"))
    open(os.path.join(run, "test-results.md"), "w", encoding="utf-8").write(
        "the kernel's own name, which this pack does not read\n"
    )
    open(os.path.join(folder, "plan.md"), "w", encoding="utf-8").write("# The plan\n")
    assert "Scenario 2" in test_flow.results_text(pack, TICKET)
    assert test_flow._newest_results(pack, TICKET) == os.path.join(run, "results.md")
    assert test_flow.run_not_ready(pack, TICKET, "It is ready for your review.") == []
    assert [os.path.basename(path) for path in test_flow.failed_media(pack, TICKET)] == ["2-shot.png"]
    shown = qa_view.ticket(TICKET, pack)
    assert shown["names"] == {"title": "Check report", "results": "results.md", "evidence": "proof", "plan": "plan.md"}
    assert [file["rel"] for file in shown["runs"][0]["files"]] == ["1-shot.png", "2-shot.png"]
    assert len(shown["runs"][0]["results"]["rows"]) == 2 and "The plan" in shown["scenarios"]
    assert qa_view.index(pack)["tickets"][0]["scenarios"] == 2
    # the failure video of a row belongs under the pack's evidence folder, and the gate looks for it there
    assert test_flow.failure_videos(pack, TICKET)["missing"] == [("2", "no video")]
    name = os.path.basename(run)
    made = record.video_path(
        pack, os.path.join(qa(), TICKET, name, "proof", "videos", "s2-empty-export-repro.mp4"), TICKET
    )
    assert made["path"].endswith(os.path.join(name, "proof", "videos", "s2-empty-export-repro.mp4"))
    with pytest.raises(CockpitError, match=r"--out must be qa/<ticket>/<run>/proof/videos/<file>"):
        record.video_path(
            pack, os.path.join(qa(), TICKET, name, "evidences", "videos", "s2-empty-export-repro.mp4"), TICKET
        )
    with pytest.raises(CockpitError, match=r"qa/<ticket>/<run>/proof/videos/<scenario>-<slug>-repro.mp4"):
        record.video_path(pack, "", TICKET)
    os.remove(os.path.join(run, "results.md"))
    with pytest.raises(CockpitError, match=f"{TICKET} has no results.md to read the failed rows from"):
        test_flow.failed_media(pack, TICKET, name)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_reader_that_is_handed_no_pack_reads_the_bound_ones_names(bare, pack_file, tmp_path, monkeypatch):
    pack = _with(pack_file, tmp_path, monkeypatch, {"results_file": "results.md", "evidence_dir": "proof"})
    assert test_flow.bound()["testflow"]["results_file"] == "results.md"
    assert acts._results_path(TICKET) == os.path.join(qa(), TICKET, "results.md")
    os.makedirs(os.path.join(qa(), TICKET, "proof"))
    open(os.path.join(qa(), TICKET, "proof", "1-shot.png"), "w", encoding="utf-8").write("x")
    open(os.path.join(qa(), TICKET, "results.md"), "w", encoding="utf-8").write("| 1 | one | Not run | | |\n")
    with pytest.raises(CockpitError):
        acts.open_test_rows(TICKET)  # the open row is read from the pack's file
    assert acts.attach_evidence(pack, TICKET) == ["1-shot.png"] or acts.attach_evidence(pack, TICKET)[0].endswith(
        "/1-shot.png"
    )
    monkeypatch.delenv("COCKPIT_PACK")
    monkeypatch.delenv("COCKPIT_WORKSPACE")
    assert test_flow.bound() is None and test_flow.results_file(test_flow.bound()) == "test-results.md"
    monkeypatch.setenv("COCKPIT_PACK", str(tmp_path / "broken.yaml"))
    (tmp_path / "broken.yaml").write_text("- not a pack\n", encoding="utf-8")
    assert test_flow.bound() is None  # a pack that does not load is read as the kernel's own names


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "block, said",
    [
        ({"title": "two\nlines"}, "testflow.title is the heading of a test report: one line of text"),
        ({"title": " "}, "testflow.title is the heading"),
        ({"title": 7}, "testflow.title is the heading"),
        ({"banners": ["Passed"]}, "testflow.banners takes ok, not_ok and in_progress"),
        ({"banners": {"good": "Passed"}}, "testflow.banners takes ok, not_ok and in_progress"),
        ({"banners": {"ok": ""}}, "each of ok, not_ok and in_progress is one line of text"),
        (
            {"banners": {"ok": "Passed", "not_ok": "Passed"}},
            "the three lines must differ (Passed, Passed, In progress)",
        ),
        ({"banners": {"ok": "In progress"}}, "the three lines must differ"),
        ({"evidence_dir": "a/b"}, "testflow.evidence_dir is one file or folder name"),
        ({"plan_file": ".."}, "testflow.plan_file is one file or folder name"),
        ({"results_file": ""}, "testflow.results_file is one file or folder name"),
        ({"results_file": 3}, "testflow.results_file is one file or folder name"),
        ({"plan_file": "notes.md", "results_file": "notes.md"}, ", notes.md, notes.md)"),
        ({"evidence_dir": "proof", "plan_file": "proof"}, "must be three names (proof, proof, test-results.md)"),
        ({"heading": "x"}, "testflow takes never_write, run_dir and review_mark"),
    ],
)
def test_a_wording_or_a_name_of_the_wrong_shape_is_refused_with_the_right_one(
    bare, pack_file, tmp_path, monkeypatch, block, said
):
    with pytest.raises(PackError) as refused:
        _with(pack_file, tmp_path, monkeypatch, block)
    assert said in str(refused.value)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_key_named_with_no_value_and_a_partial_banner_map_keep_the_kernels_words(
    bare, pack_file, tmp_path, monkeypatch
):
    pack = _with(
        pack_file,
        tmp_path,
        monkeypatch,
        {
            "title": None,
            "banners": {"ok": "Passed", "not_ok": None},
            "evidence_dir": None,
            "plan_file": None,
            "results_file": None,
        },
    )
    assert test_flow.title(pack) == "Test run" and test_flow.banners(pack) == {
        "ok": "Passed",
        "not_ok": "Failed",
        "in_progress": "In progress",
    }
    assert (test_flow.evidence_dir(pack), test_flow.plan_file(pack), test_flow.results_file(pack)) == (
        "evidence",
        "test-plan.md",
        "test-results.md",
    )
