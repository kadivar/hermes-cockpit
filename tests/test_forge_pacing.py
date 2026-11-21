# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""GitHub's secondary rate limit refuses a burst with a 403; the forge tries once more, then every process pauses."""

import subprocess

import pytest

from cockpitlib.errors import CockpitError
from cockpitlib.forge import Forge

REFUSED = (
    "gh: ... For more on scraping GitHub and how it may affect your rights, please review our Terms of Service "
    "(HTTP 403)"
)


def _forge(answers, waits, tmp_path, now=1000.0):
    calls = []

    def runner(argv, **_kwargs):
        calls.append(argv)
        code, out, err = answers[min(len(calls), len(answers)) - 1]
        return subprocess.CompletedProcess(argv, code, out, err)

    forge = Forge({"forge": {"org": "acme"}}, runner=runner)
    forge.pause = waits.append
    forge.clock = lambda: now
    forge._pause_file = lambda: str(tmp_path / "watch" / "forge-pause.json")
    return forge, calls


def test_a_refused_burst_is_asked_once_more_after_a_wait_and_then_answers(tmp_path):
    waits = []
    forge, calls = _forge([(1, "", REFUSED), (0, '{"state": "open"}', "")], waits, tmp_path)
    assert forge.get("repos/acme/api/pulls/1") == {"state": "open"}
    assert len(calls) == 2 and waits == [4] and forge._pause_until() == 0.0


def test_a_second_refusal_starts_a_pause_every_call_keeps_until_it_is_over(tmp_path):
    waits = []
    forge, calls = _forge([(1, "", "You have exceeded a secondary rate limit (HTTP 403)")], waits, tmp_path)
    with pytest.raises(CockpitError, match="secondary rate limit, not the hourly quota"):
        forge.get("repos/acme/api/pulls/1")
    assert len(calls) == 2 and forge._pause_until() == 1090.0
    with pytest.raises(CockpitError, match="try again after"):
        forge.get_if_changed("repos/acme/api/pulls/1")
    assert len(calls) == 2  # GitHub was not asked again during the pause
    later, calls_later = _forge([(0, '{"state": "open"}', "")], [], tmp_path, now=1091.0)
    assert later.get("repos/acme/api/pulls/1") == {"state": "open"} and len(calls_later) == 1


def test_another_403_fails_at_once_as_before(tmp_path):
    waits = []
    forge, calls = _forge([(1, "", "Resource not accessible by integration (HTTP 403)")], waits, tmp_path)
    with pytest.raises(CockpitError, match="Resource not accessible"):
        forge.get("repos/acme/api/pulls/1")
    assert len(calls) == 1 and waits == [] and forge._pause_until() == 0.0
