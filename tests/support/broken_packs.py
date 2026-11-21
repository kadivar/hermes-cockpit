# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deliberately broken packs, each a fixture pack with one or more values spoiled: the corpus the pack loader's first
error is held against. A mutation is (name, {file: change(data)}); make() writes the spoiled copy and returns its
pack.yaml."""

import os
import shutil

import yaml


def _set(path, value):
    """A change that writes a value at a dotted path of a file's data (a missing block is made)."""

    def change(data):
        node = data
        parts = path.split(".")
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    return change


def _drop(key):
    return lambda data: data.pop(key, None)


def _all(*changes):
    def change(data):
        for one in changes:
            one(data)

    return change


P, R, S, E = "pack.yaml", "repos.yaml", "skills.yaml", "egress.yaml"
ONE = [
    ("no-name", {P: _drop("name")}),
    ("no-board", {P: _drop("board")}),
    ("no-seats", {P: _drop("seats")}),
    ("unknown-key", {P: _set("shiny_new_thing", 1)}),
    ("removed-key", {P: _set("worker_branch_prefixes", ["x"])}),
    ("ticket-pattern", {P: _set("ticket_pattern", "(")}),
    ("protected-branches", {P: _set("protected_branches", "release")}),
    ("skills-dir", {P: _set("skills_dir", [])}),
    ("grooming", {P: _set("grooming", "push")}),
    ("bump-sequence", {P: _set("bump_sequence", {"stages": "push"})}),
    ("advisories", {P: _set("advisories", "osv")}),
    ("hours", {P: _set("hours.standup", "25:99")}),
    ("runtime", {P: _set("runtime", "container")}),
    ("records-dir", {P: _set("records_dir", "/srv/records")}),
    ("mcp-servers", {P: _set("mcp_servers", {"docs": {}})}),
    ("seat-config", {P: _set("seat_config", "souls")}),
    ("extra-plugins", {P: _set("extra_plugins", "view")}),
    ("board-workdir", {P: _set("board_workdir", "relative/folder")}),
    ("testflow-run-dir", {P: _set("testflow.run_dir", "run")}),
    ("testflow-key", {P: _set("testflow.not_a_key", 1)}),
    ("lanes", {P: _set("lanes.by_slot", "yes")}),
    ("asks", {P: _set("asks", "deploy")}),
    ("slots-provider", {P: _set("slots.provider", "cloud")}),
    ("providers", {P: _set("providers", {})}),
    ("ide", {P: _set("ide.command", [])}),
    ("desktop-override", {P: _set("desktop.overrides", ["no-such-fix"])}),
    ("standup-enabled", {P: _set("standup_enabled", "yes")}),
    ("board-done-days", {P: _set("board_done_days", 99)}),
    ("worktree-gc", {P: _set("worktree_gc", "weekly")}),
    ("seats-range", {P: _set("seats.slots", 99)}),
    ("plugins", {P: _set("plugins", "ledger")}),
    ("tracker-kind", {P: _set("tracker.kind", "carrier-pigeon")}),
    ("demo-login-origins", {P: _set("demo_login_origins", "app")}),
    ("forge", {P: _set("forge", "example-org")}),
    ("outbox", {P: _set("outbox", "auto")}),
    ("watchers", {P: _set("watchers", "all")}),
    ("perf", {P: _set("perf", "sync")}),
    ("awake", {P: _set("awake", {})}),
    ("environments", {P: _set("environments", "local")}),
    ("prompts", {P: _set("prompts", "plan.md")}),
    ("advisor", {P: _set("advisor", "ask")}),
    ("working-days", {P: _set("working_days", [9])}),
    ("refused", {P: _set("refused", "hosts")}),
    ("roles", {P: _set("roles.worker", "no-such-provider")}),
    ("kickoff", {P: _set("kickoff", "test")}),
    ("capacity", {P: _set("capacity.not_a_key", 1)}),
    ("export", {P: _set("export", "weekly")}),
    ("repos-shape", {R: _set("repos", "api")}),
    ("repos-gates", {R: lambda data: data["repos"][0].update(gates="make test")}),
    ("skills-kickoff", {S: _drop("kickoff")}),
    ("skills-intent", {S: _set("intent", "outbox")}),
    ("egress-shape", {E: _set("terminal_deny", "rm")}),
    ("egress-regex", {E: _set("production_hosts", ["("])}),
]
SEVERAL = [
    ("two-late-and-early", {P: _all(_set("advisor", "ask"), _set("ticket_pattern", "("))}),
    (
        "three-across-the-load",
        {P: _all(_set("perf", "sync"), _set("testflow.run_dir", "run"), _set("grooming", "push"))},
    ),
    ("unknown-and-shape", {P: _all(_set("shiny_new_thing", 1), _set("seats.slots", 99))}),
    ("pack-and-repos", {P: _set("watchers", "all"), R: _set("repos", "api")}),
    ("companions-and-policy", {S: _drop("kickoff"), P: _set("working_days", [9])}),
    ("desktop-and-forge", {P: _all(_set("forge", "example-org"), _set("desktop.overrides", ["no-such-fix"]))}),
]
MUTATIONS = ONE + SEVERAL
WHOLE = [("not-a-mapping", "- a list\n"), ("empty", "")]  # pack.yaml replaced by a text


def make(pack_file, tmp_path, name) -> str:
    """The fixture pack spoiled by the mutation of that name, in a folder of the caller's own."""
    folder = os.path.join(str(tmp_path), name, "packs", os.path.basename(os.path.dirname(pack_file)))
    shutil.copytree(os.path.dirname(pack_file), folder)
    whole = dict(WHOLE)
    if name in whole:
        open(os.path.join(folder, P), "w", encoding="utf-8").write(whole[name])
        return os.path.join(folder, P)
    for file, change in dict(MUTATIONS)[name].items():
        path = os.path.join(folder, file)
        data = yaml.safe_load(open(path, encoding="utf-8"))
        change(data)
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    return os.path.join(folder, P)


def names() -> list:
    return [name for name, _ in MUTATIONS] + [name for name, _ in WHOLE]
