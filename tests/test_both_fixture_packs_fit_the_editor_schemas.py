# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The schemas under kernel/schema describe the shape of each pack file for an editor: a pack that loads fits them, a
key the loader refuses is refused, and a wrong type is named."""

import json
import os

import jsonschema
import pytest
import yaml

from cockpitlib import pack_keys
from cockpitlib.accounts import manifest_path
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


def _schema(file: str) -> dict:
    with open(
        os.path.join(ROOT, "kernel", "schema", file.replace(".yaml", "") + ".schema.json"), encoding="utf-8"
    ) as handle:
        return json.load(handle)


def _files(pack) -> dict:
    """{registry file name: path} of the files this pack has."""
    beside = lambda name: os.path.join(pack["_dir"], name)
    found = {
        pack_keys.PACK: pack["_path"],
        pack_keys.REPOS: beside("repos.yaml"),
        pack_keys.SKILLS: beside("skills.yaml"),
        pack_keys.EGRESS: beside("egress.yaml"),
        pack_keys.STAGING: beside("staging.yaml"),
        pack_keys.MIGRATE: beside("migrate.yaml"),
        pack_keys.ACCOUNTS: manifest_path(pack),
    }
    if isinstance(pack.get("helpers"), str):
        found[pack_keys.HELPERS] = beside(pack["helpers"])
    return {name: path for name, path in found.items() if path and os.path.isfile(path)}


@pytest.mark.parametrize("file", pack_keys.FILES)
def test_each_schema_is_a_valid_schema(file):
    jsonschema.Draft202012Validator.check_schema(_schema(file))


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_file_of_a_pack_that_loads_fits_its_schema(pack_file):
    pack = load(pack_file)
    files = _files(pack)
    assert {pack_keys.PACK, pack_keys.REPOS, pack_keys.SKILLS, pack_keys.EGRESS} <= set(files)
    for name, path in files.items():
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        problems = sorted(
            jsonschema.Draft202012Validator(_schema(name)).iter_errors(data),
            key=lambda error: list(error.absolute_path),
        )
        assert [
            f"{name} {'.'.join(str(part) for part in error.absolute_path)}: {error.message}" for error in problems
        ] == []


def test_between_them_the_fixture_packs_exercise_every_schema():
    seen = set()
    for pack_file in PACKS:
        seen |= set(_files(load(pack_file)))
    assert seen == set(pack_keys.FILES)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_key_the_loader_refuses_is_refused_by_the_schema(pack_file):
    with open(pack_file, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    validator = jsonschema.Draft202012Validator(_schema(pack_keys.PACK))
    assert not list(validator.iter_errors(data))
    assert any("no_such_key" in error.message for error in validator.iter_errors({**data, "no_such_key": 1}))
    assert any(
        "no_such_key" in error.message for error in validator.iter_errors({**data, "tracker": {"no_such_key": 1}})
    )
    assert list(validator.iter_errors({**data, "notify": {"Not An Event": ["true"]}}))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_wrong_type_a_range_and_a_missing_required_key_are_named(pack_file):
    with open(pack_file, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    validator = jsonschema.Draft202012Validator(_schema(pack_keys.PACK))
    assert list(validator.iter_errors({**data, "name": 7}))
    assert list(validator.iter_errors({**data, "seats": {**data["seats"], "intake": 99}}))
    assert list(validator.iter_errors({**data, "runtime": "elsewhere"}))
    assert any(
        "'board' is a required property" in error.message
        for error in validator.iter_errors({key: value for key, value in data.items() if key != "board"})
    )
