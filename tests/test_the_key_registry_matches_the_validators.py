# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The key registry says what the validators accept and what the readers do with an unset key: each claim is held
against the validator's own key set, both fixture packs, a load of the example, and the reader itself."""

import ast
import copy
import os
import shutil
import time

import pytest
import yaml

from cockpitlib import pack_keys
from cockpitlib.errors import CockpitError, PackError
from cockpitlib.pack import load
from cockpitlib.pack_effective import _Dump, rows_of
from tests.guards.pack_default_scan import KERNEL, functions_of, scan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
ABSENT = object()
UNSET = (ABSENT, None, "", 0, [])  # what a pack may leave a key as: not named, and the four falsy values


def _children(parent: str, file: str = pack_keys.PACK) -> set:
    """The names the registry has directly under a place of one file ("" is the file itself; `[]` is a list's items)."""
    above = pack_keys.segments(parent)
    return {
        parts[len(above)]
        for parts in (pack_keys.segments(entry["path"]) for entry in pack_keys.entries(file))
        if len(parts) > len(above) and parts[: len(above)] == above
    }


def _path(parts) -> str:
    return "".join(part if part == "[]" else "." + part for part in parts).lstrip(".")


def test_the_top_level_keys_are_exactly_the_ones_a_pack_may_name():
    from cockpitlib.pack import KNOWN

    assert _children("") == KNOWN


def test_each_block_lists_exactly_the_keys_its_validator_takes():
    from cockpitlib import accounts, helpers, pack, pack_migration

    assert _children("slots") == pack.SLOT_KEYS
    assert _children("tracker") == pack.TRACKER_KEYS
    assert _children("forge") == pack.FORGE_KEYS
    assert _children("advisor") == pack.ADVISOR_KEYS | pack.ADVISOR_OPTIONAL
    assert _children("mcp_servers.*") == pack.MCP_FIELDS
    assert _children("seat_config.*") == set(pack.SEAT_FIELDS)
    assert set(pack.ROOT_FIELDS) <= set(pack.SEAT_FIELDS)
    assert _children("plugins.*") == set(pack.COCKPIT_PLUGIN_KEYS)
    assert _children("roles") == set(pack.ROLES)
    assert set(pack_keys.find("tracker.kind")["enum"]) == set(pack.TRACKER_KINDS)
    assert _children("helpers.*", pack_keys.HELPERS) == helpers.HELPER_KEYS
    assert _children("groups.*", pack_keys.HELPERS) == helpers.GROUP_KEYS
    assert set(pack_keys.find("helpers.yaml:helpers.*.who")["enum"]) == set(helpers.WHO)
    assert {name for name in _children("accounts", pack_keys.ACCOUNTS)} == {"[]"}
    assert _children("accounts[]", pack_keys.ACCOUNTS) == accounts.KEYS
    assert _children("", pack_keys.MIGRATE) == pack_migration.SPEC_KEYS
    assert _children("legacy", pack_keys.MIGRATE) == pack_migration.LEGACY_KEYS
    assert set(pack_keys.find("migrate.yaml:records.map[].kind")["enum"]) == set(pack_migration.RECORD_KINDS)


def test_every_entry_is_whole_and_named_once():
    seen = set()
    for entry in pack_keys.ENTRIES:
        key = (entry["file"], entry["path"])
        assert key not in seen, key
        seen.add(key)
        assert entry["file"] in pack_keys.FILES
        assert entry["doc"].endswith(".") and "\n" not in entry["doc"], key
        assert entry["type"] in (
            "str",
            "int",
            "number",
            "bool",
            "list",
            "map",
            "argv",
            "regex",
            "path",
            "url",
            "time",
        ), key
        assert entry.get("when", pack_keys.ABSENT) in pack_keys.WHENS
        assert ("site" in entry) <= ("default" in entry), key  # a reading place is named only for a default
        above = pack_keys.segments(entry["path"])[:-1]
        parent = _path(above[:-1] if above[-1:] == ["[]"] else above)
        assert not parent or pack_keys.find(pack_keys.label({**entry, "path": parent})) is not None, (
            f"{key}: no entry for {parent}"
        )
    assert pack_keys.find("no.such.key") is None
    assert pack_keys.find("repos.yaml:repos[3].base")["path"] == "repos[].base"
    assert (
        pack_keys.find("providers.coding.command")["path"] == "providers.coding.command"
    )  # its own entry, not the role's
    assert pack_keys.find("providers.judgment.model")["path"] == "providers.*.model"
    assert pack_keys.split("egress.yaml:sacred") == (pack_keys.EGRESS, "sacred") and pack_keys.split("a:b") == (
        pack_keys.PACK,
        "a:b",
    )
    assert [pack_keys.label(entry) for entry in pack_keys.entries(pack_keys.STAGING)] == [
        "staging.yaml:origins",
        "staging.yaml:origins.*",
    ]


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_key_a_fixture_pack_sets_is_in_the_registry(pack_file):
    rows = rows_of(load(pack_file))
    assert [key for key, row in rows.items() if not row["registered"]] == []
    named = {(pack_keys.split(key)[0], row["pattern"]) for key, row in rows.items()}
    assert [pack_keys.label(entry) for entry in pack_keys.ENTRIES if (entry["file"], entry["path"]) not in named] == []


