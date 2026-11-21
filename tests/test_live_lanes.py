# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live's job stream: every lane keeps its newest rows, a session is shown once (under the card it was started for),
and a plugin's own Hermes profile (the supervisor's brain) joins the stream under the ticket it was asked about."""

import json
import os

from cockpitlib import lane_feed
from cockpitlib.kanban import place_card
from cockpitlib.pack import load
from cockpitlib.paths import hermes_home
from tests.test_session_card import PACKS, _lane_db


def profile_db(name):
    return os.path.join(hermes_home(), "profiles", name, "state.db")


def register(plugin, data):
    folder = os.path.join(hermes_home(), "cockpit", "live")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{plugin}.json"), "w", encoding="utf-8") as handle:
        handle.write(data if isinstance(data, str) else json.dumps(data))


def test_a_session_is_shown_once_under_the_card_it_was_started_for(bare, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", PACKS[0])
    _lane_db(
        profile_db("tester-1"),
        [
            ("s1", "user", "Run card t_aaa111 (it follows t_bbb222)", None, None, 100.0),
            ("s1", "assistant", "testing aaa", None, None, 101.0),
            ("s2", "user", "Run card t_bbb222", None, None, 102.0),
            ("s2", "assistant", "testing bbb", None, None, 103.0),
            ("s3", "user", "a free question", None, None, 104.0),
            ("s3", "user", "now about t_ccc333 and t_bbb222", None, None, 105.0),
            ("s3", "assistant", "answer", None, None, 106.0),
        ],
    )
    texts = lambda card: [
        row["text"] for row in lane_feed.lane_messages({"id": card, "assignee": "tester-1"}) if row["kind"] == "text"
    ]
    assert texts("t_aaa111") == ["testing aaa"]
    assert texts("t_bbb222") == [
        "testing bbb",
        "answer",
    ]  # s1 only mentions it; s3 was started for no card, so it stays
    assert texts("t_ccc333") == ["answer"]
    shared = {}
    lane_feed.lane_messages({"id": "t_aaa111", "assignee": "tester-1"}, "", shared)
    assert len(shared) == 1 and texts("t_ddd444") == []
    later = lane_feed.lane_messages({"id": "t_bbb222", "assignee": "tester-1"}, since="1970-01-01T00:01:43Z")
    assert [row["text"] for row in later] == [
        "a free question",
        "now about t_ccc333 and t_bbb222",
        "answer",
    ]  # only news is read


def test_one_busy_lane_never_pushes_the_others_out_and_a_row_is_kept_once():
    rows = [{"who": "analyst", "ts": f"2026-10-31T10:{n:02d}:00Z", "kind": "text", "text": str(n)} for n in range(10)]
    rows += [{"who": "tester-1", "ts": "2026-10-31T09:00:00Z", "kind": "text", "text": "old but kept"}] * 2
    rows += [{"who": "", "ts": "2026-10-31T09:30:00Z", "kind": "created", "text": ""}]
    kept = lane_feed.per_lane(rows, limit=3)
    assert [(row["who"], row["text"]) for row in kept] == [
        ("tester-1", "old but kept"),
        ("", ""),
        ("analyst", "7"),
        ("analyst", "8"),
        ("analyst", "9"),
    ]


def test_a_plugin_registers_its_profile_and_bad_registrations_are_left_out(bare):
    assert lane_feed.live_sources() == []
    register("supervisor", {"profile": "supervisor", "label": "brain"})
    register("other", {"profile": "other-profile"})
    register("bad name", {"profile": "x"})
    register("broken", "{not json")
    register("list", "[1]")
    register("escape", {"profile": "../seat", "label": "x"})
    register("blank", {"profile": "p", "label": "  "})
    open(os.path.join(hermes_home(), "cockpit", "live", "notes.txt"), "w").write("x")
    assert lane_feed.live_sources() == [
        {"plugin": "other", "profile": "other-profile", "label": "other"},
        {"plugin": "supervisor", "profile": "supervisor", "label": "brain"},
    ]


def test_the_brain_joins_the_job_stream_under_the_ticket_it_was_asked_about(env, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", PACKS[0])
    pack = load(PACKS[0])
    project = pack["tracker"]["project"]
    card = place_card(pack["board"], f"{project}-501: test", "tester-1", "ready")
    place_card(pack["board"], f"{project}-502: work", "worker-1", "ready")
    _lane_db(
        profile_db("tester-1"),
        [("t1", "user", f"Run card {card}", None, None, 200.0), ("t1", "assistant", "on it", None, None, 201.0)],
    )
    _lane_db(
        profile_db("supervisor"),
        [
            ("b1", "user", f"An analyst's card {card} reports below; the release is {project}-900", None, None, 300.0),
            ("b1", "assistant", '{"answer": "go"}', None, None, 301.0),
            ("b2", "user", f"About {project}-502 and nothing else", None, None, 302.0),
            ("b2", "assistant", '{"answer": "hold"}', None, None, 303.0),
            ("b3", "user", "About a ticket the board does not hold: ZZZ-1", None, None, 304.0),
        ],
    )
    register("supervisor", {"profile": "supervisor", "label": "brain"})
    everything = lane_feed.job_stream(pack, "all")
    brain = [row for row in everything["entries"] if row["who"] == "brain"]
    assert {(row["ticket"], row["card"]) for row in brain} == {(f"{project}-501", card), (f"{project}-502", "")}
    assert (
        "brain" in everything["lanes"]
        and "tester-1" in everything["lanes"]
        and everything["per_lane"] == lane_feed.PER_LANE
    )
    one = lane_feed.job_stream(pack, f"{project}-502")
    assert [row["text"] for row in one["entries"] if row["who"] == "brain" and row["kind"] == "text"] == [
        '{"answer": "hold"}'
    ]
    assert one["lanes"] == ["worker-1", "brain"]
    assert (
        lane_feed.job_stream(pack, f"{project}-501", since=everything["last"])["entries"] == []
    )  # nothing new: nothing read
    # a profile that is gone, not a database, or a stream with no ticket: nothing, and no error
    assert lane_feed.source_messages({"profile": "nobody", "label": "x"}, [], [f"{project}-501"]) == []
    assert lane_feed.source_messages({"profile": "supervisor", "label": "x"}, [], []) == []
    open(profile_db("supervisor"), "w").write("not a database")
    assert lane_feed.source_messages({"profile": "supervisor", "label": "brain"}, [], [f"{project}-501"]) == []
