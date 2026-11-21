# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack may give the standup note its own headings, hide a section, order the sections and name the file of its
chat-formatted twin (the standup block). A pack without the block gets the kernel's own headings: the text of a note
that fills every section is held against a kept one, for a fixture pack with the block and for one without."""

import json
import os
import shutil

import pytest
import yaml

from cockpitlib import acts, ops, pack_keys, standup_note
from cockpitlib.errors import PackError
from cockpitlib.pack import load, tracker_project
from cockpitlib.paths import platform_dir
from tests.support.standup_sample import sample

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
KEPT = json.load(open(os.path.join(ROOT, "tests", "contract", "standup-sections.json"), encoding="utf-8"))
HEADS = [
    "Tested:",
    "Developed:",
    "Reviewed:",
    "Dependency bumps:",
    "Created:",
    "Closed:",
    "Also:",
    "Waiting on others:",
]


def _with(pack_file, tmp_path, monkeypatch, block) -> dict:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    data = yaml.safe_load((folder / "pack.yaml").read_text(encoding="utf-8"))
    data["standup"] = block
    (folder / "pack.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(folder / "pack.yaml"))
    return load(str(folder / "pack.yaml"))


def _lines(pack, fmt="md") -> list:
    given = sample(tracker_project(pack))
    touched = set(given["acts"]) | {row["ticket"] for row in given["open"]}
    return standup_note.sections(pack, given["acts"], given["titles"], fmt, given["open"], given["statuses"], touched)


def _heads(lines) -> list:
    return [line.strip("*") for line in lines if line.startswith("**")]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_gets_the_note_its_own_headings_spell_and_the_kernels_without_any(pack_file):
    pack = load(pack_file)
    name = os.path.basename(os.path.dirname(pack_file))
    written = yaml.safe_load(open(pack_file, encoding="utf-8")).get("standup")
    assert (pack_file == PACKS[0]) == bool(written), "one fixture pack words its note and the other names nothing"
    assert _lines(pack, "md") == KEPT[name]["md"] and _lines(pack, "slack") == KEPT[name]["slack"]
    heads = _heads(KEPT[name]["md"])
    assert len(heads) == len(HEADS), "the kept note has a line under every section"
    assert "Merged:" in KEPT[name]["md"]
    assert any(line.startswith("- Review: ") for line in KEPT[name]["md"]) and any(
        line.startswith("- Test: ") for line in KEPT[name]["md"]
    )
    assert standup_note.order(pack) == list(standup_note.ORDER)
    if written:
        assert standup_note.labels(pack) == {**standup_note.LABELS, **written["sections"]} and heads != HEADS
        assert written["sections"]["opened"] in KEPT[name]["md"]
        assert standup_note.chat_file(pack) == written["chat_file"] != standup_note.chat_file(None)
    else:
        assert standup_note.labels(pack) == standup_note.LABELS and heads == HEADS and "Opened:" in KEPT[name]["md"]
        assert standup_note.chat_file(pack) == "standup.chat" == standup_note.chat_file(None)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_block_that_writes_out_the_kernels_words_changes_nothing(pack_file, tmp_path, monkeypatch):
    plain = _with(pack_file, tmp_path / "plain", monkeypatch, {})
    pack = _with(
        pack_file,
        tmp_path,
        monkeypatch,
        {"sections": dict(standup_note.LABELS), "order": list(standup_note.ORDER), "chat_file": "standup.chat"},
    )
    assert _lines(pack, "md") == _lines(plain, "md") and _lines(pack, "slack") == _lines(plain, "slack")
    assert _heads(_lines(pack)) == HEADS and standup_note.chat_file(pack) == standup_note.chat_file(plain)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_heading_is_the_packs_a_section_left_out_keeps_its_own_and_an_empty_one_is_hidden(
    pack_file, tmp_path, monkeypatch
):
    pack = _with(
        pack_file,
        tmp_path,
        monkeypatch,
        {"sections": {"testings": "Checked:", "opened": "Sent:", "also": "", "merged": " ", "closed": None}},
    )
    lines = _lines(pack)
    assert _heads(lines) == [
        "Checked:",
        "Developed:",
        "Reviewed:",
        "Dependency bumps:",
        "Created:",
        "Closed:",
        "Waiting on others:",
    ]
    assert "Sent:" in lines and "Opened:" not in lines
    assert "Merged:" not in lines and not any(
        "api#6 merged](" in line and not line.startswith("- Test") for line in lines
    ), "a hidden half takes its lines with it"
    assert not any("PR comment" in line for line in lines), "a hidden section takes its lines with it"
    kept = KEPT[os.path.basename(os.path.dirname(pack_file))]["md"]
    assert [line for line in lines if line.startswith("- ")] == [
        line
        for line in kept
        if line.startswith("- ")
        and "PR comment" not in line
        and not ("api#6 merged](" in line and not line.startswith("- Test"))
    ]
    both = _with(pack_file, tmp_path / "b", monkeypatch, {"sections": {"opened": "", "merged": ""}})
    assert "Developed:" not in _heads(_lines(both)), "a section with both halves hidden has nothing to print"
    hidden = _with(pack_file, tmp_path / "c", monkeypatch, {"sections": {"developments": ""}})
    assert "Opened:" not in _lines(hidden) and _heads(_lines(hidden)) == [
        head for head in HEADS if head != "Developed:"
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_sections_are_printed_in_the_packs_order_and_one_left_out_is_not_printed(pack_file, tmp_path, monkeypatch):
    pack = _with(pack_file, tmp_path, monkeypatch, {"order": ["waiting", "developments", "testings"]})
    for fmt, mark in (("md", "**"), ("slack", "*")):
        lines = _lines(pack, fmt)
        assert [line.strip("*") for line in lines if line.startswith(mark) and line.endswith(mark)] == [
            "Waiting on others:",
            "Developed:",
            "Tested:",
        ]
        assert lines[-1] != ""
    empty = _with(pack_file, tmp_path / "e", monkeypatch, {"order": []})
    assert _heads(_lines(empty)) == HEADS, "an order with nothing in it is no order: the kernel's own"


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_chat_formatted_note_is_written_to_and_sent_from_the_file_the_pack_names(
    bare, pack_file, tmp_path, monkeypatch
):
    pack = _with(pack_file, tmp_path, monkeypatch, {"chat_file": "standup.txt"})
    built = {
        "markdown": "**note**\n",
        "slack": "*note*\n",
        "since": "2026-01-05T09:00:00+00:00",
        "until": "2026-01-06T09:00:00+00:00",
        "items": 1,
        "acts": {},
        "titles": {},
        "waiting": {},
        "statuses": {},
    }
    monkeypatch.setattr(standup_note, "draft", lambda pack, since, until: built)
    ops.standup_draft(pack)
    folder = platform_dir()
    assert open(os.path.join(folder, "standup.txt"), encoding="utf-8").read() == "*note*\n"
    assert not os.path.exists(os.path.join(folder, "standup.chat")) and os.path.isfile(
        os.path.join(folder, "standup.md")
    )
    from cockpitlib import notify

    monkeypatch.setattr(notify, "command", lambda pack, event: [])
    assert acts.standup_send(pack, "")["sent"] is False
    # the unedited draft is kept in the chat format, read from the pack's file
    assert open(os.path.join(folder, "standup.kept"), encoding="utf-8").read() == "*note*\n"


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize(
    "block, said",
    [
        (["sections"], "standup takes sections, order and chat_file"),
        ({"headings": {}}, "standup takes sections, order and chat_file"),
        (
            {"sections": ["Testings:"]},
            "standup.sections names sections of the note (testings, developments, opened, merged",
        ),
        ({"sections": {"testing": "Tested:"}}, "standup.sections names sections of the note"),
        (
            {"sections": {"testings": 7}},
            "standup.sections.testings is a heading: one line of text, or empty to hide the section",
        ),
        ({"sections": {"also": "two\nlines"}}, "standup.sections.also is a heading"),
        ({"order": "testings"}, "standup.order lists sections of the note, each once (testings, developments, reviews"),
        ({"order": ["testings", "opened"]}, "standup.order lists sections of the note, each once"),
        ({"order": ["testings", "testings"]}, "standup.order lists sections of the note, each once"),
        ({"chat_file": "notes/standup.chat"}, "standup.chat_file is one file name beside standup.md"),
        ({"chat_file": "standup.md"}, "standup.chat_file is one file name beside standup.md"),
        ({"chat_file": 3}, "standup.chat_file is one file name beside standup.md"),
    ],
)
def test_a_block_of_the_wrong_shape_is_refused_with_the_right_one(pack_file, tmp_path, monkeypatch, block, said):
    with pytest.raises(PackError) as refused:
        _with(pack_file, tmp_path, monkeypatch, block)
    assert said in str(refused.value)


def test_the_registry_gives_each_section_the_heading_the_note_prints():
    for name, heading in standup_note.LABELS.items():
        entry = pack_keys.find(f"standup.sections.{name}")
        assert entry["default"] == heading and entry["when"] == pack_keys.NONE, name
        for value, shown in ((None, heading), ("", ""), ("Mine:", "Mine:")):  # the registry's rule is the reader's
            resolved = pack_keys.default_of(entry) if pack_keys.defaulted(entry, True, value) else value
            assert standup_note.labels({"standup": {"sections": {name: value}}})[name] == resolved == shown
    listed = {
        pack_keys.segments(entry["path"])[-1]
        for entry in pack_keys.ENTRIES
        if entry["path"].startswith("standup.sections.")
    }
    assert listed == set(standup_note.LABELS) and set(standup_note.ORDER) < set(standup_note.LABELS)
    assert pack_keys.default_of(pack_keys.find("standup.order")) == list(standup_note.ORDER)
    assert pack_keys.default_of(pack_keys.find("standup.chat_file")) is standup_note.CHAT_FILE
