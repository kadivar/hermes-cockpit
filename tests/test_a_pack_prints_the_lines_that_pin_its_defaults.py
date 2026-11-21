# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit pack pin` prints the lines that write out each value a pack takes from a default that is listed for change.
It writes nothing. A pack that adds the lines means exactly what it meant, with those sources moved from the default to
the pack, and has nothing left to pin. No default is listed today, so the tests list three of their own."""

import json
import os
import re
import shutil

import pytest
import yaml

from cockpitlib import pack_keys, pack_pin
from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from cockpitlib.pack_effective import effective

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
# Defaults both fixture packs take, listed as if a later release would change them.
LISTED = [
    {"key": "forge.rereview_job", "planned": "Review it again.", "reason": "a shorter text"},
    {"key": "hours.pr_stale_hours", "planned": 48, "reason": "a shorter wait"},
    {"key": "testflow.results_file", "planned": "results.md", "reason": "a shorter name"},
]
SHIPPED = pack_pin.PENDING_FILE


@pytest.fixture(autouse=True)
def listed(monkeypatch, tmp_path):
    """The list of pending defaults the tests run by: three keys of their own, in a file of their own."""
    path = tmp_path / "pending_defaults.json"
    path.write_text(json.dumps({"pending": LISTED}), encoding="utf-8")
    monkeypatch.setattr(pack_pin, "PENDING_FILE", str(path))
    return path


@pytest.fixture
def bound(monkeypatch, tmp_path):
    """A way to bind a pack: a fixture pack as it is, or a copy of it in the test's own folder."""

    def bind(pack_file):
        monkeypatch.setenv("COCKPIT_PACK", str(pack_file))
        return load(str(pack_file))

    def copy(pack_file):
        folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
        shutil.copytree(os.path.dirname(pack_file), folder)
        return str(folder / "pack.yaml")

    bind.copy = copy
    return bind


def _out(capsys, argv) -> str:
    capsys.readouterr()
    assert main(argv) == 0
    return capsys.readouterr().out


def _put(data, key, value) -> None:
    """Write a value at a dotted key of a file's data, a[2].b reaching into item 2 of the list a."""
    parts = re.findall(r"\[(\d+)\]|([^.\[\]]+)", key)
    node = data
    for index, (number, name) in enumerate(parts):
        step = int(number) if number else name
        if index == len(parts) - 1:
            node[step] = value
            return
        if not number and node.get(step) is None:
            node[step] = {}
        node = node[step]


def apply(pack_file, lines) -> None:
    """Add printed lines to the pack's files, as an adopter does by hand."""
    folder = os.path.dirname(pack_file)
    for file in sorted({line["file"] for line in lines}):
        path = os.path.join(folder, file)
        data = yaml.safe_load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
        for line in lines:
            if line["file"] == file:
                _put(data, line["key"], line["value"])
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)


def _values(dump, lines, sourced=True) -> dict:
    """A dump's values, without the row of a block that had to be written for a key printed under it: that row says
    only that the block is there (None before, <map> after), and no reader's answer."""
    written = [line["key"] if line["file"] == pack_keys.PACK else f"{line['file']}:{line['key']}" for line in lines]
    return {
        key: (row["value"] if sourced else row)
        for key, row in dump.items()
        if not any(name.startswith(key + ".") for name in written)
    }


