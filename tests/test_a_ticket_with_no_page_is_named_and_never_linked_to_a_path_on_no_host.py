# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""tracker.browse gives a ticket's page, or nothing when none can be built: a page spelled from the tracker's address by
a pack that gives no address was `/browse/<key>`, a path on no host. The standup note then names the ticket without a
link, and the two review messages leave the line out."""

import pytest

from cockpitlib import gate, notify, standup_note, tracker, trackers
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from cockpitlib.trackers import base
from tests.support.both_packs import PACKS

NO_ADDRESS = {"tracker": {"kind": "command", "command": "bin/tracker"}}


def _refusing(monkeypatch):
    def refuse(config, dry_run=False, pack=None):
        raise CockpitError("that key is no ticket of this tracker")

    monkeypatch.setattr(trackers, "make", refuse)


def test_a_page_that_needs_an_address_the_pack_does_not_give_is_no_page(monkeypatch):
    _refusing(monkeypatch)
    assert tracker.browse(NO_ADDRESS, "TASK-100") == ""
    assert tracker.browse({"tracker": {"kind": "command", "url": "  /  "}}, "TASK-100") == ""
    # with an address, the page a tracker that cannot be made spells from its settings is still given
    assert tracker.browse({"tracker": {"url": "https://tracker.example.test"}}, "TASK-100") == (
        "https://tracker.example.test/browse/TASK-100"
    )


def test_a_page_template_that_needs_no_address_is_filled_as_the_pack_wrote_it(monkeypatch):
    _refusing(monkeypatch)
    config = {"tracker": {"kind": "command", "browse_url": "https://tickets.example.test/t/{number}"}}
    assert tracker.browse(config, "TASK-100") == "https://tickets.example.test/t/100"
    assert tracker.browse({"tracker": {"kind": "command", "browse_url": "{url}/t/{key}"}}, "TASK-100") == ""


def test_a_tracker_that_is_made_and_spells_its_page_without_an_address_gives_none(monkeypatch):
    class Made(base.Tracker):
        pass

    monkeypatch.setattr(trackers, "make", lambda config, dry_run=False, pack=None: Made(config))
    assert Made(NO_ADDRESS["tracker"]).browse_url("TASK-100") == "/browse/TASK-100"  # the protocol's own spelling
    assert tracker.browse(NO_ADDRESS, "TASK-100") == ""

    class Elsewhere(base.Tracker):
        def browse_url(self, key):
            return f"file:///tickets/{key}.md"

    monkeypatch.setattr(trackers, "make", lambda config, dry_run=False, pack=None: Elsewhere(config))
    assert tracker.browse(NO_ADDRESS, "TASK-100") == "file:///tickets/TASK-100.md"


def test_only_a_template_with_the_address_in_it_and_no_address_is_unspelled():
    assert base.unspelled({}) and base.unspelled({"url": ""}) and base.unspelled({"browse_url": "{url}/x/{key}"})
    assert not base.unspelled({"url": "https://tracker.example.test"})
    assert not base.unspelled({"browse_url": "https://tickets.example.test/{key}"})


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("fmt, linked", [("slack", "<{page}|{key}>"), ("md", "[{key}]({page})")])
def test_the_standup_note_links_a_ticket_that_has_a_page_and_names_one_that_has_none(
    env, pack_file, fmt, linked, monkeypatch
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    key = f"{pack['tracker']['project']}-100"
    link, _plink, _head = standup_note._fmt(pack, fmt)
    assert link(key) == linked.format(page=tracker.browse(pack, key), key=key) and "://" in link(key)
    monkeypatch.setattr(tracker, "browse", lambda pack, issue: "")
    link, _plink, _head = standup_note._fmt(pack, fmt)
    assert link(key) == key


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_review_messages_carry_the_tickets_page_or_leave_the_line_out(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    key = f"{pack['tracker']['project']}-100"
    sent = []

    def keep(pack, event, key, body, **fields):
        sent.append((event, body))
        return {"sent": False, "out": "kept"}

    monkeypatch.setattr(notify, "notify", keep)
    monkeypatch.setattr(gate, "ready_state", lambda pack, ticket: {"ready": True, "prs": ["u1", "u2"], "waiting": []})
    page = tracker.browse(pack, key)
    assert "://" in page
    gate.announce(pack, key)
    gate.updated(pack, key, "u1", "0123abc")
    assert sent == [
        ("ready_for_review", f"The ticket's pull requests are ready for review\n{page}\n\nu1\nu2\n"),
        ("updated_after_review", f"The pull request was updated after review\n{page}\n\nu1\n"),
    ]
    del sent[:]
    monkeypatch.setattr(tracker, "browse", lambda pack, issue: "")
    gate.announce(pack, key)
    gate.updated(pack, key, "u1", "0123abc")
    assert [body for _event, body in sent] == [
        "The ticket's pull requests are ready for review\n\nu1\nu2\n",
        "The pull request was updated after review\n\nu1\n",
    ]
