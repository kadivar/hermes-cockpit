# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Doctor's findings carry a tier. An error fails doctor and setup; a warning is printed with the line that resolves it
and fails only under --strict; a note never does. Which checks guard a boundary is pinned in
tests/contract/doctor-security.json: each of them is an error, fires as one, and no flag turns it into less. The lines
doctor.run returns for a given state are the ones it returned before the tiers existed."""

import json
import os
import re
import subprocess

import pytest
import yaml

from cockpitlib import cli, doctor, hermes_runtime, notify
from cockpitlib.errors import PackError
from cockpitlib.lanes import profile_dir, seats_from
from cockpitlib.pack import _egress, load
from cockpitlib.setup import cursor_hooks_path, setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
CONTRACT = os.path.join(ROOT, "tests", "contract")
SECURITY = json.load(open(os.path.join(CONTRACT, "doctor-security.json"), encoding="utf-8"))["security"]
LINES = json.load(open(os.path.join(CONTRACT, "doctor-lines.json"), encoding="utf-8"))
FLAGS = ([], ["--strict"], ["--online"], ["--json"], ["--strict", "--online", "--json"])


def _set_up(pack_file, monkeypatch) -> dict:
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    setup(pack)
    return pack


def _ids(found, severity) -> list:
    return [item["id"] for item in found if item["severity"] == severity]


# ---------- the lines are the ones doctor always printed ----------


def _placed(lines, env) -> list:
    """The lines with this test's folders named, as the pinned file names them."""
    out = []
    for line in lines:
        for name, path in (
            ("{home}", str(env["home"])),
            ("{workspace}", str(env["workspace"])),
            ("{root}", str(env["root"])),
            ("{plugin}", ROOT),
        ):
            line = line.replace(os.path.realpath(path), name).replace(path, name)
        out.append(line)
    return out


@pytest.mark.parametrize("pack_file", PACKS)
def test_run_returns_for_three_states_the_lines_it_returned_before_the_tiers(env, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    pinned = LINES[pack["name"]]
    assert _placed(doctor.run(pack), env) == pinned["unset"]
    setup(pack)
    assert doctor.run(pack) == pinned["set-up"] == []
    thin = dict(pack)
    thin["egress"] = {"production_hosts": [], "terminal_deny": [], "sacred": [], "infra_paths": []}
    thin["repos"] = {"repos": [{"name": "api", "gates": []}]}
    thin["_dir"] = str(env["workspace"])
    thin["skills"] = {**pack["skills"], "router": "missing.md"}
    assert _placed(doctor.run(thin), env) == pinned["thin"]


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_that_was_green_still_reads_doctor_ok_and_exits_zero(env, pack_file, monkeypatch, capsys):
    pack = _set_up(pack_file, monkeypatch)
    found = doctor.findings(pack)
    assert _ids(found, "error") == []
    assert all(doctor.CHECKS[item["id"]]["born"] for item in found if item["severity"] == "warning"), (
        "only checks born with the tiers warn"
    )
    monkeypatch.setattr(doctor, "_collect", lambda pack, online: ([], {"version": "0.22.2", "problem": "", "note": ""}))
    assert cli.main(["doctor"]) == 0 and capsys.readouterr().out == "doctor: OK\n"


# ---------- the tiers ----------


def test_every_finding_has_the_six_fields_and_every_failing_check_names_its_fix():
    for check_id, spec in doctor.CHECKS.items():
        assert re.fullmatch(r"[a-z]+(-[a-z]+)*\.[a-z]+(-[a-z]+)*", check_id), check_id
        assert spec["severity"] in ("error", "warning", "info") and isinstance(spec["security"], bool)
        assert spec["fix"] or spec["severity"] == "info", f"{check_id} names no fix"
        found = doctor._finding(
            check_id,
            "a line",
            "worker-1",
            {"pack": "/p", "home": "/h", "plugin": "/k", "verified": "0.22", "events": "x"},
        )
        assert sorted(found) == ["fix", "id", "message", "security", "severity", "subject"]
        assert found["severity"] == spec["severity"] and "{" not in found["fix"], check_id


def test_the_pinned_list_is_exactly_the_checks_that_guard_a_boundary_and_each_is_an_error():
    registered = sorted(check_id for check_id, spec in doctor.CHECKS.items() if spec["security"])
    assert SECURITY == sorted(SECURITY), "the pinned list is sorted"
    assert [check_id for check_id in SECURITY if check_id not in registered] == [], (
        "pinned, and no longer a security check"
    )
    assert [check_id for check_id in registered if check_id not in SECURITY] == [], (
        "a security check the pinned list does not name"
    )
    assert [check_id for check_id in SECURITY if doctor.CHECKS[check_id]["severity"] != "error"] == []
    assert [check_id for check_id, spec in doctor.CHECKS.items() if spec["security"] and spec["born"]] == []


def test_strict_adds_the_warnings_to_what_fails_and_takes_no_error_away():
    found = [{"severity": "error", "id": "a"}, {"severity": "warning", "id": "b"}, {"severity": "info", "id": "c"}]
    assert [item["id"] for item in doctor.failing(found)] == ["a"]
    assert [item["id"] for item in doctor.failing(found, strict=True)] == ["a", "b"]


# ---------- each security check fires, as an error, whatever the flags ----------


def _edit(path, old, new) -> None:
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new))


