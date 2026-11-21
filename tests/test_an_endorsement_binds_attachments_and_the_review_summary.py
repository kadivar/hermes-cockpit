# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the human reviewed is what leaves, for the two things an endorsement did not bind: an attachment (it stays in
the workspace and is read at publish) and the summary of a two-stage review (it is read again when the pending review
is submitted). A record made before either digest was kept publishes exactly as it did, and a relink, which changes
only the order, keeps the endorsement and its digests."""

import hashlib
import json
import os

import pytest

from cockpitlib import publish
from cockpitlib.errors import CockpitError
from cockpitlib.intents import load as load_intent
from cockpitlib.intents import save
from cockpitlib.outbox import attachment_digests, changed_attachments, create, endorse, relink
from cockpitlib.pack import load
from cockpitlib.paths import workspace
from tests.support.both_packs import PACKS


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file(relative: str, data: bytes) -> str:
    path = os.path.join(workspace(), relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    return path


def _ready(pack, ticket, kind, payload) -> dict:
    return endorse(
        create(pack, ticket, kind, "c1", "a note", payload)["id"],
        "low",
        "",
        "gatekeeper",
        "fixture-a",
        "fixture-large",
        pack=pack,
    )


def _attached(pack, monkeypatch, number=4101):
    """An endorsed tracker comment with two attachments, and a publisher that only says what it would upload."""
    sent = []

    def publisher(pack, intent, forge, dry_run, tracker):
        sent.append({path: open(os.path.join(workspace(), path), "rb").read() for path in intent["payload"]["attach"]})
        return "https://tracker.example.test/browse/1", "sent"

    monkeypatch.setitem(publish.TRACKER, "tracker-comment", publisher)
    ticket = f"{pack['tracker']['project']}-{number}"
    folder = f"{pack['records_dir']}/qa/{ticket}"
    shot, video = _file(f"{folder}/row-1.png", b"the screenshot"), _file(f"{folder}/row-1.mp4", b"the video")
    row = _ready(pack, ticket, "tracker-comment", {"issue": ticket, "body": "the run", "attach": [shot, video]})
    return row, sent, (f"{folder}/row-1.png", f"{folder}/row-1.mp4")


def _publish(row, pack):
    return publish.execute(load_intent(row["id"]), forge=object(), tracker=object(), pack=pack)


# ---------- attachments ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_endorsement_keeps_the_digest_of_each_attachment(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, _sent, (shot, video) = _attached(pack, monkeypatch)
    assert row["endorsement"]["attachments"] == {shot: _sha(b"the screenshot"), video: _sha(b"the video")}
    assert load_intent(row["id"])["endorsement"]["attachments"] == row["endorsement"]["attachments"]
    assert "files" not in row["endorsement"], "an attachment is not a draft: the drafts' table is as it was"


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_attachment_changed_after_the_endorsement_is_not_published(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent, (shot, _video) = _attached(pack, monkeypatch)
    _file(shot, b"another picture, written after the endorsement")
    refusal = f"{row['id']}: an attachment changed after it was endorsed: endorse it again \\({shot}\\)"
    with pytest.raises(CockpitError, match=refusal):
        _publish(row, pack)
    with pytest.raises(CockpitError, match="an attachment changed after it was endorsed"):
        publish.execute(load_intent(row["id"]), forge=object(), tracker=object(), pack=pack, dry_run=True)
    assert sent == [] and load_intent(row["id"])["status"] == "endorsed" and "receipt" not in load_intent(row["id"])
    _file(shot, b"the screenshot")  # the endorsed bytes again: the same intent goes out
    assert _publish(row, pack)["ok"] and sent[0][shot] == b"the screenshot"


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_attachment_that_vanished_after_the_endorsement_is_not_published(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent, (_shot, video) = _attached(pack, monkeypatch)
    os.remove(os.path.join(workspace(), video))
    with pytest.raises(
        CockpitError, match=f"an attachment changed after it was endorsed: endorse it again \\({video}\\)"
    ):
        _publish(row, pack)
    assert sent == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_untouched_attachments_are_published_as_endorsed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent, (shot, video) = _attached(pack, monkeypatch)
    assert _publish(row, pack)["ok"] and sent == [{shot: b"the screenshot", video: b"the video"}]
    assert load_intent(row["id"])["status"] == "published"


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_endorsed_before_attachments_were_digested_publishes_as_before(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent, (shot, _video) = _attached(pack, monkeypatch)
    old = load_intent(row["id"])
    del old["endorsement"]["attachments"]  # the record an earlier kernel wrote
    save(old)
    _file(shot, b"edited, with no digest to compare")
    assert publish._refuse(load_intent(row["id"]), pack, False) is None
    assert _publish(row, pack)["ok"] and sent[0][shot] == b"edited, with no digest to compare"


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_with_no_attachment_keeps_no_attachment_digests(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-4102"
    row = _ready(pack, ticket, "tracker-comment", {"issue": ticket, "body": "inline"})
    assert "attachments" not in row["endorsement"]
    assert changed_attachments(row) == [] and changed_attachments({"payload": {"attach": ["x"]}}) == []
    assert changed_attachments({"payload": {"attach": ["x"]}, "endorsement": {"attachments": "not a table"}}) == []
    assert attachment_digests(None) == {} and attachment_digests({"attach": "not a list"}) == {}


# ---------- the second stage of a review ----------


def _review(pack, env, number=6):
    """A review with a drafted summary, endorsed and posted as a pending review (stage one)."""
    from tests.support import fake_gh

    org, repo = pack["forge"]["org"], pack["repos"]["repos"][0]["name"]
    full = f"{org}/{repo}"
    ticket = f"{pack['tracker']['project']}-4103"
    head = "9" * 40
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[full])
    fake_gh.pull(full, number, f"work/{ticket}", head)
    threads = env["workspace"] / "threads.json"
    threads.write_text(json.dumps([{"path": "a.py", "line": 2, "body": "one"}]), encoding="utf-8")
    summary = env["workspace"] / "summary.md"
    summary.write_text("the summary the human read", encoding="utf-8")
    row = _ready(
        pack,
        ticket,
        "pr-review-submit",
        {
            "repo": repo,
            "number": number,
            "sha": head,
            "threads_file": str(threads),
            "body_file": str(summary),
            "event": "COMMENT",
        },
    )
    assert publish.execute(row, pack=pack)["stage"] == "pending"
    posted = load_intent(row["id"])
    assert posted["status"] == "posted"

    def shown() -> dict:
        return fake_gh.state()["repos"][full]["pulls"][str(number)]["reviews"][str(posted["review"]["id"])]

    return posted, os.path.join(workspace(), posted["payload"]["body_file"]), shown


@pytest.mark.parametrize("pack_file", PACKS)
def test_posting_a_pending_review_keeps_the_digest_of_the_summary_the_human_published(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    posted, _kept, _shown = _review(load(pack_file), env)
    assert posted["review"]["files"] == {"body_file": _sha(b"the summary the human read")}
    assert posted["review"]["files"]["body_file"] == posted["endorsement"]["files"]["body_file"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_summary_changed_after_stage_one_is_not_submitted(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    posted, kept, shown = _review(pack, env)
    open(kept, "w", encoding="utf-8").write("other words, written while the review was pending")
    with pytest.raises(CockpitError, match=f"{posted['id']}: the body changed after its pending review was posted"):
        publish.execute(load_intent(posted["id"]), pack=pack)
    with pytest.raises(CockpitError, match="the body changed after its pending review was posted"):
        publish.execute(load_intent(posted["id"]), pack=pack, dry_run=True)
    os.remove(kept)
    with pytest.raises(CockpitError, match="the body changed after its pending review was posted"):
        publish.submit_review(load_intent(posted["id"]), publish.forge_for(pack), pack=pack)
    assert shown()["state"] == "PENDING" and load_intent(posted["id"])["status"] == "posted"
    open(kept, "w", encoding="utf-8").write("the summary the human read")
    assert publish.execute(load_intent(posted["id"]), pack=pack)["ok"]
    assert shown()["state"] == "COMMENTED" and shown()["body"] == "the summary the human read"
    assert load_intent(posted["id"])["status"] == "published"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_summary_the_human_gives_at_stage_two_is_theirs_and_is_not_compared(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    posted, kept, shown = _review(pack, env)
    open(kept, "w", encoding="utf-8").write("a draft that moved on")
    receipt = publish.submit_review(
        load_intent(posted["id"]), publish.forge_for(pack), body="the human's own closing words", pack=pack
    )
    assert receipt["ok"] and shown()["body"] == "the human's own closing words"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_review_posted_before_its_summary_was_digested_is_submitted_as_before(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    posted, kept, shown = _review(pack, env)
    del posted["review"]["files"]  # the record an earlier kernel wrote
    save(posted)
    open(kept, "w", encoding="utf-8").write("edited, with no digest to compare")
    assert publish.execute(load_intent(posted["id"]), pack=pack)["ok"]
    assert shown()["body"] == "edited, with no digest to compare"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_review_with_an_inline_summary_keeps_no_digest_and_is_submitted(env, pack_file, monkeypatch):
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    org, repo = pack["forge"]["org"], pack["repos"]["repos"][0]["name"]
    ticket = f"{pack['tracker']['project']}-4104"
    fake_gh.setup(me=pack["forge"]["human_login"], repos=[f"{org}/{repo}"])
    fake_gh.pull(f"{org}/{repo}", 8, f"work/{ticket}", "7" * 40)
    row = _ready(
        pack,
        ticket,
        "pr-review-submit",
        {"repo": repo, "number": 8, "sha": "7" * 40, "body": "inline words", "event": "COMMENT"},
    )
    assert publish.execute(row, pack=pack)["stage"] == "pending"
    assert "files" not in load_intent(row["id"])["review"]
    assert publish.execute(load_intent(row["id"]), pack=pack)["ok"]


# ---------- a relink keeps the endorsement ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_relinked_intent_keeps_its_digests_and_is_still_held_to_them(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    sent = []

    def publisher(pack, intent, forge, dry_run, tracker):
        sent.append((publish._text(intent["payload"]), sorted(intent["payload"].get("attach") or [])))
        return "https://tracker.example.test/browse/1", "sent"

    monkeypatch.setitem(publish.TRACKER, "tracker-comment", publisher)
    ticket = f"{pack['tracker']['project']}-4105"
    folder = f"{pack['records_dir']}/qa/{ticket}"
    shot = _file(f"{folder}/row-2.png", b"the screenshot")
    draft = _file("second.md", b"the reviewed words")
    first = _ready(pack, ticket, "tracker-comment", {"issue": ticket, "body": "the first"})
    second = _ready(pack, ticket, "tracker-comment", {"issue": ticket, "body_file": draft, "attach": [shot]})
    before = dict(second["endorsement"])
    assert before["files"] == {"body_file": _sha(b"the reviewed words")} and before["attachments"] == {
        f"{folder}/row-2.png": _sha(b"the screenshot")
    }
    moved = relink(second["id"], first["id"])
    assert moved["status"] == "endorsed" and moved["payload"]["waits_for"] == first["id"]
    assert load_intent(second["id"])["endorsement"] == before, (
        "only the order changed: the endorsement and its digests stay"
    )
    assert _publish(first, pack)["ok"]
    kept = os.path.join(workspace(), load_intent(second["id"])["payload"]["body_file"])
    open(kept, "w", encoding="utf-8").write("changed after the relink")
    with pytest.raises(CockpitError, match="the body changed after it was endorsed: endorse it again"):
        _publish(second, pack)
    open(kept, "w", encoding="utf-8").write("the reviewed words")
    _file(f"{folder}/row-2.png", b"another picture")
    with pytest.raises(CockpitError, match="an attachment changed after it was endorsed: endorse it again"):
        _publish(second, pack)
    _file(f"{folder}/row-2.png", b"the screenshot")
    assert _publish(second, pack)["ok"] and sent[-1] == ("the reviewed words", [f"{folder}/row-2.png"])