def _merge(into, more) -> None:
    for key, value in more.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _merge(into[key], value)
        else:
            into[key] = value


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_printed_lines_make_the_pack_say_what_it_took_from_a_default(bound, pack_file, capsys):
    copied = bound.copy(pack_file)
    before = effective(bound(copied), sources=True)
    lines = json.loads(_out(capsys, ["pack", "pin", "--json"]))
    listed = pack_pin.pending()
    assert lines and {
        line["file"] + ":" + line["key"] if line["file"] != pack_keys.PACK else line["key"] for line in lines
    } <= set(listed)
    for line in lines:
        key = line["key"] if line["file"] == pack_keys.PACK else f"{line['file']}:{line['key']}"
        assert before[key]["source"] in ("default", "default-falsy") and before[key]["value"] == line["value"]
        assert line["pending"] is True and line["as_yaml"] is True and line["doc"] == pack_keys.find(key)["doc"]
        assert line["planned"] == listed[key]["planned"] and line["reason"] == listed[key]["reason"]
    kept = {
        name: open(os.path.join(os.path.dirname(copied), name), encoding="utf-8").read()
        for name in ("pack.yaml", "migrate.yaml")
    }
    assert _out(capsys, ["pack", "pin"]) and kept == {
        name: open(os.path.join(os.path.dirname(copied), name), encoding="utf-8").read() for name in kept
    }, "printing writes nothing"
    apply(copied, lines)
    after = effective(bound(copied), sources=True)  # it loads
    assert _out(capsys, ["pack", "pin"]) == "" and json.loads(_out(capsys, ["pack", "pin", "--json"])) == []
    assert _values(after, lines) == _values(before, lines)
    pinned = {line["key"] if line["file"] == pack_keys.PACK else f"{line['file']}:{line['key']}" for line in lines}
    for key, row in after.items():
        if key in pinned:
            assert row == {"value": before[key]["value"], "source": "pack"}, key
        elif not any(key.startswith(name + ".") or name.startswith(key + ".") for name in pinned):
            assert row == before[key], (
                key
            )  # a block that had to be written for a key under it is the pack's now, and only that


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_text_is_one_yaml_document_per_file_that_merges_into_it(bound, pack_file, capsys):
    copied = bound.copy(pack_file)
    before = effective(bound(copied))
    lines = json.loads(_out(capsys, ["pack", "pin", "--json"]))
    text = _out(capsys, ["pack", "pin"])
    files = [line.split(":")[0][2:] for line in text.splitlines() if re.match(r"# [a-z]+\.yaml: add these lines", line)]
    assert files == sorted({line["file"] for line in lines}, key=pack_keys.FILES.index)
    documents = list(yaml.safe_load_all(text))
    assert len(documents) == len(files)
    for file, document in zip(files, documents):
        wanted = {}
        for line in lines:
            if line["file"] == file:
                _put(wanted, line["key"], line["value"])
        assert document == wanted
        path = os.path.join(os.path.dirname(copied), file)
        data = yaml.safe_load(open(path, encoding="utf-8"))
        _merge(data, document)
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    for line in lines:  # each key has its meaning above it, and what its default will become
        assert f"# {line['doc']}" in text and f": {line['reason']}" in text
    assert (
        _values(effective(bound(copied)), lines, False) == _values(before, lines, False)
        and _out(capsys, ["pack", "pin"]) == ""
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_all_prints_every_key_a_default_decides_and_writing_them_changes_no_value(bound, pack_file, capsys):
    copied = bound.copy(pack_file)
    before = effective(bound(copied), sources=True)
    few = json.loads(_out(capsys, ["pack", "pin", "--json"]))
    lines = json.loads(_out(capsys, ["pack", "pin", "--all", "--json"]))
    assert len(lines) > len(few) and all(line in lines for line in few)
    for line in lines:
        key = line["key"] if line["file"] == pack_keys.PACK else f"{line['file']}:{line['key']}"
        entry = pack_keys.find(key)
        assert before[key]["source"] in ("default", "default-falsy") and before[key]["value"] == line["value"]
        assert not pack_keys.defaulted(entry, True, line["value"]), f"{key}: written out, it would still be unset"
        assert not isinstance(entry["default"], pack_keys.Key)
    text = _out(capsys, ["pack", "pin", "--all"])
    aside = [line for line in lines if not line["as_yaml"]]
    assert all(f"{line['key']} = " in text for line in aside)
    assert all(line.startswith("#") for line in text.splitlines() if "not printed as a line" in line)
    apply(copied, [line for line in lines if line["as_yaml"]])
    after = effective(bound(copied), sources=True)
    assert _values(after, lines) == _values(before, lines)
    left = json.loads(_out(capsys, ["pack", "pin", "--all", "--json"]))
    # what was not printed as a line is all that a default still decides
    assert [(line["file"], line["key"]) for line in left] == [(line["file"], line["key"]) for line in aside]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_key_written_with_an_unset_value_is_still_printed(bound, pack_file, capsys):
    """A pack that names the key with nothing in it takes the default as much as one that leaves it out."""
    copied = bound.copy(pack_file)
    data = yaml.safe_load(open(copied, encoding="utf-8"))
    data["forge"]["rereview_job"] = None
    open(copied, "w", encoding="utf-8").write(yaml.safe_dump(data))
    rows = effective(bound(copied), sources=True)
    entry = pack_keys.find("forge.rereview_job")
    assert rows["forge.rereview_job"] == {"value": pack_keys.default_of(entry), "source": "default-falsy"}
    assert "forge.rereview_job" in [line["key"] for line in json.loads(_out(capsys, ["pack", "pin", "--json"]))]


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_text_dump_says_which_values_come_from_a_default_that_will_change(bound, pack_file, capsys):
    """Only the text says it. The JSON is what two kernels are compared by, and it reads exactly as before."""
    from cockpitlib.pack_effective import rows_of

    pack = bound(pack_file)
    marked = pack_pin.awaited(rows_of(pack))
    lines = json.loads(_out(capsys, ["pack", "pin", "--json"]))
    assert (
        marked
        == {line["key"] if line["file"] == pack_keys.PACK else f"{line['file']}:{line['key']}" for line in lines}
        != set()
    )
    found = json.loads(_out(capsys, ["pack", "effective", "--json", "--sources"]))
    assert all(set(row) == {"value", "source"} for row in found.values())
    assert all(found[key]["source"] in ("default", "default-falsy") for key in marked)
    for line in _out(capsys, ["pack", "effective", "--sources"]).splitlines():
        key = line.split(" = ")[0]
        assert line.endswith("(this default will change: cockpit pack pin)") == (key in marked), line
        assert re.search(r"  \[(pack|default|default-falsy|settings)[^\]]*\]", line), (
            line
        )  # the source reads as it always did
    assert "this default will change" not in _out(capsys, ["pack", "effective"])


@pytest.mark.parametrize("pack_file", PACKS)
def test_no_default_is_listed_today_and_a_pack_has_nothing_to_pin(bound, pack_file, capsys, monkeypatch):
    monkeypatch.setattr(pack_pin, "PENDING_FILE", SHIPPED)
    assert json.load(open(SHIPPED, encoding="utf-8")) == {"pending": []} and pack_pin.pending() == {}
    pack = bound(pack_file)
    assert pack_pin.lines(pack) == [] and pack_pin.lines(pack, every=True)
    assert _out(capsys, ["pack", "pin"]) == "" and json.loads(_out(capsys, ["pack", "pin", "--json"])) == []
    assert "this default will change" not in _out(capsys, ["pack", "effective", "--sources"])


@pytest.mark.parametrize("file", ("shipped", "listed"))
def test_every_listed_default_is_a_registry_key_with_a_default_and_a_reason(file, monkeypatch):
    if file == "shipped":
        monkeypatch.setattr(pack_pin, "PENDING_FILE", SHIPPED)
    listed = pack_pin.pending()
    rows = json.load(open(pack_pin.PENDING_FILE, encoding="utf-8"))["pending"]
    assert [row["key"] for row in rows] == sorted(listed) and len(rows) == len(listed)
    for key, row in listed.items():
        entry = pack_keys.find(key)
        assert entry is not None and pack_keys.label(entry) == key and "default" in entry, key
        assert "*" not in key and "[]" not in key, f"{key}: a key of every item cannot be printed as a line"
        today = pack_keys.default_of(entry)
        assert not pack_keys.defaulted(entry, True, today), f"{key}: today's default written out must count as set"
        assert row["planned"] != today, f"{key}: the planned value is today's"
        assert isinstance(row["reason"], str) and row["reason"].strip() and "\n" not in row["reason"]


def test_a_list_that_cannot_be_read_is_an_error_and_never_an_empty_list(monkeypatch, tmp_path, bound):
    bound(PACKS[0])
    for text in ("not json", "{}", '{"pending": [{"key": "name"}]}'):
        path = tmp_path / "pending.json"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(pack_pin, "PENDING_FILE", str(path))
        with pytest.raises(CockpitError, match="does not list the defaults that will change"):
            pack_pin.pending()
        assert main(["pack", "pin"]) == 1
    monkeypatch.setattr(pack_pin, "PENDING_FILE", str(tmp_path / "absent.json"))
    assert main(["pack", "effective", "--sources"]) == 1 and main(["pack", "effective"]) == 0
    assert main(["pack", "effective", "--sources", "--json"]) == 0  # the JSON never reads the list


def test_a_wrong_pin_command_does_not_run(bound, capsys):
    bound(PACKS[0])
    for argv, reason in (
        (["pack", "pin", "extra"], "stray argument"),
        (["pack", "pin", "--sources"], "unknown option --sources"),
        (["pack", "pin", "--nope"], "unknown option --nope"),
        (["pack", "effective", "--all"], "unknown option --all"),
        (["pack", "explain", "name", "--all"], "unknown option --all"),
    ):
        capsys.readouterr()
        assert main(argv) == 2, argv
        captured = capsys.readouterr()
        assert captured.err.startswith(reason) and captured.out == "", argv


def test_a_long_value_is_printed_on_one_line_yaml_reads_back():
    for value in (
        "two\nlines\n",
        ["a", "b\nc"],
        {"k": "v\nw"},
        "plain words",
        "ends...",
        [],
        {"rc": "inline:"},
        True,
        3,
        1.5,
        "- dash",
        "a: b",
    ):
        text = pack_pin._inline(value)
        assert "\n" not in text and yaml.safe_load(f"key: {text}") == {"key": value}, value
