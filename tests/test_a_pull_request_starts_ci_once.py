# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pull request starts CI on its own event. A push starts CI only on the branches an installation follows."""

import os

import pytest
import yaml

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ci() -> dict:
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    data["on"] = data.pop(True) if True in data else data.get("on")
    return data


def test_a_pull_request_starts_ci_once_and_a_push_only_on_the_branches_an_installation_follows():
    data = _ci()
    assert data["on"]["pull_request"] is None
    assert data["on"]["push"] == {"branches": ["master", "rc"]}
    assert data["concurrency"]["cancel-in-progress"] is True
