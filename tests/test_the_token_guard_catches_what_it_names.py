# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The token guard, rule by rule: a planted example is caught with its rule, file and line, and the allowlisted line passes."""

import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "grep_tokens_under_test", os.path.join(ROOT, "tests", "guards", "grep_tokens.py")
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

KEY = "OPS-" + "4821"
LONG = "TASK-" + "12345"
CARD = "t_" + "1a2b3c4d"
HOME = "/Users/" + "somebody/work"
DAY = "2031-" + "02-03"
VENDOR = "Vendor" + "Name"

# (rule, file, the planted line, a line of the same shape the rule lets through)
PLANTED = (
    ("ticket-key", "kernel/a.py", f"x = 1  # as {KEY} showed", "x = 1  # as TASK-100 and CVE-2031-12345 showed"),
    ("fixture-key", "tests/a.py", f'ticket = "{LONG}"', 'ticket = "TASK-101"'),
    ("pr-number", "docs/a.md", "see api" + "#4120 for the fix", "see api#41 and colour #333333"),
    ("pr-number", "docs/b.md", "the fix (" + "#4120)", "the fix (#41)"),
    ("card-id", "desktop/test/a.mjs", f"const card = '{CARD}'", "const card = 't_00000001'"),
    ("home-path", "docs/a.md", f"open {HOME}", "open /home/someone/work and ~/work"),
    ("dated-note", "kernel/b.py", f"x = 1  # seen on {DAY}", f'x = "{DAY}"  # a clock the test freezes'),
    (
        "dated-note",
        "kernel/c.py",
        f'def f():\n    """Seen on {DAY}."""\n',
        f'def f():\n    """A docstring."""\n    return "{DAY}"\n',
    ),
    ("dated-note", "desktop/src/a.js", f"const a = 1 // since {DAY}", f"const a = '{DAY}' // a fixed day"),
    ("dated-note", "desktop/src/b.js", f"/* note\n   of {DAY} */\nconst a = 1", f"const a = 'http://x.test/{DAY}'"),
    ("dated-note", "cron/a.sh", f"#!/bin/sh\necho hi # {DAY}", f"#!/bin/sh\necho {DAY}"),
    ("dated-note", "packs/p/pack.yaml", f"key: 1  # {DAY}", f"day: {DAY}"),
    ("process-word", "kernel/d.py", "x = 'the Widgetry report'", "x = 'the order report'"),
    ("process-word", "skills/a/SKILL.md", "open the widgetry", "open the record"),
)


def _tree(tmp_path, files: dict, allow: str = "", vendors: str = VENDOR) -> str:
    root = str(tmp_path)
    for name, text in {
        "tests/guards/forbidden-tokens.txt": "fixturename\n",
        "tests/guards/ui-vendor-names.txt": vendors + "\n",
        "tests/guards/process-words.txt": "widgetry\n",
        "tests/guards/token-allow.txt": allow,
        **files,
    }.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as out:
            out.write(text)
    return root


def _line(text: str, mark: str) -> tuple:
    """(number, stripped line) of the first line of the text that holds the mark."""
    for number, line in enumerate(text.splitlines(), 1):
        if mark in line:
            return number, line.strip()
    raise AssertionError(mark)


@pytest.mark.parametrize("rule, name, planted, clean", PLANTED, ids=[f"{row[0]}-{row[1]}" for row in PLANTED])
def test_a_planted_shape_is_caught_with_its_rule_file_and_line_and_its_allowlisted_line_passes(
    tmp_path, monkeypatch, rule, name, planted, clean
):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    root = _tree(tmp_path, {name: planted + "\n"})
    hits = [row for row in guard.shapes(root, [name]) if row[0] == rule]
    assert hits and all(row[1] == name for row in hits)
    number, line = hits[0][2], hits[0][3]
    assert planted.splitlines()[number - 1].strip() == line
    told = guard.problems(root, [name])
    assert any(row.startswith(f"{rule}: ") and row.endswith(f" in {name}:{number}") for row in told)

    excepted = _tree(
        tmp_path,
        {name: planted + "\n"},
        "".join(f"reason: a planted example\n{rule} {name}:{row[3]}\n\n" for row in hits),
    )
    assert guard.problems(excepted, [name]) == []

    assert guard.problems(_tree(tmp_path, {name: clean + "\n"}), [name]) == []


@pytest.mark.parametrize(
    "name",
    [
        ".coverage.host-a",
        "tmp/Some-Laptop.log",
        "run/gateway.host.local.pid",
        f"qa/{'OPS-' + '4821'}/plan.md",
        "docs/widgetry.md",
    ],
)
def test_a_file_name_that_carries_a_machine_or_a_ticket_is_caught(tmp_path, monkeypatch, name):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    root = _tree(tmp_path, {name: "nothing\n"})
    told = guard.problems(root, [name])
    assert len(told) == 1 and told[0].endswith(f": the file name in {name}")
    rule = told[0].split(":")[0]
    assert (
        guard.problems(
            _tree(tmp_path, {name: "nothing\n"}, f"reason: a planted example\n{rule} {name}:{name}\n"), [name]
        )
        == []
    )


