# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A draft kept beside an intent is bound to its endorsement: the publish refuses a draft that changed since, an amend
asks for a new endorsement, and an intent endorsed before digests were kept publishes as it always did."""

import hashlib
import os

import pytest

from cockpitlib import publish
from cockpitlib.errors import CockpitError
from cockpitlib.intents import load as load_intent
from cockpitlib.intents import save
from cockpitlib.outbox import amend, confirm, create, draft_digests, endorse, hold
from cockpitlib.pack import load
from cockpitlib.paths import workspace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _draft(name: str, text: str) -> str:
    path = os.path.join(workspace(), name)
    open(path, "w", encoding="utf-8").write(text)
    return path


def _comment(pack, monkeypatch, text="the reviewed words"):
    """A comment intent with a draft body, and a publisher that only says what it would send."""
    sent = []

    def publisher(pack, intent, forge, dry_run):
        sent.append(publish._text(intent["payload"]))
        return "https://forge.example.test/pull/1#comment", "sent"

    monkeypatch.setitem(publish.FORGE, "pr-comment", publisher)
    ticket = f"{pack['tracker']['project']}-3901"
    repo = pack["repos"]["repos"][0]["name"]
    row = create(
        pack, ticket, "pr-comment", "c1", "a note", {"repo": repo, "number": 1, "body_file": _draft("draft.md", text)}
    )
    return row, sent


def _kept(row) -> str:
    return os.path.join(workspace(), load_intent(row["id"])["payload"]["body_file"])


def _publish(row, pack):
    return publish.execute(load_intent(row["id"]), forge=object(), tracker=object(), pack=pack)


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_endorsement_keeps_the_digest_of_the_draft_it_read(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, _sent = _comment(pack, monkeypatch)
    endorsed = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    assert endorsed["endorsement"]["files"] == {"body_file": hashlib.sha256(b"the reviewed words").hexdigest()}
    assert load_intent(row["id"])["endorsement"]["files"] == endorsed["endorsement"]["files"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_draft_changed_after_the_endorsement_is_not_published(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent = _comment(pack, monkeypatch)
    endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    open(_kept(row), "w", encoding="utf-8").write("other words, written after the endorsement")
    with pytest.raises(CockpitError, match=f"{row['id']}: the body changed after it was endorsed: endorse it again"):
        _publish(row, pack)
    with pytest.raises(CockpitError, match="the body changed after it was endorsed"):
        publish.execute(load_intent(row["id"]), forge=object(), tracker=object(), pack=pack, dry_run=True)
    assert sent == [] and load_intent(row["id"])["status"] == "endorsed" and "receipt" not in load_intent(row["id"])
    os.remove(_kept(row))
    with pytest.raises(CockpitError, match="the body changed after it was endorsed"):
        _publish(row, pack)
    open(_kept(row), "w", encoding="utf-8").write(
        "the reviewed words"
    )  # the endorsed words again: the same intent goes out
    assert _publish(row, pack)["ok"] and sent == ["the reviewed words"]
    assert load_intent(row["id"])["status"] == "published"


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_untouched_draft_is_published_as_endorsed(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent = _comment(pack, monkeypatch)
    endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    open(os.path.join(workspace(), "draft.md"), "w", encoding="utf-8").write(
        "the lane's own draft moved on"
    )  # not the kept copy
    assert _publish(row, pack)["ok"] and sent == ["the reviewed words"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_amend_asks_for_a_new_endorsement_and_the_new_one_binds_the_new_draft(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent = _comment(pack, monkeypatch)
    endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    amended = amend(row["id"], payload={"body_file": _draft("second.md", "the second words")}, pack=pack)
    assert amended["status"] == "pending" and "endorsement" not in load_intent(row["id"])
    with pytest.raises(CockpitError, match="is pending, not endorsed"):
        _publish(row, pack)
    again = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    assert again["endorsement"]["files"] == {"body_file": hashlib.sha256(b"the second words").hexdigest()}
    assert _publish(row, pack)["ok"] and sent == ["the second words"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_hold_drops_the_digests_and_the_humans_confirm_keeps_new_ones(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent = _comment(pack, monkeypatch)
    endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    hold(row["id"], "commits by another author", waits="human")
    assert "endorsement" not in load_intent(row["id"])
    open(_kept(row), "w", encoding="utf-8").write("words the human read while it was held")
    confirmed = confirm(row["id"], pack=pack)
    assert confirmed["endorsement"]["by"] == "owner"
    assert confirmed["endorsement"]["files"] == {
        "body_file": hashlib.sha256(b"words the human read while it was held").hexdigest()
    }
    open(_kept(row), "w", encoding="utf-8").write("changed after the human confirmed")
    with pytest.raises(CockpitError, match="the body changed after it was endorsed"):
        _publish(row, pack)
    assert sent == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_endorsed_before_digests_were_kept_publishes_as_before(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    row, sent = _comment(pack, monkeypatch)
    endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    old = load_intent(row["id"])
    del old["endorsement"]["files"]  # the record an earlier kernel wrote
    save(old)
    before = open(
        os.path.join(os.path.dirname(_kept(row)), os.path.basename(row["id"]) + ".json"), encoding="utf-8"
    ).read()
    open(_kept(row), "w", encoding="utf-8").write("edited, with no digest to compare")
    assert publish._refuse(load_intent(row["id"]), pack, False) is None
    assert (
        open(os.path.join(os.path.dirname(_kept(row)), os.path.basename(row["id"]) + ".json"), encoding="utf-8").read()
        == before
    )
    assert _publish(row, pack)["ok"] and sent == ["edited, with no digest to compare"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_intent_with_no_draft_has_no_digests_and_publishes(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    monkeypatch.setitem(
        publish.FORGE, "pr-comment", lambda pack, intent, forge, dry_run: ("https://forge.example.test/pull/1", "sent")
    )
    row = create(
        pack,
        f"{pack['tracker']['project']}-3902",
        "pr-comment",
        "c1",
        "a note",
        {"repo": pack["repos"]["repos"][0]["name"], "number": 1, "body": "inline"},
    )
    endorsed = endorse(row["id"], "low", "", "gatekeeper", "fixture-a", "fixture-large", pack=pack)
    assert "files" not in endorsed["endorsement"]
    assert _publish(row, pack)["ok"]


def test_every_draft_field_is_digested_and_a_missing_one_is_seen(env):
    one, two, three = _draft("a.md", "body"), _draft("t.json", "[]"), _draft("p.json", "[1]")
    payload = {
        "body_file": "a.md",
        "threads_file": two,
        "patch_comments": "p.json",
        "review_body_update": "gone.md",
        "attach": ["a.md"],
        "body": "inline",
        "repo": "api",
    }
    assert draft_digests(payload) == {
        "body_file": hashlib.sha256(b"body").hexdigest(),
        "threads_file": hashlib.sha256(b"[]").hexdigest(),
        "patch_comments": hashlib.sha256(b"[1]").hexdigest(),
        "review_body_update": "",
    }
    assert draft_digests({}) == {} and draft_digests(None) == {}
    from cockpitlib.outbox import changed_drafts

    kept = draft_digests(payload)
    assert changed_drafts({"payload": payload, "endorsement": {"files": kept}}) == []
    open(three, "w", encoding="utf-8").write("[2]")
    open(one, "w", encoding="utf-8").write("body")
    assert changed_drafts({"payload": payload, "endorsement": {"files": kept}}) == ["patch comments"]
    assert changed_drafts({"payload": {**payload, "patch_file": "a.md"}, "endorsement": {"files": kept}}) == [
        "patch comments",
        "patch",
    ]
    assert changed_drafts({"payload": payload, "endorsement": {}}) == [] and changed_drafts({"payload": payload}) == []
    assert changed_drafts({"payload": payload, "endorsement": {"files": "not a table"}}) == []
