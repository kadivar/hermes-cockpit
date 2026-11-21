# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A test kickoff's run card closes as done only when every Fail row of its run has a failure video that plays, or the
human saw why there is none. Both fixture packs; a tester phase inside a dev flow and a supervisor card are untouched."""

import os
import shutil
import subprocess

import pytest

from cockpitlib.errors import Conflict
from cockpitlib.pack import load
from tests.support import words
from tests.test_browser_standard import PACKS, _on_card, _run_dir, _test_kickoff

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg and ffprobe check the video")

RESULTS = """# {ticket} · test run

## Summary

| # | Area | Scenario | Result | Evidence | Note |
|---|---|---|---|---|---|
| 1 | Editor | Save keeps the title | ✅ Pass | [shot](evidences/1-save.png) | |
| 3 | Editor | Totals add up | ❌ **Fail** | [shot](evidences/3-totals.png) | {note3} |
| 5 | Catalog | Stars show | ❌ **Fail** | [shot](evidences/5-stars.png) | It shows no stars but it should five |
"""
ALL_PASS = """# {ticket} · test run

## Summary

| # | Area | Scenario | Result | Evidence | Note |
|---|---|---|---|---|---|
| 1 | Editor | Save keeps the title | ✅ Pass | [shot](evidences/1-save.png) | |
"""


def _results(run: str, text: str) -> None:
    """The run's results, written in the bound pack's own words."""
    from cockpitlib.test_flow import bound

    open(os.path.join(run, "test-results.md"), "w", encoding="utf-8").write(words.worded(bound(), text))


def _video(path: str, legacy: bool = False) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    codec = ["-c:v", "mpeg4", "-r", "25"] if legacy else ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "8"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1:r=8", *codec, path], check=True
    )
    return path


def _block(pack, card: str, reason: str) -> None:
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(pack["board"])
    writes.block(card, reason)
    writes.flush()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_fail_row_needs_a_playable_video_before_the_run_card_closes(env, pack_file, monkeypatch):
    from cockpitlib.acts import answer_card
    from cockpitlib.egress import check_tool
    from cockpitlib.test_flow import run_not_ready

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-451"
    card = _test_kickoff(pack, ticket, chrome=False)
    run = _run_dir(pack, ticket)
    _results(run, RESULTS.format(ticket=ticket, note3="It shows 9 but it should 10"))
    videos = os.path.join(run, words.evidence(pack), "videos")
    _on_card(monkeypatch, pack, card)
    refused = check_tool("kanban_complete", {"summary": "run done"})
    assert "row 3" in refused and "row 5" in refused and "row 1" not in refused
    assert f'cockpit record start --session "tester-1-{ticket}"' in refused and "cockpit record stop" in refused
    assert os.path.basename(run) in refused and "video: not possible" in refused
    # the human's go on the review is refused too, and the Inbox offers Send back
    review = words.worded(pack, "Run 001 ready for your review: 1 pass, 2 fail")
    assert run_not_ready(pack, ticket, review, card=card) == ["3·video", "5·video"]
    assert run_not_ready(pack, ticket, review) == []  # without the card: no kind to tell, as before
    _block(pack, card, review)
    with pytest.raises(Conflict, match="3·video"):
        answer_card(pack, card, "go")
    # a file that does not play is no video
    os.makedirs(videos)
    open(os.path.join(videos, "s3-totals-wrong-repro.mp4"), "wb").write(b"\0" * 64)
    refused = check_tool("kanban_complete", {"summary": "run done"})
    assert "row 3" in refused and "does not play" in refused
    # a playable take, and a .mov made by hand for the other row: the card closes
    _video(os.path.join(videos, "s3-totals-wrong-repro-take2.mp4"))
    assert "row 3" not in check_tool("kanban_complete", {"summary": "run done"})
    _video(os.path.join(videos, "5-stars-repro.mov"), legacy=True)
    assert check_tool("kanban_complete", {"summary": "run done"}) == ""
    assert run_not_ready(pack, ticket, review, card=card) == []
    # another scenario's video never stands in for a row (s35 is not s3)
    os.remove(os.path.join(videos, "s3-totals-wrong-repro-take2.mp4"))
    _video(os.path.join(videos, "s35-other-repro.mp4"))
    assert "row 3" in check_tool("kanban_complete", {"summary": "run done"})


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_run_without_a_fail_needs_no_video(env, pack_file, monkeypatch):
    from cockpitlib.egress import check_tool

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-452"
    card = _test_kickoff(pack, ticket, chrome=False)
    _results(_run_dir(pack, ticket), ALL_PASS.format(ticket=ticket))
    _on_card(monkeypatch, pack, card)
    assert check_tool("kanban_complete", {"summary": "all pass"}) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_video_gate_leaves_a_dev_tester_and_a_supervisor_card_alone(env, pack_file, monkeypatch):
    from cockpitlib.egress import check_tool
    from cockpitlib.kanban import place_card
    from cockpitlib.test_flow import run_not_ready

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-453"
    _results(_run_dir(pack, ticket), RESULTS.format(ticket=ticket, note3="It shows 9 but it should 10"))
    chain = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready", kind="tester", ticket=ticket, pack=pack)
    release = place_card(
        pack["board"],
        f"{ticket}: chrome-qa",
        "tester-1",
        "ready",
        kind="test",
        ticket=ticket,
        pack=pack,
        scope="release",
        body="policy: release\n",
    )
    for card in (chain, release):
        _on_card(monkeypatch, pack, card)
        assert check_tool("kanban_complete", {"summary": "done"}) == "", card
        assert not any(
            item.endswith("·video")
            for item in run_not_ready(pack, ticket, words.worded(pack, "Run 001 ready for your review"), card=card)
        )
    worker = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", ticket=ticket, pack=pack)
    _on_card(monkeypatch, pack, worker, lane="worker-1")
    assert "record" not in check_tool("kanban_complete", {"summary": "done"})


@pytest.mark.parametrize("pack_file", PACKS)
def test_video_not_possible_closes_only_after_the_human_saw_why(env, pack_file, monkeypatch):
    from cockpitlib.acts import answer_card
    from cockpitlib.egress import check_tool
    from cockpitlib.test_flow import NO_VIDEO_MARK, run_not_ready

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-454"
    card = _test_kickoff(pack, ticket, chrome=False)
    run = _run_dir(pack, ticket)
    _results(
        run,
        RESULTS.format(
            ticket=ticket,
            note3="It shows 9 but it should 10. video: not possible — the loan of the external browser has expired",
        ),
    )
    _video(os.path.join(run, words.evidence(pack), "videos", "s5-stars-repro.mp4"))
    _on_card(monkeypatch, pack, card)
    # the lane may not pass silently: it asks the human, and the ask is a row on the Inbox (a blocked card)
    refused = check_tool("kanban_complete", {"summary": "run done"})
    assert "row 3" in refused and "loan of the external browser has expired" in refused and NO_VIDEO_MARK in refused
    assert "cockpit record start" not in refused
    assert (
        run_not_ready(pack, ticket, words.worded(pack, "Run 001 ready for your review"), card=card) == []
    )  # the note answers the gate
    _block(
        pack,
        card,
        f"{NO_VIDEO_MARK} for row 3 (the loan of the external browser has expired): go to close the run without it",
    )
    from cockpitlib.kanban import open_card_rows

    assert any(row["id"] == card and row["status"] == "blocked" for row in open_card_rows(pack["board"], pack))
    assert "row 3" in check_tool("kanban_complete", {"summary": "run done"})  # asked, not yet answered
    answer_card(pack, card, "go")
    assert check_tool("kanban_complete", {"summary": "run done"}) == ""


def test_the_tester_soul_and_the_recording_page_name_the_video_gate():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    soul = open(os.path.join(root, "souls", "tester.md"), encoding="utf-8").read()
    page = open(
        os.path.join(root, "docs", "operations", "browser-and-recording.md"), encoding="utf-8"
    ).read()  # where the README's text on it lives now
    for text in (soul, page):
        assert "video: not possible" in text
    assert "cannot close" in soul or "refuses the close" in soul
