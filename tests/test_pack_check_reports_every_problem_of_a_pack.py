# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit pack check --all` reports every problem of a pack, where a load stops at the first. Each check of a load
runs by itself; one that reads what an earlier, failed check would have settled is not run and says which it waits
for. A load itself is unchanged: over a corpus of deliberately broken packs it raises exactly the message it raised
before the checks became a list (tests/contract/pack-first-errors.json, written by the loader as it was)."""

import json
import os

import pytest

from cockpitlib import pack as packs
from cockpitlib.cli import main
from cockpitlib.errors import PackError
from cockpitlib.pack import load, problems
from tests.support import broken_packs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
KEPT = json.load(open(os.path.join(ROOT, "tests", "contract", "pack-first-errors.json"), encoding="utf-8"))


def _first(pack_file, tmp_path, name):
    """(the spoiled pack's file, what a load says first: its PackError's words, or None when it loads)."""
    made = broken_packs.make(pack_file, tmp_path, name)
    try:
        load(made)
        return made, None
    except PackError as exc:
        return made, str(exc).replace(os.path.realpath(str(tmp_path)), "<tmp>").replace(str(tmp_path), "<tmp>")


def test_the_corpus_is_large_and_most_of_it_does_not_load():
    for name in ("acme", "bravo"):
        assert (
            set(KEPT[name]) == set(broken_packs.names())
            and len(broken_packs.names()) == len(set(broken_packs.names())) >= 55
        )
        assert sum(1 for said in KEPT[name].values() if said) >= 50
        assert not [said for said in KEPT[name].values() if said and said.startswith("!")], (
            "the loader never crashed on one"
        )


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("name", broken_packs.names())
def test_a_load_raises_the_message_it_always_raised_and_the_report_starts_with_it(pack_file, tmp_path, name):
    kept = KEPT[os.path.basename(os.path.dirname(pack_file))][name]
    made, said = _first(pack_file, tmp_path, name)
    assert said == kept
    found = [line.replace(os.path.realpath(str(tmp_path)), "<tmp>") for line in problems(made)]
    assert found[:1] == ([kept] if kept else []), "the first line of the report is the error a load raises"
    assert (found == []) == (kept is None)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_that_loads_has_no_problem_and_the_report_keeps_nothing(pack_file):
    before = dict(packs._LOADED)
    assert problems(pack_file) == []
    assert packs._LOADED == before, "a report is no load: nothing is kept for the next one"
    assert [name for name, _ in packs.STEPS][0] == "required" and len(packs.STEPS) == len(
        {name for name, _ in packs.STEPS}
    ) >= 40
    assert set(packs.NEEDS) <= {name for name, _ in packs.STEPS}
    order = [name for name, _ in packs.STEPS]
    assert all(order.index(need) < order.index(name) for name, needs in packs.NEEDS.items() for need in needs), (
        "a check waits only for an earlier one"
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_problem_of_a_pack_with_several_is_reported_in_the_order_a_load_meets_them(pack_file, tmp_path):
    made = broken_packs.make(pack_file, tmp_path, "three-across-the-load")
    alone = [_first(pack_file, tmp_path / name, name)[1] for name in ("grooming", "testflow-run-dir", "perf")]
    assert problems(made) == alone and all(alone)
    with pytest.raises(PackError) as first:
        load(made)
    assert str(first.value) == alone[0]
    both = broken_packs.make(pack_file, tmp_path, "unknown-and-shape")
    assert problems(both) == ["unknown key shiny_new_thing", "seats.slots out of range"]
    files = broken_packs.make(pack_file, tmp_path, "pack-and-repos")
    assert len(problems(files)) >= 2 and problems(files)[0] == _first(pack_file, tmp_path / "w", "watchers")[1]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_check_that_waits_for_a_failed_one_is_not_run_and_says_which(pack_file, tmp_path):
    missing = problems(broken_packs.make(pack_file, tmp_path, "no-seats"))
    assert missing[0] == "missing seats"
    waits = [line for line in missing[1:] if ": not checked: depends on " in line]
    assert len(missing) == len(waits) + 1 == len(packs.STEPS), "nothing is checked on a pack without its required keys"
    assert waits[0] == "ticket_pattern: not checked: depends on required"
    late = problems(broken_packs.make(pack_file, tmp_path, "companions-and-policy"))
    assert (
        "accounts: not checked: depends on companions" in late and "helpers: not checked: depends on companions" in late
    )
    assert "working_days" in late, "a check that does not wait for the failed one is still run"
    removed = problems(broken_packs.make(pack_file, tmp_path, "removed-key"))
    assert removed == ["unknown key worker_branch_prefixes"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_check_that_trips_over_what_a_failed_one_left_is_reported_as_waiting_and_a_crash_on_a_sound_pack_is_a_line_that_names_it(
    pack_file, tmp_path, monkeypatch
):
    made = broken_packs.make(pack_file, tmp_path, "ticket-pattern")

    def trips(data):
        raise KeyError("ticket_pattern")

    steps = tuple((name, trips if name == "grooming" else step) for name, step in packs.STEPS)
    monkeypatch.setattr(packs, "STEPS", steps)
    found = problems(made)
    assert (
        found[0].startswith("ticket_pattern") and "grooming: not checked: depends on ticket_pattern (KeyError)" in found
    )
    # with no failed check before it, a crash is reported in the words a load refuses it with: the check and the error
    crashed = problems(pack_file)
    assert (
        len(crashed) == 1
        and crashed[0].startswith("a value in the pack has a shape ")
        and "(KeyError: 'ticket_pattern')" in crashed[0]
    )
    packs._LOADED.clear()
    with pytest.raises(PackError) as refused:
        load(pack_file)
    # the stand-in lives in this file, so each names its own caller as the place; a real check is named alike by both
    assert str(refused.value) == crashed[0].replace("pack.problems cannot read", "pack.load cannot read")
    packs._LOADED.clear()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_command_prints_every_problem_and_the_plain_check_prints_what_it_always_did(
    pack_file, tmp_path, monkeypatch, capsys
):
    made = broken_packs.make(pack_file, tmp_path, "three-across-the-load")
    monkeypatch.setenv("COCKPIT_PACK", made)
    assert main(["pack", "check"]) == 2
    plain = capsys.readouterr()
    assert plain.out == "" and plain.err == f"cockpit: {problems(made)[0]}\n"
    assert main(["pack", "check", "--all"]) == 2
    every = capsys.readouterr()
    assert (
        every.out == ""
        and every.err.splitlines() == [f"cockpit: {line}" for line in problems(made)]
        and len(every.err.splitlines()) == 3
    )
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert main(["pack", "check", "--all"]) == 0
    assert capsys.readouterr().out == f"pack ok {load(pack_file)['name']}\n"
    for argv, reason in (
        (["pack", "check", "--all", "extra"], "stray argument"),
        (["pack", "check", "--all", "--json"], "unknown option --json"),
        (["pack", "--all"], "unknown option --all"),
    ):
        assert main(argv) == 2 and capsys.readouterr().err.startswith(reason), argv


def test_a_file_that_is_missing_or_no_mapping_is_the_one_problem(tmp_path):
    assert problems(str(tmp_path / "absent.yaml")) == [
        f"missing pack {os.path.realpath(str(tmp_path / 'absent.yaml'))}"
    ]
    made = broken_packs.make(PACKS[0], tmp_path, "not-a-mapping")
    assert problems(made) == ["pack.yaml must be a mapping"]


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("name", ("pack.yaml", "egress.yaml"))
def test_a_file_that_is_not_yaml_is_the_first_line_of_the_report_as_a_load_says_it(
    pack_file, tmp_path, name, monkeypatch, capsys
):
    import shutil

    folder = os.path.join(str(tmp_path), "packs", os.path.basename(os.path.dirname(pack_file)))
    shutil.copytree(os.path.dirname(pack_file), folder, symlinks=True)
    made = os.path.join(folder, "pack.yaml")
    target = os.path.join(folder, name)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\nbroken: [unclosed\n")
    with pytest.raises(PackError) as refused:
        load(made)
    assert f"{name}, line " in str(refused.value) and "not valid YAML" in str(refused.value)
    found = problems(made)
    assert found[0] == str(refused.value), "the first line of the report is the error a load raises"
    monkeypatch.setenv("COCKPIT_PACK", made)
    assert main(["pack", "check", "--all"]) == 2
    assert "not valid YAML" in capsys.readouterr().err
