# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plugin API's version check: a plugin names the version it was built for, and every version this kernel still
serves is accepted, so raising API_VERSION does not strand the plugins written before it."""

import json
import os

import pytest

from cockpitlib import plugin_api
from cockpitlib.errors import CockpitError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_pinned_contract_names_the_oldest_api_version_still_served():
    pinned = json.load(open(os.path.join(ROOT, "tests", "contract", "cockpit-api.json"), encoding="utf-8"))
    assert pinned["api_min_supported"] == plugin_api.API_MIN_SUPPORTED, (
        "dropping an old API version is a contract change"
    )
    assert 1 <= plugin_api.API_MIN_SUPPORTED <= plugin_api.API_VERSION


def test_a_plugin_built_for_the_current_api_is_accepted():
    assert plugin_api.require(plugin_api.API_VERSION) is None


def test_a_plugin_built_for_an_older_api_is_accepted_on_a_newer_kernel(monkeypatch):
    monkeypatch.setattr(plugin_api, "API_VERSION", 3)
    for built_for in (1, 2, 3):
        assert plugin_api.require(built_for) is None


def test_a_plugin_built_for_a_newer_api_is_refused_and_told_to_update_cockpit(monkeypatch):
    with pytest.raises(
        CockpitError, match=f"cockpit API {plugin_api.API_VERSION}, not {plugin_api.API_VERSION + 1}: .*update cockpit"
    ):
        plugin_api.require(plugin_api.API_VERSION + 1)


def test_a_plugin_built_for_an_api_below_the_floor_is_refused_and_told_to_update_itself(monkeypatch):
    monkeypatch.setattr(plugin_api, "API_VERSION", 4)
    monkeypatch.setattr(plugin_api, "API_MIN_SUPPORTED", 2)
    assert plugin_api.require(2) is None
    with pytest.raises(CockpitError, match="cockpit API 4, not 1: this cockpit serves 2 and later .update the plugin."):
        plugin_api.require(1)
    with pytest.raises(CockpitError, match="cockpit API 4, not 0"):
        plugin_api.require(0)


@pytest.mark.parametrize("version", ["1", None, [1]])
def test_a_version_that_is_not_a_number_is_refused_as_it_was(version):
    with pytest.raises(CockpitError, match=f"cockpit API {plugin_api.API_VERSION}, not .*is a number"):
        plugin_api.require(version)
