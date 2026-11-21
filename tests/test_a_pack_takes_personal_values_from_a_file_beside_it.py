# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pack is shared unchanged between two people: `{home}` in any value of its YAML files is the reader's home folder,
and `{local.<name>}` is the value `pack.local.yaml` beside pack.yaml gives that name. Nothing else is rewritten, a
pack that uses neither loads as it always did, and a name the local file does not set is refused with the file and
the key that asked for it."""

import glob
import os
import shutil
import sys

import pytest
import yaml

from cockpitlib import pack as packmod
from cockpitlib import pack_effective, pack_local, paths
from cockpitlib.errors import PackError
from cockpitlib.pack import load, problems
from tests.support.both_packs import PACKS, ROOT

UNSET = '{file}, {where}: {{local.{name}}} is not set: add "{name}: …" to pack.local.yaml beside the pack'


@pytest.fixture
def home(tmp_path, monkeypatch) -> str:
    folder = tmp_path / "people" / "dev.one"
    folder.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(folder))
    return str(folder)


def _copy(pack_file, tmp_path) -> str:
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder)
    return str(folder / "pack.yaml")


def _beside(path: str, *names) -> str:
    return os.path.join(os.path.dirname(path), *names)


def _edit(path: str, change) -> None:
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    change(data)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)


def _local(path: str, text=None, **values) -> None:
    with open(_beside(path, "pack.local.yaml"), "w", encoding="utf-8") as handle:
        handle.write(yaml.safe_dump(values, sort_keys=False) if text is None else text)


def _unset(file: str, where: str, name: str) -> str:
    return UNSET.format(file=file, where=where, name=name)


# ---------- the tokens, on the reader itself ----------


def test_home_is_filled_in_a_nested_value_and_in_a_list_and_never_in_a_key(home, tmp_path):
    data = {"a": {"b": "{home}/src", "{home}": ["x", "{home}/y", {"{local.k}": "see {home}"}]}, "n": 3, "none": None}
    filled = pack_local.fill(data, "pack.yaml", str(tmp_path))
    assert filled == {
        "a": {"b": f"{home}/src", "{home}": ["x", f"{home}/y", {"{local.k}": f"see {home}"}]},
        "n": 3,
        "none": None,
    }


def test_every_other_brace_form_stays_as_it_was_written(home, tmp_path):
    kept = [
        "{ticket}",
        "{slot}",
        "{files}",
        "{pack}/bin/tool",
        "{workspace}/evidence",
        "{root}/slots/{slot}",
        "pass-{n:03d}",
        "{project}-DEPS-{week}",
        r"\b\d{12}\b",
        "a{1,3}",
        "{local}",
        "{local.}",
        "{local.Upper}",
        "{local.9lives}",
        "{ home }",
        "{HOME}",
        "$HOME",
        "~/src",
    ]
    data = {"kept": list(kept), "mixed": r"{home}/run-{n:03d}/{ticket} \d{12}"}
    filled = pack_local.fill(data, "pack.yaml", str(tmp_path))
    assert filled["kept"] == kept
    assert filled["mixed"] == home + r"/run-{n:03d}/{ticket} \d{12}"


def test_a_value_that_is_one_local_name_takes_that_values_type_and_a_longer_text_takes_its_text(home, tmp_path):
    (tmp_path / "pack.local.yaml").write_text(
        "login: dev-one\nslots: 2\nratio: 1.5\nquiet: false\nbranches: [main, release]\n"
        'tool: {argv: ["{home}/bin/tool", run]}\nnothing:\n',
        encoding="utf-8",
    )
    data = {
        "whole": ["{local.login}", "{local.slots}", "{local.ratio}", "{local.quiet}", "{local.nothing}"],
        "list": "{local.branches}",
        "again": "{local.branches}",
        "mapping": "{local.tool}",
        "text": "{local.login}/work-{local.slots}-{local.ratio} in {home}",
    }
    filled = pack_local.fill(data, "pack.yaml", str(tmp_path))
    assert filled["whole"] == ["dev-one", 2, 1.5, False, None]
    assert filled["list"] == ["main", "release"] and filled["list"] is not filled["again"]
    assert filled["mapping"] == {"argv": [f"{home}/bin/tool", "run"]}
    assert filled["text"] == f"dev-one/work-2-1.5 in {home}"


@pytest.mark.parametrize(
    ("value", "kind"), [("[a, b]", "list"), ("{a: 1}", "dict"), ("true", "bool"), ("", "NoneType")]
)
def test_a_value_that_is_no_text_or_number_is_refused_inside_a_longer_text(home, tmp_path, value, kind):
    (tmp_path / "pack.local.yaml").write_text(f"many: {value}\n", encoding="utf-8")
    with pytest.raises(PackError) as refused:
        pack_local.fill({"branch_prefix": "work-{local.many}"}, "pack.yaml", str(tmp_path))
    assert str(refused.value).startswith(f"pack.yaml, branch_prefix: {{local.many}} is a {kind} in pack.local.yaml")


def test_a_name_the_local_file_does_not_set_is_refused_with_every_place_that_asked_for_it(home, tmp_path):
    data = {"forge": {"human_login": "{local.forge_login}"}, "repos": [{"path": "{home}/src/{local.checkout}"}]}
    with pytest.raises(pack_local.Unset) as refused:
        pack_local.fill(data, "repos.yaml", str(tmp_path))
    lines = [
        _unset("repos.yaml", "forge.human_login", "forge_login"),
        _unset("repos.yaml", "repos[0].path", "checkout"),
    ]
    assert refused.value.lines == lines and str(refused.value) == "\n".join(lines)
    assert isinstance(refused.value, PackError)
    asked = []
    left = pack_local.fill(data, "repos.yaml", str(tmp_path), unset=asked)
    assert asked == lines
    assert left == {
        "forge": {"human_login": "{local.forge_login}"},
        "repos": [{"path": f"{home}/src/{{local.checkout}}"}],
    }


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("- a\n- b\n", "pack.local.yaml must be a mapping of names to values"),
        ("just text\n", "pack.local.yaml must be a mapping of names to values"),
        ("Login: x\n", "pack.local.yaml: 'Login' is not a name"),
        ("my-login: x\n", "pack.local.yaml: 'my-login' is not a name"),
        ("1: x\n", "pack.local.yaml: 1 is not a name"),
        ('a: x\nb: "{local.a}"\n', "pack.local.yaml: b uses {local.…}"),
        ('a: x\nb: {deep: ["see {local.a}"]}\n', "pack.local.yaml: b uses {local.…}"),
    ],
)
def test_a_malformed_local_file_is_refused_by_its_name(home, tmp_path, text, said):
    (tmp_path / "pack.local.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(PackError) as refused:
        pack_local.values(str(tmp_path))
    assert str(refused.value).startswith(said)


def test_the_local_file_is_parsed_once_per_version_and_per_home_and_a_caller_gets_its_own_copy(
    home, tmp_path, monkeypatch
):
    parsed = []
    real = pack_local._parse
    monkeypatch.setattr(pack_local, "_parse", lambda path: parsed.append(path) or real(path))
    folder = str(tmp_path)
    assert pack_local.values(folder) == {} and pack_local.stamp(folder) is None and not parsed
    (tmp_path / "pack.local.yaml").write_text('where: ["{home}/src"]\n', encoding="utf-8")
    first = pack_local.values(folder)
    first["where"].append("mine")
    assert pack_local.values(folder) == {"where": [f"{home}/src"]} and len(parsed) == 1
    other = tmp_path / "people" / "dev.two"
    other.mkdir()
    monkeypatch.setenv("HOME", str(other))
    assert pack_local.values(folder) == {"where": [f"{other}/src"]} and len(parsed) == 2
    (tmp_path / "pack.local.yaml").write_text("", encoding="utf-8")
    assert pack_local.values(folder) == {} and len(parsed) == 3
    os.remove(tmp_path / "pack.local.yaml")
    assert pack_local.values(folder) == {} and len(parsed) == 3


# ---------- a pack that uses neither token ----------


def _yaml_files(pack_file):
    folder = os.path.dirname(pack_file)
    return sorted(glob.glob(os.path.join(folder, "*.yaml")) + glob.glob(os.path.join(folder, "platform", "*.yaml")))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_file_without_a_token_is_returned_exactly_as_it_was_parsed(bare, pack_file):
    files = _yaml_files(pack_file)
    assert {"pack.yaml", "repos.yaml", "skills.yaml", "egress.yaml", "staging.yaml", "accounts.yaml"} <= {
        os.path.basename(path) for path in files
    }
    for path in files:
        with open(path, encoding="utf-8") as handle:
            parsed = yaml.safe_load(handle)
        assert pack_local.fill(parsed, os.path.basename(path), os.path.dirname(pack_file)) is parsed
        assert pack_local.read(path, os.path.dirname(pack_file)) == parsed
    assert not os.path.exists(pack_local.local_path(os.path.dirname(pack_file)))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_without_a_token_or_a_local_file_loads_and_prints_what_it_did_before(bare, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    loaded = load(pack_file)
    printed = pack_effective.render(loaded, sources=True, as_json=True)
    packmod._LOADED.clear()
    monkeypatch.setattr(pack_local, "fill", lambda data, *args, **kwargs: data)  # the files as they were always read
    assert load(pack_file) == loaded
    assert pack_effective.render(load(pack_file), sources=True, as_json=True) == printed
    assert problems(pack_file) == []


# ---------- a loaded pack ----------


def _personal(path: str) -> None:
    """A copy of a fixture that asks for a personal value in pack.yaml and in each file beside it."""

    def pack(data):
        data["branch_prefix"] = "{local.login}/work"
        data["forge"]["human_login"] = "{local.login}"
        data["seats"]["slots"] = "{local.slots}"
        data["standup_enabled"] = "{local.standup}"
        data["protected_branches"] = "{local.protected}"
        data["slots"]["state_dir"] = "{home}/slots/{slot}"
        data["notify"]["ci_green"].append("{home}/notes")
        data.pop("environments", None)

    _edit(path, pack)
    _edit(_beside(path, "repos.yaml"), lambda data: data["repos"][0].update(path="{home}/src/{local.checkout}"))
    _edit(_beside(path, "egress.yaml"), lambda data: data["terminal_deny"].extend([r"\b\d{12}\b", "{home}/keys/"]))
    _edit(_beside(path, "accounts.yaml"), lambda data: data["accounts"][0].update(identifier="{local.account}"))
    _edit(
        _beside(path, "helpers.yaml"),
        lambda data: data["groups"][sorted(data["groups"])[0]].update(label="{local.login}'s stack"),
    )
    _edit(_beside(path, "staging.yaml"), lambda data: data["origins"].update(app="https://{local.stage}.example.test/"))
    _edit(_beside(path, "platform", "map.yaml"), lambda data: data["areas"][0].update(title="{local.login}'s area"))

    def migrate(data):
        data["exporters"]["vault"]["argv"] = ["bin/export", "{home}/vault", "{local.login}"]
        data["records"]["watch_id_prefixes"] = {"rc": "{local.inline}"}

    _edit(_beside(path, "migrate.yaml"), migrate)


VALUES = {
    "login": "dev-one",
    "slots": 2,
    "standup": False,
    "protected": ["main", "release"],
    "checkout": "api",
    "account": "dev-one@example.test",
    "stage": "stage-one",
    "inline": "inline:",
}


@pytest.fixture
def personal(bare, home, tmp_path, monkeypatch, request):
    path = _copy(request.param, tmp_path)
    _personal(path)
    _local(path, **VALUES)
    monkeypatch.setenv("COCKPIT_PACK", path)
    return path


@pytest.mark.parametrize("personal", PACKS, indirect=True)
def test_a_loaded_pack_holds_the_personal_values_with_their_types(personal, home):
    loaded = load(personal)
    assert loaded["branch_prefix"] == "dev-one/work" and loaded["forge"]["human_login"] == "dev-one"
    assert loaded["seats"]["slots"] == 2 and loaded["standup_enabled"] is False
    assert loaded["protected_branches"] == ["main", "release"]
    assert loaded["slots"]["state_dir"] == f"{home}/slots/{{slot}}"
    assert loaded["notify"]["ci_green"][-1] == f"{home}/notes"
    with open(personal, encoding="utf-8") as handle:
        assert yaml.safe_load(handle)["branch_prefix"] == "{local.login}/work"  # the pack's own file is never rewritten


@pytest.mark.parametrize("personal", PACKS, indirect=True)
def test_every_file_beside_the_pack_is_filled_where_it_is_read(personal, home):
    from cockpitlib import accounts, acts, environments, lane_vault, map_build, pack_migration, pr_watch
    from dashboard.cockpit.routes import pages

    loaded = load(personal)
    assert loaded["repos"]["repos"][0]["path"] == f"{home}/src/api"
    assert loaded["egress"]["terminal_deny"][-2:] == [r"\b\d{12}\b", f"{home}/keys/"]
    assert accounts.manifest(loaded)["accounts"][0]["identifier"] == "dev-one@example.test"
    assert "dev-one's stack" in [group["label"] for group in loaded["_helpers"]["groups"].values()]
    origin = "https://stage-one.example.test"
    assert origin in lane_vault.accepted_origins(loaded) and acts._public_origin(loaded) == origin
    assert pages._staging(loaded)["origins"]["app"] == origin + "/"
    assert environments.environments(loaded)[1]["origins"]["app"] == origin + "/"
    assert map_build.load_document(loaded)["areas"][0]["title"] == "dev-one's area"
    # in migrate.yaml {home} is the runtime's home, which the migration fills itself: only the names are filled
    spec = pack_migration.load_spec(loaded)
    assert spec["exporters"]["vault"]["argv"] == ["bin/export", "{home}/vault", "dev-one"]
    assert pr_watch.watch_id_prefixes(loaded) == (("rc", "inline:"),)


@pytest.mark.parametrize("personal", PACKS, indirect=True)
def test_the_effective_settings_and_one_keys_explanation_show_the_filled_values(personal, home):
    loaded = load(personal)
    found = pack_effective.effective(loaded, sources=True)
    assert found["branch_prefix"] == {"value": "dev-one/work", "source": "pack"}
    assert found["seats.slots"]["value"] == 2 and found["protected_branches"]["value"] == ["main", "release"]
    assert found["repos.yaml:repos[0].path"]["value"] == f"{home}/src/api"
    assert found["staging.yaml:origins.app"]["value"] == "https://stage-one.example.test/"
    assert "{local." not in pack_effective.render(loaded, as_json=True)
    explained = pack_effective.explain(loaded, "forge.human_login")
    assert explained["values"]["forge.human_login"] == {"value": "dev-one", "source": "pack"}


@pytest.mark.parametrize("personal", PACKS, indirect=True)
def test_the_local_file_appearing_changing_and_going_loads_the_pack_again(personal, monkeypatch):
    parsed = []
    real = yaml.safe_load
    monkeypatch.setattr(yaml, "safe_load", lambda stream: parsed.append(1) or real(stream))
    first = load(personal)
    seen = len(parsed)
    assert load(personal) == first and len(parsed) == seen
    _local(personal, **{**VALUES, "login": "dev-two"})
    second = load(personal)
    assert len(parsed) > seen and second["branch_prefix"] == "dev-two/work" and first["branch_prefix"] == "dev-one/work"
    os.remove(_beside(personal, "pack.local.yaml"))
    with pytest.raises(PackError) as refused:
        load(personal)
    assert _unset("pack.yaml", "branch_prefix", "login") in str(refused.value).splitlines()
    _local(personal, **VALUES)
    assert load(personal) == first


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_local_file_no_pack_file_asks_for_changes_nothing_but_is_still_checked(bare, home, pack_file, tmp_path):
    path = _copy(pack_file, tmp_path)
    plain = load(path)
    _local(path, unused="value")
    assert load(path) == plain
    _local(path, text="- not\n- a mapping\n")
    with pytest.raises(PackError, match="pack.local.yaml must be a mapping"):
        load(path)
    assert problems(path) == ["pack.local.yaml must be a mapping of names to values"]


@pytest.mark.parametrize("personal", PACKS, indirect=True)
def test_a_missing_name_is_one_line_for_each_place_in_every_file_and_check_all_prints_them_all(personal, capsys):
    from cockpitlib.cli import main

    _local(personal, slots=2, standup=False, protected=["main"], inline="inline:")
    wanted = [
        _unset("pack.yaml", "branch_prefix", "login"),
        _unset("pack.yaml", "forge.human_login", "login"),
        _unset("repos.yaml", "repos[0].path", "checkout"),
        _unset("accounts.yaml", "accounts[0].identifier", "account"),
        _unset("staging.yaml", "origins.app", "stage"),
        _unset("migrate.yaml", "exporters.vault.argv[2]", "login"),
        _unset("map.yaml", "areas[0].title", "login"),
    ]
    with pytest.raises(pack_local.Unset) as refused:
        load(personal)
    assert refused.value.lines == wanted[:2], "a load stops at the first file"
    found = problems(personal)
    later = {wanted[3]}  # the accounts are read once the files the pack must have are settled, as every such check is
    assert found[:2] == wanted[:2] and set(wanted) - later <= set(found)
    assert "accounts: not checked: depends on companions" in found and not later & set(found)
    _local(personal, slots=2, standup=False, protected=["main"], inline="inline:", checkout="api")
    settled = problems(personal)
    assert wanted[3] in settled and wanted[2] not in settled
    assert any(line.startswith("helpers.yaml, groups.") and "{local.login} is not set" in line for line in settled)
    _local(personal, slots=2, standup=False, protected=["main"], inline="inline:")
    assert main(["pack", "check"]) == 2
    assert wanted[0] in capsys.readouterr().err
    assert main(["pack", "check", "--all"]) == 2
    printed = capsys.readouterr().err.splitlines()
    assert {f"cockpit: {line}" for line in set(wanted) - later} <= set(printed)
    assert main(["pack", "effective"]) == 2 and wanted[0] in capsys.readouterr().err


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_file_the_load_does_not_read_is_refused_at_load_only_for_a_name_that_is_not_set(
    bare, home, pack_file, tmp_path
):
    path = _copy(pack_file, tmp_path)
    plain = load(path)
    _edit(_beside(path, "staging.yaml"), lambda data: data["origins"].update(app="https://{local.stage}.example.test"))
    with pytest.raises(PackError) as refused:
        load(path)
    assert str(refused.value) == _unset("staging.yaml", "origins.app", "stage")
    # a file no reader could parse, or that is not there, is not this check's to refuse: the load did not read it before
    with open(_beside(path, "staging.yaml"), "w", encoding="utf-8") as handle:
        handle.write("origins: [unclosed  # {local.stage}\n")
    assert load(path) == plain
    os.remove(_beside(path, "staging.yaml"))
    os.remove(_beside(path, "migrate.yaml"))
    assert load(path)["name"] == plain["name"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_file_that_is_one_unset_name_and_no_mapping_is_reported_as_no_mapping(bare, home, pack_file, tmp_path):
    path = _copy(pack_file, tmp_path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('"{local.everything}"\n')
    assert problems(path) == ["pack.yaml must be a mapping"]


# ---------- the readers that run without a loaded pack ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_records_folder_may_be_a_personal_value_and_a_path_lookup_never_fails_on_one(
    bare, home, pack_file, tmp_path, monkeypatch
):
    path = _copy(pack_file, tmp_path)
    _edit(path, lambda data: data.update(records_dir="{local.records}"))
    _local(path, records="notes")
    link = str(tmp_path / "linked-pack.yaml")
    os.symlink(path, link)
    for bound in (path, link):  # the local file sits beside the file the binding leads to
        monkeypatch.setenv("COCKPIT_PACK", bound)
        assert paths.records_name() == "notes" == load(bound)["records_dir"]
    _local(path, records="journal")
    assert paths.records_name() == "journal"
    _local(path, text="- not a mapping\n")
    assert isinstance(paths.records_name(), str)  # the lookup answers; the load is what refuses the file
    with pytest.raises(PackError, match="pack.local.yaml must be a mapping"):
        load(path)
    os.remove(_beside(path, "pack.local.yaml"))
    assert paths.records_name() == "{local.records}"
    assert problems(path)[0] == _unset("pack.yaml", "records_dir", "records")


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_watch_id_prefixes_follow_the_local_file_and_an_unset_name_stops_the_pass(bare, home, pack_file, tmp_path):
    from cockpitlib import pr_watch

    path = _copy(pack_file, tmp_path)
    _edit(_beside(path, "migrate.yaml"), lambda data: data["records"].update(watch_id_prefixes={"rc": "{local.kind}"}))
    pack = {"_dir": os.path.dirname(path)}
    with pytest.raises(pr_watch.SpecUnreadable, match="local.kind. is not set"):
        pr_watch.watch_id_prefixes(pack)
    _local(path, kind="inline:")
    assert pr_watch.watch_id_prefixes(pack) == (("rc", "inline:"),)
    _local(path, kind="review:")
    assert pr_watch.watch_id_prefixes(pack) == (("rc", "review:"),)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_soul_names_the_readers_home(bare, home, pack_file, tmp_path, monkeypatch):
    from cockpitlib import setup

    path = _copy(pack_file, tmp_path)
    souls = glob.glob(_beside(path, "souls", "*.md"))
    assert souls
    for soul in souls:
        with open(soul, "a", encoding="utf-8") as handle:
            handle.write("\nYour own notes are under {{HOME}}/notes.\n")
    monkeypatch.setenv("COCKPIT_PACK", path)
    loaded = load(path)
    kinds = [kind for kind, block in loaded["seat_config"].items() if kind != "_common" and block.get("soul")]
    assert kinds
    for kind in kinds:
        text = setup._soul(loaded, f"{kind}-1", kind)
        assert f"Your own notes are under {home}/notes." in text and "{{HOME}}" not in text


def test_init_writes_an_example_of_the_local_file_and_keeps_the_real_one_out_of_version_control(home, tmp_path):
    from cockpitlib import scaffold

    assert scaffold.PERSONAL_FILES[".gitignore"].splitlines() == [pack_local.LOCAL_FILE]
    example = scaffold.PERSONAL_FILES["pack.local.example.yaml"]
    assert "# forge_login: your-login" in example and '# checkouts: "{home}/src"' in example
    (tmp_path / pack_local.LOCAL_FILE).write_text(example, encoding="utf-8")
    assert pack_local.values(str(tmp_path)) == {}  # copied as it is, it sets nothing and is a valid local file
    (tmp_path / pack_local.LOCAL_FILE).write_text(example.replace("# forge_login", "forge_login"), encoding="utf-8")
    assert pack_local.values(str(tmp_path)) == {"forge_login": "your-login"}


@pytest.mark.parametrize("personal", PACKS, indirect=True)
def test_a_snapshot_for_a_replay_holds_the_local_file_with_the_pack(personal, tmp_path):
    from scripts.replay_support import tool

    copied = tmp_path / "snapshot" / "packs" / os.path.basename(os.path.dirname(personal))
    tool.copy_tree(os.path.dirname(personal), str(copied), 0)
    with open(_beside(personal, "pack.local.yaml"), encoding="utf-8") as handle:
        assert (copied / "pack.local.yaml").read_text(encoding="utf-8") == handle.read()
    assert load(str(copied / "pack.yaml"))["branch_prefix"] == "dev-one/work"


@pytest.mark.parametrize("personal", PACKS, indirect=True)
def test_a_replay_reads_a_pack_file_as_its_kernel_does(personal, home, monkeypatch):
    support = os.path.join(ROOT, "scripts", "replay_support")
    monkeypatch.syspath_prepend(support)
    import driver

    repos = _beside(personal, "repos.yaml")
    assert driver.pack_file(repos)["repos"][0]["path"] == f"{home}/src/api"
    os.remove(_beside(personal, "pack.local.yaml"))
    assert driver.pack_file(repos)["repos"][0]["path"] == f"{home}/src/{{local.checkout}}"

    def older(module, name):
        raise driver.Skip(f"this kernel has no {module}")

    monkeypatch.setattr(driver, "lookup", older)
    assert driver.pack_file(repos)["repos"][0]["path"] == "{home}/src/{local.checkout}"
    sys.modules.pop("driver", None)
