# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Desktop names the tracker on a note by the pack's tracker kind, which the /repos route sends as the kernel
resolves it: a pack that names none is on the default kind, and one that only names a command is on the command kind."""

import pytest

from cockpitlib.pack import load
from cockpitlib.trackers import kind_of
from tests.support.both_packs import PACKS, _client


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_repos_route_sends_the_tracker_kind_the_kernel_resolves(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    page = _client().get("/repos").json()
    assert page["tracker_kind"] == kind_of(pack.get("tracker") or {})
    # every other field of the route is what it was
    assert {"repos", "org", "board", "tracker", "project", "origins", "mermaid_url", "hints"} <= set(page)


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "section, kind",
    [
        (None, "connector"),
        ({}, "connector"),
        ({"kind": "jira"}, "jira"),
        ({"command": ["tracker-tool"]}, "command"),
        ({"kind": "local"}, "local"),
    ],
)
def test_a_pack_without_a_kind_is_on_the_default_and_a_command_alone_means_the_command(
    bare, pack_file, monkeypatch, section, kind
):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = dict(load(pack_file))
    pack["tracker"] = section
    monkeypatch.setattr("dashboard.cockpit.routes.pages._guard", lambda *args, **kwargs: pack)
    assert _client().get("/repos").json()["tracker_kind"] == kind
