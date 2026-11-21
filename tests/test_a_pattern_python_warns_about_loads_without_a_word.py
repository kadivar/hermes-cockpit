# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pattern with a `[` inside a set compiles today, and Python warns that it may be read otherwise one day ("possible
nested set"). A pack that carries one loads as it always did, and the load prints no warning; a text that is no pattern
is still refused."""

import os
import re
import shutil
import warnings

import pytest
import yaml

from cockpitlib.errors import PackError
from cockpitlib.pack import compiles, load
from tests.support.both_packs import PACKS

NESTED = "^advice: [[A-Z]+ (OK|FIX)$"


def _copy(tmp_path, pack_file, change) -> str:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    for name in ("pack.yaml", "egress.yaml"):
        raw = yaml.safe_load((folder / name).read_text(encoding="utf-8"))
        change(name, raw)
        (folder / name).write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(folder / "pack.yaml")


def test_python_does_warn_about_such_a_pattern_and_the_check_does_not():
    with pytest.warns(FutureWarning, match="nested set"):
        re.compile(NESTED + "x")  # another text than the one below: a compiled pattern is not compiled again
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compiles(NESTED)
        with pytest.raises(re.error):
            compiles("advice: (")


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_with_such_a_pattern_loads_and_no_warning_leaves_the_load(tmp_path, pack_file, monkeypatch):
    def change(name, raw):
        if name == "pack.yaml":
            raw["advisor"] = {**(raw.get("advisor") or {}), "report_line": NESTED}
        else:
            raw["local_domains"] = [*(raw.get("local_domains") or []), "[[a-z]+\\.test"]

    file = _copy(tmp_path, pack_file, change)
    monkeypatch.setenv("COCKPIT_PACK", file)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pack = load(file)
    assert pack["advisor"]["report_line"] == NESTED and "[[a-z]+\\.test" in pack["egress"]["local_domains"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_text_that_is_no_pattern_is_refused_as_before(tmp_path, pack_file, monkeypatch):
    def change(name, raw):
        if name == "pack.yaml":
            raw["advisor"] = {**(raw.get("advisor") or {}), "report_line": "advice: ("}

    file = _copy(tmp_path, pack_file, change)
    with pytest.raises(PackError, match="advisor.report_line:"):
        load(file)
