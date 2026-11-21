# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Moving an install that ran another pipeline onto cockpit. The engine is generic: every legacy name, path, cron,
plugin, hook and record layout comes from the pack's migrate.yaml, and the adopter's own exporters hand over what
only they can read (logins as neutral JSON lines on a pipe).

plan     what would change, with counts; exporters run in count-only mode, no secret is read
apply    gateway stopped and board drained; a snapshot first; then each action, journaled, idempotent
verify   the cutover gate: every line with its evidence
rollback the snapshot back, record moves reversed
"""

import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess

import yaml

from . import pack_local
from .errors import CockpitError, PackError
from .paths import hermes_home, workspace

SPEC_KEYS = {"legacy", "records", "board", "slots", "exporters"}
LEGACY_KEYS = {"profiles", "plugins", "crons", "shell_hooks", "root", "editor_hooks"}
RECORD_KINDS = ("dir", "file", "intents")


# --- the spec ---------------------------------------------------------------------------------------------------


def spec_path(pack) -> str:
    return os.path.join(pack["_dir"], "migrate.yaml")


def load_spec(pack) -> dict:
    """migrate.yaml beside the pack, checked. A pack without one has nothing to migrate."""
    path = spec_path(pack)
    if not os.path.isfile(path):
        return {}
    raw = pack_local.read(path, fill_home=False) or {}  # {home} is the runtime's home here (_command)
    if not isinstance(raw, dict) or set(raw) - SPEC_KEYS:
        raise PackError(f"migrate.yaml takes {', '.join(sorted(SPEC_KEYS))}")
    legacy = raw.get("legacy") or {}
    if not isinstance(legacy, dict) or set(legacy) - LEGACY_KEYS:
        raise PackError(f"migrate.yaml legacy takes {', '.join(sorted(LEGACY_KEYS))}")
    for group, fields in (
        ("profiles", ("replace", "remove")),
        ("plugins", ("disable", "keep")),
        ("crons", ("retire", "replace")),
    ):
        block = legacy.get(group) or {}
        if (
            not isinstance(block, dict)
            or set(block) - set(fields)
            or not all(_names(block.get(field)) for field in fields)
        ):
            raise PackError(f"migrate.yaml legacy.{group} takes {' and '.join(fields)}, each a list of names")
    keep = (legacy.get("plugins") or {}).get("keep") or []
    extra = {plugin.get("name") for plugin in pack.get("extra_plugins") or [] if isinstance(plugin, dict)}
    if set(keep) - extra:
        raise PackError(
            f"migrate.yaml keeps plugin {sorted(set(keep) - extra)[0]}, which extra_plugins does not attach"
        )
    for hook in legacy.get("shell_hooks") or []:
        if not isinstance(hook, dict) or set(hook) != {"event", "command"}:
            raise PackError("migrate.yaml legacy.shell_hooks lists {event, command}")
    root = legacy.get("root") or {}
    if not isinstance(root, dict) or set(root) - {"soul_blocks", "env_drop", "config_drop"}:
        raise PackError("migrate.yaml legacy.root takes soul_blocks, env_drop and config_drop")
    for block in root.get("soul_blocks") or []:
        if not isinstance(block, dict) or set(block) != {"start", "end"}:
            raise PackError("migrate.yaml legacy.root.soul_blocks lists {start, end}")
    records = raw.get("records") or {}
    from .pr_watch import ID_KINDS

    prefixes = records.get("watch_id_prefixes")
    if prefixes is not None and (
        not isinstance(prefixes, dict)
        or not all(isinstance(old, str) and old.isalpha() and ours in ID_KINDS for old, ours in prefixes.items())
    ):
        raise PackError(
            f"migrate.yaml records.watch_id_prefixes maps a prefix of letters to one of {', '.join(ID_KINDS)}"
        )
    for row in records.get("map") or []:
        if not isinstance(row, dict) or set(row) - {"from", "to", "kind"} or row.get("kind", "dir") not in RECORD_KINDS:
            raise PackError(f"migrate.yaml records.map lists {{from, to, kind: {'|'.join(RECORD_KINDS)}}}")
        for side in ("from", "to"):
            if (
                not isinstance(row.get(side), str)
                or not row[side]
                or os.path.isabs(row[side])
                or ".." in row[side].split("/")
            ):
                raise PackError("migrate.yaml records.map paths are relative to the workspace and stay inside it")
    for group, keys in (("flows", {"pattern", "flow"}), ("rewrite", {"pattern", "replace"})):
        for row in (raw.get("board") or {}).get(group) or []:
            if not isinstance(row, dict) or set(row) != keys:
                raise PackError(f"migrate.yaml board.{group} lists {{{', '.join(sorted(keys))}}}")
            try:
                re.compile(row["pattern"])
            except re.error as exc:
                raise PackError(f"migrate.yaml board.{group} {row['pattern']}: {exc}") from exc
    for row in (raw.get("slots") or {}).get("bindings") or []:
        if (
            not isinstance(row, dict)
            or set(row) != {"from", "to", "format"}
            or row["to"] not in ("ticket", "owner")
            or "{n}" not in row["from"]
        ):
            raise PackError("migrate.yaml slots.bindings lists {from (with {n}), to: ticket|owner, format}")
    exporters = raw.get("exporters") or {}
    vault = exporters.get("vault")
    if vault is not None and (
        not isinstance(vault, dict)
        or set(vault) != {"argv", "count_argv"}
        or not _argv(vault["argv"])
        or not _argv(vault["count_argv"])
    ):
        raise PackError("migrate.yaml exporters.vault is {argv, count_argv}")
    for row in exporters.get("extra") or []:
        if not isinstance(row, dict) or set(row) != {"name", "argv"} or not _argv(row["argv"]):
            raise PackError("migrate.yaml exporters.extra lists {name, argv}")
    return raw


def _names(value) -> bool:
    return value is None or (isinstance(value, list) and all(isinstance(item, str) and item for item in value))


def _argv(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(word, str) and word for word in value)


def _command(pack, argv) -> list:
    words = [str(word).replace("{workspace}", workspace()).replace("{home}", hermes_home()) for word in argv]
    if "/" in words[0] and not os.path.isabs(words[0]):
        words[0] = os.path.join(pack["_dir"], words[0])
    return words


# --- what is there ----------------------------------------------------------------------------------------------


def _config(home: str) -> dict:
    path = os.path.join(home, "config.yaml")
    try:
        data = yaml.safe_load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
    except yaml.YAMLError:
        data = {}
    return data if isinstance(data, dict) else {}


def _jobs(home: str) -> list:
    from .setup import _cron_jobs

    return [job for job in _cron_jobs(home) if isinstance(job, dict)]


def _hook_commands(config: dict, event: str) -> list:
    entries = ((config.get("hooks") or {}).get(event)) or []
    return [str(entry.get("command") if isinstance(entry, dict) else entry) for entry in entries if entry]


def _soul_text() -> str:
    path = os.path.join(hermes_home(), "SOUL.md")
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""


def _env_keys(path: str) -> list:
    if not os.path.isfile(path):
        return []
    return [
        line.split("=", 1)[0].strip()
        for line in open(path, encoding="utf-8")
        if "=" in line and not line.lstrip().startswith("#")
    ]


def _dotted(config: dict, dotted: str):
    node = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _open_cards(pack) -> list:
    from .kanban import OPEN_STATUSES, board_cards

    return [card for card in board_cards(pack["board"]) if card.get("status") in OPEN_STATUSES]


def scan(pack, spec=None) -> dict:
    """Read-only: every legacy thing the spec names that is still present."""
    spec = load_spec(pack) if spec is None else spec
    legacy = spec.get("legacy") or {}
    home = hermes_home()
    config = _config(home)
    profiles = os.path.join(home, "profiles")
    present = set(os.listdir(profiles)) if os.path.isdir(profiles) else set()
    enabled = set(((config.get("plugins") or {}).get("enabled")) or [])
    crons = legacy.get("crons") or {}
    retire, replace = set(crons.get("retire") or []), set(crons.get("replace") or [])
    soul = _soul_text()
    root = legacy.get("root") or {}
    env_keys = set(_env_keys(os.path.join(home, ".env")))
    rewrites = (spec.get("board") or {}).get("rewrite") or []
    return {
        "profiles_remove": sorted(present & set((legacy.get("profiles") or {}).get("remove") or [])),
        "profiles_replace": sorted(present & set((legacy.get("profiles") or {}).get("replace") or [])),
        "plugins": sorted(enabled & set((legacy.get("plugins") or {}).get("disable") or [])),
        "crons": sorted(
            {
                str(job.get("name"))
                for job in _jobs(home)
                if job.get("name") in retire or (job.get("name") in replace and not _cockpits_job(job))
            }
        ),
        "shell_hooks": [
            hook for hook in legacy.get("shell_hooks") or [] if hook["command"] in _hook_commands(config, hook["event"])
        ],
        "soul_blocks": [block for block in root.get("soul_blocks") or [] if block["start"] in soul],
        "env": sorted(env_keys & set(root.get("env_drop") or [])),
        "config": [key for key in root.get("config_drop") or [] if _dotted(config, key) is not None],
        "editor_hooks": [
            path for path in legacy.get("editor_hooks") or [] if os.path.exists(os.path.join(workspace(), path))
        ],
        "records": [
            row
            for row in (spec.get("records") or {}).get("map") or []
            if os.path.exists(os.path.join(workspace(), row["from"]))
        ],
        "cards": [
            card["id"]
            for card in _open_cards(pack)
            if any(re.search(row["pattern"], card.get("body") or "") for row in rewrites)
        ],
        "bindings": [row for row in (spec.get("slots") or {}).get("bindings") or [] if _binding_files(row)],
    }


def _cockpits_job(job) -> bool:
    """A job cockpit registered under that name: its own script for it (a replaced legacy job shares only the name)."""
    from .setup import CRON_JOBS

    scripts = {name: script for name, _default, script in CRON_JOBS}
    return job.get("name") in scripts and str(job.get("script") or "") == scripts[job["name"]]


def _binding_files(row) -> list:
    found = []
    for number in range(1, 9):
        path = os.path.join(workspace(), row["from"].replace("{n}", str(number)))
        if os.path.isfile(path):
            found.append((number, path))
    return found


def _count(pack, spec) -> int:
    vault = (spec.get("exporters") or {}).get("vault")
    if not vault:
        return 0
    done = subprocess.run(_command(pack, vault["count_argv"]), capture_output=True, text=True, timeout=300, check=False)
    if done.returncode != 0:
        raise CockpitError(f"vault exporter count failed: {(done.stderr or done.stdout).strip()[-200:]}")
    try:
        return int(done.stdout.strip() or 0)
    except ValueError as exc:
        raise CockpitError("vault exporter count answered no number") from exc


def plan(pack) -> dict:
    """What apply would do. The exporters only count."""
    spec = load_spec(pack)
    found = scan(pack, spec)
    actions = {key: len(value) for key, value in found.items()}
    actions["vault_logins"] = _count(pack, spec)
    return {"actions": actions, "found": found, "ready": _blockers(pack) or []}


# --- apply ------------------------------------------------------------------------------------------------------


def _gateway_running() -> bool:
    """Hermes's gateway serves this home: its gateway.pid here names a live process. (cockpit's own gateway.state is
    the human's on/off switch for cockpit, not the process.)"""
    path = os.path.join(hermes_home(), "gateway.pid")
    try:
        record = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pid = record.get("pid") if isinstance(record, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _blockers(pack) -> list:
    blockers = []
    if _gateway_running():
        blockers.append("the Hermes gateway is running: stop it first")
    running = [card["id"] for card in _open_cards(pack) if card.get("status") == "running"]
    if running:
        blockers.append(f"{len(running)} card(s) still running ({running[0]}): let them finish or halt them")
    return blockers


def _stamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")


def snapshots_dir() -> str:
    return os.path.join(hermes_home(), "backups", "migrate")


def _snapshot(pack, spec, stamp: str) -> str:
    """config, SOUL, .env, cron jobs, binding, profiles (without Hermes's own checkout) and the board (through SQLite's
    backup API, so a live write-ahead log is consistent)."""
    from .kanban import db_path

    home = hermes_home()
    folder = os.path.join(snapshots_dir(), stamp)
    os.makedirs(folder)
    for name in ("config.yaml", "SOUL.md", ".env", "cockpit.yaml", os.path.join("cron", "jobs.json")):
        source = os.path.join(home, name)
        if os.path.isfile(source):
            os.makedirs(os.path.dirname(os.path.join(folder, name)), exist_ok=True)
            shutil.copy2(source, os.path.join(folder, name))
    profiles = os.path.join(home, "profiles")
    if os.path.isdir(profiles):
        shutil.copytree(
            profiles,
            os.path.join(folder, "profiles"),
            symlinks=True,
            ignore=shutil.ignore_patterns("hermes-agent", "*.db-wal", "*.db-shm"),
        )
    board = db_path(pack["board"])
    if os.path.isfile(board):
        target = os.path.join(folder, "board.db")
        source, copy = sqlite3.connect(board), sqlite3.connect(target)
        with copy:
            source.backup(copy)
        source.close()
        copy.close()
    for path in (spec.get("legacy") or {}).get("editor_hooks") or []:
        full = os.path.join(workspace(), path)
        if os.path.isfile(full):
            os.makedirs(os.path.dirname(os.path.join(folder, "editor", path)), exist_ok=True)
            shutil.copy2(full, os.path.join(folder, "editor", path))
    return folder


class Journal:
    """One line per action; never an exporter's output."""

    def __init__(self, folder: str):
        self.path = os.path.join(folder, "journal.jsonl")
        self.rows = []

    def add(self, action: str, **fields) -> None:
        row = {"action": action, **fields}
        self.rows.append(row)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


def _write_config(home: str, config: dict) -> None:
    open(os.path.join(home, "config.yaml"), "w", encoding="utf-8").write(yaml.safe_dump(config, sort_keys=False))


def _same_repo(source: str, target: str) -> str:
    """The git top level both paths sit in, or empty."""

    def top(path):
        probe = path if os.path.isdir(path) else os.path.dirname(path)
        while probe and not os.path.isdir(probe):
            probe = os.path.dirname(probe)
        done = subprocess.run(
            ["git", "-C", probe, "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else ""

    first = top(source)
    return first if first and first == top(os.path.dirname(target)) else ""


def _tracked(repo: str, path: str) -> bool:
    done = subprocess.run(
        ["git", "-C", repo, "ls-files", "--error-unmatch", path], capture_output=True, text=True, check=False
    )
    return done.returncode == 0


def _move(source: str, target: str, journal: Journal) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    repo = _same_repo(source, target)
    if repo and _tracked(repo, source):
        subprocess.run(["git", "-C", repo, "mv", source, target], check=True, capture_output=True)
        journal.add("move", source=source, target=target, git=repo)
        return
    shutil.move(source, target)
    journal.add("move", source=source, target=target, git="")


LEGACY_FIELDS = {
    "risk_hint": "risk",
    "agent_summary": "summary",
}  # an earlier pipeline's names for fields the page reads


def _convert_intents(folder: str, journal: Journal) -> int:
    """Each intent keeps its known fields; anything cockpit does not know waits under `legacy`.
    Only an intent is converted: a file without an id and a type (a comment body kept beside its intent, a note) is left as it
    is. An earlier pipeline's field names are mapped onto cockpit's (LEGACY_FIELDS). An intent of a type cockpit lacks becomes
    an infra-note under its own file name, so the lister sees it: an open one is held for the human with the reason, a closed
    one (published, dropped) keeps its status, because history is not a decision."""
    from .intents import FIELDS, OPEN_STATUSES, SCHEMAS

    known_top = {
        "id",
        "ticket",
        "type",
        "status",
        "summary",
        "payload",
        "card_id",
        "created_by",
        "created_at",
        "endorsement",
        "hold",
        "returned",
        "human",
        "receipt",
        "history",
        "risk",
        "evidence",
        "review",
        "skills_deferred",
        "legacy",
    }
    converted = skipped = 0
    for dirpath, _dirs, names in os.walk(folder):
        for name in sorted(names):
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            try:
                data = json.load(open(path, encoding="utf-8"))
            except ValueError:
                continue
            if not isinstance(data, dict) or "legacy_converted" in data:
                continue
            if not isinstance(data.get("id"), str) or not isinstance(data.get("type"), str):
                skipped += 1
                continue
            for old, new in LEGACY_FIELDS.items():
                if old in data and new not in data:
                    data[new] = data.pop(old)
            extra = {key: data.pop(key) for key in list(data) if key not in known_top}
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            extra.update({f"payload.{key}": payload.pop(key) for key in list(payload) if key not in FIELDS})
            data["payload"] = payload
            if data.get("type") not in SCHEMAS:
                extra["type"] = data.get("type")
                extra["id"] = data["id"]
                data["type"] = "infra-note"
                data["id"] = re.sub(r"/(\d{3})-[^/]+$", r"/\1-infra-note", data["id"])
                if data.get("status") in OPEN_STATUSES or not data.get("status"):
                    data["status"] = "held"
                    data["hold"] = {
                        "reason": f"migrated: legacy type {extra['type']} has no cockpit type",
                        "waits": "human",
                    }
                renamed = os.path.join(dirpath, re.sub(r"^(\d{3})-.+\.json$", r"\1-infra-note.json", name))
                if renamed != path and not os.path.exists(renamed):
                    os.remove(path)
                    path = renamed
            if extra:
                data["legacy"] = {**(data.get("legacy") or {}), **extra}
            data["legacy_converted"] = True
            json.dump(data, open(path, "w", encoding="utf-8"), indent=1)
            converted += 1
    journal.add("intents", folder=folder, converted=converted, skipped=skipped)
    return converted


def _import_vault(pack, spec, journal: Journal) -> dict:
    """The exporter's JSON lines straight into the vault, deduplicated against what the seat stores hold."""
    vault = (spec.get("exporters") or {}).get("vault")
    if not vault:
        return {"imported": 0, "kept": 0}
    done = subprocess.run(_command(pack, vault["argv"]), capture_output=True, text=True, timeout=600, check=False)
    if done.returncode != 0:
        raise CockpitError("vault exporter failed (its output is not kept)")
    from .vault import import_logins

    result = import_logins(done.stdout, pack)
    journal.add("vault", imported=result["imported"], kept=result["kept"])
    return result


def apply(pack) -> dict:
    """Snapshot, then every action of the spec. Refused while the gateway runs or a card is running."""
    blockers = _blockers(pack)
    if blockers:
        raise CockpitError("; ".join(blockers))
    spec = load_spec(pack)
    if not spec:
        raise CockpitError(f"no {spec_path(pack)}: nothing to migrate")
    found = scan(pack, spec)
    stamp = _stamp()
    folder = _snapshot(pack, spec, stamp)
    journal = Journal(folder)
    home = hermes_home()
    config = _config(home)
    for name in found["profiles_remove"]:
        shutil.rmtree(os.path.join(home, "profiles", name))
        journal.add("profile-removed", name=name)
    enabled = ((config.get("plugins") or {}).get("enabled")) or []
    if found["plugins"]:
        config.setdefault("plugins", {})["enabled"] = [name for name in enabled if name not in found["plugins"]]
        journal.add("plugins-disabled", names=found["plugins"])
    for hook in found["shell_hooks"]:
        entries = config["hooks"][hook["event"]]
        config["hooks"][hook["event"]] = [
            entry
            for entry in entries
            if str(entry.get("command") if isinstance(entry, dict) else entry) != hook["command"]
        ]
        journal.add("hook-removed", event=hook["event"], command=hook["command"])
    for dotted in found["config"]:
        *parents, last = dotted.split(".")
        node = config
        for part in parents:
            node = node[part]
        node.pop(last, None)
        journal.add("config-dropped", key=dotted)
    if found["plugins"] or found["shell_hooks"] or found["config"]:
        _write_config(home, config)
    jobs_path = os.path.join(home, "cron", "jobs.json")
    if found["crons"]:
        data = json.load(open(jobs_path, encoding="utf-8"))
        jobs = data.get("jobs") if isinstance(data, dict) else data
        kept = [
            job
            for job in jobs
            if not (isinstance(job, dict) and job.get("name") in found["crons"] and not _cockpits_job(job))
        ]
        json.dump({"jobs": kept} if isinstance(data, dict) else kept, open(jobs_path, "w", encoding="utf-8"), indent=2)
        journal.add("crons-removed", names=found["crons"])
    if found["soul_blocks"]:
        text = _soul_text()
        for block in found["soul_blocks"]:
            start = text.index(block["start"])
            end = text.find(block["end"], start)
            end = len(text) if end < 0 else end + len(block["end"])
            text = (text[:start].rstrip("\n") + "\n" + text[end:].lstrip("\n")).lstrip("\n")
        open(os.path.join(home, "SOUL.md"), "w", encoding="utf-8").write(text)
        journal.add("soul-blocks-removed", count=len(found["soul_blocks"]))
    if found["env"]:
        path = os.path.join(home, ".env")
        lines = open(path, encoding="utf-8").read().splitlines()
        kept = [line for line in lines if line.split("=", 1)[0].strip() not in found["env"]]
        open(path, "w", encoding="utf-8").write("\n".join(kept) + ("\n" if kept else ""))
        journal.add("env-dropped", keys=found["env"])
    for row in found["records"]:
        source = os.path.join(workspace(), row["from"])
        target = os.path.join(workspace(), row["to"])
        if os.path.exists(target) and row.get("kind", "dir") != "file":
            for name in sorted(os.listdir(source)):
                _move(os.path.join(source, name), os.path.join(target, name), journal)
            os.rmdir(source)
        else:
            _move(source, target, journal)
        if row.get("kind") == "intents":
            _convert_intents(target, journal)
    _rewrite_cards(pack, spec, found["cards"], journal)
    _map_flows(pack, spec, journal)
    for row in found["bindings"]:
        from .slots import write_owner, write_ticket

        for number, path in _binding_files(row):
            value = open(path, encoding="utf-8").read().strip()
            value = row["format"].replace("{value}", value) if row["format"] else value
            (write_ticket if row["to"] == "ticket" else write_owner)(number, value)
            journal.add("binding", slot=number, to=row["to"])
    vault = _import_vault(pack, spec, journal)
    for row in (spec.get("exporters") or {}).get("extra") or []:
        done = subprocess.run(_command(pack, row["argv"]), capture_output=True, text=True, timeout=600, check=False)
        journal.add("exporter", name=row["name"], exit=done.returncode)
        if done.returncode != 0:
            raise CockpitError(
                f"exporter {row['name']} failed (exit {done.returncode}); snapshot {stamp} restores everything"
            )
    return {
        "ok": True,
        "snapshot": stamp,
        "journal": journal.path,
        "actions": len(journal.rows),
        "vault": vault,
        "replace_profiles": found["profiles_replace"],
    }


def _rewrite_cards(pack, spec, cards, journal) -> None:
    if not cards:
        return
    from .kanban import BoardWrites, board_cards

    bodies = {card["id"]: card.get("body") or "" for card in board_cards(pack["board"])}
    writes = BoardWrites(pack["board"])
    for card in cards:
        body = bodies.get(card, "")
        for row in (spec.get("board") or {}).get("rewrite") or []:
            body = re.sub(row["pattern"], row["replace"], body)
        writes.edit(card, body=body)
        journal.add("card-rewritten", card=card)
    writes.flush()


def _map_flows(pack, spec, journal) -> None:
    """Open cards cockpit did not make get a flow, from their titles."""
    from .kanban import _index, remember_card

    rows = (spec.get("board") or {}).get("flows") or []
    if not rows:
        return
    known = _index().get(str(pack["board"])) or {}
    for card in _open_cards(pack):
        if card["id"] in known:
            continue
        for row in rows:
            if re.search(row["pattern"], card.get("title") or ""):
                remember_card(pack["board"], card["id"], row["flow"], ticket=card.get("ticket") or "")
                journal.add("flow", card=card["id"], flow=row["flow"])
                break


# --- verify -----------------------------------------------------------------------------------------------------


def verify(pack, expected_logins=None) -> list:
    """[(ok, line, evidence)] — the cutover gate."""
    spec = load_spec(pack)
    found = scan(pack, spec)
    lines = []

    def check(ok, line, evidence=""):
        lines.append((bool(ok), line, evidence))

    check(not found["crons"], "no legacy cron is registered", ", ".join(found["crons"]) or "none")
    check(not found["plugins"], "no legacy plugin is enabled", ", ".join(found["plugins"]) or "none")
    check(
        not found["shell_hooks"],
        "no legacy shell hook is registered",
        ", ".join(hook["command"] for hook in found["shell_hooks"]) or "none",
    )
    check(not found["profiles_remove"], "no legacy profile remains", ", ".join(found["profiles_remove"]) or "none")
    from .setup import seat_drift

    drift = [item for item in seat_drift(pack) if any(f" {name}" in item for name in found["profiles_replace"])]
    check(not drift, "every replaced profile is cockpit's seat", "; ".join(drift) or "none drifted")
    check(
        not found["soul_blocks"] and not found["env"] and not found["config"],
        "the root holds no legacy soul block, env key or config key",
        ", ".join([*found["env"], *found["config"]]) or "none",
    )
    check(
        not found["records"],
        "the old record locations are empty",
        ", ".join(row["from"] for row in found["records"]) or "none",
    )
    check(not found["cards"], "no open card body calls a legacy command", ", ".join(found["cards"]) or "none")
    from .intents import SCHEMAS, all_intents

    broken = [row["id"] for row in all_intents() if row.get("type") not in SCHEMAS]
    check(not broken, "every intent loads with a cockpit type", ", ".join(broken) or f"{len(all_intents())} intents")
    from .kanban import FLOWS, _index

    known = _index().get(str(pack["board"])) or {}

    def by_title(title):
        rest = re.sub(r"^\s*[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\s*", "", title or "")
        return any(re.search(pattern, rest) for pattern, _name in FLOWS)

    unmapped = [card["id"] for card in _open_cards(pack) if card["id"] not in known and not by_title(card.get("title"))]
    check(not unmapped, "every open card maps to a flow", ", ".join(unmapped) or "all mapped")
    from .doctor import run as doctor_run

    problems = doctor_run(pack)
    check(not problems, "doctor is empty", "; ".join(problems[:5]) or "empty")
    if (spec.get("exporters") or {}).get("vault"):
        from .lane_vault import items
        from .lane_vault import seats as seat_lanes

        want = _count(pack, spec) if expected_logins is None else expected_logins
        have = sum(len(items(lane)) for lane in seat_lanes(pack))
        check(have >= want, "the seat stores hold every exported login", f"{have} of {want}")
    return lines


# --- rollback ---------------------------------------------------------------------------------------------------


def rollback(pack, stamp: str) -> list:
    """The snapshot back in place, and every record move of its journal reversed (newest first)."""
    from .kanban import db_path

    folder = os.path.join(snapshots_dir(), stamp)
    if not stamp or not os.path.isdir(folder):
        raise CockpitError(f"no snapshot {stamp}; refusing to guess")
    home = hermes_home()
    restored = []
    journal = os.path.join(folder, "journal.jsonl")
    rows = [json.loads(line) for line in open(journal, encoding="utf-8")] if os.path.isfile(journal) else []
    for row in reversed(rows):
        if row["action"] != "move" or not os.path.exists(row["target"]):
            continue
        os.makedirs(os.path.dirname(row["source"]), exist_ok=True)
        if row["git"]:
            subprocess.run(
                ["git", "-C", row["git"], "mv", row["target"], row["source"]], check=True, capture_output=True
            )
        else:
            shutil.move(row["target"], row["source"])
        restored.append(row["source"])
    for name in ("config.yaml", "SOUL.md", ".env", "cockpit.yaml", os.path.join("cron", "jobs.json")):
        source = os.path.join(folder, name)
        target = os.path.join(home, name)
        if os.path.isfile(source):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
            restored.append(target)
        elif os.path.isfile(target):
            os.remove(target)
            restored.append(f"removed {target}")
    profiles = os.path.join(folder, "profiles")
    if os.path.isdir(profiles):
        target = os.path.join(home, "profiles")
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(profiles, target, symlinks=True)
        restored.append(target)
    board = os.path.join(folder, "board.db")
    if os.path.isfile(board):
        target = db_path(pack["board"])
        for suffix in ("-wal", "-shm"):
            if os.path.isfile(target + suffix):
                os.remove(target + suffix)
        shutil.copy2(board, target)
        restored.append(target)
    editor = os.path.join(folder, "editor")
    for dirpath, _dirs, names in os.walk(editor) if os.path.isdir(editor) else []:
        for name in names:
            relative = os.path.relpath(os.path.join(dirpath, name), editor)
            os.makedirs(os.path.dirname(os.path.join(workspace(), relative)), exist_ok=True)
            shutil.copy2(os.path.join(dirpath, name), os.path.join(workspace(), relative))
            restored.append(relative)
    return restored
