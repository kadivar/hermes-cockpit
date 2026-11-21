# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit pack effective` prints every setting of the bound pack with the value in force and where it came from, the
same text for the same pack; `cockpit pack explain` says what one key means. Neither changes anything."""

import json
import os
import shutil

import pytest
import yaml

from cockpitlib import pack_keys
from cockpitlib.cli import main
from cockpitlib.pack import load
from cockpitlib.pack_effective import HIDDEN, SOURCES, effective, rows_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


@pytest.fixture
def bound(monkeypatch, tmp_path):
    """A workspace of the test's own and a way to bind a pack to it."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("COCKPIT_WORKSPACE", str(workspace))

    def bind(pack_file):
        monkeypatch.setenv("COCKPIT_PACK", str(pack_file))
        return load(str(pack_file))

    bind.workspace = workspace
    return bind


def _copy(pack_file, tmp_path, change) -> str:
    """A fixture pack in a folder of the test's own, with its pack.yaml changed."""
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    path = folder / "pack.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def _out(capsys, argv) -> str:
    capsys.readouterr()
    assert main(argv) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_dump_is_json_that_covers_every_registry_key_and_is_the_same_twice(bound, pack_file, capsys):
    pack = bound(pack_file)
    first = _out(capsys, ["pack", "effective", "--json", "--sources"])
    assert _out(capsys, ["pack", "effective", "--json", "--sources"]) == first
    found = json.loads(first)
    assert list(found) == sorted(found)
    assert all(set(row) == {"value", "source"} and row["source"] in SOURCES for row in found.values())
    rows = rows_of(pack)
    named = {(pack_keys.split(key)[0], row["pattern"]) for key, row in rows.items()}
    assert all((entry["file"], entry["path"]) in named for entry in pack_keys.ENTRIES)
    assert found["name"] == {"value": pack["name"], "source": "pack"}
    assert found["board_done_days"]["source"] == "default" and found["forge.bump_batch"]["source"] == "pack"
    plain = json.loads(_out(capsys, ["pack", "effective", "--json"]))
    assert plain == {key: row["value"] for key, row in found.items()}


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_dump_names_no_folder_of_this_machine(bound, pack_file, capsys):
    """Two machines print the same for the same pack: a value is the pack's own words, never a resolved path."""
    pack = bound(pack_file)
    text = _out(capsys, ["pack", "effective", "--sources"])
    assert pack["_dir"] not in text and ROOT not in text and str(bound.workspace) not in text
    lines = text.splitlines()
    assert lines == sorted(lines, key=lambda line: line.split(" = ")[0])
    assert f'name = "{pack["name"]}"  [pack]' in lines
    assert f'name = "{pack["name"]}"' in _out(capsys, ["pack", "effective"]).splitlines()
    raw = yaml.safe_load(open(pack_file, encoding="utf-8"))
    assert f"skills_dir = {json.dumps(raw['skills_dir'])}  [pack]" in lines  # as written, not the folder it resolves to


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_falsy_value_that_means_the_default_says_so(bound, pack_file, tmp_path):
    def change(data):
        data["finding_labels"] = "B"
        data["forge"] = {**data["forge"], "rereview_job": None}
        data["budget"] = None

    found = effective(bound(_copy(pack_file, tmp_path, change)), sources=True)
    assert found["finding_labels"] == {"value": [], "source": "default-falsy"}
    assert found["forge.rereview_job"]["source"] == "default-falsy"
    assert found["budget"] == {"value": None, "source": "pack"}  # a block written empty: its keys are all defaults
    assert found["budget.monthly_usd"]["source"] == "default"


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_settings_save_shows_as_the_source_of_what_it_overlays(bound, pack_file):
    pack = bound(pack_file)
    before = effective(pack, sources=True)
    assert "settings" not in {row["source"] for row in before.values()}
    watch = bound.workspace / pack.get("records_dir", "hermes") / "watch"
    watch.mkdir(parents=True)
    for junk in ("{not json", "[]"):  # a file that is not a settings record overlays nothing, as for the kernel
        (watch / "settings.json").write_text(junk, encoding="utf-8")
        assert effective(pack, sources=True) == before
    (watch / "settings.json").write_text(
        json.dumps(
            {
                "seats": {"reviewer": 3},
                "budget": {"monthly_usd": 250.0},
                "shared_chrome_hours": "6",
                "worktree_gc": {"enabled": True, "days": 9},
            }
        ),
        encoding="utf-8",
    )
    found = effective(pack, sources=True)
    assert found["seats.reviewer"] == {"value": 3, "source": "settings"}
    assert found["budget.monthly_usd"] == {"value": 250.0, "source": "settings"}
    assert found["shared_chrome_hours"] == {"value": 6, "source": "settings"}
    assert (
        found["worktree_gc.enabled"] == {"value": True, "source": "settings"}
        and found["worktree_gc.days"]["value"] == 9
    )
    assert found["seats.intake"] == before["seats.intake"] and found["seats.intake"]["source"] == "pack"
    assert {row["source"] for row in found.values()} == set(SOURCES) - (
        {"default-falsy"} if "default-falsy" not in {row["source"] for row in before.values()} else set()
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_file_the_pack_does_not_have_prints_its_keys_as_defaults(bound, pack_file, tmp_path):
    path = _copy(pack_file, tmp_path, lambda data: (data["logins"].pop("accounts"), data.pop("helpers")))
    os.remove(os.path.join(os.path.dirname(path), "migrate.yaml"))
    found = effective(bound(path), sources=True)
    assert found["migrate.yaml:records.map"] == {"value": None, "source": "default"}
    assert found["migrate.yaml:records.map[].kind"] == {"value": "dir", "source": "default"}
    assert found["accounts.yaml:accounts"] == {"value": [], "source": "default"}
    assert found["helpers.yaml:helpers.*.who"] == {"value": "human", "source": "default"}
    assert {
        row["source"]
        for key, row in found.items()
        if key.startswith(("migrate.yaml:", "accounts.yaml:", "helpers.yaml:"))
    } == {"default"}


def test_without_a_workspace_there_is_no_overlay_to_read():
    assert "settings" not in {row["source"] for row in effective(load(PACKS[0]), sources=True).values()}


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_value_under_a_name_that_reads_like_a_secret_is_never_printed(bound, pack_file, tmp_path, capsys):
    def change(data):
        data["providers"]["chat"] = {"command": ["true"], "env": {"SERVICE_TOKEN": "s3cr3t-value", "LANG": "C"}}
        data["budget"]["api_key"] = "another-s3cr3t"
        data["commit_trailer"] = __import__("datetime").date(2020, 1, 2)

    bound(_copy(pack_file, tmp_path, change))
    text = _out(capsys, ["pack", "effective", "--json", "--sources"])
    assert "s3cr3t" not in text
    found = json.loads(text)
    assert found["providers.chat.env"]["value"] == {"SERVICE_TOKEN": HIDDEN, "LANG": "C"}
    assert found["budget.api_key"] == {"value": HIDDEN, "source": "pack"}
    assert found["commit_trailer"]["value"] == "2020-01-02"  # whatever YAML made of it, the dump is plain data
    assert "s3cr3t" not in _out(capsys, ["pack", "explain", "budget.api_key"])


@pytest.mark.parametrize("pack_file", PACKS)
def test_explain_gives_one_key_its_value_its_source_and_its_meaning(bound, pack_file, capsys):
    pack = bound(pack_file)
    found = json.loads(_out(capsys, ["pack", "explain", "forge.bump_batch", "--json"]))
    entry = pack_keys.find("forge.bump_batch")
    assert found["doc"] == entry["doc"] and found["file"] == "pack.yaml" and found["type"] == "str"
    assert found["values"] == {"forge.bump_batch": {"value": pack["forge"]["bump_batch"], "source": "pack"}}
    assert found["default"] == "{project}-BUMPS" and found["when"] == "falsy"
    text = _out(capsys, ["pack", "explain", "forge.bump_batch"])
    assert text.splitlines()[0] == f"forge.bump_batch = {json.dumps(pack['forge']['bump_batch'])}  [pack]"
    assert entry["doc"] in text and 'default "{project}-BUMPS" when falsy' in text
    labels = json.loads(_out(capsys, ["pack", "explain", "finding_labels", "--json"]))
    assert labels["default"] == [] and labels["values"]["finding_labels"]["source"] == (
        "pack" if "finding_labels" in pack else "default"
    )
    passes = _out(capsys, ["pack", "explain", "outbox.sweep_passes"])
    assert "min 1" in passes and "max 10" in passes and "security true" in passes
    # a key of every item: each item's value, under the key as the registry writes it
    bases = json.loads(_out(capsys, ["pack", "explain", "repos.yaml:repos[].base", "--json"]))
    assert bases["key"] == "repos.yaml:repos[].base"
    assert list(bases["values"]) == [f"repos.yaml:repos[{index}].base" for index in range(len(pack["repos"]["repos"]))]
    one = json.loads(_out(capsys, ["pack", "explain", "repos.yaml:repos[0].base", "--json"]))
    assert list(one["values"]) == ["repos.yaml:repos[0].base"] and one["doc"] == bases["doc"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_explain_of_a_key_the_registry_does_not_describe_still_shows_what_the_pack_set(
    bound, pack_file, tmp_path, capsys
):
    bound(_copy(pack_file, tmp_path, lambda data: data["budget"].update({"weekly_usd": 5})))
    found = json.loads(_out(capsys, ["pack", "explain", "budget.weekly_usd", "--json"]))
    assert (
        found["values"] == {"budget.weekly_usd": {"value": 5, "source": "pack"}} and "does not describe" in found["doc"]
    )
    assert "type" not in found
    assert "budget.weekly_usd = 5  [pack]" in _out(capsys, ["pack", "explain", "budget.weekly_usd"])
    assert rows_of(load(os.environ["COCKPIT_PACK"]))["budget.weekly_usd"]["registered"] is False


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_unknown_key_is_a_usage_error_that_lists_the_close_ones(bound, pack_file, capsys):
    bound(pack_file)
    assert main(["pack", "explain", "forge.bump_batsh"]) == 2
    err = capsys.readouterr().err
    assert (
        "no pack key forge.bump_batsh" in err
        and "forge.bump_batch" in err
        and "cockpit pack explain forge.bump_batch" in err
    )
    assert main(["pack", "explain", "qqqqqqqq"]) == 2
    assert "close:" not in capsys.readouterr().err


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_wrong_pack_command_does_not_run(bound, pack_file, capsys, monkeypatch):
    bound(pack_file)
    for argv, reason in (
        (["pack", "effective", "extra"], "stray argument"),
        (["pack", "explain"], "missing argument"),
        (["pack", "explain", "name", "board"], "stray argument"),
        (["pack", "explain", "name", "--sources"], "unknown option --sources"),
        (["pack", "effective", "--nope"], "unknown option --nope"),
        (["pack", "check", "--json"], "unknown option --json"),
        (["pack", "check", "extra"], "stray argument"),
        (["pack", "nope"], "invalid value"),
        (["pack"], "missing argument"),
    ):
        capsys.readouterr()
        assert main(argv) == 2, argv
        captured = capsys.readouterr()
        assert captured.err.startswith(reason) and captured.out == "", argv
    monkeypatch.delenv("COCKPIT_WORKSPACE")  # with a workspace bound, check also looks for the repos' checkouts
    assert main(["pack", "check"]) == 0
    assert capsys.readouterr().out == f"pack ok {load(pack_file)['name']}\n"
