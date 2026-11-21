# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Setup renders every seat from the pack (profile, soul, skills, plugins, crons) and doctor names what differs."""

import io
import json
import os
import re
import sys

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from tests.support.both_packs import PACKS, ROOT, _client, _other, _plugged


@pytest.mark.parametrize(
    "pack_file,key,kind,raised",
    (
        (PACKS[0], "slots", "worker", "worker-2"),
        (PACKS[1], "reviewer", "reviewer", "reviewer-2"),
    ),
)
def test_lowering_a_seat_keeps_the_profile_and_assigns_no_card(env, pack_file, key, kind, raised, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.kanban import open_cards, place_card
    from cockpitlib.lanes import free_lane, profile_dir
    from cockpitlib.settings import frozen
    from cockpitlib.setup import setup

    setup(pack)
    client = _client()
    intake_config = os.path.join(profile_dir("intake"), "config.yaml")
    os.remove(intake_config)
    assert "intake" in client.post("/settings-apply").json()["created"]
    assert os.path.isfile(intake_config)
    seats = {"slots": 1, "intake": 1, "reviewer": 1, "analyst": 1}
    seats[key] = 2
    assert client.post("/settings", json={"seats": seats}).status_code == 200
    created = client.post("/settings-apply").json()["created"]
    if raised == "worker-2":
        assert created == ["worker-2", "tester-2"]
    if raised == "reviewer-2":
        assert created == ["reviewer-2"]
    profile = os.path.join(profile_dir(raised), "config.yaml")
    assert os.path.isfile(profile)
    seats[key] = 1
    assert client.post("/settings", json={"seats": seats}).status_code == 200
    assert raised not in client.post("/settings-apply").json()["created"]
    assert os.path.isfile(profile)
    assert raised in frozen()
    lane = free_lane(kind, pack, {})
    assert lane != raised
    place_card(pack["board"], "TASK-100: keep", lane, "ready")
    assert open_cards(pack["board"]).get(raised, 0) == 0
    seats[key] = 2
    assert client.post("/settings", json={"seats": seats}).status_code == 200
    assert raised not in frozen()
    assert free_lane(kind, pack, {lane: 1}) == raised


@pytest.mark.parametrize("pack_file", PACKS)
def test_second_setup_fills_a_missing_seat_and_a_changed_schedule(env, pack_file, monkeypatch):
    import shutil

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import CRON_JOBS, _register_crons, cron_plan, cron_schedule, job_schedule, setup

    setup(pack)
    soul = os.path.join(profile_dir("worker-1"), "SOUL.md")
    open(soul, "w", encoding="utf-8").write("kept\n")
    shutil.rmtree(profile_dir("tester-1"))
    setup(pack)
    assert open(soul, encoding="utf-8").read() == "kept\n"
    assert os.path.isfile(os.path.join(profile_dir("tester-1"), "config.yaml"))
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    hour = int(pack["hours"]["standup"])
    assert hour != int(other["hours"]["standup"])
    assert job_schedule({"schedule": {"kind": "interval", "minutes": 60}}) == "1h"
    assert job_schedule({"schedule": {"kind": "interval", "minutes": 5}}) == "5m"
    assert job_schedule({"schedule": {"kind": "cron", "display": "daily"}}) == "daily"
    assert job_schedule({"schedule": "0 1 * * *"}) == ""
    assert cron_plan(None, pack)[0]["op"] == "create"

    def stored(schedule):
        if schedule.endswith("m") and schedule[:-1].isdigit():
            return {"kind": "interval", "minutes": int(schedule[:-1])}
        if schedule.endswith("h") and schedule[:-1].isdigit():
            return {"kind": "interval", "minutes": int(schedule[:-1]) * 60}
        return {"kind": "cron", "expr": schedule}

    jobs = []
    for name, default, _script in CRON_JOBS:
        schedule = cron_schedule(pack, name, default)
        if name == "standup":
            schedule = "0 1 * * *"
        if name == "morning-digest":
            continue
        jobs.append({"name": name, "id": f"id-{name}", "schedule": stored(schedule)})
    planned = cron_plan(jobs, pack)
    assert [row["name"] for row in planned] == ["standup", "morning-digest"]
    assert planned[0]["op"] == "update" and planned[0]["schedule"] == f"0 {hour} * * *"
    assert planned[1]["op"] == "create"
    folder = env["home"] / "cron"
    folder.mkdir(exist_ok=True)
    (folder / "jobs.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    os.remove(os.path.join(profile_dir("analyst"), "cron", "jobs.json"))
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: "/usr/bin/hermes")
    monkeypatch.setattr("cockpitlib.setup.subprocess.run", run)
    _register_crons(pack)
    assert calls[0] == ["/usr/bin/hermes", "cron", "edit", "id-standup", "--schedule", f"0 {hour} * * *"]
    assert calls[1][calls[1].index("--name") + 1] == "morning-digest"
    for job in jobs:
        if job["name"] == "standup":
            job["id"] = ""
    (folder / "jobs.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    with pytest.raises(CockpitError, match="standup: schedule changed and the job has no id"):
        _register_crons(pack)
    shutil.rmtree(profile_dir("analyst"))
    monkeypatch.setattr("cockpitlib.setup.shutil.which", lambda _name: None)

    def named(*_args, **_kwargs):
        raise CockpitError("stop")

    monkeypatch.setattr("cockpitlib.setup._profile", named)
    with pytest.raises(CockpitError, match="stop"):
        setup(pack)

    def broken(*_args, **_kwargs):
        raise ValueError("missing model")

    monkeypatch.setattr("cockpitlib.setup._profile", broken)
    with pytest.raises(CockpitError, match="seat render failed analyst: missing model"):
        setup(pack)


@pytest.mark.parametrize("pack_file", PACKS)
def test_one_setup_registers_the_cron_table_and_doctor_sees_it(env, pack_file, monkeypatch):
    import subprocess

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.setup import CRON_JOBS, cron_home, cron_schedule, job_schedule, registered_jobs, setup

    def recorded():
        return {job["name"]: job for job in registered_jobs(pack)}

    setup(pack)
    assert doctor_run(pack) == []
    jobs = recorded()
    assert sorted(jobs) == sorted(name for name, _default, _script in CRON_JOBS)
    for name, default, _script in CRON_JOBS:
        assert job_schedule(jobs[name]) == cron_schedule(pack, name, default)
    assert job_schedule(jobs["bumps"]) != cron_schedule(other, "bumps", "0 0 * * 1-5")
    seat = profile_dir(seats_from(pack)["analyst"][0])
    assert cron_home(pack, "morning-digest") == seat
    seat_jobs = json.load(open(os.path.join(seat, "cron", "jobs.json"), encoding="utf-8"))["jobs"]
    assert [job["name"] for job in seat_jobs] == ["morning-digest"]
    assert jobs["morning-digest"]["no_agent"] is False and jobs["ci-watch"]["no_agent"] is True
    runner = subprocess.run([os.path.join(seat, "scripts", "run"), "help"], check=False, capture_output=True, text=True)
    assert runner.returncode == 0, runner.stderr

    ids = {name: job["id"] for name, job in jobs.items()}
    setup(pack)
    assert {name: job["id"] for name, job in recorded().items()} == ids
    assert doctor_run(pack) == []

    root_file = env["home"] / "cron" / "jobs.json"
    data = json.loads(root_file.read_text(encoding="utf-8"))
    data["jobs"] = [job for job in data["jobs"] if job["name"] != "perf-sync"]
    for job in data["jobs"]:
        if job["name"] == "bumps":
            job["schedule"] = {"kind": "cron", "expr": "0 1 * * 0", "display": "0 1 * * 0"}
    root_file.write_text(json.dumps(data), encoding="utf-8")
    assert sorted(doctor_run(pack)) == ["bumps cron schedule differs", "perf-sync cron not registered"]
    setup(pack)
    assert doctor_run(pack) == []
    again = recorded()
    assert again["bumps"]["id"] == ids["bumps"]
    assert job_schedule(again["bumps"]) == cron_schedule(pack, "bumps", "0 0 * * 1-5")
    assert again["perf-sync"]["id"] != ids["perf-sync"]
    assert {name: job["id"] for name, job in again.items() if name != "perf-sync"} == {
        name: ident for name, ident in ids.items() if name != "perf-sync"
    }

    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(CockpitError, match="hermes not found"):
        setup(pack)


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_seat_loads_the_plugin_and_doctor_names_one_that_does_not(env, pack_file, monkeypatch):
    import shutil

    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.pack import plugin_root
    from cockpitlib.setup import calls_tools, plugin_enabled, plugin_present, setup

    def enabled(home):
        return (yaml.safe_load(open(os.path.join(home, "config.yaml"), encoding="utf-8"))["plugins"] or {})["enabled"]

    setup(pack)
    lanes = [lane for names in seats_from(pack).values() for lane in names]
    for home in [*map(profile_dir, lanes), str(env["home"])]:
        assert os.path.realpath(os.path.join(home, "plugins", "cockpit")) == os.path.realpath(plugin_root())
        assert "cockpit" in enabled(home)
        assert plugin_present(home) and plugin_enabled(home)
    assert doctor_run(pack) == []

    seat = profile_dir("reviewer")
    os.remove(os.path.join(seat, "plugins", "cockpit"))
    config = os.path.join(seat, "config.yaml")
    settings = yaml.safe_load(open(config, encoding="utf-8"))
    stripped = {key: value for key, value in settings.items() if key != "plugins"}
    open(config, "w", encoding="utf-8").write(yaml.safe_dump(stripped, sort_keys=False))
    assert sorted(item for item in doctor_run(pack) if "plugins" in item) == [
        "reviewer plugins.enabled lacks cockpit",
        "reviewer plugins/ lacks cockpit",
    ]
    setup(pack)
    assert yaml.safe_load(open(config, encoding="utf-8")) == {**stripped, "plugins": {"enabled": ["cockpit"]}}
    assert doctor_run(pack) == []

    copied = os.path.join(profile_dir("intake"), "plugins", "cockpit")
    os.remove(copied)
    os.makedirs(copied)
    open(os.path.join(copied, "plugin.yaml"), "w", encoding="utf-8").write("name: cockpit\n")
    stale = os.path.join(profile_dir("analyst"), "plugins", "cockpit")
    os.remove(stale)
    os.symlink(str(env["root"]), stale)
    setup(pack)
    assert not os.path.islink(copied)
    assert os.path.realpath(stale) == os.path.realpath(plugin_root())

    root_link = env["home"] / "plugins" / "cockpit"
    os.remove(root_link)
    root_config = env["home"] / "config.yaml"
    root_config.write_text(
        root_config.read_text(encoding="utf-8") + "platform_toolsets:\n  cli: []\n", encoding="utf-8"
    )
    assert calls_tools(str(env["home"])) is False
    setup(pack)
    assert not os.path.lexists(root_link)
    assert not any(item.startswith("root ") for item in doctor_run(pack))
    root_config.write_text(
        root_config.read_text(encoding="utf-8").replace("  cli: []\n", "  cli: [terminal]\n"), encoding="utf-8"
    )
    assert "root plugins/ lacks cockpit" in doctor_run(pack)
    root_config.write_text("plugins: [\n", encoding="utf-8")
    assert calls_tools(str(env["home"])) is True and plugin_enabled(str(env["home"])) is False
    root_config.write_text("- not a mapping\n", encoding="utf-8")
    assert plugin_enabled(str(env["home"])) is False
    shutil.rmtree(profile_dir("gatekeeper"))
    assert plugin_enabled(profile_dir("gatekeeper")) is False


# What each fixture attaches: acme a root plugin and a skill on every seat, bravo a plugin and a skill on some seats.
EXTRAS = {
    "acme": {
        "root": ["ledger-view"],
        "plugins": {},
        "skills": {
            kind: ["house-style"] for kind in ("intake", "reviewer", "analyst", "worker", "tester", "gatekeeper")
        },
    },
    "bravo": {
        "root": [],
        "plugins": {"worker": ["trace-tap"], "tester": ["trace-tap"]},
        "skills": {"worker": ["bench-notes"]},
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_extra_plugins_and_seat_skills_land_where_the_pack_puts_them(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.errors import PackError
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.pack import _listed_providers, _plugin_providers, check_known_providers
    from cockpitlib.setup import plugin_enabled, plugin_present, setup

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    expected = EXTRAS[pack["name"]]
    other = EXTRAS["bravo" if pack["name"] == "acme" else "acme"]
    paths = {plugin["name"]: plugin["path"] for plugin in pack["extra_plugins"]}
    root_config = env["home"] / "config.yaml"
    root_config.write_text(yaml.safe_dump({"plugins": {"enabled": ["other"]}}), encoding="utf-8")

    setup(pack)
    names = {name for plugins in (expected["root"], *expected["plugins"].values()) for name in plugins}
    others = {name for plugins in (other["root"], *other["plugins"].values()) for name in plugins}
    assert names and not names & others
    home = str(env["home"])
    root_enabled = yaml.safe_load(root_config.read_text(encoding="utf-8"))["plugins"]["enabled"]
    assert root_enabled[0] == "other" and set(root_enabled) == {"other", "cockpit", *expected["root"]}
    for name in names | others:
        assert plugin_present(home, name) is (name in expected["root"])
    for kind, lanes in seats_from(pack).items():
        for lane in lanes:
            folder = profile_dir(lane)
            enabled = yaml.safe_load(open(os.path.join(folder, "config.yaml"), encoding="utf-8"))["plugins"]["enabled"]
            assert enabled == ["cockpit", *expected["plugins"].get(kind, [])]
            for name in names | others:
                attached = name in expected["plugins"].get(kind, [])
                assert plugin_present(folder, name) is attached and plugin_enabled(folder, name) is attached
                if attached:
                    assert os.path.realpath(os.path.join(folder, "plugins", name)) == paths[name]
            skills = sorted(
                entry
                for entry in os.listdir(os.path.join(folder, "skills"))
                if entry in {*sum(expected["skills"].values(), []), *sum(other["skills"].values(), [])}
            )
            assert skills == expected["skills"].get(kind, [])
    assert doctor_run(pack) == []

    kind = next(iter(expected["plugins"] or {"root": None}))
    seat = profile_dir(seats_from(pack)[kind][0]) if kind != "root" else home
    plugin = (expected["plugins"].get(kind) or expected["root"])[0]
    os.remove(os.path.join(seat, "plugins", plugin))
    skill_kind = next(iter(expected["skills"]))
    skill_lane = seats_from(pack)[skill_kind][0]
    skill = expected["skills"][skill_kind][0]
    os.remove(os.path.join(profile_dir(skill_lane), "skills", skill))
    label = seats_from(pack)[kind][0] if kind != "root" else "root"
    assert {item for item in doctor_run(pack) if "lacks" in item} == {
        f"{label} plugins/ lacks {plugin}",
        f"{skill_lane} skills/ lacks {skill}",
    }
    setup(pack)
    assert doctor_run(pack) == []

    # A seat is its own Hermes home: a provider plugin in the root home is not loaded there until the pack attaches it.
    ident = "relay-" + pack["name"][0]
    copied = tmp_path / "packs" / pack["name"]
    shutil.copytree(os.path.dirname(pack_file), copied)
    provider = copied / "plugins" / ident
    provider.mkdir(parents=True)
    (provider / "plugin.yaml").write_text(f"name: {ident}\nkind: model-provider\n", encoding="utf-8")
    (provider / "__init__.py").write_text("", encoding="utf-8")
    (env["home"] / "plugins" / "model-providers" / ident).mkdir(parents=True)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw["providers"]["relay"] = {"hermes_provider": ident, "model": "fixture-relay"}
    raw["roles"]["gatekeeper"] = "relay"
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    relayed = load(str(copied / "pack.yaml"))
    with pytest.raises(PackError, match=f"provider {ident} is a plugin of the root home only; attach it to gatekeeper"):
        check_known_providers(relayed, home)
    raw["extra_plugins"].append({"name": ident, "path": f"plugins/{ident}", "where": ["gatekeeper"]})
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    relayed = load(str(copied / "pack.yaml"))
    check_known_providers(relayed, home)
    setup(relayed)
    lane = seats_from(relayed)["gatekeeper"][0]
    gatekeeper = profile_dir(lane)
    assert ident in _listed_providers(gatekeeper) | _plugin_providers(gatekeeper)
    assert plugin_present(gatekeeper, ident, provider=True) and not plugin_enabled(gatekeeper, ident)
    assert any(f"--seat {lane}" in item for item in doctor_run(relayed))
    setup(relayed, rerender=True, seat=lane)
    assert yaml.safe_load(open(os.path.join(gatekeeper, "config.yaml"), encoding="utf-8"))["model"]["provider"] == ident
    assert doctor_run(relayed) == []
    os.remove(os.path.join(gatekeeper, "plugins", "model-providers", ident))
    assert f"{seats_from(relayed)['gatekeeper'][0]} plugins/ lacks {ident}" in doctor_run(relayed)
    shutil.rmtree(env["home"] / "plugins" / "model-providers" / ident)
    raw["extra_plugins"].pop()
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match=f"provider {ident} is not configured in Hermes"):
        check_known_providers(load(str(copied / "pack.yaml")), home)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_provider_moved_off_a_kind_leaves_its_seats(env, pack_file, monkeypatch, tmp_path):
    # Two provider plugins can claim one id; a stale link left on a seat would keep claiming it after the pack moved on.
    import shutil

    import yaml

    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.setup import plugin_present, setup

    ident = "relay-" + load(pack_file)["name"][0]
    copied = tmp_path / "packs" / "moved"
    shutil.copytree(os.path.dirname(pack_file), copied)
    provider = copied / "plugins" / ident
    provider.mkdir(parents=True)
    (provider / "plugin.yaml").write_text(f"name: {ident}\nkind: model-provider\n", encoding="utf-8")
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw["extra_plugins"].append({"name": ident, "path": f"plugins/{ident}", "where": ["gatekeeper", "reviewer"]})
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    setup(load(str(copied / "pack.yaml")))
    gatekeeper = profile_dir(seats_from(load(str(copied / "pack.yaml")))["gatekeeper"][0])
    reviewer = profile_dir(seats_from(load(str(copied / "pack.yaml")))["reviewer"][0])
    assert plugin_present(gatekeeper, ident, provider=True) and plugin_present(reviewer, ident, provider=True)
    by_hand = tmp_path / "hand-installed"
    by_hand.mkdir()
    (by_hand / "plugin.yaml").write_text("name: hand\nkind: model-provider\n", encoding="utf-8")
    os.symlink(by_hand, os.path.join(gatekeeper, "plugins", "model-providers", "hand"))
    raw["extra_plugins"][-1]["where"] = ["reviewer"]
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    setup(load(str(copied / "pack.yaml")))
    assert not os.path.lexists(os.path.join(gatekeeper, "plugins", "model-providers", ident))
    assert plugin_present(reviewer, ident, provider=True)
    assert plugin_present(gatekeeper, "hand", provider=True)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_skill_and_a_cockpit_skill_of_one_name_both_resolve(env, pack_file, monkeypatch, tmp_path):
    import shutil

    from cockpitlib.acts import kickoff_text
    from cockpitlib.errors import PackError
    from cockpitlib.lanes import profile_dir
    from cockpitlib.pack import find_skill, plugin_root
    from cockpitlib.paths import qa
    from cockpitlib.setup import setup
    from cockpitlib.skill_log import append, missing

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    own = os.path.join(os.path.dirname(pack_file), "skills", "outbox", "SKILL.md")
    has_own = pack["name"] == "bravo"
    assert os.path.isfile(own) is has_own
    bundled = os.path.join(plugin_root(), "skills", "outbox", "SKILL.md")
    assert find_skill(pack, "cockpit:outbox") == bundled
    assert find_skill(pack, "outbox") == (os.path.realpath(own) if has_own else None)
    assert find_skill(pack, "cockpit:analyze-ticket") is None
    assert "cockpit:outbox" in kickoff_text(pack, "TASK-100", "tester", "")

    ticket = "NORTH-31" if has_own else "TASK-331"
    loaded = ["test", "cockpit:outbox", *(["outbox"] if has_own else [])]
    for name in loaded:
        append(ticket, "tester-1", name)
    text = open(os.path.join(qa(), ticket, "skills", "tester-1.log"), encoding="utf-8").read()
    assert text.splitlines() == [f"skill:{name}" for name in loaded]
    asks = {"skills": {"intent": {"tracker-comment": ["outbox"], "pr-comment": ["test"]}}, "board": pack["board"]}
    intent = {"type": "tracker-comment", "ticket": "TASK-332", "created_by": "tester-1"}
    append("TASK-332", "tester-1", "cockpit:outbox")
    append("TASK-332", "tester-1", "test-extra")
    assert missing(asks, intent) == ["outbox"]
    assert missing(asks, {**intent, "type": "pr-comment"}) == ["test"]

    copied = tmp_path / "packs" / pack["name"]
    shutil.copytree(os.path.dirname(pack_file), copied)
    skills_yaml = copied / "skills.yaml"
    original = skills_yaml.read_text(encoding="utf-8")
    skills_yaml.write_text(original.replace("worker: [cockpit:outbox]", "worker: [outbox]"), encoding="utf-8")
    if has_own:
        assert load(str(copied / "pack.yaml"))["skills"]["kickoff"]["worker"] == ["outbox"]
    if not has_own:
        with pytest.raises(PackError, match="skill outbox not found \\(cockpit's own is cockpit:outbox\\)"):
            load(str(copied / "pack.yaml"))
    skills_yaml.write_text(original.replace("worker: [cockpit:outbox]", "worker: [cockpit:nope]"), encoding="utf-8")
    with pytest.raises(PackError, match="skill cockpit:nope not found$"):
        load(str(copied / "pack.yaml"))

    os.makedirs(os.path.join(profile_dir("intake"), "skills"))
    stale = os.path.join(profile_dir("intake"), "skills", "platform-map")
    os.symlink(os.path.join(plugin_root(), "skills", "platform-map"), stale)
    setup(pack)
    assert not os.path.lexists(stale)
    assert os.path.islink(os.path.join(profile_dir("intake"), "skills", "workspace"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_board_anchors_worktree_cards_where_the_pack_says(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.setup import setup

    expected = {"acme": str(env["workspace"]), "bravo": str(env["root"] / "repos" / "ledger")}[pack["name"]]
    marker = env["home"] / "kanban" / "boards" / pack["board"] / "board.json"
    setup(pack)
    assert json.loads(marker.read_text(encoding="utf-8"))["default_workdir"] == expected
    meta = json.loads(marker.read_text(encoding="utf-8"))
    meta["default_workdir"] = "/elsewhere"
    marker.write_text(json.dumps(meta), encoding="utf-8")
    setup(pack)
    assert json.loads(marker.read_text(encoding="utf-8"))["default_workdir"] == expected
    stamp = marker.stat().st_mtime_ns
    setup(pack)
    assert marker.stat().st_mtime_ns == stamp
    from cockpitlib.setup import _set_board_workdir

    marker.write_text("{not json", encoding="utf-8")
    _set_board_workdir(pack, str(marker))
    assert json.loads(marker.read_text(encoding="utf-8"))["default_workdir"] == expected
    meta["default_workdir"] = None
    marker.write_text(json.dumps(meta), encoding="utf-8")
    with (
        pytest.MonkeyPatch.context() as mp
    ):  # nested: undo() on the fixture's monkeypatch would drop the env fixture's COCKPIT_* too
        mp.setattr("cockpitlib.setup.shutil.which", lambda _name: None)
        with pytest.raises(CockpitError, match="board_workdir needs the hermes command"):
            _set_board_workdir(pack, str(marker))
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    with pytest.raises(CockpitError, match="does not exist"):
        _set_board_workdir({**pack, "board": "missing-board"}, str(marker))


# What each fixture renders: its MCP servers by seat kind, and its plain env values by seat kind.
SEAT_RENDER = {
    "acme": {
        "mcp": {
            "reviewer": {
                "docs": {
                    "command": "fixture-docs-mcp",
                    "args": ["--stdio"],
                    "env": {"DOCS_TOKEN": "${DOCS_TOKEN}"},
                    "tools": {"include": ["search", "get_page"]},
                }
            }
        },
        "env": {
            kind: {"ACME_REGION": "eu-1"}
            for kind in ("intake", "reviewer", "analyst", "worker", "tester", "gatekeeper")
        },
    },
    "bravo": {
        "mcp": {
            kind: {
                "fleet": {
                    "url": "https://mcp.north.test/sse",
                    "headers": {"Authorization": "${NORTH_MCP_AUTH}"},
                    "tools": {"exclude": ["deploy_*"]},
                }
            }
            for kind in ("intake", "reviewer", "analyst", "worker", "tester", "gatekeeper")
        },
        "env": {"worker": {"NORTH_ZONE": "b"}},
    },
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_seats_get_the_packs_mcp_servers_and_env_and_no_secret_value(env, pack_file, monkeypatch, tmp_path):
    import shutil
    import subprocess

    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    expected = SEAT_RENDER[pack["name"]]
    from cockpitlib.doctor import _env_file_problems
    from cockpitlib.errors import PackError
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.setup import _pack_env_names, seat_drift, setup

    setup(pack)
    for kind, lanes in seats_from(pack).items():
        for lane in lanes:
            config = yaml.safe_load(open(os.path.join(profile_dir(lane), "config.yaml"), encoding="utf-8"))
            assert config.get("mcp_servers", {}) == expected["mcp"].get(kind, {}), lane
            text = open(os.path.join(profile_dir(lane), ".env"), encoding="utf-8").read()
            assert sorted(_pack_env_names(text)) == sorted(expected["env"].get(kind, {}))
            for key, value in expected["env"].get(kind, {}).items():
                assert f"{key}={value}" in text
            assert oct(os.stat(os.path.join(profile_dir(lane), ".env")).st_mode & 0o777) == "0o600"
    assert seat_drift(pack) == []

    # A changed value is not drift; a missing name is. A person's own line stays through a rerender.
    kind, values = next(iter(expected["env"].items()))
    lane = seats_from(pack)[kind][0]
    path = os.path.join(profile_dir(lane), ".env")
    key = next(iter(values))
    text = open(path, encoding="utf-8").read()
    open(path, "w", encoding="utf-8").write(text.replace(f"{key}={values[key]}", f"{key}=changed") + "MINE=kept\n")
    assert seat_drift(pack) == []
    text = open(path, encoding="utf-8").read()
    open(path, "w", encoding="utf-8").write(text.replace(f"{key}=changed\n", ""))
    assert seat_drift(pack) == [f"seat drift {lane} (cockpit setup --rerender --seat {lane})"]
    setup(pack, rerender=True, seat=lane)
    assert (
        f"{key}={values[key]}" in open(path, encoding="utf-8").read()
        and "MINE=kept" in open(path, encoding="utf-8").read()
    )

    # Secrets come from an env file outside every git tree, mode 600; doctor says when one is not.
    copied = tmp_path / "packs" / pack["name"]
    shutil.copytree(os.path.dirname(pack_file), copied)
    secrets_dir = tmp_path / "private"
    secrets_dir.mkdir()
    secret_file = secrets_dir / "seat.env"
    secret_file.write_text(f"TRACKER_TOKEN=tok-{pack['name']}\n# a note\n", encoding="utf-8")
    secret_file.chmod(0o600)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw["seat_config"].setdefault("tester", {})["env_files"] = [str(secret_file)]
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    secured = load(str(copied / "pack.yaml"))
    assert _env_file_problems(secured) == []
    setup(secured, rerender=True, seat="tester-1")
    assert (
        f"TRACKER_TOKEN=tok-{pack['name']}"
        in open(os.path.join(profile_dir("tester-1"), ".env"), encoding="utf-8").read()
    )
    assert f"tok-{pack['name']}" not in (copied / "pack.yaml").read_text(encoding="utf-8")
    secret_file.chmod(0o644)
    assert _env_file_problems(secured) == [f"env file {secret_file} is readable by others (chmod 600)"]
    secret_file.chmod(0o600)
    subprocess.run(["git", "init", "-q", str(secrets_dir)], check=True)
    assert _env_file_problems(secured) == [f"env file {secret_file} is inside a git tree"]
    os.remove(secret_file)
    assert _env_file_problems(secured) == [f"env file missing {secret_file}"]
    raw["seat_config"]["tester"]["env"] = {"DEPLOY_TOKEN": "x"}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match="DEPLOY_TOKEN reads like a secret"):
        load(str(copied / "pack.yaml"))
    raw["seat_config"]["tester"].pop("env")
    raw["seat_config"]["tester"]["hermes"] = {"mcp_servers": {"x": {"url": "https://x.test"}}}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match="mcp_servers is set by cockpit"):
        load(str(copied / "pack.yaml"))


# Each fixture's block for its own extra plugin, as that plugin's validator returns it.
PLUGIN_BLOCKS = {
    "acme": ("ledger-view", {"pages": 3, "currency": "EUR"}, {"pages": "many"}, "pages must be a whole number"),
    "bravo": ("trace-tap", {"sample_rate": 0.25}, {"sample_rate": 3}, "sample_rate is between 0 and 1"),
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_another_plugins_block_is_checked_by_that_plugin(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.errors import PackError
    from cockpitlib.pack import plugin_block
    from cockpitlib.setup import setup

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    name, normalized, wrong, message = PLUGIN_BLOCKS[pack["name"]]
    assert plugin_block(pack, name) == normalized and pack["_plugins_unchecked"] == []
    copied = tmp_path / "packs" / pack["name"]
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for block, expected in (
        (wrong, f"plugins.{name}: {message}"),
        ({"cockpit": {}}, "plugins maps another plugin's name to its block"),
    ):
        raw["plugins"] = {name: block} if "cockpit" not in block else block
        (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        with pytest.raises(PackError, match=re.escape(expected)):
            load(str(copied / "pack.yaml"))
    raw["plugins"] = {name: None, "absent-plugin": {"anything": 1}}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    loose = load(str(copied / "pack.yaml"))
    assert loose["_plugins_unchecked"] == ["absent-plugin"] and plugin_block(loose, "absent-plugin") == {"anything": 1}
    monkeypatch.setenv("COCKPIT_PACK", str(copied / "pack.yaml"))
    setup(loose)
    assert "plugins.absent-plugin: the plugin is not installed, so its block is not checked" in doctor_run(loose)


@pytest.mark.parametrize("pack_file", PACKS)
def test_seat_souls_carry_the_lane_procedures_and_no_adopter_name(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import setup

    setup(pack)

    def soul(lane):
        return open(os.path.join(profile_dir(lane), "SOUL.md"), encoding="utf-8").read()

    worker = soul("worker-1")
    for phrase in (
        "`cockpit gate --background`",
        "`cockpit gate --wait <id>`",
        "`cockpit gate --baseline`",
        "Never start a second run",
        "Never pipe it through `tail`",
    ):
        assert phrase in worker
    reviewer = soul("reviewer")
    for phrase in (
        "`delegate_task`",
        "up to three subagents",
        "never for a verdict",
        "read its cited lines yourself with `read_file`",
    ):
        assert phrase in reviewer
    tester = soul("tester-1")
    for phrase in (
        "Log out of your own account",
        "do exactly the approved step and nothing else",
        "log in again with your own account",
        "the human's own session",
        "An undo is a new request.",
    ):
        assert phrase in tester
    assert "PRIVILEGED LOGIN NEEDED · <environment> · <step> · <why>" in tester

    names = set()
    for each in (load(path) for path in PACKS):
        names.update(str(each[key]) for key in ("name", "board", "workspace_branch"))
        names.update((str(each["forge"]["org"]), str(each["tracker"]["project"])))
        names.update(str(each["privileged"][key]) for key in ("environment", "label"))
        names.update(str(host) for host in each["refused"]["hosts"])
        names.update(str(store["name"]) for store in each["stores"])
    names.discard("master")
    # Cockpit's own soul text names no adopter. A pack's soul additions may; they are its own words.
    import glob
    import re

    for path in glob.glob(os.path.join(ROOT, "souls", "*.md")):
        text = open(path, encoding="utf-8").read()
        assert not [name for name in names if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text)], path


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_seat_carries_the_packs_settings_under_the_ones_cockpit_owns(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import PackError
    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import seat_drift, setup

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    setup(pack)

    def seat(lane):
        return yaml.safe_load(open(os.path.join(profile_dir(lane), "config.yaml"), encoding="utf-8"))

    common = pack["seat_config"]["_common"]["hermes"]
    assert common["agent"]["max_turns"] != other["seat_config"]["_common"]["hermes"]["agent"]["max_turns"]
    for lane in ("intake", "worker-1", "tester-1", "reviewer", "gatekeeper"):
        rendered = seat(lane)
        assert rendered["agent"]["max_turns"] == common["agent"]["max_turns"]
        assert rendered["hooks_auto_accept"] is False and rendered["approvals"]["unattended_mode"] == "deny"
        assert rendered["approvals"]["deny"][:2] == ["git push*", "cockpit publish*"]
        assert set(common.get("approvals", {}).get("deny", [])) <= set(rendered["approvals"]["deny"])
        assert rendered["model"]["provider"] == pack["providers"][pack["roles"][lane.split("-")[0]]]["hermes_provider"]
    own_role, own = next((kind, block) for kind, block in pack["seat_config"].items() if kind != "_common")
    lane = {"tester": "tester-1", "worker": "worker-1"}.get(own_role, own_role)
    key, value = next(iter(own["hermes"].items()))
    assert seat(lane)[key] == value
    assert key not in seat("gatekeeper")
    assert seat_drift(pack) == []
    path = os.path.join(profile_dir("gatekeeper"), "config.yaml")
    stamped = seat("gatekeeper")
    stamped["_config_version"] = 99
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(stamped))
    assert seat_drift(pack) == []
    stamped["agent"]["max_turns"] = 1
    open(path, "w", encoding="utf-8").write(yaml.safe_dump(stamped))
    assert seat_drift(pack) == ["seat drift gatekeeper (cockpit setup --rerender --seat gatekeeper)"]

    copied = tmp_path / "packs" / pack["name"]
    shutil.copytree(os.path.dirname(pack_file), copied)
    text = (copied / "pack.yaml").read_text(encoding="utf-8")
    assert "  intake:\n" not in text
    for bad, message in (
        (
            "  intake:\n    hermes:\n      hooks_auto_accept: true\n",
            "intake.hermes: hooks_auto_accept is set by cockpit",
        ),
        (
            "  intake:\n    hermes:\n      model:\n        provider: other\n",
            "intake.hermes: model.provider is set by cockpit",
        ),
        ("  planner:\n    hermes: {}\n", "seat_config planner: not a seat kind"),
        ("  intake:\n    mood: calm\n", "seat_config intake: mood is not a seat field"),
        ("  intake: nope\n", "seat_config intake must be a mapping"),
        ("  intake:\n    hermes: nope\n", "seat_config intake.hermes must be a mapping"),
    ):
        (copied / "pack.yaml").write_text(text.replace("seat_config:\n", "seat_config:\n" + bad), encoding="utf-8")
        with pytest.raises(PackError, match=message.replace(".", "\\.")):
            load(str(copied / "pack.yaml"))
    import yaml

    raw = yaml.safe_load(text)
    raw["seat_config"] = "nope"
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(PackError, match="seat_config must be a mapping"):
        load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_seat_soul_carries_the_packs_text_and_a_rerender_brings_it_back(env, pack_file, monkeypatch, tmp_path):
    import shutil

    from cockpitlib.errors import CockpitError
    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import ROOT_SOUL_BEGIN, seat_drift, setup

    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    pack_path = str(copied / "pack.yaml")
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    root_soul = env["home"] / "SOUL.md"
    root_soul.write_text("The human's own words stay.\n", encoding="utf-8")
    setup(pack)

    def soul(lane):
        return open(os.path.join(profile_dir(lane), "SOUL.md"), encoding="utf-8").read()

    own_kind = next(
        kind for kind, block in pack["seat_config"].items() if kind not in ("_common", "root") and block.get("soul")
    )
    lane = {"tester": "tester-1", "worker": "worker-1"}.get(own_kind, own_kind)
    text = soul(lane)
    assert f"for the {pack['name']} fixture" in text and f"for the {other['name']} fixture" not in text
    assert f"You are {lane}" in text and "{{LANE}}" not in text and "{{SLOT}}" not in text
    if own_kind == "tester":
        assert "on slot 1" in text
    assert f"for the {pack['name']} fixture" not in soul("gatekeeper")
    root_text = root_soul.read_text(encoding="utf-8")
    assert root_text.startswith("The human's own words stay.") and root_text.count(ROOT_SOUL_BEGIN) == 1
    setup(pack)
    assert root_soul.read_text(encoding="utf-8") == root_text

    soul_file = copied / "souls" / f"{own_kind}.md"
    soul_file.write_text(soul_file.read_text(encoding="utf-8") + "A later rule.\n", encoding="utf-8")
    pack = load(pack_path)
    hint = f"seat drift {lane} (cockpit setup --rerender --seat {lane})"
    assert hint in seat_drift(pack)
    with pytest.raises(CockpitError, match="no seat nobody"):
        setup(pack, rerender=True, seat="nobody")
    before = soul(lane)
    setup(pack, rerender=True, seat=lane)
    assert "A later rule." in soul(lane) and hint not in seat_drift(pack)
    backups = list((env["home"] / "backups" / "profiles").glob(f"*/{lane}/SOUL.md"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == before
    assert not list((env["home"] / "backups" / "profiles").glob("*/gatekeeper"))

    (copied / "pack.yaml").write_text(
        (copied / "pack.yaml").read_text(encoding="utf-8").replace("  root:\n    soul: souls/root.md\n", ""),
        encoding="utf-8",
    )
    setup(load(pack_path))
    assert root_soul.read_text(encoding="utf-8") == "The human's own words stay.\n"
    assert main(["setup", "--seat", lane]) == 2
    assert main(["setup", "--rerender", "--seat"]) == 2
    assert main(["setup", "now"]) == 2


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_seat_memory_starts_from_the_packs_seed_and_keeps_what_the_lane_wrote(env, pack_file, monkeypatch, tmp_path):
    import shutil

    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import KERNEL_SEED, setup

    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    pack_path = str(copied / "pack.yaml")
    monkeypatch.setenv("COCKPIT_PACK", pack_path)
    pack = load(pack_path)
    setup(pack)

    def memory(lane):
        return os.path.join(profile_dir(lane), "memories", "MEMORY.md")

    seeded_kind = next(kind for kind, block in pack["seat_config"].items() if block.get("memory_seed"))
    seed = (copied / "memory.md").read_text(encoding="utf-8")
    seeded = "intake" if seeded_kind == "_common" else {"tester": "tester-1"}.get(seeded_kind, seeded_kind)
    assert open(memory(seeded), encoding="utf-8").read() == seed
    plain = "gatekeeper" if seeded_kind != "_common" else None
    if plain:
        assert open(memory(plain), encoding="utf-8").read() == KERNEL_SEED
    lane_wrote = "worker-1" if seeded_kind == "_common" else seeded
    learned = open(memory(lane_wrote), encoding="utf-8").read() + "A lesson the lane learned.\n"
    open(memory(lane_wrote), "w", encoding="utf-8").write(learned)
    (copied / "memory.md").write_text(seed + "A newer seed line.\n", encoding="utf-8")
    pack = load(pack_path)
    setup(pack, rerender=True)
    assert open(memory(lane_wrote), encoding="utf-8").read() == learned
    untouched = "reviewer" if seeded_kind == "_common" else None
    if untouched:
        assert open(memory(untouched), encoding="utf-8").read().endswith("A newer seed line.\n")
    legacy = "analyst"
    os.remove(os.path.join(profile_dir(legacy), "memories", ".cockpit-seed"))
    open(memory(legacy), "w", encoding="utf-8").write(KERNEL_SEED)
    setup(pack, rerender=True, seat=legacy)
    expected = (copied / "memory.md").read_text(encoding="utf-8") if seeded_kind == "_common" else KERNEL_SEED
    assert open(memory(legacy), encoding="utf-8").read() == expected


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_resume_hook_is_the_pre_model_call(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.paths import hermes_home
    from cockpitlib.resume import hook_registered
    from cockpitlib.setup import setup

    path = os.path.join(hermes_home(), "config.yaml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write("hooks:\n  pre_tool_call:\n    - command: /tmp/resume-context.sh\n")
    assert hook_registered() is False
    assert "resume hook not registered" in doctor_run(pack)
    setup(pack)
    text = open(path, encoding="utf-8").read()
    assert hook_registered() is True
    assert text.count("pre_llm_call:") == 1
    assert "resume hook not registered" not in doctor_run(pack)
    setup(pack)
    assert open(path, encoding="utf-8").read().count("pre_llm_call:") == 1


@pytest.mark.parametrize("pack_file", PACKS)
def test_doctor_lists_every_seat_whose_profile_differs(env, pack_file, monkeypatch):
    import copy

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.lanes import profile_dir
    from cockpitlib.setup import _render_seat, seat_drift

    changed = copy.deepcopy(pack)
    changed["providers"]["judgment"]["model"] = f"model-{pack['name']}"
    changed["providers"]["judgment"]["context_length"] = 4096
    changed["providers"]["judgment"]["reasoning_effort"] = pack["name"]
    other_model = f"model-{other['name']}"
    assert changed["providers"]["judgment"]["model"] != other_model
    rendered = _render_seat(changed, "intake", "intake")
    assert f"model-{pack['name']}" in rendered["config"]
    assert other_model not in rendered["config"]
    assert "4096" in rendered["config"] and pack["name"] in rendered["config"]
    folder = profile_dir("intake")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "SOUL.md"), "w", encoding="utf-8").write(rendered["soul"])
    open(os.path.join(folder, "config.yaml"), "w", encoding="utf-8").write(
        rendered["config"].replace(f"model-{pack['name']}", other_model)
    )
    review = _render_seat(changed, "reviewer", "reviewer")
    reviewer = profile_dir("reviewer")
    os.makedirs(reviewer, exist_ok=True)
    open(os.path.join(reviewer, "SOUL.md"), "w", encoding="utf-8").write("other soul\n")
    open(os.path.join(reviewer, "config.yaml"), "w", encoding="utf-8").write(review["config"])
    drifted = seat_drift(changed)
    assert (
        "seat drift intake (cockpit setup --rerender --seat intake)" in drifted
        and "seat drift reviewer (cockpit setup --rerender --seat reviewer)" in drifted
    )
    open(os.path.join(folder, "config.yaml"), "w", encoding="utf-8").write(rendered["config"])
    from cockpitlib.setup import _write_seat_env

    _write_seat_env(changed, "intake", os.path.join(folder, ".env"), "intake")
    fixed = seat_drift(changed)
    assert (
        "seat drift intake (cockpit setup --rerender --seat intake)" not in fixed
        and "seat drift reviewer (cockpit setup --rerender --seat reviewer)" in fixed
    )
    broken = copy.deepcopy(changed)
    broken["providers"]["judgment"] = "nope"
    failed = seat_drift(broken)
    assert any(item.startswith("seat render failed intake: missing model") for item in failed)
    assert all("default:" not in item for item in failed)
    monkeypatch.setattr("cockpitlib.setup._soul", lambda *_args, **_kwargs: " ")
    assert any("empty render" in item for item in seat_drift(changed))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_missing_calendar_does_not_copy_the_other_pack(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.pack import policy
    from cockpitlib.settings import load as load_settings
    from cockpitlib.setup import cron_schedule

    assert pack["working_days"] != other["working_days"]
    assert load_settings(pack)["shared_chrome_hours"] == pack["shared_chrome_hours"]
    assert load_settings(pack)["shared_chrome_hours"] != other["shared_chrome_hours"]
    bare = {"hours": {"digest": 1}, "seats": pack["seats"]}
    assert policy(bare)["working_days"] == []
    assert other["working_days"] not in (policy(bare)["working_days"],)
    assert cron_schedule(bare, "morning-digest", "0 0 * * *") == "0 0 * * *"
    assert load_settings(bare)["shared_chrome_hours"] == 0


@pytest.mark.parametrize("pack_file", PACKS)
def test_cron_hours_come_from_the_pack(env, pack_file):
    pack = load(pack_file)
    other = load(PACKS[0] if pack["name"] == "bravo" else PACKS[1])
    from cockpitlib.setup import CRON_JOBS, cron_schedule

    timed = {"standup", "bumps", "export", "morning-digest", "perf-sync", "advisories"}
    for name, default, _script in CRON_JOBS:
        for hour in (8, 9, 11, 12, 15):
            assert f" {hour} " not in f" {default} "
        if name not in timed:
            assert cron_schedule(pack, name, default) == default
            continue
        schedule = cron_schedule(pack, name, default)
        assert schedule != cron_schedule(other, name, default)
        assert schedule != default
        assert cron_schedule({}, name, default) == default


@pytest.mark.parametrize("pack_file", PACKS[:1])
def test_a_seat_raised_in_the_settings_is_set_up_the_same_as_one_the_pack_declares(
    env, pack_file, monkeypatch, tmp_path
):
    """A seat is its config *and* its plugins, and the config names a provider only a plugin supplies.

    The Settings page writes the owner's seat count to the settings, and dispatch reads it from there,
    so raising it makes lanes cockpit will hand cards to. Creating the config without the plugins made
    a lane whose every card died in the worker with `Unknown provider`, before the agent existed to
    say so — the config promised something the seat could not reach.
    """
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.settings import ensure_seat_profiles, save
    from cockpitlib.settings import load as settings_load
    from cockpitlib.setup import setup

    plugged = _plugged(pack_file, tmp_path)
    monkeypatch.setenv("COCKPIT_PACK", plugged)
    pack = load(plugged)
    setup(pack)

    def linked(lane):
        folder = os.path.join(profile_dir(lane), "plugins")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    declared = linked("analyst")
    assert declared, "the seat the pack declares has its plugins"

    # the owner raises the count in Settings; the pack is untouched
    save(pack, {**settings_load(pack), "seats": {**settings_load(pack)["seats"], "analyst": 3}})
    assert seats_from(pack, settings_load(pack)["seats"])["analyst"] == ["analyst", "analyst-2", "analyst-3"]
    assert ensure_seat_profiles(pack) == ["analyst-2", "analyst-3"]

    for lane in ("analyst-2", "analyst-3"):
        assert os.path.isfile(os.path.join(profile_dir(lane), "config.yaml")), f"{lane} has a config"
        assert linked(lane) == declared, f"{lane} reaches the same plugins as the seat the pack declares"


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_hh_mm_time_gives_the_cron_its_minute_and_a_bad_time_is_refused(env, pack_file, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import PackError
    from cockpitlib.setup import cron_schedule
    from cockpitlib.window import clock

    pack = load(pack_file)
    hour, minute = clock(pack["hours"]["bumps"])
    assert cron_schedule(pack, "bumps", "x").startswith(f"{minute} {hour} ") and minute != 0
    assert cron_schedule(pack, "bumps", "x") != cron_schedule(_other(pack), "bumps", "x")
    assert clock(7) == (7, 0) and clock("23:59") == (23, 59)
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for value, message in (
        ({"bumps": "25:00"}, "hours.bumps: a time is a whole hour or HH:MM"),
        ({"perf": "noon"}, "hours.perf"),
        ({"ci_settle_minutes": 0}, "hours.ci_settle_minutes is a number above zero"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, "hours": {**raw["hours"], **value}}, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_named_prompts_fill_souls_and_kickoff_text_and_a_missing_one_turns_doctor_red(
    env, pack_file, monkeypatch, tmp_path
):
    import shutil

    import yaml

    from cockpitlib.errors import PackError

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    other = _other(pack)
    from cockpitlib.acts import kickoff_text
    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.paths import records_name
    from cockpitlib.prompts import path_of, resolve
    from cockpitlib.setup import _soul

    own = open(pack["prompts"]["plan-format"], encoding="utf-8").read().strip()
    theirs = open(other["prompts"]["plan-format"], encoding="utf-8").read().strip()
    assert own != theirs
    soul = _soul(pack, "intake", "intake")
    assert (
        own in soul
        and theirs not in soul
        and "{{prompt:" not in soul
        and "{{RECORDS}}" not in _soul(pack, "worker-1", "worker")
    )
    assert f"`{records_name()}/qa`" in _soul(pack, "reviewer", "reviewer")
    named = "handover" if "handover" in pack["prompts"] else "plan-format"
    assert own in kickoff_text(pack, "TASK-1", "intake", f"please {{{{prompt:{named}}}}}")
    with pytest.raises(CockpitError, match="no prompt nowhere"):
        resolve(pack, "{{prompt:nowhere}}")
    bare = {key: value for key, value in pack.items() if key != "prompts"}
    assert path_of(bare, "plan-format").endswith(os.path.join("prompts", "plan-format.md"))  # cockpit's own default
    assert path_of(bare, "nowhere") == ""
    assert not any(item.startswith("prompt ") for item in doctor_run(pack))
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    (copied / "pack.yaml").write_text(
        yaml.safe_dump({**raw, "prompts": {"plan-format": "prompts/gone.md"}}, sort_keys=False), encoding="utf-8"
    )
    broken = load(str(copied / "pack.yaml"))
    assert f"prompt plan-format missing: {copied / 'prompts' / 'gone.md'}" in doctor_run(broken)
    for value in ({"Bad Name": "x"}, ["x"], {"ok": ""}):
        (copied / "pack.yaml").write_text(yaml.safe_dump({**raw, "prompts": value}, sort_keys=False), encoding="utf-8")
        with pytest.raises(PackError, match="prompts maps a lowercase name"):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_two_seats_of_every_role_render_every_seat(env, pack_file, monkeypatch, tmp_path):
    import shutil

    import yaml

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.setup import setup

    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    raw["seats"] = {"slots": 2, "intake": 2, "reviewer": 2, "analyst": 2}
    (copied / "pack.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    pack = load(str(copied / "pack.yaml"))
    seats = seats_from(pack)
    assert (
        seats["intake"] == ["intake", "intake-2"]
        and seats["worker"] == ["worker-1", "worker-2"]
        and seats["tester"] == ["tester-1", "tester-2"]
    )
    setup(pack)
    for lane in [lane for names in seats.values() for lane in names]:
        assert os.path.isfile(os.path.join(profile_dir(lane), "config.yaml")), lane
        assert lane in open(os.path.join(profile_dir(lane), "SOUL.md"), encoding="utf-8").read()


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_advisories_block_and_its_schedule_come_from_the_pack(env, pack_file, tmp_path):
    import shutil

    import yaml

    from cockpitlib.errors import PackError
    from cockpitlib.setup import cron_schedule

    pack = load(pack_file)
    assert (
        cron_schedule(pack, "advisories", "30m")
        == f"{pack['advisories']['minutes']}m"
        != cron_schedule(_other(pack), "advisories", "30m")
    )
    assert cron_schedule({**pack, "advisories": None}, "advisories", "30m") == "30m"
    name = os.path.basename(os.path.dirname(pack_file))
    copied = tmp_path / "packs" / name
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    for value, message in (
        ([], "advisories takes sources"),
        ({"feeds": []}, "advisories takes sources"),
        ({"sources": ["mailing-list"]}, "advisories.sources names sources"),
        ({"sources": []}, "advisories.sources names sources"),
        ({"alert": {"critical": "yes"}}, "advisories.alert takes"),
        ({"alert": {"high_days": -1}}, "advisories.alert takes"),
        ({"alert": {"loud": True}}, "advisories.alert takes"),
        ({"minutes": 1}, "advisories.minutes"),
        ({"minutes": True}, "advisories.minutes"),
    ):
        (copied / "pack.yaml").write_text(
            yaml.safe_dump({**raw, "advisories": value}, sort_keys=False), encoding="utf-8"
        )
        with pytest.raises(PackError, match=re.escape(message)):
            load(str(copied / "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_daily_standup_note_is_on_by_default_and_the_pack_can_turn_it_off(env, pack_file, monkeypatch, tmp_path):
    """standup_enabled: false — no cron job (one a setup made before is removed), no draft, no Inbox row."""
    import shutil

    import yaml

    from cockpitlib.errors import CockpitError, PackError
    from cockpitlib.ops import standup_draft
    from cockpitlib.setup import CRON_JOBS, cron_plan, cron_schedule, standup_enabled

    pack = load(pack_file)
    assert standup_enabled(pack) is True, "on by default"
    copied = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), copied)
    raw = yaml.safe_load((copied / "pack.yaml").read_text(encoding="utf-8"))
    (copied / "pack.yaml").write_text(
        yaml.safe_dump({**raw, "standup_enabled": "no"}, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(PackError, match="standup_enabled"):
        load(str(copied / "pack.yaml"))
    (copied / "pack.yaml").write_text(
        yaml.safe_dump({**raw, "standup_enabled": False}, sort_keys=False), encoding="utf-8"
    )
    off = load(str(copied / "pack.yaml"))
    assert standup_enabled(off) is False
    jobs = [
        {"name": name, "id": f"id-{name}", "schedule": {"kind": "cron", "expr": cron_schedule(off, name, default)}}
        for name, default, _script in CRON_JOBS
    ]
    planned = cron_plan(jobs, off)
    assert planned == [{"op": "remove", "name": "standup", "schedule": "", "script": "standup.sh", "id": "id-standup"}]
    assert all(row["name"] != "standup" for row in cron_plan(None, off)), "never created while off"
    assert standup_draft(off, after_send="skip") == "the standup note is off (standup_enabled: false)"
    with pytest.raises(CockpitError, match="standup note is off"):
        standup_draft(off)


@pytest.mark.parametrize("pack_file", PACKS)
def test_doctor_sees_a_seat_run_on_another_provider_and_a_missing_provider_dependency(
    env, pack_file, monkeypatch, tmp_path
):
    # Two plugins can claim one provider id; nothing errors, the seat just runs on the wrong one. Its root sessions show
    # it two in a row; one session elsewhere is a fallback or a /model switch, and a delegated child may run elsewhere.
    import sqlite3
    import time

    import yaml

    from cockpitlib import doctor
    from cockpitlib.lanes import profile_dir, seats_from
    from cockpitlib.setup import setup

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    setup(pack)
    lane = seats_from(pack)["reviewer"][0]
    folder = profile_dir(lane)
    configured = yaml.safe_load(open(os.path.join(folder, "config.yaml"), encoding="utf-8"))["model"]["provider"]
    db = sqlite3.connect(os.path.join(folder, "state.db"))
    db.execute("create table sessions (id text, billing_provider text, started_at real, parent_session_id text)")
    later = time.time() + 60

    def session(name, provider, offset, parent=None):
        db.execute("insert into sessions values (?, ?, ?, ?)", (name, provider, later + offset, parent))
        db.commit()

    def resolver(name, request):
        # Hermes's alias table, as hermes_bridge/plugins.py `canonical` answers from it.
        return {
            "results": [
                {
                    item: {"an-alias": configured.lower()}.get(item.lower(), item.lower())
                    for item in request["ops"][0]["names"]
                }
            ]
        }

    monkeypatch.setattr("cockpitlib.hermes_runtime.run_helper", resolver)
    session("old", "someone-else", -(10**6) - 60)
    session("one", "someone-else", 1)
    assert doctor.provider_problems(pack) == []  # one session elsewhere is not a claim
    session("child", configured, 2, parent="one")  # a delegated child does not count either way
    session("two", "Someone-Else", 3)
    session("empty", "", 4)
    expected = (
        f"{lane} ran its last two sessions on provider Someone-Else, configured {configured}: "
        f"another provider plugin may claim {configured}"
    )
    assert doctor.provider_problems(pack) == [expected]
    assert expected in doctor.run(pack)
    monkeypatch.setattr(
        "cockpitlib.hermes_runtime.run_helper", lambda name, request: (_ for _ in ()).throw(RuntimeError("no hermes"))
    )
    assert doctor.provider_problems(pack) == [expected]  # Hermes cannot resolve the names: still reported
    monkeypatch.setattr("cockpitlib.hermes_runtime.run_helper", resolver)
    config_path = os.path.join(folder, "config.yaml")
    aliased = yaml.safe_load(open(config_path, encoding="utf-8"))
    aliased["model"]["provider"] = "someone-else-alias"
    resolved = {"someone-else-alias": "someone-else"}
    monkeypatch.setattr(
        "cockpitlib.hermes_runtime.run_helper",
        lambda name, request: {
            "results": [{item: resolved.get(item.lower(), item.lower()) for item in request["ops"][0]["names"]}]
        },
    )
    stamp = os.path.getmtime(config_path)
    open(config_path, "w", encoding="utf-8").write(yaml.safe_dump(aliased))
    os.utime(config_path, (stamp, stamp))
    assert doctor.provider_problems(pack) == []  # an alias Hermes resolves to the provider it ran on
    aliased["model"]["provider"] = configured
    open(config_path, "w", encoding="utf-8").write(yaml.safe_dump(aliased))
    os.utime(config_path, (stamp, stamp))
    monkeypatch.setattr("cockpitlib.hermes_runtime.run_helper", resolver)
    session("back", configured.upper(), 5)
    assert doctor.provider_problems(pack) == []  # case is not a different provider
    session("c1", "custom", 6)
    session("c2", "custom", 7)
    assert doctor.provider_problems(pack) == []  # custom is stored without its name
    db.close()
    assert doctor.provider_drift(str(tmp_path), "x") == "" and doctor.last_providers(str(tmp_path)) == []
    (tmp_path / "state.db").write_text("not a database")
    assert doctor.last_providers(str(tmp_path)) == []
    bare = tmp_path / "bare"
    bare.mkdir()
    plain = sqlite3.connect(bare / "state.db")
    plain.execute("create table sessions (id text, started_at real)")
    plain.close()
    assert doctor.last_providers(str(bare)) == []

    provider = tmp_path / "sdk-provider"
    provider.mkdir()
    (provider / "plugin.yaml").write_text(
        "name: sdk\nkind: model-provider\npython_dependencies:\n  - cursor-sdk>=1.0.32,<2\n"
        "pip_dependencies: [PyYAML]\n",
        encoding="utf-8",
    )
    pack["extra_plugins"] = [
        *pack["extra_plugins"],
        {"name": "sdk", "path": str(provider), "where": ["reviewer"], "provider": True},
    ]
    asked = []

    def helper(name, request):
        asked.append((name, request["ops"][0]))
        return {"results": [{"cursor-sdk>=1.0.32,<2": True, "PyYAML": False}]}

    monkeypatch.setattr("cockpitlib.hermes_runtime.run_helper", helper)
    assert doctor.provider_problems(pack)[-1] == "Hermes's environment lacks PyYAML, a provider plugin's dependency"
    assert asked == [("plugins", {"op": "installed", "requirements": ["PyYAML", "cursor-sdk>=1.0.32,<2"]})]

    def broken(name, request):
        raise RuntimeError("hermes not found")

    monkeypatch.setattr("cockpitlib.hermes_runtime.run_helper", broken)
    assert doctor.provider_problems(pack)[-1] == "provider dependencies not checked: hermes not found"
    monkeypatch.setattr(
        "cockpitlib.hermes_runtime.run_helper", lambda name, request: {"results": [{"error": "bad requirement"}]}
    )
    assert doctor.provider_problems(pack)[-1].startswith("provider dependencies not checked:")


def test_the_plugins_helper_resolves_provider_aliases_as_hermes_does(monkeypatch):
    import runpy
    import types

    helper = runpy.run_path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hermes_bridge", "plugins.py")
    )
    providers = types.ModuleType("hermes_cli.providers")
    providers.normalize_provider = lambda name: {"claude": "anthropic"}.get(name.strip().lower(), name.strip().lower())
    auth = types.ModuleType("hermes_cli.auth")
    auth._plugin_aliases = lambda: {"cursor-cli": "cursor-agent"}
    package = types.ModuleType("hermes_cli")
    monkeypatch.setitem(sys.modules, "hermes_cli", package)
    monkeypatch.setitem(sys.modules, "hermes_cli.providers", providers)
    monkeypatch.setitem(sys.modules, "hermes_cli.auth", auth)
    assert helper["_canonical"]({"names": ["Claude", "cursor-cli", "cursor"]}) == {
        "Claude": "anthropic",
        "cursor-cli": "cursor-agent",
        "cursor": "cursor",
    }
    del auth._plugin_aliases
    assert helper["_canonical"]({"names": ["cursor-cli"]}) == {"cursor-cli": "cursor-cli"}


def test_the_plugins_helper_says_which_requirements_hermes_has(monkeypatch, capsys):
    # By distribution, not a guessed import name: PyYAML imports as yaml.
    import runpy

    helper = runpy.run_path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hermes_bridge", "plugins.py")
    )
    wanted = ["PyYAML", "pytest>=1", "pytest>=999", "no-such-dist-x", "foo; python_version < '3'"]
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"ops": [{"op": "installed", "requirements": wanted}, {"op": "missing"}]}))
    )
    assert helper["main"]() == 0
    results = json.loads(capsys.readouterr().out)["results"]
    assert results[0] == {
        "PyYAML": True,
        "pytest>=1": True,
        "pytest>=999": False,
        "no-such-dist-x": False,
        "foo; python_version < '3'": None,
    }
    assert "error" in results[1]
    import builtins

    real = builtins.__import__

    def no_packaging(name, *args, **kwargs):
        if name.startswith("packaging"):
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_packaging)
    assert helper["_installed"]({"requirements": ["PyYAML>=999", "no-such-dist-x", "foo; python_version < '3'"]}) == {
        "PyYAML>=999": True,
        "no-such-dist-x": False,
        "foo; python_version < '3'": None,
    }


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_that_still_names_more_worker_branch_prefixes_is_refused(pack_file, tmp_path):
    import shutil

    from cockpitlib.errors import PackError

    key = "worker_branch_prefixes"
    copied = tmp_path / "pack"
    shutil.copytree(os.path.dirname(pack_file), copied)
    with open(copied / "pack.yaml", "a", encoding="utf-8") as handle:
        handle.write(f"\n{key}: [agent]\n")
    with pytest.raises(
        PackError,
        match=f"^unknown key {key}$",
    ):
        load(str(copied / "pack.yaml"))


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("fixture-b", ("fixture-strong", "high")),  # any Hermes provider: Hermes's own effort field
        ("cursor", ("fixture-strong@reasoning_effort=high", None)),  # Cursor's SDK names the parameter in the model id
        ("cursor-subscription-directsdk", ("fixture-strong@reasoning_effort=high", None)),
    ],
)
def test_a_card_model_names_its_effort_whatever_provider_runs_the_lane(env, monkeypatch, provider, expected):
    """`model@reasoning_effort=high` on a card (a supervisor card model) runs at that effort on any provider: a
    pack that moves its seats from one provider to another keeps its plan cards at high effort."""
    import sqlite3

    from cockpitlib.kanban import db_path, place_card

    pack = load(PACKS[0])
    pack["providers"]["worker"]["hermes_provider"] = provider
    card = place_card(
        pack["board"],
        "ACME-1: plan",
        "analyst",
        body="plan",
        pack=pack,
        model_override="fixture-strong@reasoning_effort=high",
    )
    db = sqlite3.connect(db_path(pack["board"]))
    assert db.execute("select model_override, reasoning_effort from tasks where id = ?", (card,)).fetchone() == expected
    plain = place_card(
        pack["board"], "ACME-2: plan", "analyst-2", body="plan", pack=pack, model_override="fixture-fast"
    )
    assert db.execute("select model_override, reasoning_effort from tasks where id = ?", (plain,)).fetchone() == (
        "fixture-fast",
        None,
    )
