# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The diff pane's mode against the base branch is named `base`, the one a pane takes when none is named. A mode of
any other name is refused. The commits a rebase brings under a branch are served as commits_base."""

import json
import re

import pytest

from cockpitlib import diffs
from cockpitlib.errors import CockpitError
from tests.support.both_packs import _client
from tests.test_read_only_view_edges import rebased, rebased_repo  # noqa: F401 - the fixtures: a pushed branch, rebased, then extended


def _steady(out) -> str:
    """A pane as text without the age git words each commit with ("3 seconds ago"), which moves between two reads."""
    return re.sub(r"\d+ \w+ ago", "ago", json.dumps(out, sort_keys=True, default=str))


@pytest.mark.parametrize("row", ("step_row", "content_row"))
def test_an_intent_is_read_against_the_base_when_no_mode_is_named(rebased, row):  # noqa: F811
    by_base = diffs.intent_diff({}, rebased[row], rebased["rows"], mode="base")
    unnamed = diffs.intent_diff({}, rebased[row], rebased["rows"])
    assert _steady(by_base) == _steady(unnamed)
    assert by_base["head"] == rebased[row]["payload"]["sha"] and by_base["commits"] and "feature.txt" in by_base["stat"]
    assert "remote" not in by_base  # the base diff, not what the push changes on origin


def test_a_checkout_is_read_against_the_base_when_no_mode_is_named(env, rebased):  # noqa: F811
    client = _client()
    answers = [
        client.get("/diff", params={"ticket": "TASK-100", "repo": "api", **mode}) for mode in ({"mode": "base"}, {})
    ]
    assert [answer.status_code for answer in answers] == [200, 200]
    assert _steady(answers[0].json()) == _steady(answers[1].json())
    assert answers[0].json()["head"] == "HEAD" and "Extend the feature" in answers[0].json()["commits"][0]
    origin = client.get("/diff", params={"ticket": "TASK-100", "repo": "api", "mode": "origin"}).json()
    assert origin["mode"] == "origin" and _steady(origin) != _steady(answers[0].json())


def test_a_pane_with_no_checkout_names_the_mode_it_was_asked_for(env):
    client = _client()
    pane = client.get("/diff", params={"ticket": "TASK-missing", "repo": "api", "mode": "origin"}).json()
    assert pane["mode"] == "origin" and pane["note"].startswith("no worktree")
    assert client.get("/diff", params={"ticket": "TASK-missing", "repo": "api"}).json()["mode"] == "base"


@pytest.mark.parametrize("mode", ("rc", "main", "", "BASE"))
def test_a_mode_of_another_name_is_refused(env, mode):
    with pytest.raises(CockpitError, match="a diff is asked as one of base, origin, change, rebase"):
        diffs.mode_of(mode)
    answer = _client().get("/diff", params={"ticket": "TASK-100", "repo": "api", "mode": mode})
    assert answer.status_code >= 400 and "a diff is asked as one of base, origin, change, rebase" in answer.text
    assert [diffs.mode_of(name) for name in diffs.MODES] == list(diffs.MODES)


def test_the_commits_a_rebase_brings_are_served_as_commits_base(rebased):  # noqa: F811
    rebase = diffs.intent_diff({}, rebased["content_row"], rebased["rows"], mode="rebase")
    assert len(rebase["commits_base"]) == 1 and "Move the base" in rebase["commits_base"][0]
    change = diffs.intent_diff({}, rebased["content_row"], rebased["rows"], mode="change")
    assert change["commits_base"] == []
    origin = diffs.intent_diff({}, rebased["content_row"], rebased["rows"], mode="origin")
    assert len(origin["commits_base"]) == 1
    assert not any("commits_rc" in pane for pane in (rebase, change, origin))


def test_a_branch_origin_does_not_know_has_no_such_commits(rebased):  # noqa: F811
    out = diffs.origin_diff_payload(str(rebased["repo"]), "HEAD", "never-pushed", "main", include_uncommitted=False)
    assert out["remote_exists"] is False and out["commits_base"] == []