# ---------- an example is a value the validators take ----------

FILE_OF = {
    pack_keys.PACK: "pack.yaml",
    pack_keys.REPOS: "repos.yaml",
    pack_keys.SKILLS: "skills.yaml",
    pack_keys.EGRESS: "egress.yaml",
    pack_keys.STAGING: "staging.yaml",
    pack_keys.HELPERS: "helpers.yaml",
    pack_keys.ACCOUNTS: "accounts.yaml",
    pack_keys.MIGRATE: "migrate.yaml",
}


@pytest.fixture(scope="module")
def acme_copy(tmp_path_factory):
    """The acme pack in a folder of this module's own: a fixture pack's @anchors need the folder above to be packs."""
    folder = tmp_path_factory.mktemp("k") / "packs" / "acme"
    shutil.copytree(os.path.dirname(PACKS[0]), folder)
    return str(folder)


def _place(node, parts, value) -> None:
    """Write a value at a registry path: `*` is the first name already there (else sample), `[]` the first item."""
    part, rest = parts[0], parts[1:]
    if part == "[]":
        if not node:
            node.append({} if rest else value)
        part = 0
    elif part == "*":
        part = next(iter(node), "sample")
    if not rest:
        node[part] = value
        return
    if (node[part] if part == 0 else node.get(part)) is None:
        node[part] = [] if rest[0] == "[]" else {}
    _place(node[part], rest, value)


def _load_with(folder, entry, value):
    path = os.path.join(folder, FILE_OF[entry["file"]])
    kept = open(path, encoding="utf-8").read()
    data = yaml.safe_load(kept) or {}
    _place(data, pack_keys.segments(entry["path"]), value)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle)
        pack = load(os.path.join(folder, "pack.yaml"))
        if entry["file"] == pack_keys.MIGRATE:
            from cockpitlib.pack_migration import load_spec

            load_spec(pack)
        return pack
    finally:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(kept)


def test_every_example_is_accepted_on_a_copy_of_a_fixture_pack(acme_copy):
    refused, bare = [], []
    for entry in pack_keys.ENTRIES:
        if "example" not in entry:
            bare.append(pack_keys.label(entry))
            continue
        if entry.get("needs"):
            continue
        try:
            _load_with(acme_copy, entry, entry["example"])
        except PackError as exc:
            refused.append(f"{pack_keys.label(entry)}: {exc}")
    assert refused == []
    # an entry without an example is a block whose keys carry their own
    assert [
        name
        for name in bare
        if not _children(pack_keys.split(name)[1], pack_keys.split(name)[0]) and not pack_keys.find(name).get("open")
    ] == []


CLOSED = (
    "testflow",
    "lanes",
    "outbox",
    "watchers",
    "desktop",
    "worktree_gc",
    "capacity",
    "kickoff",
    "ide",
    "export",
    "perf",
    "awake",
    "advisories",
    "advisories.alert",
    "slots",
    "slots.close",
    "slots.session",
    "slots.session_card",
    "tracker",
    "forge",
    "advisor",
    "bump_sequence",
)


@pytest.mark.parametrize("block", CLOSED)
def test_a_block_takes_no_key_the_registry_does_not_list(acme_copy, block):
    entry = {"file": pack_keys.PACK, "path": f"{block}.not_a_key"}
    with pytest.raises(PackError):
        _load_with(acme_copy, entry, True)


# ---------- a default is what the reader does: through the reader itself ----------


