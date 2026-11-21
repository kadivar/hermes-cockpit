# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The licence is stated once in meaning: every manifest, the notice, the README, the contributor pages and the header
script name the same SPDX expression, and no file names the licence the project carried before."""

import json
import os
import re
import subprocess
import tomllib

import pytest
import yaml

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPDX = "AGPL-3.0-or-later"
# the words of the licence the project carried before it was published, built so this file does not hold them
FORMER = (
    "poly" + "form",
    "non" + "commercial",
    "non-" + "commercial",
    "source" + "-available",
    "source" + " available",
)


def _read(*parts) -> str:
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def test_every_manifest_states_the_same_spdx_expression():
    project = tomllib.loads(_read("pyproject.toml"))["project"]
    stated = {
        "pyproject.toml": project["license"],
        "plugin.yaml": yaml.safe_load(_read("plugin.yaml"))["license"],
        "desktop/package.json": json.loads(_read("desktop", "package.json"))["license"],
        "desktop/package-lock.json": json.loads(_read("desktop", "package-lock.json"))["packages"][""]["license"],
        "dashboard/package.json": json.loads(_read("dashboard", "package.json"))["license"],
        "scripts/headers": re.search(r'(?m)^LICENCE = "([^"]+)"$', _read("scripts", "headers")).group(1),
    }
    assert stated == dict.fromkeys(stated, SPDX)
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    for name in ("desktop/package.json", "dashboard/package.json"):
        assert json.loads(_read(name))["private"] is True


def test_every_page_that_speaks_of_the_licence_names_the_same_one():
    for name in (
        "README.md",
        "COMMERCIAL.md",
        "CONTRIBUTION-TERMS.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "THIRD-PARTY-NOTICES.md",
        "AGENTS.md",
        "docs/contributing/architecture.md",
        "docs/contributing/dependencies.md",
    ):
        assert SPDX in _read(name), f"{name} does not name {SPDX}"
    readme = _read("README.md")
    assert "[LICENSE](LICENSE)" in readme and "[COMMERCIAL.md](COMMERCIAL.md)" in readme
    assert "For the licence, see" not in readme


def test_every_file_is_under_the_projects_licence_but_the_bundle_and_the_starter():
    """REUSE.toml covers what has no header. Two of its entries name another licence, each for a reason the pages give:
    the bundle carries the terminal widget (MIT), and the starter is 0BSD so that a pack made from it is its author's."""
    tables = tomllib.loads(_read("REUSE.toml"))["annotations"]
    other = {
        str(table["path"]): table["SPDX-License-Identifier"]
        for table in tables
        if table["SPDX-License-Identifier"] != SPDX
    }
    assert other == {"desktop/plugin.js": f"{SPDX} AND MIT", "starter/**": "0BSD"}
    assert sorted(os.listdir(os.path.join(ROOT, "LICENSES"))) == ["0BSD.txt", f"{SPDX}.txt", "MIT.txt"]
    official = _read("LICENSES", "0BSD.txt")
    assert official.startswith(
        "Copyright (C) YEAR by AUTHOR EMAIL\n\nPermission to use, copy, modify, and/or distribute"
    )
    assert "with or without fee is hereby granted." in official and official.rstrip().endswith(
        "PERFORMANCE OF THIS SOFTWARE."
    )
    for name in ("NOTICE", "COMMERCIAL.md", "starter/README.md", "docs/contributing/architecture.md"):
        page = " ".join(_read(name).split())
        assert "0BSD" in page and "starter" in page, f"{name} does not say that the starter is under 0BSD"
    assert "so that a pack made from it is yours" in " ".join(_read("NOTICE").split())
    # no file of the starter states a licence of its own: the one statement is REUSE.toml's
    listed = subprocess.run(["git", "ls-files", "-z", "starter"], cwd=ROOT, capture_output=True, check=True).stdout
    for path in filter(None, listed.decode("utf-8").split("\0")):
        assert "SPDX-License-Identifier" not in _read(path), path


def test_no_file_names_the_licence_the_project_carried_before():
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    found = []
    for path in filter(None, listed.split("\0")):
        if path == "LICENSE" or path.startswith("LICENSES/"):
            continue  # a licence's own text uses one of the words
        try:
            text = _read(path).lower()
        except (UnicodeDecodeError, OSError):
            continue
        found += [f"{path}: {word}" for word in FORMER if word in text]
    # the changelog says once what the licence replaced
    assert found == ["CHANGELOG.md: " + FORMER[1]], found


def test_the_commercial_page_offers_both_licences_and_states_no_terms():
    page = _read("COMMERCIAL.md")
    assert (
        "open source" in page
        and "[LICENSE](LICENSE)" in page
        and "[CONTRIBUTION-TERMS.md](CONTRIBUTION-TERMS.md)" in page
    )
    assert "github.com/" in page and "TODO(owner)" not in page and "@" in page
    assert not re.search(r"[$€£]|\b(fee|price|pricing)\b", page, re.I)


def test_the_contribution_terms_agree_with_the_commercial_page():
    cla = " ".join(_read("CONTRIBUTION-TERMS.md").split())
    assert cla.startswith("# How a contribution is licensed **The Maintainer** is ") and "template" not in cla
    assert "You retain all right, title and interest in your contribution." in cla
    assert "under AGPL-3.0-or-later and under any other terms the Maintainer chooses" in cla
    assert "It is **not merged**." in cla and "under the BSD Zero Clause License (0BSD" in cla
    assert "named in `NOTICE`" in cla and "`COMMERCIAL.md`" in cla
    commercial = " ".join(_read("COMMERCIAL.md").split())
    assert (
        "keeps the copyright in their work and grants the maintainer the right to license it under AGPL-3.0-or-later and under other terms"
        in commercial
    )