def test_a_vendor_name_is_caught_in_any_letter_case_and_only_its_listed_line_passes(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    table = f'PROGRAMS = ("{VENDOR.lower()}",)'
    text = f"{table}\nprint('{VENDOR.upper()} is here')\n"
    root = _tree(tmp_path, {"kernel/tools.py": text})
    assert guard.problems(root, []) == [
        f"vendor: {VENDOR} in kernel/tools.py:1",
        f"vendor: {VENDOR} in kernel/tools.py:2",
    ]
    root = _tree(
        tmp_path,
        {"kernel/tools.py": text},
        f"reason: a program name matched against PATH, never printed\nvendor kernel/tools.py:{table}\n",
    )
    assert guard.problems(root, []) == [f"vendor: {VENDOR} in kernel/tools.py:2"]


def test_a_fixture_name_outside_the_fixture_homes_has_no_exception(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    files = {"docs/a.md": "ask fixturename\n", "packs/p/pack.yaml": "name: fixturename\n"}
    allow = "reason: tried\nforbidden-tokens.txt docs/a.md:ask fixturename\n"
    told = guard.problems(_tree(tmp_path, files, allow), [])
    assert "forbidden-tokens.txt: fixturename in docs/a.md:1" in told and not any("packs/" in row for row in told)


def test_a_local_list_of_real_names_is_read_over_the_tests_too_and_never_printed(tmp_path, monkeypatch):
    extra = tmp_path / "local-names.txt"
    extra.write_text("# local only\nrealname\n", encoding="utf-8")
    monkeypatch.setenv("COCKPIT_EXTRA_TOKENS", str(extra))
    root = _tree(tmp_path / "tree", {"tests/test_a.py": "x = 'realname'\n", "docs/a.md": "fine\n"})
    # the name itself is never printed: its place in the local list says which
    assert guard.problems(root, []) == ["local-names.txt: private name 1 in tests/test_a.py:1"]


def test_an_empty_word_list_fails_the_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    assert guard.problems(_tree(tmp_path, {}, vendors=""), []) == ["ui-vendor-names.txt is empty"]


def test_an_exception_needs_a_reason_a_shape_and_a_line_that_still_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    allow = (
        "# a comment\ncard-id docs/a.md:no reason above\n\nreason: fine\nnot-an-entry\n"
        "card-id docs/gone.md:a line that is not there\n"
    )
    told = guard.problems(_tree(tmp_path, {"docs/a.md": "fine\n"}, allow), ["docs/a.md"])
    assert told == [
        "allowlist: tests/guards/token-allow.txt:2 has no `reason:` line above it",
        "allowlist: tests/guards/token-allow.txt:5 is not `<rule> <path>:<the exact line>`",
        "allowlist: unused exception `card-id docs/gone.md:a line that is not there` in tests/guards/token-allow.txt",
    ]


def test_text_that_is_not_this_projects_is_left_unread(tmp_path, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    body = f"{KEY} {CARD} {HOME}\n"
    files = {
        "LICENSE": body,
        "THIRD-PARTY-NOTICES.md": body,
        "desktop/plugin.js": body,
        "requirements.lock": body,
        "desktop/package-lock.json": body,
        "art/logo.bin": "\0" + body,
    }
    root = _tree(tmp_path, files)
    with open(os.path.join(root, "art", "raw.bin"), "wb") as out:
        out.write(b"\xff\xfe" + body.encode())
    assert guard.problems(root, [*files, "art/raw.bin", "gone.txt"]) == []


def test_a_python_file_that_does_not_parse_still_gives_its_comments(tmp_path):
    assert guard.python_notes(f"def broken(:\n    pass  # {DAY}\n") in ([], [(2, f"# {DAY}")])
    assert guard.python_notes(f"# {DAY}\nx = (\n") == [(1, f"# {DAY}")]


def test_a_script_comment_is_told_from_a_quoted_string(tmp_path):
    text = "const a = 'it''s // not a note'\nconst b = `two\nlines // inside`\nconst c = \"a\\\"b\" // real\nconst d = 'open\n// next\n/* never closed"
    assert [row for row in guard.script_notes(text)] == [(4, "// real"), (6, "// next"), (7, "/* never closed")]
    assert guard.script_notes("const s = `a\\\nb` // after") == [(2, "// after")]
    assert guard.script_notes("// last line, no newline") == [(1, "// last line, no newline")]


def test_the_tracked_files_are_gits_and_a_folder_that_is_no_checkout_has_none(tmp_path):
    assert "tests/guards/grep_tokens.py" in guard.tracked(ROOT)
    assert guard.tracked(str(tmp_path)) == []


def test_this_tree_passes_its_own_guard(capsys, monkeypatch):
    monkeypatch.delenv("COCKPIT_EXTRA_TOKENS", raising=False)
    assert guard.main() == 0 and capsys.readouterr().out.strip() == "tokens ok"


def test_a_failing_guard_prints_each_problem(capsys, monkeypatch):
    monkeypatch.setattr(guard, "problems", lambda: ["card-id: x in a.py:1"])
    assert guard.main() == 1 and capsys.readouterr().out.strip() == "card-id: x in a.py:1"