def _push_passes(pack, env, monkeypatch, tmp_path):
    real = doctor.check
    monkeypatch.setattr(
        doctor, "check", lambda command, **how: "" if command.startswith("git push") else real(command, **how)
    )


def _forge_write_passes(pack, env, monkeypatch, tmp_path):
    real = doctor.check
    monkeypatch.setattr(
        doctor, "check", lambda command, **how: "" if command.startswith("gh pr create") else real(command, **how)
    )


def _allowed_read_is_a_push(pack, env, monkeypatch, tmp_path):
    pack["allowed"] = {"reads": [*pack["allowed"]["reads"], "git push origin main"]}


def _auto_decompose(pack, env, monkeypatch, tmp_path):
    _edit(os.path.join(str(env["home"]), "config.yaml"), "auto_decompose: false", "auto_decompose: true")


def _review_dispatch(pack, env, monkeypatch, tmp_path):
    _edit(os.path.join(str(env["home"]), "config.yaml"), "review_dispatch: false", "review_dispatch: true")


def _hook_unlisted(pack, env, monkeypatch, tmp_path):
    os.remove(os.path.join(profile_dir("reviewer"), "shell-hooks-allowlist.json"))


def _seat_without_plugin(pack, env, monkeypatch, tmp_path):
    os.remove(os.path.join(profile_dir("reviewer"), "plugins", "cockpit"))


def _seat_without_lane(pack, env, monkeypatch, tmp_path):
    _edit(os.path.join(profile_dir("intake"), ".env"), "COCKPIT_LANE=intake", "COCKPIT_LANE_WAS=intake")


def _seat_shares_the_browser_home(pack, env, monkeypatch, tmp_path):
    pack["lanes"] = {**(pack.get("lanes") or {}), "browser_session": True}  # the seats were rendered before the setting


def _no_hosts(pack, env, monkeypatch, tmp_path):
    pack["egress"] = {**pack["egress"], "production_hosts": [], "host_probes": {}}


def _host_passes(pack, env, monkeypatch, tmp_path):
    pack["egress"] = {
        **pack["egress"],
        "production_hosts": [r"app\.example\.test"],
        "host_probes": {"refused": ["curl https://shop.example.test/login"], "allowed": []},
    }


def _pattern_unreadable(pack, env, monkeypatch, tmp_path):
    pack["egress"] = {**pack["egress"], "production_hosts": [*pack["egress"]["production_hosts"], "shop(.example"]}


def _probe_refused(pack, env, monkeypatch, tmp_path):
    pack["egress"] = {
        **pack["egress"],
        "production_hosts": [r"example\.test"],
        "host_probes": {"refused": [], "allowed": ["git -C /srv/example.test status"]},
    }


