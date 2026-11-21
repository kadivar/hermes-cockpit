# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AGENTS.md is the one source a coding assistant reads; every other entry file is a generated pointer of a few lines
to it and to the contribute skill. A pointer that restated a rule would drift from the source, so none may."""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "gen-pointers")
SKILL = ".agents/skills/contribute/SKILL.md"
VENDORS = os.path.join(ROOT, "tests", "guards", "ui-vendor-names.txt")


def _load():
    loader = importlib.machinery.SourceFileLoader("cockpit_gen_pointers", SCRIPT)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


gen = _load()


def _read(path: str) -> str:
    return open(os.path.join(ROOT, path), encoding="utf-8").read()


def _body(text: str) -> list:
    """A pointer's lines of content: without its frontmatter, the generated-file note and blank lines."""
    rest = text[len(gen.frontmatter(text)) :]
    return [line for line in rest.splitlines() if line.strip() and not line.startswith("<!--")]


def _rules() -> list:
    """Every line of AGENTS.md that states something: list items, table rows and sentences, not headings or fences."""
    return [
        line.strip()
        for line in _read("AGENTS.md").splitlines()
        if len(line.strip()) > 30 and not line.startswith(("#", "```"))
    ]


def test_the_guide_names_the_skill_and_the_one_command_and_stays_short():
    guide = _read("AGENTS.md")
    assert f"`{SKILL}`" in guide and "scripts/check" in guide and "tests/reports/" in guide
    assert len(guide.splitlines()) <= 90, (
        "AGENTS.md is an entry point of about seventy lines: move detail into the skill"
    )


@pytest.mark.parametrize("path", gen.POINTERS)
def test_a_pointer_exists_is_a_few_lines_and_names_the_skill(path):
    assert os.path.isfile(os.path.join(ROOT, path)), f"{path} is missing: run scripts/gen-pointers"
    body = _body(_read(path))
    assert 1 <= len(body) <= 10, f"{path}: a pointer holds at most ten lines of content"
    assert len(body) <= 3
    assert SKILL in "\n".join(body)


@pytest.mark.parametrize("path", gen.POINTERS)
def test_a_pointer_repeats_no_rule_of_the_guide(path):
    rules = _rules()
    assert len(rules) > 20
    repeated = [line for line in _body(_read(path)) if any(line.strip() in rule or rule in line for rule in rules)]
    assert repeated == [], f"{path} restates AGENTS.md: {repeated}"


@pytest.mark.parametrize("path", gen.POINTERS)
def test_a_pointer_names_no_vendor_in_its_content(path):
    words = [line.strip() for line in open(VENDORS, encoding="utf-8") if line.strip() and not line.startswith("#")]
    text = _read(path)
    assert words and [word for word in words if word in text] == []


@pytest.mark.parametrize("path", gen.SKILLS)
def test_a_skill_pointer_carries_the_source_s_frontmatter(path):
    source = gen.frontmatter(_read(SKILL))
    assert source.startswith("---\nname: contribute\ndescription: ") and gen.frontmatter(_read(path)) == source


def test_the_rule_pointer_with_a_head_carries_the_source_s_description_and_nothing_of_its_own_but_the_switch():
    source = gen.frontmatter(_read(SKILL))
    head = gen.frontmatter(_read(gen.RULE_WITH_HEAD)).splitlines()
    assert head == ["---", gen.field(source, "description"), "alwaysApply: true", "---"]
    assert [gen.frontmatter(_read(path)) for path in gen.RULES] == ["", ""]


def test_the_committed_pointers_are_what_the_generator_writes():
    done = subprocess.run([sys.executable, SCRIPT, "--check"], capture_output=True, text=True, check=False)
    assert done.returncode == 0 and done.stdout.strip() == "pointers ok", done.stdout + done.stderr


def test_a_changed_pointer_is_reported_as_stale_and_an_unknown_flag_is_refused(tmp_path):
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    (tree / ".agents" / "skills" / "contribute").mkdir(parents=True)
    (tree / "scripts" / "gen-pointers").write_text(open(SCRIPT, encoding="utf-8").read(), encoding="utf-8")
    (tree / SKILL).write_text(
        "---\nname: contribute\ndescription: A short one.\n---\n\n# Contribute\n", encoding="utf-8"
    )
    run = lambda *args: subprocess.run(
        [sys.executable, str(tree / "scripts" / "gen-pointers"), *args], capture_output=True, text=True, check=False
    )
    assert run("--check").returncode == 1 and "stale pointer files" in run("--check").stdout
    assert run().returncode == 0 and run("--check").returncode == 0
    assert (
        (tree / ".cursor" / "skills" / "contribute" / "SKILL.md")
        .read_text(encoding="utf-8")
        .startswith("---\nname: contribute\ndescription: A short one.\n---\n")
    )
    (tree / "CLAUDE.md").write_text("Always push to main.\n", encoding="utf-8")
    stale = run("--check")
    assert stale.returncode == 1 and "CLAUDE.md" in stale.stdout
    assert run("--force").returncode == 2
    (tree / SKILL).write_text("# Contribute\n", encoding="utf-8")
    assert run().returncode != 0 and "has no frontmatter" in run().stderr