def _registry(name, holder, key, pack=None):
    """What the registry says is in force for a key of the block the reader reads."""
    entry = pack_keys.find(name)
    present, value = key in holder, holder.get(key)
    if pack_keys.defaulted(entry, present, value):
        return pack_keys.default_of(entry, _Dump({pack_keys.PACK: pack or {}}).lookup)
    return value


def _outcome(call):
    try:
        return ("ok", call())
    except (CockpitError, TypeError, ValueError, AttributeError, LookupError) as exc:
        return ("error", type(exc).__name__)


def _raise(error):
    raise error


def _batch(pack, template) -> str:
    stamp = time.gmtime(0)
    return (
        str(template)
        .format(
            project="TASK",
            week=time.strftime("%GW%V", stamp),
            month=time.strftime("%Y%m", stamp),
            date=time.strftime("%Y%m%d", stamp),
        )
        .upper()
    )


def _standup(value):
    from cockpitlib.window import clock

    if value is None:
        raise CockpitError("no standup hour")
    hour, minute = clock(value)
    return hour, (0,), minute


def _days(value):
    if not isinstance(value, list) or any(not isinstance(day, int) or not 0 <= day <= 6 for day in value):
        raise PackError("working_days")
    return value


def _names(value):
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise PackError("names")
    return [item.strip() for item in value]


def _providers_data(coding) -> dict:
    lane = {"hermes_provider": "example-provider", "model": "example-large"}
    return {
        "providers": {"coding": {"command": ["true"], **coding}, "lane": lane},
        "roles": {role: "lane" for role in pack_keys._SEATS},
    }


def _run(module, function, *args):
    import importlib

    found = importlib.import_module(f"cockpitlib.{module}")
    for part in function.split("."):
        found = getattr(found, part)
    return found(*args)


def _const(module, name):
    import importlib

    return getattr(importlib.import_module(f"cockpitlib.{module}"), name)


def _after(module, function, data, read):
    """A validator's answer: it writes into the pack it is given."""
    _run(module, function, data)
    return read(data)


BASE = {
    "tracker": {"project": "TASK", "url": "https://tracker.example.test/"},
    "forge": {"org": "example-org"},
    "hours": {"standup": 9},
    "working_days": [0],
    "seats": {"slots": 1},
}
REPO = {"repos": {"repos": [{"name": "api"}]}}
SAMPLE_TAGS = ("B", "Q", "CS", "X")  # lines a review comment may start with: the pack's tags decide which ask for work

