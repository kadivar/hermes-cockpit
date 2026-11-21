# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The README and the pages under docs/ are what a stranger reads first: every relative link points at a file that is
there (and at a heading that is there, when it names one), the README stays one screen long, every recipe has the same
five headings, and the architecture page names every module of the kernel."""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_LINES = 150

# Files a page may link to before they are in the tree. A link to one is allowed only while the file is missing: once
# it is there the link is checked like any other. Empty today: every file the pages link to exists. Add none.
FORWARD = set()
RECIPE_HEADINGS = ["Goal", "The pack lines", "The script contract", "A copy-paste example", "How to test it"]
# Modules the architecture page describes without their file name (a name the docs do not print).
UNNAMED_MODULES = set()

LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)


def _pages() -> list:
    found = [
        os.path.join(ROOT, name)
        for name in ("README.md", "SECURITY.md", "SUPPORT.md", "CHANGELOG.md", "CODE_OF_CONDUCT.md")
    ]
    for folder, _dirs, names in os.walk(os.path.join(ROOT, "docs")):
        found += [os.path.join(folder, name) for name in names if name.endswith(".md")]
    return sorted(path for path in found if os.path.isfile(path))


def _prose(path: str) -> str:
    """A page's text without its code blocks and inline code: a link written inside code is an example, not a link."""
    with open(path, encoding="utf-8") as handle:
        text = FENCE.sub("", handle.read())
    return re.sub(r"`[^`\n]*`", "", text)


def _anchor(heading: str) -> str:
    """A heading as GitHub's renderer names it: lowercase, punctuation dropped, each space a hyphen."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(path: str) -> set:
    with open(path, encoding="utf-8") as handle:
        text = FENCE.sub("", handle.read())
    return {_anchor(match.group(1)) for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", text, re.M)}


def _links(path: str) -> list:
    return [target for target in LINK.findall(_prose(path)) if not re.match(r"[a-z][a-z0-9+.-]*:", target)]


def test_the_readme_and_the_docs_are_there():
    names = {os.path.relpath(path, ROOT) for path in _pages()}
    assert {
        "README.md",
        "SECURITY.md",
        "SUPPORT.md",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "docs/concepts.md",
        "docs/quickstart.md",
        "docs/security.md",
        "docs/desktop-pages.md",
        "docs/plugins.md",
        "docs/customize/README.md",
        "docs/contributing/architecture.md",
        "docs/operations/vault.md",
        "docs/operations/browser-and-recording.md",
        "docs/operations/update.md",
        "docs/operations/worktrees.md",
        "docs/operations/migrating.md",
        "docs/operations/replay.md",
        "docs/reference/pack-keys.md",
    } <= names


@pytest.mark.parametrize("page", [os.path.relpath(path, ROOT) for path in _pages()])
def test_every_relative_link_points_at_a_file_and_a_heading_that_exist(page):
    path = os.path.join(ROOT, page)
    problems = []
    for target in _links(path):
        file, _, anchor = target.partition("#")
        where = os.path.normpath(os.path.join(os.path.dirname(path), file)) if file else path
        name = os.path.relpath(where, ROOT)
        if name in FORWARD and not os.path.exists(where):
            continue
        if not os.path.exists(where):
            problems.append(f"{target}: no file {name}")
        elif anchor and where.endswith(".md") and anchor not in _anchors(where):
            problems.append(f"{target}: no heading #{anchor} in {name}")
    assert problems == []


def test_every_forward_reference_is_still_linked_from_a_page():
    linked = set()
    for path in _pages():
        for target in _links(path):
            file = target.partition("#")[0]
            if file:
                linked.add(os.path.relpath(os.path.normpath(os.path.join(os.path.dirname(path), file)), ROOT))
    assert FORWARD <= linked


def test_the_readme_is_one_screen_long_and_says_what_this_is_first():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    assert len(lines) <= README_LINES
    opening = " ".join(lines[:12])
    assert "https://github.com/NousResearch/hermes-agent" in opening and "plugin" in opening
    assert "The repository is private" not in "\n".join(lines)


def _recipes() -> list:
    folder = os.path.join(ROOT, "docs", "customize")
    return sorted(name for name in os.listdir(folder) if name.endswith(".md") and name != "README.md")


def test_there_is_a_recipe_for_each_extension_point_and_the_index_lists_each():
    recipes = _recipes()
    assert len(recipes) == 19
    with open(os.path.join(ROOT, "docs", "customize", "README.md"), encoding="utf-8") as handle:
        index = handle.read()
    assert [name for name in recipes if f"]({name})" not in index] == []


@pytest.mark.parametrize("recipe", _recipes())
def test_every_recipe_has_the_same_five_headings_in_the_same_order(recipe):
    with open(os.path.join(ROOT, "docs", "customize", recipe), encoding="utf-8") as handle:
        text = FENCE.sub("", handle.read())
    assert re.findall(r"^## (.+?)\s*$", text, re.M) == RECIPE_HEADINGS


def test_the_architecture_page_names_every_module_of_the_kernel_once():
    kernel = os.path.join(ROOT, "kernel", "cockpitlib")
    modules = {name[:-3] for name in os.listdir(kernel) if name.endswith(".py") and name != "__init__.py"}
    modules |= {name + "/" for name in os.listdir(kernel) if os.path.isfile(os.path.join(kernel, name, "__init__.py"))}
    with open(os.path.join(ROOT, "docs", "contributing", "architecture.md"), encoding="utf-8") as handle:
        table = handle.read().split("## The kernel, by area", 1)[1].split("\n## ", 1)[0]
    named = []
    for row in table.splitlines():
        cells = row.split("|")
        if len(cells) > 3 and cells[1].strip().startswith("**"):
            named += re.findall(r"`([^`]+)`", cells[2])
    assert sorted(set(named)) == sorted(named)  # no module in two areas
    assert set(named) - modules == set()  # no module that is not there
    assert modules - set(named) - UNNAMED_MODULES == set()  # none left out
    assert UNNAMED_MODULES <= modules


def test_the_invariants_other_documents_cite_are_numbered_one_to_six():
    with open(os.path.join(ROOT, "docs", "security.md"), encoding="utf-8") as handle:
        section = handle.read().split("## Invariants", 1)[1]
    assert re.findall(r"^(\d)\. \*\*", section, re.M) == ["1", "2", "3", "4", "5", "6"]
