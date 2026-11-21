# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A lent login stays lent: the housekeeping's take-back, running beside the approval, does not undo it."""

import os
import time

from cockpitlib import lend

PACK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs", "acme", "pack.yaml")


def _approve(monkeypatch, tmp_path, during_place=None, answer=None):
    from cockpitlib import paths

    monkeypatch.setenv("COCKPIT_WORKSPACE", str(tmp_path))  # the fixture pack, never this machine's own
    monkeypatch.setenv("COCKPIT_PACK", PACK)
    monkeypatch.setattr(paths, "watch_dir", lambda: str(tmp_path))
    monkeypatch.setattr(lend, "watch_dir", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr("cockpitlib.vault.sealed_to", lambda: "FP")
    monkeypatch.setattr(
        "cockpitlib.vault._items",
        lambda: [{"privileged": True, "email": "a@b.test", "origin": "https://x", "secret": "s", "label": "x"}],
    )
    monkeypatch.setattr("cockpitlib.scrub.rebuild", lambda *a, **k: None)
    monkeypatch.setattr(lend, "_drop_previous_lend", lambda card: None)
    monkeypatch.setattr(lend, "_step_for", lambda card, pack=None: "Admin → Email logs")

    def place(*_a, **_k):
        if during_place:
            during_place()
        return "item-1"

    monkeypatch.setattr("cockpitlib.lane_vault.place", place)
    monkeypatch.setattr("cockpitlib.acts.answer_card", answer or (lambda pack, card, text: None))
    return lend.approve("t_card", "tester-3", 1, {"board": "acme"})


def test_the_lend_is_on_record_before_its_copy_is_placed(monkeypatch, tmp_path):
    seen = []
    assert _approve(monkeypatch, tmp_path, during_place=lambda: seen.append(lend._read("admin-lends.json"))) == "lent"
    assert [row["card"] for row in seen[0]] == ["t_card"] and seen[0][0][
        "item"
    ] == ""  # a take-back in between finds it held
    final = lend._read("admin-lends.json")
    assert len(final) == 1 and final[0]["item"] == "item-1" and final[0]["step"] == "Admin → Email logs"


def test_the_approvals_own_answer_is_not_read_as_the_card_blocking_again(monkeypatch, tmp_path):
    clock = {"now": 1_800_000_000}
    monkeypatch.setattr(time, "time", lambda: clock["now"])
    said = {}

    def answer(_pack, _card, _text):
        clock["now"] += 3  # the answer lands seconds after the copy was placed
        said["at"] = clock["now"]

    assert _approve(monkeypatch, tmp_path, answer=answer) == "lent"
    lent_at = lend._read("admin-lends.json")[0]["at"]
    assert lent_at >= said["at"]
    monkeypatch.setattr(lend, "_lent_items", lambda card="": [])
    monkeypatch.setattr("cockpitlib.vault.entry_records", lambda: [])
    restored = []
    monkeypatch.setattr(lend, "_restore_own_login", restored.append)
    # the card is still blocked (the board has not started it again) and its newest comment is the approval's answer
    assert lend.take_back(now=clock["now"] + 20, status_of=lambda card: ("triage", said["at"])) == [] and restored == []
    # a comment after the lend on a blocked card is the lane blocking again: taken back, as before
    assert lend.take_back(now=clock["now"] + 60, status_of=lambda card: ("blocked", lent_at + 30)) == [
        ("t_card", "tester-3", "the card blocked again")
    ]
