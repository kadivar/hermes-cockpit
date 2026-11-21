# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the Desktop bundle carries from a third party is a declared dependency at an exact version, named in
THIRD-PARTY-NOTICES.md with its licence, and no Desktop source asks a content network for code."""

import json
import os
import re

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP = os.path.join(ROOT, "desktop")
PACKAGE = json.load(open(os.path.join(DESKTOP, "package.json"), encoding="utf-8"))
LOCK = json.load(open(os.path.join(DESKTOP, "package-lock.json"), encoding="utf-8"))
NOTICES = open(os.path.join(ROOT, "THIRD-PARTY-NOTICES.md"), encoding="utf-8").read()


def _sources() -> dict:
    found = {}
    for folder, _names, files in os.walk(os.path.join(DESKTOP, "src")):
        for name in files:
            path = os.path.join(folder, name)
            found[os.path.relpath(path, DESKTOP)] = open(path, encoding="utf-8").read()
    return found


def test_every_bundled_package_is_pinned_and_named_with_its_version_and_licence():
    bundled = PACKAGE["dependencies"]
    assert sorted(bundled) == ["@xterm/addon-fit", "@xterm/xterm"]
    for name, version in bundled.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{name} is not pinned to one version"
        locked = LOCK["packages"][f"node_modules/{name}"]
        assert locked["version"] == version and locked["license"] == "MIT" and locked["integrity"].startswith("sha512-")
        assert f"| `{name}` | {version} | MIT | Copyright (c) " in NOTICES, (
            f"{name} {version} is not named in THIRD-PARTY-NOTICES.md"
        )
    assert "The above copyright notice and this permission notice shall be included" in NOTICES


def test_every_package_a_source_imports_is_bundled_or_given_by_the_desktop():
    given = {"react", "react/jsx-runtime", "@hermes/plugin-sdk"}
    imported = set()
    for text in _sources().values():
        imported.update(
            match.group(1)
            for match in re.finditer(r"""(?m)^import\s+(?:[\w{}\s,*$]+\s+from\s+)?['"]([^'".][^'"]*)['"]""", text)
        )
    packages = {
        "/".join(name.split("/")[:2]) if name.startswith("@") else name.split("/")[0] for name in imported - given
    }
    assert packages == set(PACKAGE["dependencies"])


def test_no_desktop_source_loads_code_from_a_content_network():
    for name, text in _sources().items():
        assert not re.search(r"cdn\.jsdelivr|unpkg\.com|cdnjs\.|<script src=|rel=\"stylesheet\" href=", text), name
    bundle = open(os.path.join(DESKTOP, "plugin.js"), encoding="utf-8").read()
    assert "jsdelivr" not in bundle and "e.Terminal=" in bundle