# name -> (the block of the pack the key sits in, how the pack is made from that block, the reader, what the reader
# should answer for the value the registry resolves). An extra pack per probe shows a default that depends on another key.
PROBES = {
    "finding_labels": (
        "",
        lambda pack: [tag for tag in SAMPLE_TAGS if _run("pr_watch", "_tag_pattern", pack).search(f"{tag}: a finding")],
        lambda value: [tag for tag in SAMPLE_TAGS if tag in [str(given) for given in value]],
    ),
    "testflow.run_dir": ("testflow", lambda pack: _run("test_flow", "run_pattern", pack), str),
    "testflow.review_mark": (
        "testflow",
        lambda pack: [
            bool(_run("test_flow", "run_not_ready", pack, "TASK-100", f"It is {text} now."))
            for text in ("READY FOR YOUR REVIEW", "ready for review")
        ],
        lambda value: [
            str(value).lower() in text for text in ("it is ready for your review now.", "it is ready for review now.")
        ],
    ),
    "forge.bump_batch": (
        "forge",
        lambda pack: (
            _run("kickoff", "batch_key", pack, 0),
            _run("sequence", "is_batch", pack, _run("kickoff", "batch_key", pack, 0)),
        ),
        lambda value: (_batch(None, value), True),
    ),
    "forge.human_login": ("forge", lambda pack: _run("forge", "Forge", pack).human_login, lambda value: value or ""),
    "tracker.kind": (
        "tracker",
        lambda pack: _run("tracker", "tracker_kind", _run("tracker", "_config", pack)),
        lambda value: value,
    ),
    "hours.standup_window": ("hours", lambda pack: _run("window", "pack_standup", pack), _standup),
    "hours.ci_settle_minutes": (
        "hours",
        lambda pack: _run("ci_watch", "_minutes", pack, "ci_settle_minutes", _const("ci_watch", "SETTLE_MINUTES")),
        float,
    ),
    "hours.no_ci_minutes": (
        "hours",
        lambda pack: _run("ci_watch", "_minutes", pack, "no_ci_minutes", _const("ci_watch", "NO_CI_MINUTES")),
        float,
    ),
    "standup_enabled": ("", lambda pack: _run("setup", "standup_enabled", pack), lambda value: value is not False),
    "budget.monthly_usd": ("budget", lambda pack: _run("settings", "_base", pack)["budget"]["monthly_usd"], float),
    "budget.plan_window_max_pct": (
        "budget",
        lambda pack: _run("settings", "_base", pack)["budget"]["plan_window_max_pct"],
        int,
    ),
    "shared_chrome_hours": ("", lambda pack: _run("settings", "_base", pack)["shared_chrome_hours"], int),
    "worktree_gc.enabled": ("worktree_gc", lambda pack: _run("settings", "_worktree_gc_base", pack)["enabled"], bool),
    "worktree_gc.days": ("worktree_gc", lambda pack: _run("settings", "_worktree_gc_base", pack)["days"], int),
    "board_done_days": ("", lambda pack: _run("board_view", "done_days", pack), int),
    "outbox.sweep_passes": ("outbox", lambda pack: _run("gate", "sweep_passes", pack), int),
    "outbox.ci_override": (
        "outbox",
        lambda pack: _run("outbox", "ci_override_allowed", pack),
        lambda value: value is not False,
    ),
    "privileged.scope": ("privileged", lambda pack: _run("pack", "policy", pack)["privileged_scope"], str),
    "privileged.environment": ("privileged", lambda pack: _run("pack", "policy", pack)["privileged_env"], str),
    "privileged.label": ("privileged", lambda pack: _run("pack", "policy", pack)["privileged_label"], str),
    "logins.scope": ("logins", lambda pack: _run("pack", "policy", pack)["login_scope"], str),
    "scratch": ("", lambda pack: _run("pack", "policy", pack)["scratch"], str),
    "refused.hosts": (
        "refused",
        lambda pack: _run("pack", "policy", pack)["hosts"],
        lambda value: [str(item) for item in value],
    ),
    "refused.commands": (
        "refused",
        lambda pack: _run("pack", "policy", pack)["commands"],
        lambda value: [str(item) for item in value],
    ),
    "allowed.reads": (
        "allowed",
        lambda pack: _run("pack", "policy", pack)["reads"],
        lambda value: [str(item) for item in value],
    ),
    "working_days": ("", lambda pack: _run("pack", "policy", pack)["working_days"], _days),
    "ticket_pattern": (
        "",
        lambda pack: _after("pack", "_ticket_pattern", pack, lambda data: data["ticket_pattern"]),
        lambda value: value,
    ),
    "workspace_branch": (
        "",
        lambda pack: _after("pack", "_ticket_pattern", pack, lambda data: data["workspace_branch"]),
        lambda value: str(value).strip(),
    ),
    "protected_branches": (
        "",
        lambda pack: _after("pack", "_protected_branches", pack, lambda data: data["protected_branches"]),
        _names,
    ),
    "slot_provider": (
        "",
        lambda pack: _after(
            "pack",
            "_seats",
            {**pack, "seats": {"slots": pack["seats"]["slots"], "intake": 1, "reviewer": 1, "analyst": 1}},
            lambda data: data["slot_provider"],
        ),
        lambda value: value,
    ),
    "providers.coding.display_name": (
        "providers.coding",
        lambda pack: _after(
            "pack",
            "_providers",
            _providers_data(pack["providers"]["coding"]),
            lambda data: data["providers"]["coding"]["display_name"],
        ),
        lambda value: value,
    ),
    "base_branch": ("", lambda pack: _run("git_push", "repo_branch", {**pack, **REPO}, "api"), lambda value: value),
    "skills.yaml:cards.decompose": ("skills.cards", lambda pack: _run("decompose", "chain", pack), list),
    "slots.lock_wait_seconds": ("slots", lambda pack: _run("slots", "_lock_wait", pack), float),
    "repos.yaml:repos[].shipped": (None, lambda repo: _run("pack", "shipped", repo), lambda value: value is not False),
    "repos.yaml:repos[].watched": (None, lambda repo: _run("pack", "watched", repo), lambda value: value is not False),
    "repos.yaml:repos[].base": (
        None,
        lambda repo: _run(
            "git_push",
            "repo_branch",
            {**BASE, "base_branch": "trunk", "repos": {"repos": [{"name": "api", **repo}]}},
            "api",
        ),
        lambda value: value,
    ),
    "helpers.yaml:helpers.*.who": (
        None,
        lambda raw: _run("helpers", "_helper", "queue", {"argv": ["true"], **raw}, {})["who"],
        lambda value: value if value in ("human", "lane", "both") else _raise(PackError("who")),
    ),
    "helpers.yaml:helpers.*.verbs": (
        None,
        lambda raw: _run("helpers", "_helper", "queue", {"argv": ["true"], **raw}, {})["verbs"],
        lambda value: _names(value) or _raise(PackError("no verb")),
    ),
    "helpers.yaml:helpers.*.warn": (
        None,
        lambda raw: _run("helpers", "_helper", "queue", {"argv": ["true"], **raw}, {})["warn"],
        str,
    ),
}
# A second pack for a default that another key decides.
VARIANTS = {
    "tracker.kind": ({"tracker": {"command": ["bin/tracker"]}},),
    "slot_provider": ({"seats": {"slots": 0}},),
    "hours.standup_window": ({"hours": {"standup": "08:15"}},),
}
# A place that reads a key the scanner cannot follow and no probe above runs: the words of the source that give the default.
PINNED = {
    "hours.ci_settle_minutes": '_minutes(pack, "ci_settle_minutes", SETTLE_MINUTES)',
    "hours.no_ci_minutes": '_minutes(pack, "no_ci_minutes", NO_CI_MINUTES)',
    "slots.idle_minutes": "60 if idle is None else idle",
    "slots.commands.*.who": 'entry.get("who", "both")',
    "capacity.waiting_holds_seat": 'rules.get("waiting_holds_seat") is False',
    "extra_plugins": 'data["extra_plugins"] = []',
    "lanes.by_slot": 'isinstance(raw.get(key, False), bool) for key in ("by_slot", "browser_session")',
    "lanes.browser_session": 'isinstance(raw.get(key, False), bool) for key in ("by_slot", "browser_session")',
    "helpers.yaml:helpers.*.self": '"self": bool(raw.get("self"))',
    "accounts.yaml:command": 'command = [] if data.get("command") is None else data["command"]',
    "accounts.yaml:accounts": 'rows = [] if data.get("accounts") is None else data["accounts"]',
    "accounts.yaml:verify_command": '"verify_command": bool(data.get("verify_command"))',
    "accounts.yaml:accounts[].renew_days": 'int(row.get("renew_days") or 0)',
    "migrate.yaml:records.map[].kind": 'row.get("kind", "dir") not in RECORD_KINDS',
}


