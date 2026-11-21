# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sources of the two pages have no formatter of their own (none is among the Desktop's packages): the one rule
held here is that no line runs past 400 characters, so a change to a view can be read in a diff."""

import os
import subprocess

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 400
FOLDERS = ("desktop/src", "dashboard/src")
# a source that may hold a line past the limit: none; the page's own help texts, one text a line, fit as well
WHOLE_SENTENCES = ()


def too_long(text: str, limit: int = LIMIT) -> list:
    """(line number, length) of every line of a source that runs past the limit."""
    return [(number, len(line)) for number, line in enumerate(text.split("\n"), 1) if len(line) > limit]


def _sources() -> list:
    listed = subprocess.run(["git", "ls-files", *FOLDERS], cwd=ROOT, capture_output=True, text=True, check=True)
    names = [name for name in listed.stdout.split("\n") if name.endswith((".js", ".mjs", ".css"))]
    return [name for name in names if name not in WHOLE_SENTENCES]


def test_the_measure_counts_characters_and_names_the_line():
    assert too_long("a\n" + "é" * 400 + "\n" + "b" * 401) == [(3, 401)]


def test_both_pages_have_sources_to_measure():
    names = _sources()
    assert any(name.startswith("desktop/src/views/") for name in names)
    assert any(name.startswith("dashboard/src/") for name in names)


def test_no_file_is_left_out_and_the_table_of_help_texts_is_measured_too():
    assert WHOLE_SENTENCES == () and "desktop/src/lib/packwords.js" in _sources()
    text = open(os.path.join(ROOT, "desktop/src/lib/packwords.js"), encoding="utf-8").read()
    assert "HINTS" in text and too_long(text) == []


def test_no_line_of_a_page_source_runs_past_the_limit():
    found = {}
    for name in _sources():
        lines = too_long(open(os.path.join(ROOT, name), encoding="utf-8").read())
        if lines:
            found[name] = lines
    assert found == {}, "break these lines (after a comma, or a long sentence into two strings joined with +)"