def _fence_absent(pack, env, monkeypatch, tmp_path):
    pack["agent"] = {**pack["agent"], "cursor_hooks": True}
    if os.path.isfile(cursor_hooks_path()):
        os.remove(cursor_hooks_path())


def _env_file(pack, tmp_path, mode=0o600) -> str:
    folder = tmp_path / "private"
    folder.mkdir()
    path = folder / "seat.env"
    path.write_text("TRACKER_TOKEN=tok\n", encoding="utf-8")
    path.chmod(mode)
    config = dict(pack.get("seat_config") or {})
    config["tester"] = {**(config.get("tester") or {}), "env_files": [str(path)]}
    pack["seat_config"] = config
    return str(path)


def _env_file_gone(pack, env, monkeypatch, tmp_path):
    os.remove(_env_file(pack, tmp_path))


def _env_file_open(pack, env, monkeypatch, tmp_path):
    _env_file(pack, tmp_path, 0o644)


def _env_file_tracked(pack, env, monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", os.path.dirname(_env_file(pack, tmp_path))], check=True)


def _index_stale(pack, env, monkeypatch, tmp_path):
    # a stand-in for the index: the real state takes a GPG key and a store changed behind it (tests/test_vault.py builds it)
    monkeypatch.setattr(
        "cockpitlib.scrub.load", lambda: {"sources": [{"source": "gpg", "locked": True, "mtime": 1, "mtime_now": 2}]}
    )


def _key_unwrapped(pack, env, monkeypatch, tmp_path):
    from cockpitlib.vault import _hermes_key

    os.makedirs(os.path.dirname(_hermes_key()), exist_ok=True)
    open(_hermes_key(), "w", encoding="utf-8").write("k\n")


def _soul_edited(pack, env, monkeypatch, tmp_path):
    with open(os.path.join(profile_dir("analyst"), "SOUL.md"), "a", encoding="utf-8") as handle:
        handle.write("\nan edit made by hand\n")


def _newer_hermes_changed_its_hooks(pack, env, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "0.24.0")
    monkeypatch.setenv("COCKPIT_STUB_HOOKS", "no-block")
    monkeypatch.setattr(hermes_runtime, "_published", {})


# Two of these stand in for the kernel's own deny function (a push that passes cannot be made without replacing it), and
# the stale index stands in for scrub's file; every other case is the real state on disk or in the pack.
CASES = {
    "egress.push-blocked": _push_passes,
    "egress.forge-write-blocked": _forge_write_passes,
    "egress.allowed-read-denied": _allowed_read_is_a_push,
    "hermes.auto-decompose": _auto_decompose,
    "hermes.review-dispatch": _review_dispatch,
    "egress.hook-allowlisted": _hook_unlisted,
    "seat.plugin": _seat_without_plugin,
    "seat.env-lane": _seat_without_lane,
    "seat.env-browser-home": _seat_shares_the_browser_home,
    "egress.production-hosts-empty": _no_hosts,
    "egress.production-host-blocked": _host_passes,
    "egress.pattern-invalid": _pattern_unreadable,
    "egress.host-probe-allowed": _probe_refused,
    "fence.editor-hook": _fence_absent,
    "env-file.missing": _env_file_gone,
    "env-file.readable": _env_file_open,
    "env-file.in-git": _env_file_tracked,
    "vault.locked": _index_stale,
    "vault.key-unsealed": _key_unwrapped,
    "seat.drift": _soul_edited,
    "hermes.newer-unprobed": _newer_hermes_changed_its_hooks,
}


def test_every_pinned_security_check_has_a_case_that_makes_it_fire():
    assert sorted(CASES) == SECURITY


@pytest.mark.parametrize("check_id", sorted(CASES))
@pytest.mark.parametrize("pack_file", PACKS)
def test_a_security_check_fires_as_an_error_and_no_flag_lets_doctor_pass(
    env, pack_file, check_id, monkeypatch, tmp_path, capsys
):
    pack = _set_up(pack_file, monkeypatch)
    assert check_id not in [item["id"] for item in doctor.findings(pack)], "the state is green before the case is built"
    CASES[check_id](pack, env, monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_pack", lambda: pack)
    fired = [item for item in doctor.findings(pack) if item["id"] == check_id]
    assert fired and all(item["severity"] == "error" and item["security"] and item["fix"] for item in fired)
    assert fired[0]["message"] in doctor.run(pack), "migrate verify still sees it"
    for flags in FLAGS:
        capsys.readouterr()
        assert cli.main(["doctor", *flags]) == 1, flags
        out = capsys.readouterr().out
        if "--json" in flags:
            told = json.loads(out)
            assert told["ok"] is False and told["errors"] >= 1
            assert [item["severity"] for item in told["findings"] if item["id"] == check_id][0] == "error"
        else:
            assert fired[0]["message"] in out.splitlines() and f"  fix: {fired[0]['fix']}" in out.splitlines()
            assert "doctor: OK" not in out
    monkeypatch.setattr(cli, "do_setup", lambda data, rerender, seat: None)
    monkeypatch.setattr(cli, "gateway_up", lambda: None)
    monkeypatch.setattr("cockpitlib.vault.init_vault", lambda: "sealed")
    assert cli.main(["setup"]) == 1 and fired[0]["message"] in capsys.readouterr().err.splitlines()


# ---------- production: the pack says what it is, or that there is none ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_that_declares_no_production_turns_the_empty_list_into_a_note_and_nothing_else(
    env, pack_file, monkeypatch, capsys
):
    pack = _set_up(pack_file, monkeypatch)
    pack["egress"] = {**pack["egress"], "production_hosts": [], "host_probes": {}, "no_production_hosts": True}
    found = doctor.findings(pack)
    assert "egress.production-hosts-empty" not in [item["id"] for item in found] and "egress.no-production" in _ids(
        found, "info"
    )
    assert doctor.run(pack) == []
    monkeypatch.setattr(cli, "_pack", lambda: pack)
    assert cli.main(["doctor"]) == 0
    assert (
        "note: egress no_production_hosts: the pack declares that this project has no production"
        in capsys.readouterr().out.splitlines()
    )
    pack["egress"]["no_production_hosts"] = False
    assert "egress.production-hosts-empty" in _ids(doctor.findings(pack), "error")
    pack["egress"]["no_production_hosts"] = "yes"  # only the pack's own true counts: a text that reads as yes does not
    assert "egress.production-hosts-empty" in _ids(doctor.findings(pack), "error")


def test_no_production_is_true_or_false_and_cannot_stand_beside_a_host_list():
    _egress({"no_production_hosts": True})
    _egress({"no_production_hosts": False, "production_hosts": [r"app\.example\.test"]})
    with pytest.raises(PackError, match="no_production_hosts is true or false"):
        _egress({"no_production_hosts": "yes"})
    with pytest.raises(PackError, match="keep one"):
        _egress({"no_production_hosts": True, "production_hosts": [r"app\.example\.test"]})


# ---------- warnings ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_warning_is_printed_with_its_fix_and_fails_only_under_strict(env, pack_file, monkeypatch, capsys):
    pack = _set_up(pack_file, monkeypatch)
    pack["repos"] = {"repos": [{**repo, "gates": []} for repo in pack["repos"]["repos"]]}
    monkeypatch.setattr(cli, "_pack", lambda: pack)
    found = doctor.findings(pack)
    assert _ids(found, "error") == [] and "repos.no-gates" in _ids(found, "warning")
    assert doctor.run(pack) == ["no repo gates"], (
        "a line that failed doctor before the tiers still fails migrate verify"
    )
    count = len(_ids(found, "warning"))
    assert cli.main(["doctor"]) == 0
    lines = capsys.readouterr().out.splitlines()
    fix = f"  fix: give one repo its test command under gates in {pack['_dir']}/repos.yaml"
    assert lines[lines.index("warning: no repo gates") + 1] == fix
    assert lines[-1] == f"doctor: OK ({count} warning{'s' if count > 1 else ''})"
    assert cli.main(["doctor", "--strict"]) == 1 and "doctor: OK" not in capsys.readouterr().out
    assert cli.main(["doctor", "--json"]) == 0
    told = json.loads(capsys.readouterr().out)
    assert sorted(told) == ["errors", "findings", "hermes", "ok", "pack", "warnings"]
    assert (told["ok"], told["errors"], told["warnings"], told["pack"], told["hermes"]) == (
        True,
        0,
        count,
        pack["name"],
        "0.22.2",
    )
    assert cli.main(["doctor", "--json", "--strict"]) == 1 and json.loads(capsys.readouterr().out)["ok"] is False
    monkeypatch.setattr(cli, "do_setup", lambda data, rerender, seat: None)
    monkeypatch.setattr(cli, "gateway_up", lambda: None)
    monkeypatch.setattr("cockpitlib.vault.init_vault", lambda: "sealed")
    assert cli.main(["setup"]) == 0
    printed = capsys.readouterr()
    assert "setup ok" in printed.out and printed.err.splitlines()[:2] == ["warning: no repo gates", fix]


def test_doctor_takes_three_flags_and_no_word(env, capsys):
    assert cli.main(["doctor", "extra"]) == 2 and "stray argument" in capsys.readouterr().err
    assert cli.main(["doctor", "--quiet"]) == 2 and "unknown option --quiet" in capsys.readouterr().err


WARNINGS = {
    "MEMORY.md not writable": "seat.memory-full",
    "ran its last two sessions on provider b, configured a": "provider.drift",
    "provider dependencies not checked: hermes not found": "provider.dependencies-unchecked",
}


@pytest.mark.parametrize("pack_file", PACKS)
def test_what_does_not_guard_a_boundary_and_does_not_stop_work_is_a_warning(env, pack_file, monkeypatch, tmp_path):
    pack = _set_up(pack_file, monkeypatch)
    lane = seats_from(pack)["intake"][0]
    os.makedirs(os.path.join(profile_dir(lane), "memories"), exist_ok=True)
    open(os.path.join(profile_dir(lane), "memories", "MEMORY.md"), "w", encoding="utf-8").write(
        "a note the lane can no longer add to. " * 40
    )
    monkeypatch.setattr(
        doctor,
        "provider_problems",
        lambda pack: [
            f"{lane} ran its last two sessions on provider b, configured a: x",
            "provider dependencies not checked: hermes not found",
            "Hermes's environment lacks PyYAML, a provider plugin's dependency",
        ],
    )
    monkeypatch.setattr(
        doctor,
        "cron_plan",
        lambda jobs, pack: [
            {"op": "remove", "name": "standup"},
            {"op": "update", "name": "bumps"},
            {"op": "create", "name": "export"},
        ],
    )
    monkeypatch.setattr("cockpitlib.setup.desktop_copy_stale", lambda: "Desktop runs a stale copy of the plugin UI")
    monkeypatch.setattr("cockpitlib.helpers.problems", lambda pack: ["helper web: /opt/web is not an executable file"])
    monkeypatch.setattr(
        "cockpitlib.vault.public_fingerprints", lambda: ["F" * 40]
    )  # a public key, and nothing sealed or stored yet
    pack["_plugins_unchecked"] = ["absent-plugin"]
    pack["_dir"] = str(tmp_path)
    found = doctor.findings(pack)
    assert set(_ids(found, "warning")) >= {
        "seat.memory-full",
        "provider.drift",
        "provider.dependencies-unchecked",
        "staging.missing",
        "helper.program-missing",
        "plugin.block-unchecked",
        "vault.key-unsealed-empty",
        "cron.turned-off",
        "cron.schedule-differs",
        "desktop.stale-copy",
    }
    assert {"provider.dependency-missing", "cron.not-registered"} <= set(_ids(found, "error"))
    assert "vault.key-unsealed" not in [item["id"] for item in found]
    drift = next(item for item in found if item["id"] == "provider.drift")
    assert drift["subject"] == lane and f"--profile {lane} " in drift["fix"]
    assert all(item["fix"] for item in found if item["severity"] != "info")
    assert "vault key not sealed" in doctor.run(pack) and "staging.yaml missing" in doctor.run(pack)


@pytest.mark.parametrize(
    "text, empty",
    [
        ("origins: {}\n", True),
        ("origins:\n  app: ''\n  api: ' '\n", True),
        ("origins:\n  app:\n", True),
        ("origins:\n  app: ''\n  api: https://api.example.test\n", False),
    ],
)
def test_staging_origins_that_are_all_empty_texts_count_as_none(env, monkeypatch, tmp_path, text, empty):
    pack = _set_up(PACKS[0], monkeypatch)
    pack["_dir"] = str(tmp_path)
    (tmp_path / "staging.yaml").write_text(text, encoding="utf-8")
    assert ("staging.origins-empty" in _ids(doctor.findings(pack), "warning")) is empty
    assert ("staging origins empty" in doctor.run(pack)) is empty


# ---------- the checks born with the tiers ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_coding_tool_that_is_not_there_is_a_warning_and_fails_nothing_that_passed_before(
    env, pack_file, monkeypatch, tmp_path
):
    pack = _set_up(pack_file, monkeypatch)
    assert doctor._coding_problems(pack) == []
    pack["providers"] = {**pack["providers"], "coding": {"command": ["no-such-coding-tool", "--print"]}}
    found = [item for item in doctor.findings(pack) if item["id"] == "coding.command-missing"]
    assert [item["message"] for item in found] == [
        "providers.coding.command: no-such-coding-tool is not on PATH"
    ] and found[0]["severity"] == "warning"
    assert found[0]["message"] not in doctor.run(
        pack
    )  # born with the tiers: an installation that was green stays green
    pack["providers"]["coding"] = {"command": [str(tmp_path / "tool")]}
    assert doctor._coding_problems(pack) == [f"providers.coding.command: {tmp_path / 'tool'} is not an executable file"]
    (tmp_path / "tool").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "tool").chmod(0o755)
    assert (
        doctor._coding_problems(pack) == []
        and doctor._coding_problems({"providers": {"coding": {"command": []}}}) == []
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_checks_born_with_the_tiers_warn_and_are_not_in_the_lines_that_always_failed(
    env, pack_file, monkeypatch, tmp_path
):
    pack = _set_up(pack_file, monkeypatch)
    import shutil

    real = shutil.which
    absent = ("ffmpeg", "ffprobe", "gh", "python3")
    monkeypatch.setattr(
        shutil, "which", lambda name, *more, **how: None if name in absent else real(name, *more, **how)
    )
    monkeypatch.setattr("cockpitlib.paths.PLUGIN_ROOT", str(tmp_path / "plugin-without-a-venv"))
    pack["notify"] = {**(pack.get("notify") or {}), "ci_grene": ["true"], "ready": ["true"], "ci_failed": ["true"]}
    pack["tracker"] = {
        **pack["tracker"],
        "kind": "jira",
        "auth_env": ["EXAMPLE_TRACKER_EMAIL", "EXAMPLE_TRACKER_TOKEN"],
    }
    monkeypatch.setenv("EXAMPLE_TRACKER_EMAIL", "human@example.test")
    pack["repos"] = {
        "repos": [*pack["repos"]["repos"], {"name": "gone", "path": "repos/gone", "gates": []}, {"name": "pathless"}]
    }
    found = doctor.findings(pack)
    born = [(item["id"], item["subject"], item["message"]) for item in found if doctor.CHECKS[item["id"]]["born"]]
    gone = os.path.join(os.environ["COCKPIT_ROOT"], "repos", "gone")
    assert born == [
        ("tools.video", "ffmpeg", "ffmpeg not found: a failure video cannot be encoded or checked"),
        ("tools.video", "ffprobe", "ffprobe not found: a failure video cannot be encoded or checked"),
        ("forge.cli-missing", "gh", "gh is not on PATH"),
        (
            "notify.unknown-event",
            "ci_grene",
            "notify.ci_grene: no kernel code sends an event of that name, so its command never runs",
        ),
        (
            "notify.unknown-event",
            "ready",
            "notify.ready: no kernel code sends an event of that name, so its command never runs",
        ),
        (
            "tracker.auth-env-unset",
            "EXAMPLE_TRACKER_TOKEN",
            "tracker.auth_env: EXAMPLE_TRACKER_TOKEN is not set in this environment",
        ),
        ("repos.path-missing", "gone", f"repo gone: missing {gone}"),
        ("python.yaml-missing", "", "python3 is not on PATH and the plugin has no .venv"),
    ]
    assert all(item["severity"] == "warning" and item["fix"] for item in found if doctor.CHECKS[item["id"]]["born"])
    unknown = next(item for item in found if item["id"] == "notify.unknown-event")
    assert "standup, advisory, ready_for_review" in unknown["fix"] and "ci_<state>" in unknown["fix"]
    assert [
        line
        for line in doctor.run(pack)
        if "not found" in line or "notify." in line or "auth_env" in line or "gone" in line
    ] == []


def test_a_tracker_that_is_not_rest_and_an_absolute_repo_are_not_asked_about(env, monkeypatch, tmp_path):
    assert doctor._tracker_env_problems({"tracker": {"kind": "command", "auth_env": ["A", "B"]}}) == []
    assert doctor._tracker_env_problems({}) == [] and doctor._tracker_env_problems(
        {"tracker": {"kind": "jira", "auth_env": ["A_UNSET_NAME"]}}
    ) == ["A_UNSET_NAME"]
    assert doctor._repo_path_problems(
        {"repos": {"repos": [{"name": "here", "path": str(tmp_path)}, {"name": "x", "path": str(tmp_path / "x")}]}}
    ) == [("x", str(tmp_path / "x"))]


def test_the_bare_python_is_asked_for_yaml_only_when_the_plugin_has_no_venv(monkeypatch, tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / ".venv" / "bin").mkdir(parents=True)
    monkeypatch.setattr("cockpitlib.paths.PLUGIN_ROOT", str(plugin))
    tools = tmp_path / "bin"
    tools.mkdir()
    monkeypatch.setenv("PATH", str(tools))
    assert doctor._python_problems() == ["python3 is not on PATH and the plugin has no .venv"]
    python = tools / "python3"
    python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    python.chmod(0o755)
    assert doctor._python_problems() == [f"{python} lacks PyYAML and the plugin has no .venv"]
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    assert doctor._python_problems() == []
    python.write_text("#!/bin/sh\n/bin/sleep 5\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "YAML_TIMEOUT", 0.2)
    assert doctor._python_problems() == [f"{python} could not be asked for PyYAML and the plugin has no .venv"]
    (plugin / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    assert doctor._python_problems() == []


def test_the_forge_sign_in_is_asked_only_online_and_within_a_time_box(monkeypatch, tmp_path):
    tools = tmp_path / "bin"
    tools.mkdir()
    monkeypatch.setenv("PATH", str(tools))
    assert doctor._forge_problems(True) == [("forge.cli-missing", "gh is not on PATH")]
    program = tools / "gh"
    program.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/asked\nexit 1\n', encoding="utf-8")
    program.chmod(0o755)
    assert doctor._forge_problems(False) == [] and not (tmp_path / "asked").exists(), "offline, the forge is not asked"
    assert doctor._forge_problems(True) == [("forge.cli-login", "gh is not signed in to the forge")]
    assert (tmp_path / "asked").read_text(encoding="utf-8") == "auth status\n"
    program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    assert doctor._forge_problems(True) == []
    program.write_text("#!/bin/sh\n/bin/sleep 5\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "LOGIN_TIMEOUT", 0.2)
    assert doctor._forge_problems(True) == [("forge.cli-login", "gh auth status did not answer within 0.2 s")]
    program.write_text("#!/no/such/interpreter\n", encoding="utf-8")
    assert doctor._forge_problems(True)[0][1].startswith("gh auth status could not run: ")


def test_the_video_tools_are_found_the_way_the_recorder_finds_them(env, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert doctor._video_problems() == ["ffmpeg", "ffprobe"]
    bundled = env["home"] / "tools" / "ffmpeg-7" / "bin"
    bundled.mkdir(parents=True)
    for name in ("ffmpeg", "ffprobe"):
        (bundled / name).write_text("", encoding="utf-8")
    assert doctor._video_problems() == []


# ---------- the events the kernel sends ----------


def test_the_event_list_is_exactly_what_kernel_code_sends():
    sent, states = set(), set()
    folder = os.path.join(ROOT, "kernel", "cockpitlib")
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".py") or name == "notify.py":
            continue
        text = open(os.path.join(folder, name), encoding="utf-8").read()
        if "from .notify import" not in text:
            continue
        # a call the formatter wrapped opens its bracket on one line and names the event on the next
        sent.update(re.findall(r"""\bnotify\(\s*pack,\s*"([a-z_]+)\"""", text))
        sent.update(re.findall(r"""\bcommand\(\s*pack,\s*"([a-z_]+)",?\s*\)""", text))
        if 'notify(pack, f"ci_{what}"' in text:
            states.update(re.findall(r"""_announce\(\s*pack,\s*ticket,\s*sha,\s*"([a-z_]+)",?\s*\)""", text))
    assert sent == set(notify.EVENTS) and len(notify.EVENTS) == len(set(notify.EVENTS))
    assert states == set(notify.CI_STATES)
    assert (
        notify.known_event("ci_green")
        and notify.known_event("standup")
        and not notify.known_event("ci_grene")
        and not notify.known_event("ci_")
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_every_event_a_fixture_pack_names_is_one_the_kernel_sends(pack_file):
    raw = yaml.safe_load(open(pack_file, encoding="utf-8"))
    assert [event for event in raw.get("notify") or {} if not notify.known_event(event)] == []


# ---------- a line that changes its words never drops a tier ----------


def test_a_line_the_sorter_does_not_know_stays_in_the_hardest_tier_of_its_group():
    assert doctor._host_check("a new line about hosts") == "egress.production-host-blocked"
    assert doctor._env_file_check("env file /x is something new") == ("env-file.in-git", "env file /x is something new")
    assert doctor._env_file_check("env file /x/seat.env is inside a git tree") == ("env-file.in-git", "/x/seat.env")
    assert doctor._provider_check("a new line about providers") == "provider.dependency-missing"
    assert all(
        doctor.CHECKS[check_id]["severity"] == "error"
        for check_id in ("egress.production-host-blocked", "env-file.in-git", "provider.dependency-missing")
    )


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_old_hermes_is_an_error_and_an_accepted_newer_one_is_a_note(env, pack_file, monkeypatch):
    pack = _set_up(pack_file, monkeypatch)
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "0.21.9")
    old = [item for item in doctor.findings(pack) if item["id"].startswith("hermes.")]
    assert [(item["id"], item["severity"], item["security"]) for item in old] == [("hermes.version", "error", False)]
    assert old[0]["fix"] == "install Hermes 0.22 or 0.23 and put `hermes` on PATH"
    monkeypatch.setenv("COCKPIT_STUB_VERSION", "0.24.0")
    monkeypatch.setattr(hermes_runtime, "_published", {})
    newer = [item for item in doctor.findings(pack) if item["id"].startswith("hermes.")]
    assert [(item["id"], item["severity"]) for item in newer] == [("hermes.note", "info")] and newer[0][
        "message"
    ] == doctor.notes(pack)[0]
    assert doctor.report(pack)["hermes"] == "0.24.0" and doctor.run(pack) == []
