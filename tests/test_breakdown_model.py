# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A breakdown row's model is a model id; a description of a level is not passed to the provider as one."""

import pytest

from cockpitlib import decompose


@pytest.mark.parametrize(
    "text, wanted",
    [
        ("sonnet high + advisor", ""),  # what intake wrote: the provider answered 404 for it
        ("sonnet high", ""),
        ("opus, high", ""),
        ("a;b", ""),
        ("", ""),
        (None, ""),
        ("  claude-sonnet-5-5  ", "claude-sonnet-5-5"),
        ("claude-sonnet-5-5@reasoning_effort=high", "claude-sonnet-5-5@reasoning_effort=high"),
        ("anthropic/claude-opus-5-5", "anthropic/claude-opus-5-5"),
    ],
)
def test_only_a_model_id_is_passed_on(text, wanted):
    assert decompose._model_id(text) == wanted


def test_the_checked_row_carries_the_id_or_nothing(monkeypatch):
    from cockpitlib import plan

    monkeypatch.setattr(plan, "decided", lambda ticket: True)
    pack = {"repos": {"repos": [{"name": "api"}, {"name": "web"}]}}
    rows = decompose.check(
        pack,
        "TASK-9",
        {"repos": [{"repo": "api", "model": "sonnet high + advisor"}, {"repo": "web", "model": "claude-sonnet-5-5"}]},
    )
    assert [row["model"] for row in rows] == ["", "claude-sonnet-5-5"]
