# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""After GitHub refuses a burst twice, every cockpit process leaves it alone for a while: the pause is a file in the
workspace's watch folder. The forge found that folder through an import that named no module, so the file was never
written and never read, and each process went on asking. This test uses the forge's own path, with no stand-in."""

import os
import subprocess

import pytest

from cockpitlib import paths
from cockpitlib.errors import CockpitError
from cockpitlib.forge import Forge

REFUSED = "gh: You have exceeded a secondary rate limit. Please wait a few minutes before you try again. (HTTP 403)"


def _forge(calls, now=1000.0):
    def runner(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", REFUSED)

    forge = Forge({"forge": {"org": "acme"}}, runner=runner)
    forge.pause = lambda seconds: None
    forge.clock = lambda: now
    return forge


def test_the_pause_file_is_in_the_workspaces_watch_folder(env):
    assert Forge._pause_file() == os.path.join(paths.watch_dir(), "forge-pause.json")


def test_a_second_refusal_writes_the_pause_and_another_process_keeps_it_without_asking(env):
    calls = []
    first = _forge(calls)
    with pytest.raises(CockpitError, match="GitHub is refusing requests for a moment"):
        first.get("repos/acme/api/pulls/1")
    assert len(calls) == 2 and os.path.isfile(os.path.join(paths.watch_dir(), "forge-pause.json"))
    assert first._pause_until() == 1000.0 + first.pause_seconds
    asked = []
    second = _forge(asked, now=1010.0)  # another process, a moment later
    with pytest.raises(CockpitError, match="try again after"):
        second.get("repos/acme/api/pulls/2")
    assert asked == []
    later = _forge(asked, now=1000.0 + first.pause_seconds + 1)  # the pause is over: GitHub is asked again
    with pytest.raises(CockpitError):
        later.get("repos/acme/api/pulls/2")
    assert len(asked) == 2
