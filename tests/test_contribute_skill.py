# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The contribute skill and AGENTS.md are instructions a coding assistant follows to the letter, so everything they
cite must be real: every repository path, every `cockpit` verb, every script, every pack key. The skill's modes table
and its mode sections say the same thing, and the file stays short enough to be read in full."""

import os
import re

import pytest

from cockpitlib import pack_keys
from cockpitlib.cli import COMMANDS

pytestmark = pytest.mark.structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = ".agents/skills/contribute/SKILL.md"
GUIDE = "AGENTS.md"
LIMIT = 450
MODES = ("triage", "report", "fix", "feature", "check", "pr")

# Paths a document may cite before they are in the tree. Each entry is a debt: remove it as soon as the path exists, so
# a citation of it is checked like every other. A folder covers what is under it.
MAY_NOT_EXIST_YET = (
    "docs/proposals/",  # the first proposal of a kernel change creates it (the skill's ladder, rung 4)
)
# Written by scripts/check on request and never committed.
NOT_IN_THE_TREE = ("check-result.json",)
ROOT_FILE = re.compile(r"^(?:[A-Z][A-Z_]*\.md|pyproject\.toml|plugin\.yaml|check-result\.json)$")
PATH = re.compile(r"^\.?[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.<>*-]+)+/?$")


def _read(path: str) -> str:
    return open(os.path.join(ROOT, path), encoding="utf-8").read()


def _spans(text: str) -> list:
    """Every backticked span of a document, fenced blocks left out (they hold examples, not citations)."""
    prose = re.sub(r"^ *```.*?^ *```", "", text, flags=re.MULTILINE | re.DOTALL)
    return re.findall(r"`([^`\n]+)`", prose)


def _paths(text: str) -> list:
    """The repository paths a document cites: a backticked word with a slash under a top-level entry, or a root file."""
    tops = set(os.listdir(ROOT)) | {entry.split("/")[0] for entry in MAY_NOT_EXIST_YET}
    found = []
    for span in _spans(text):
        for word in span.split():
            word = re.sub(r":\d+$", "", word.strip(".,;:()"))
            if ROOT_FILE.match(word) or (PATH.match(word) and word.split("/")[0] in tops):
                found.append(word)
    return sorted(set(found))


def _concrete(path: str) -> str:
    """The part of a cited path that names something real: up to its first placeholder or wildcard."""
    cut = re.search(r"[<*]", path)
    return path if not cut else path[: cut.start()].rsplit("/", 1)[0] + "/"


def _allowed_missing(path: str) -> bool:
    return any(path == entry or (entry.endswith("/") and (path + "/").startswith(entry)) for entry in MAY_NOT_EXIST_YET)


def _sections(text: str) -> dict:
    """Each `## ` section of the skill by its heading."""
    found, name = {}, ""
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            found[name] = []
        elif name:
            found[name].append(line)
    return {name: "\n".join(lines) for name, lines in found.items()}


@pytest.mark.parametrize("document", [SKILL, GUIDE])
def test_every_repository_path_a_document_cites_exists(document):
    cited = _paths(_read(document))
    assert len(cited) > 10, f"{document}: the path reader found almost nothing; it no longer reads this document"
    missing = [
        path
        for path in cited
        if not os.path.exists(os.path.join(ROOT, _concrete(path)))
        and not _allowed_missing(_concrete(path))
        and path not in NOT_IN_THE_TREE
    ]
    assert missing == [], f"{document} cites paths that are not in the tree: {missing}"


def test_the_list_of_paths_that_may_not_exist_yet_only_shrinks():
    settled = [entry for entry in MAY_NOT_EXIST_YET if os.path.exists(os.path.join(ROOT, entry))]
    assert settled == [], (
        f"these exist now: remove them from MAY_NOT_EXIST_YET so their citations are checked: {settled}"
    )
    assert len(MAY_NOT_EXIST_YET) <= 1


@pytest.mark.parametrize("document", [SKILL, GUIDE])
def test_every_script_a_document_cites_can_be_run(document):
    scripts = [
        path
        for path in _paths(_read(document))
        if path.startswith(("scripts/", "bin/")) and not path.endswith("/") and os.path.isfile(os.path.join(ROOT, path))
    ]
    assert "scripts/check" in scripts
    assert [path for path in scripts if not os.access(os.path.join(ROOT, path), os.X_OK)] == []


@pytest.mark.parametrize("document", [SKILL, GUIDE])
def test_every_cockpit_verb_a_document_cites_is_a_command(document):
    verbs = {match for span in _spans(_read(document)) for match in re.findall(r"\bcockpit ([a-z][a-z-]*)", span)}
    assert [verb for verb in sorted(verbs) if verb not in COMMANDS] == []
    assert document == GUIDE or {"pack", "describe"} <= verbs


def test_every_pack_key_the_skill_cites_is_in_the_registry():
    """The skill writes a key as: the key `<path>`. That form is what this test reads."""
    keys = re.findall(r"\bkeys? `([^`]+)`", _read(SKILL))
    assert len(keys) >= 5, "the skill cites its pack keys as: the key `name`"
    assert [key for key in keys if pack_keys.find(key) is None] == []


def test_the_modes_table_and_the_mode_sections_name_the_same_modes_in_the_same_order():
    text = _read(SKILL)
    sections = _sections(text)
    rows = re.findall(r"^\| `([a-z]+)` \| `contribute ", sections["Modes"], flags=re.MULTILINE)
    headings = [name[len("Mode: ") :] for name in sections if name.startswith("Mode: ")]
    assert tuple(rows) == MODES and tuple(headings) == MODES
    described = re.search(r"^description: (.*)$", text, flags=re.MULTILINE).group(1)
    assert [mode for mode in MODES if not re.search(rf"\b{mode} \(", described)] == [], (
        "the description lists every mode"
    )


@pytest.mark.parametrize("mode", MODES)
def test_a_mode_has_numbered_steps_a_do_not_line_and_its_required_output(mode):
    body = _sections(_read(SKILL))[f"Mode: {mode}"]
    steps = [int(number) for number in re.findall(r"^(\d+)\. ", body, flags=re.MULTILINE)]
    assert len(steps) >= 4 and steps == list(range(1, len(steps) + 1)), (
        f"{mode}: steps are numbered from 1 without a gap"
    )
    assert re.search(r"^Do not ", body, flags=re.MULTILINE), f"{mode}: no line starts with 'Do not'"
    assert "Required output:" in body


@pytest.mark.parametrize("mode", ("report", "fix", "feature"))
def test_an_editing_mode_starts_with_triage(mode):
    assert re.search(r"^1\. Run `triage`\.", _sections(_read(SKILL))[f"Mode: {mode}"], flags=re.MULTILINE)


def test_the_skill_carries_the_ladder_its_warning_signs_and_the_sections_a_change_needs():
    text = _read(SKILL)
    sections = _sections(text)
    for heading in (
        "The genericity ladder",
        "The repo map",
        "The test recipe",
        "Compatibility",
        "The invariants",
        "Generic names",
        "Regenerate",
        "The pull request standard",
        'If your shell command is refused with "outside the lanes"',
    ):
        assert heading in sections, f"the skill has no section: {heading}"
    ladder = sections["The genericity ladder"]
    assert [
        rung for rung in ("1. **PACK RECIPE", "2. **PLUGIN", "3. **PACK KEY", "4. **KERNEL") if rung not in ladder
    ] == []
    assert (
        "### Signs you are a rung too high" in ladder and ladder.count("\n**") >= 4
    )  # the none-fits rule and three examples
    assert "No quote, no kernel change" in ladder and "docs/proposals/<slug>.md" in ladder
    assert "Never report a pass you did not see" in text and "Stop and say so instead of guessing" in text
    assert "COCKPIT_HUMAN" in sections['If your shell command is refused with "outside the lanes"']


def test_the_skill_is_short_enough_to_be_read_in_full_and_is_not_registered_into_the_lanes():
    assert len(_read(SKILL).splitlines()) < LIMIT
    assert not os.path.exists(os.path.join(ROOT, "skills", "contribute")), (
        "skills/ is registered into every adopter's lanes"
    )


def test_the_path_reader_tells_a_citation_from_other_backticked_text():
    sample = (
        "See `tests/conftest.py`, `kernel/cockpitlib/window.py:40` and `scripts/check --only tokens`; a key `hours.standup`, "
        "the module `cockpitlib.plugin_api`, a record at `qa/<ticket>/plan.md`, `docs/proposals/<slug>.md` and `README.md`.\n"
        "```sh\n`tests/never_cited.py`\n```\n"
    )
    assert _paths(sample) == [
        "README.md",
        "docs/proposals/<slug>.md",
        "kernel/cockpitlib/window.py",
        "scripts/check",
        "tests/conftest.py",
    ]
    assert (
        _concrete("docs/proposals/<slug>.md") == "docs/proposals/"
        and _concrete("tests/contract/*.json") == "tests/contract/"
    )
    assert (
        _allowed_missing("docs/proposals/")
        and _allowed_missing("docs/proposals/a-wish.md")
        and not _allowed_missing("docs/nope.md")
    )


@pytest.mark.parametrize(
    "document",
    ["CONTRIBUTING.md", ".github/pull_request_template.md", "tests/reports/README.md", "evals/contribute/README.md"],
)
def test_the_pages_for_people_cite_only_paths_that_exist(document):
    missing = [
        path
        for path in _paths(_read(document))
        if not os.path.exists(os.path.join(ROOT, _concrete(path)))
        and not _allowed_missing(_concrete(path))
        and path not in NOT_IN_THE_TREE
    ]
    assert missing == [], f"{document} cites paths that are not in the tree: {missing}"


def test_the_pull_request_template_asks_for_what_the_skill_says_a_pull_request_carries():
    template = _read(".github/pull_request_template.md")
    heads = re.findall(r"^## (.+)$", template, flags=re.MULTILINE)
    assert heads == ["Kind", "Rung of the ladder", "Evidence", "Compatibility", "Check", "Not verified"]
    assert "Existing packs: unchanged because" in template and "Nothing is looser:" in template
    assert (
        template.count("- [ ] ") == 2
        and "CONTRIBUTION-TERMS.md" in template
        and "Allow edits by maintainers" in template
    )
    standard = _sections(_read(SKILL))["The pull request standard"]
    assert [
        head
        for head in ("Title", "Kind", "Rung", "Evidence", "Compatibility", "Check", "Not verified")
        if f"**{head}**" not in standard
    ] == []
    config = _read(".github/ISSUE_TEMPLATE/config.yml")
    assert "blank_issues_enabled: false" in config and "CONTRIBUTING.md" in config


def test_the_evaluation_set_has_ten_scenarios_each_with_a_prompt_a_classification_and_its_grading_lines():
    folder = os.path.join(ROOT, "evals", "contribute")
    scenarios = sorted(name for name in os.listdir(folder) if re.match(r"^\d\d-[a-z0-9-]+\.md$", name))
    assert [name[:2] for name in scenarios] == [f"{number:02d}" for number in range(1, 11)]
    for name in scenarios:
        text = _read(os.path.join("evals", "contribute", name))
        heads = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
        assert heads == [
            "Prompt",
            "Expected classification",
            "A good result has every one of these",
            "Any one of these fails the scenario",
        ], name
        assert text.count("\n- [ ] ") >= 3 and "\n> " in text, name
    readme = _read(os.path.join("evals", "contribute", "README.md"))
    assert [
        word
        for word in ("Who runs it, and when", "A fresh clone", "The forge offline", "## Grading")
        if word not in readme
    ] == []
