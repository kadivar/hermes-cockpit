# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plugin's manifest states what the code does: the systems it runs on, and the oldest Hermes it was checked against."""

import json
import os
import re

import pytest
import yaml

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


MANIFEST = yaml.safe_load(open(os.path.join(ROOT, "plugin.yaml"), encoding="utf-8"))


def test_the_manifest_names_only_the_systems_the_code_runs_on():
    # the chat terminal needs a pseudo-terminal (pty, termios, fcntl) and the scheduled jobs are shell scripts
    assert MANIFEST["platforms"] == ["linux", "macos"]
    assert "Linux or macOS" in open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()


def test_the_oldest_hermes_the_manifest_asks_for_is_the_oldest_doctor_was_checked_against():
    from cockpitlib import doctor

    asked = re.fullmatch(r">=(\d+)\.(\d+)(?:\.(\d+))?", MANIFEST["requires_hermes"])
    assert asked, MANIFEST["requires_hermes"]
    oldest = min(tuple(int(part) for part in known.split(".")) for known in doctor.HERMES_VERIFIED)
    assert (int(asked.group(1)), int(asked.group(2))) == oldest
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert f"**Hermes** {MANIFEST['requires_hermes'][2:]} or newer" in readme
    # and the shapes the tests hold Hermes to were recorded from a version that old or newer
    recorded = json.load(open(os.path.join(ROOT, "tests", "contract", "hermes-hooks.json"), encoding="utf-8"))[
        "recorded_from"
    ]
    assert MANIFEST["requires_hermes"][2:] in recorded
