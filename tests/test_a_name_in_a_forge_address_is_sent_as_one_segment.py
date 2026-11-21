# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A label, a branch or an id that the GitHub forge puts into an API address is encoded: a label with a space or a
slash is removed under its own name, a branch with a `#` is asked for whole, and an id that carries a path is one
segment and no deeper address. A plain name is sent exactly as it was."""

import subprocess

import pytest

from cockpitlib.forge import Forge
from cockpitlib.forges import github


def _forge():
    calls = []

    def runner(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    return Forge({"forge": {"org": "acme"}}, runner=runner), calls


def _address(call: list) -> str:
    return next(word for word in call if isinstance(word, str) and word.startswith("repos/"))


@pytest.mark.parametrize(
    "label, sent",
    [
        ("review required", "review%20required"),
        ("area/ui", "area%2Fui"),
        ("needs: triage?", "needs%3A%20triage%3F"),
        ("50%", "50%25"),
        ("bug", "bug"),
        ("good-first_issue.v2~", "good-first_issue.v2~"),
    ],
)
def test_a_label_is_removed_under_its_own_name_whatever_it_is_made_of(label, sent):
    forge, calls = _forge()
    forge.remove_label("api", 7, label)
    assert _address(calls[-1]) == f"repos/acme/api/issues/7/labels/{sent}"


def test_a_plain_number_branch_and_commit_are_sent_exactly_as_before():
    forge, calls = _forge()
    forge.pr("api", 12)
    forge.compare("api", "main", "feature/login-form")
    forge.pr_for_head("api", "work/TASK-100", "release/2.x")
    forge.open_prs_for_branch("api", "dependabot/npm_and_yarn/left-pad-1.3.0")
    forge.runs("api", "0123abc")
    assert [_address(call) for call in calls] == [
        "repos/acme/api/pulls/12",
        "repos/acme/api/compare/main...feature/login-form",
        "repos/acme/api/pulls?state=open&head=acme:work/TASK-100&base=release/2.x",
        "repos/acme/api/pulls?state=open&head=acme:dependabot/npm_and_yarn/left-pad-1.3.0",
        "repos/acme/api/actions/runs?head_sha=0123abc&per_page=100",
    ]


def test_a_branch_that_would_end_the_address_or_start_another_field_is_asked_for_whole():
    forge, calls = _forge()
    forge.pr_for_head("api", "fix #1&state=closed", "release 2")
    forge.compare("api", "main", "topic?x#y")
    assert [_address(call) for call in calls] == [
        "repos/acme/api/pulls?state=open&head=acme:fix%20%231%26state%3Dclosed&base=release%202",
        "repos/acme/api/compare/main...topic%3Fx%23y",
    ]


def test_an_id_that_carries_a_path_is_one_segment_and_no_deeper_address():
    forge, calls = _forge()
    forge.pr("api", "1/merge")
    forge.edit_review_comment("api", "5/../../../issues/9", "x")
    assert _address(calls[0]) == "repos/acme/api/pulls/1%2Fmerge"
    assert _address(calls[1]) == "repos/acme/api/pulls/comments/5%2F..%2F..%2F..%2Fissues%2F9"


def test_the_two_encoders_leave_what_needs_no_encoding():
    plain = "AZaz09-._~"
    assert github._seg(plain) == plain and github._ref(plain) == plain and github._seg(42) == "42"
    assert github._seg("a/b c") == "a%2Fb%20c" and github._ref("a/b c") == "a/b%20c"