def _packs(name, block, value):
    """(what the reader is given, the block the key sits in, the pack other keys are looked up in) for one written
    value: the plain pack and each variant. A probe with no block reads the block itself (a repo, a helper)."""
    key = pack_keys.segments(pack_keys.split(name)[1])[-1]
    if block is None:
        holder = {} if value is ABSENT else {key: value}
        return [(holder, holder, {**BASE, "base_branch": "trunk"})]
    made = []
    for extra in ({}, *VARIANTS.get(name, ())):
        pack = copy.deepcopy({**BASE, **extra})
        node = pack
        for part in [part for part in block.split(".") if part]:
            node = node.setdefault(part, {})
        node.pop(key, None)
        if value is not ABSENT:
            node[key] = value
        made.append((pack, node, pack))
    return made


@pytest.mark.parametrize("name", sorted(PROBES))
def test_the_registry_resolves_an_unset_key_as_its_reader_does(name, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_WORKSPACE", str(tmp_path))
    block, reader, expected = PROBES[name]
    entry = pack_keys.find(name)
    key = pack_keys.segments(entry["path"])[-1]
    assert "default" in entry and "example" in entry
    for value in (*UNSET, entry["example"]):
        for given, holder, pack in _packs(name, block, value):
            resolved = _registry(name, holder, key, pack)
            answer = _outcome(lambda: reader(given))
            assert answer == _outcome(lambda: expected(resolved)), (name, value, given)
            assert answer[0] == "ok" or value not in (ABSENT, entry["example"]), (
                name,
                value,
                answer,
            )  # the reader was really run


def test_the_records_folder_resolves_as_the_path_lookup_reads_it(monkeypatch, tmp_path):
    from cockpitlib.paths import records_name

    entry = pack_keys.find("records_dir")
    for index, value in enumerate((*UNSET, entry["example"], " notes ")):
        path = tmp_path / f"pack-{index}.yaml"
        path.write_text(yaml.safe_dump({} if value is ABSENT else {"records_dir": value}), encoding="utf-8")
        monkeypatch.setenv("COCKPIT_PACK", str(path))
        holder = {} if value is ABSENT else {"records_dir": value}
        assert records_name() == os.path.normpath(_registry("records_dir", holder, "records_dir").strip()), value


def _source(file, function) -> str:
    text = open(os.path.join(KERNEL, file), encoding="utf-8").read()
    tree = ast.parse(text)
    node = tree
    for part in function.split("."):
        node = next(
            item for item in ast.walk(node) if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == part
        )
    return ast.get_source_segment(text, node)


def _agrees(entry, hit) -> bool:
    """A found default says what the entry says: the same rule for an unset key, and the same value."""
    if (hit["form"] == "get") != (entry["when"] == pack_keys.ABSENT):
        return False
    default = entry["default"]
    if isinstance(default, pack_keys.Ref):
        return default.target.split(":")[1] in hit["fallback"]
    if isinstance(default, pack_keys.Key):
        return repr(pack_keys.segments(default.path)[-1]) in hit["fallback"]
    try:
        return ast.literal_eval(hit["fallback"].split(" or ")[0]) == default
    except (ValueError, SyntaxError):
        return False


def test_every_default_with_a_reading_place_is_held_against_that_place():
    """A default the registry gives a reading place for is proven there: the reader is run (PROBES), or its source gives
    the same default in the same form (the scan), or the words that give it are still in the function (PINNED)."""
    hits = scan(trivial=True)
    unproven = []
    for entry in pack_keys.ENTRIES:
        if "site" not in entry:
            continue
        name = pack_keys.label(entry)
        module, _, function = entry["site"].partition(".")
        assert function in functions_of(module + ".py"), f"{name}: no {entry['site']}"
        found = [hit for hit in hits if (hit["file"], hit["function"], hit["key"]) == (module + ".py", function, name)]
        assert name in PROBES or all(_agrees(entry, hit) for hit in found), (
            name,
            found,
        )  # a probe runs the reader: the stronger proof
        if name in PINNED:
            assert PINNED[name] in _source(module + ".py", function), name
        if not found and name not in PROBES and name not in PINNED and name != "records_dir":
            unproven.append(name)
    assert unproven == []
    assert set(PROBES) | set(PINNED) <= {pack_keys.label(entry) for entry in pack_keys.ENTRIES if "site" in entry}


def test_a_default_names_the_readers_constant_and_never_a_copy():
    from cockpitlib import board_view, pr_watch, test_flow

    assert pack_keys.default_of(pack_keys.find("finding_labels")) == []
    assert pack_keys.default_of(pack_keys.find("testflow.review_mark")) is test_flow.REVIEW_MARK
    assert pack_keys.default_of(pack_keys.find("testflow.run_dir")) is test_flow.DEFAULT_RUN_DIR
    assert pack_keys.default_of(pack_keys.find("forge.rereview_job")) is pr_watch.REREVIEW_JOB
    assert pack_keys.default_of(pack_keys.find("board_done_days")) is board_view.DONE_DAYS
    assert pack_keys.default_of(pack_keys.find("hours.rereview_quiet_minutes")) == pr_watch.QUIET_SECONDS / 60
    assert repr(pack_keys.find("hours.rereview_quiet_minutes")["default"]) == "Ref('pr_watch:QUIET_SECONDS', per=60)"
    assert repr(pack_keys.find("testflow.run_dir")["default"]) == "Ref('test_flow:DEFAULT_RUN_DIR')"
    other = pack_keys.default_of(
        pack_keys.find("repos.yaml:repos[].base")
    )  # with nothing to look the other key up in, it stays a name
    assert isinstance(other, pack_keys.Key) and repr(other) == "Key('base_branch')"
    assert pack_keys.default_of(pack_keys.find("repos.yaml:repos[].base"), {"base_branch": "main"}.get) == "main"
    assert pack_keys.default_of(pack_keys.find("name")) is None and not pack_keys.defaulted(
        pack_keys.find("name"), False, None
    )


def test_the_registry_imports_no_reader_until_a_default_is_asked_for():
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, 'kernel'); import cockpitlib.pack_keys as keys; "
        "print(sorted(name for name in sys.modules if name.startswith('cockpitlib.')))"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "['cockpitlib.pack_keys']"
    assert (
        "pack_keys" not in open(os.path.join(KERNEL, "pack.py"), encoding="utf-8").read()
    )  # a load never pays for the table
