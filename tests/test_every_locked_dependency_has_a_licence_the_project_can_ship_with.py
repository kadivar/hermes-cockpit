# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every locked dependency declares a licence the project can be distributed with under AGPL-3.0-or-later, read from
what is installed, and docs/contributing/dependencies.md lists each one with that licence."""

import json
import os
import re
from importlib import metadata

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# SPDX ids a dependency may have. Adding one is the owner's decision: docs/contributing/dependencies.md says why each
# is here.
ALLOWED = {"MIT", "ISC", "0BSD", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "PSF-2.0", "Python-2.0"}
# One package, one licence, one reason on the docs page: never a licence for every package.
REVIEWED = {"certifi": "MPL-2.0", "pathspec": "MPL-2.0"}
# What an older package states in a classifier instead of an expression.
CLASSIFIERS = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
}
PAGE = open(os.path.join(ROOT, "docs", "contributing", "dependencies.md"), encoding="utf-8").read()
NODE_LOCK = json.load(open(os.path.join(ROOT, "desktop", "package-lock.json"), encoding="utf-8"))


def _locked(name: str) -> list:
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return sorted(
            {match.group(1).lower() for match in (re.match(r"^([A-Za-z0-9_.\-]+)==", line) for line in handle) if match}
        )


# the tools' lock too: they are never shipped, and their licences are still read, so the page says what is installed
LOCKS = ("requirements.lock", "requirements-test.lock", "requirements-dev.lock")
PYTHON = sorted({name for lock in LOCKS for name in _locked(lock)})
NODE = sorted(path.split("node_modules/")[-1] for path in NODE_LOCK["packages"] if path)


def _declared(name: str) -> str:
    """The licence an installed Python package states: its expression, else a short licence field, else a classifier."""
    found = metadata.metadata(name)
    if found.get("License-Expression"):
        return found["License-Expression"]
    if found.get("License") and len(found["License"]) < 60 and "\n" not in found["License"]:
        return found["License"]
    named = [CLASSIFIERS[line] for line in found.get_all("Classifier") or [] if line in CLASSIFIERS]
    return " AND ".join(sorted(set(named)))


def _acceptable(name: str, expression: str) -> bool:
    """Whether every part of an expression is allowed: of a choice (OR), one allowed alternative is enough."""
    if not expression:
        return False
    if REVIEWED.get(name) == expression:
        return True
    return all(
        any(choice.strip("() ") in ALLOWED for choice in re.split(r"\s+OR\s+", part))
        for part in re.split(r"\s+AND\s+", expression)
    )


def test_the_rule_reads_an_expression_as_spdx_does():
    assert (
        _acceptable("x", "MIT")
        and _acceptable("x", "Apache-2.0 OR BSD-2-Clause")
        and _acceptable("x", "GPL-3.0-only OR MIT")
    )
    assert _acceptable("x", "MIT AND BSD-3-Clause") and not _acceptable("x", "MIT AND GPL-2.0-only")
    assert not _acceptable("x", "") and not _acceptable("x", "MPL-2.0") and not _acceptable("x", "SSPL-1.0")
    assert _acceptable("certifi", "MPL-2.0") and not _acceptable("certifi", "GPL-2.0-only")


def test_the_lock_files_name_packages():
    assert len(PYTHON) >= 12 and "fastapi" in PYTHON and "pyyaml" in PYTHON
    assert "@xterm/xterm" in NODE and "esbuild" in NODE


@pytest.mark.parametrize("name", PYTHON)
def test_a_locked_python_package_has_a_licence_on_the_list_and_a_row_on_the_page(name):
    try:
        licence = _declared(name)
    except metadata.PackageNotFoundError:
        pytest.skip(f"{name} is locked and not installed here: its licence cannot be read from its metadata")
    assert _acceptable(name, licence), (
        f"{name} declares {licence or 'no licence'}: not on the list in docs/contributing/dependencies.md"
    )
    assert f"| `{name}` | {licence} |" in PAGE, f"docs/contributing/dependencies.md has no row `{name}` with {licence}"


@pytest.mark.parametrize("name", NODE)
def test_a_locked_package_of_the_page_has_a_licence_on_the_list_and_a_row_on_the_page(name):
    manifest = os.path.join(ROOT, "desktop", "node_modules", name, "package.json")
    locked = NODE_LOCK["packages"]["node_modules/" + name]
    if os.path.isfile(manifest):
        licence = json.load(open(manifest, encoding="utf-8")).get("license") or ""
        assert licence == locked.get("license"), (
            f"{name}: installed says {licence}, the lock says {locked.get('license')}"
        )
    elif locked.get("optional") and os.path.isdir(os.path.join(ROOT, "desktop", "node_modules")):
        licence = (
            locked.get("license") or ""
        )  # another platform's program is never installed here: the lock is its record
    else:
        pytest.skip(
            f"{name} is not installed here (run `npm ci` in desktop/): its licence cannot be read from its manifest"
        )
    assert _acceptable(name, licence), f"{name} declares {licence or 'no licence'}"
    row = (
        "| `@esbuild/*` (one per platform, optional) | MIT |"
        if name.startswith("@esbuild/")
        else f"| `{name}` | {licence} |"
    )
    assert row in PAGE, f"docs/contributing/dependencies.md has no row for {name} with {licence}"


def test_every_reviewed_exception_is_explained_on_the_page_and_still_locked():
    for name, licence in REVIEWED.items():
        assert name in PYTHON, f"{name} is no longer locked: remove its exception"
        assert re.search(rf"(?m)^\| `{re.escape(name)}` \| {re.escape(licence)} \| \S.{{40,}}\|$", PAGE)
    for licence in ALLOWED:
        assert f"`{licence}`" in PAGE, f"the page does not say why {licence} is allowed"


def test_the_page_lists_no_package_that_is_not_locked():
    rows = set(re.findall(r"(?m)^\| `([^`*]+)` \| [^|]+ \| (?:run time|tests only|tools only|bundled|build)", PAGE))
    assert rows == set(PYTHON) | {name for name in NODE if not name.startswith("@esbuild/")}
