# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every tracked file states its copyright and licence: a source file in its first lines (scripts/headers writes them
by file type), every other file through REUSE.toml. The header never moves a shebang, never changes what a Python file
means, and a second run writes nothing."""

import ast
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import tomllib

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPDX = "AGPL-3.0-or-later"
HOLDER = "2026 Mohammadreza Kadivar"
# What the REUSE tool itself never asks about: the licence texts, and the root LICENSE.
LICENCE_TEXTS = re.compile(r"^(LICENSE|LICENSES/.+)$")


def _script():
    loader = importlib.machinery.SourceFileLoader("headers_script", os.path.join(ROOT, "scripts", "headers"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


HEADERS = _script()
REUSE = tomllib.load(open(os.path.join(ROOT, "REUSE.toml"), "rb"))


def _globs() -> list:
    found = []
    for table in REUSE["annotations"]:
        paths = table["path"]
        found += [(path, table) for path in ([paths] if isinstance(paths, str) else paths)]
    return found


def _pattern(glob: str):
    """A REUSE.toml path as the specification reads it: `*` stays within a folder, `**` crosses folders, a backslash
    makes the next character literal."""
    out, index = "", 0
    while index < len(glob):
        char = glob[index]
        if char == "\\" and index + 1 < len(glob):
            out, index = out + re.escape(glob[index + 1]), index + 2
        elif glob.startswith("**", index):
            out, index = out + ".*", index + 2
        elif char == "*":
            out, index = out + "[^/]*", index + 1
        else:
            out, index = out + re.escape(char), index + 1
    return re.compile(out)


def _annotation(path: str):
    """The table that covers a path: the last one that matches, as the specification says."""
    found = None
    for glob, table in _globs():
        if _pattern(glob).fullmatch(path):
            found = table
    return found


def _text(path: str):
    try:
        return open(os.path.join(ROOT, path), encoding="utf-8").read()
    except UnicodeDecodeError:
        return None


def test_the_glob_reading_is_the_specifications():
    assert _pattern("*.md").fullmatch("README.md") and not _pattern("*.md").fullmatch("docs/a.md")
    assert _pattern("**/*.md").fullmatch("docs/x/a.md") and not _pattern("**/*.md").fullmatch("README.md")
    assert _pattern("starter/**").fullmatch("starter/bin/slot") and not _pattern("starter/**").fullmatch("starters/a")
    assert _pattern("packs/*/files/**").fullmatch("packs/one/files/a.env") and not _pattern(
        "packs/*/files/**"
    ).fullmatch("packs/a/b/files/c")
    assert _pattern(r"a\*b").fullmatch("a*b") and not _pattern(r"a\*b").fullmatch("axb")


def test_no_source_file_lacks_its_header():
    found = subprocess.run(
        [os.path.join(ROOT, "scripts", "headers"), "--check"], check=False, capture_output=True, text=True
    )
    assert found.returncode == 0 and found.stdout.strip() == "headers ok", found.stdout[-2000:]


def test_every_tracked_file_is_headed_or_covered_by_the_reuse_file():
    uncovered, both = [], []
    for path in HEADERS.tracked(ROOT):
        text = _text(path)
        if LICENCE_TEXTS.match(path) or path == "REUSE.toml" or text == "":
            continue
        own = text is not None and HEADERS.headed(text)
        if not own and _annotation(path) is None:
            uncovered.append(path)
        if own and f"SPDX-FileCopyrightText: {HOLDER}" not in text:
            both.append(path)
    assert not uncovered, "neither headed nor matched by REUSE.toml: " + ", ".join(uncovered)
    assert not both, "a licence line without the copyright line: " + ", ".join(both)


def test_every_path_of_the_reuse_file_matches_a_file_and_names_the_holder_and_a_licence_text():
    files = HEADERS.tracked(ROOT)
    assert REUSE["version"] == 1
    for glob, table in _globs():
        assert any(_pattern(glob).fullmatch(path) for path in files), f"REUSE.toml: {glob} matches no file"
        holders = table["SPDX-FileCopyrightText"]
        assert HOLDER in ([holders] if isinstance(holders, str) else holders), glob
        for licence in re.split(r"\s+(?:AND|OR)\s+", table["SPDX-License-Identifier"]):
            assert os.path.isfile(os.path.join(ROOT, "LICENSES", licence + ".txt")), (
                f"LICENSES/{licence}.txt is missing"
            )


def test_a_file_that_is_never_headed_is_covered_whatever_its_type():
    for path in HEADERS.tracked(ROOT):
        if any(path == rule or (rule.endswith("/") and path.startswith(rule)) for rule in HEADERS.UNHEADED):
            assert LICENCE_TEXTS.match(path) or _annotation(path) is not None, path
            assert not HEADERS.headed(_text(path) or ""), f"{path} is headed and should not be"


def test_the_bundle_is_marked_with_both_licences_it_carries():
    table = _annotation("desktop/plugin.js")
    assert table["SPDX-License-Identifier"] == f"{SPDX} AND MIT"
    assert any("xterm.js authors" in holder for holder in table["SPDX-FileCopyrightText"])


def test_the_licence_text_is_the_official_one_and_its_two_copies_are_equal():
    root = open(os.path.join(ROOT, "LICENSE"), "rb").read()
    assert root == open(os.path.join(ROOT, "LICENSES", f"{SPDX}.txt"), "rb").read()
    lines = root.decode("utf-8").splitlines()
    # nothing before the title and nothing after the text's own last line: a notice appended here would stop a code
    # host from recognising the licence
    assert lines[0].strip() == "GNU AFFERO GENERAL PUBLIC LICENSE" and lines[1].strip() == "Version 3, 19 November 2007"
    assert lines[-1] == "<https://www.gnu.org/licenses/>."
    assert "Kadivar" not in root.decode("utf-8") and "Required Notice" not in root.decode("utf-8")
    import hashlib

    assert hashlib.sha256(root).hexdigest() == "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"


def test_the_notice_names_the_holder_the_licence_and_where_other_terms_are():
    notice = open(os.path.join(ROOT, "NOTICE"), encoding="utf-8").read()
    assert f"Copyright (C) {HOLDER}" in notice
    flat = " ".join(notice.split())
    assert (
        "under the terms of the GNU Affero General Public License as published by the Free Software Foundation, "
        "either version 3 of the License, or (at your option) any later version."
    ) in flat
    assert "COMMERCIAL.md" in notice


def test_every_executable_still_opens_with_its_shebang():
    listed = subprocess.run(["git", "ls-files", "-s"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    programs = [line.split("\t", 1)[1] for line in listed.splitlines() if line.startswith("100755")]
    assert len(programs) > 40
    for path in programs:
        assert _text(path).startswith("#!"), f"{path} is executable and its first line is not a shebang"


@pytest.mark.parametrize(
    "path, text, want",
    [
        (
            "a.py",
            '"""Doc."""\nx = 1\n',
            '# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n# SPDX-License-Identifier: AGPL-3.0-or-later\n"""Doc."""\nx = 1\n',
        ),
        (
            "bin/tool",
            '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n"""Doc."""\n',
            '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n# SPDX-License-Identifier: AGPL-3.0-or-later\n"""Doc."""\n',
        ),
        (
            "run.sh",
            "#!/bin/sh\n# why\nexit 0\n",
            "#!/bin/sh\n# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n# SPDX-License-Identifier: AGPL-3.0-or-later\n\n# why\nexit 0\n",
        ),
        (
            "bin/page",
            "#!/usr/bin/env node\nrun()\n",
            "#!/usr/bin/env node\n// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n// SPDX-License-Identifier: AGPL-3.0-or-later\nrun()\n",
        ),
        (
            "a.yaml",
            "# yaml-language-server: $schema=./pack.schema.json\nname: one\n",
            "# yaml-language-server: $schema=./pack.schema.json\n# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n# SPDX-License-Identifier: AGPL-3.0-or-later\nname: one\n",
        ),
        (
            "a.yml",
            "name: one\n",
            "# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n# SPDX-License-Identifier: AGPL-3.0-or-later\nname: one\n",
        ),
        (
            "a.mjs",
            "import x from 'y'\n",
            "// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n// SPDX-License-Identifier: AGPL-3.0-or-later\nimport x from 'y'\n",
        ),
        (
            "a.css",
            ".a{}\n",
            "/* SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar */\n/* SPDX-License-Identifier: AGPL-3.0-or-later */\n.a{}\n",
        ),
        (
            "only-a-shebang",
            "#!/bin/sh",
            "#!/bin/sh\n# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar\n# SPDX-License-Identifier: AGPL-3.0-or-later\n",
        ),
    ],
)
def test_a_header_goes_where_its_file_type_takes_it_and_only_once(path, text, want):
    assert HEADERS.with_header(path, text) == want
    assert HEADERS.with_header(path, want) is None


@pytest.mark.parametrize(
    "path, text",
    [
        ("README.md", "# Title\n"),
        ("data.json", "{}\n"),
        ("words.txt", "one\n"),
        ("no-shebang", "plain\n"),
        ("starter/bin/slot", "#!/bin/sh\n"),
        ("docs/reference/x.yaml", "a: 1\n"),
        ("desktop/plugin.js", "var a\n"),
        ("empty.py", ""),
        ("theirs.js", "// SPDX-License-Identifier: MIT\nvar a\n"),
    ],
)
def test_a_file_that_takes_no_header_is_left_as_it_is(path, text):
    assert HEADERS.with_header(path, text) is None


def test_a_header_changes_nothing_a_python_file_means():
    for path in HEADERS.tracked(ROOT):
        text = _text(path)
        if not path.endswith(".py") or not text or not HEADERS.headed(text):
            continue
        bare = "".join(
            line for line in text.splitlines(keepends=True) if "SPDX-" not in line or not line.startswith("#")
        )
        assert ast.dump(ast.parse(bare)) == ast.dump(ast.parse(text)), path
        assert ast.get_docstring(ast.parse(bare)) == ast.get_docstring(ast.parse(text)), path


def test_the_command_refuses_what_it_does_not_know():
    found = subprocess.run([os.path.join(ROOT, "scripts", "headers")], check=False, capture_output=True, text=True)
    assert found.returncode == 2 and "usage: scripts/headers --check|--write" in found.stderr


def test_write_heads_a_new_file_keeps_its_mode_and_a_second_run_writes_nothing(tmp_path):
    name = os.path.relpath(tmp_path / "probe-tool", ROOT)
    (tmp_path / "probe-tool").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(tmp_path / "probe-tool", 0o755)
    script = os.path.join(ROOT, "scripts", "headers")
    assert (
        subprocess.run(
            [script, "--check", str(tmp_path / "probe-tool")], check=False, capture_output=True, text=True
        ).returncode
        == 1
    )
    first = subprocess.run(
        [script, "--write", str(tmp_path / "probe-tool")], check=False, capture_output=True, text=True
    )
    assert first.returncode == 0 and f"headed {name}" in first.stdout
    text = (tmp_path / "probe-tool").read_text(encoding="utf-8")
    assert text == f"#!/bin/sh\n# SPDX-FileCopyrightText: {HOLDER}\n# SPDX-License-Identifier: {SPDX}\nexit 0\n"
    assert os.access(tmp_path / "probe-tool", os.X_OK)
    again = subprocess.run(
        [script, "--write", str(tmp_path / "probe-tool")], check=False, capture_output=True, text=True
    )
    assert "wrote 0 file(s)" in again.stdout and (tmp_path / "probe-tool").read_text(encoding="utf-8") == text
