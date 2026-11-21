# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pack's helpers: the dev stack, tunnels and local services a human (or a lane, where the pack allows it) starts
and stops from one place.

helpers.yaml (named by pack.yaml `helpers:`) lists groups, each with a status command, and helpers, each an argv
template with verbs. A helper may depend on others (started first, in order) or be a composite of others. A verb
whose argv takes {choice} picks from the helper's options. Each command answers with the slot runtime's contract:
exit 0 ok, 1 failed, 2 still working, 3 a dependency is down; JSON on stdout is read as data.

Each run has a record and a log under <records>/helpers/. A run of a helper still going is not started twice.
"""

import json
import os
import re
import subprocess
import sys
import time

from .errors import CockpitError, PackError
from .store import dump_json

GROUP_KEYS = {"label", "status"}
HELPER_KEYS = {
    "label",
    "group",
    "argv",
    "verbs",
    "depends_on",
    "composite",
    "options",
    "who",
    "warn",
    "self",
    "status_names",
}
WHO = ("human", "lane", "both")
PARSE = ("lines", "json")
STATES = ("running", "stopped", "skipped", "failed", "working")
# "<name>: <state> (<detail>)", one helper per line. A skipped row is kept: the human sees why it did not run.
STATUS_LINE = re.compile(r"^(?P<name>.+?):\s+(?P<state>" + "|".join(STATES) + r")\s*(?:\((?P<detail>.*)\))?\s*$", re.I)
CODES = {0: "ok", 1: "failed", 2: "working", 3: "dependency down"}
TEMPLATE_FIELDS = ("pack", "workspace", "root", "records", "verb", "choice", "helper")


def _command(raw, where) -> dict:
    """{argv: [words], parse: lines|json}, or a bare argv list."""
    if isinstance(raw, list):
        raw = {"argv": raw}
    if not isinstance(raw, dict) or set(raw) - {"argv", "parse"}:
        raise PackError(f"helpers.yaml {where}: {{argv, parse}}")
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(word, str) and word for word in argv):
        raise PackError(f"helpers.yaml {where}.argv is a list of words")
    if raw.get("parse", "lines") not in PARSE:
        raise PackError(f"helpers.yaml {where}.parse is lines or json")
    return {"argv": list(argv), "parse": raw.get("parse", "lines")}


def _helper(name, raw, groups) -> dict:
    if not isinstance(raw, dict) or set(raw) - HELPER_KEYS:
        raise PackError(f"helpers.yaml helpers.{name} takes {', '.join(sorted(HELPER_KEYS))}")
    if bool(raw.get("argv")) == bool(raw.get("composite")):
        raise PackError(f"helpers.yaml helpers.{name}: an argv or a composite, not both")
    entry = {
        "name": name,
        "label": str(raw.get("label") or name),
        "group": str(raw.get("group") or ""),
        "who": raw.get("who", "human"),
        "warn": str(raw.get("warn") or ""),
        "self": bool(raw.get("self")),
        "verbs": raw.get("verbs", ["start", "stop"]),
        "depends_on": raw.get("depends_on", []),
        "composite": raw.get("composite", []),
        "status_names": raw.get("status_names", [name]),
        "argv": [],
        "options": None,
    }
    if entry["group"] and entry["group"] not in groups:
        raise PackError(f"helpers.yaml helpers.{name}: no group {entry['group']}")
    if entry["who"] not in WHO:
        raise PackError(f"helpers.yaml helpers.{name}.who is one of {', '.join(WHO)}")
    for field in ("verbs", "depends_on", "composite", "status_names"):
        value = entry[field]
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise PackError(f"helpers.yaml helpers.{name}.{field} is a list of names")
    if not entry["verbs"]:
        raise PackError(f"helpers.yaml helpers.{name}.verbs names at least one verb")
    if raw.get("argv"):
        entry["argv"] = _command(raw["argv"], f"helpers.{name}")["argv"]
    options = raw.get("options")
    if options is not None:
        if isinstance(options, list) and all(isinstance(item, str) and item for item in options):
            entry["options"] = list(options)
        else:
            entry["options"] = _command(options, f"helpers.{name}.options")
    if any("{choice}" in word for word in entry["argv"]) and entry["options"] is None:
        raise PackError(f"helpers.yaml helpers.{name}: an argv with {{choice}} needs options")
    for word in entry["argv"]:
        for field in re.findall(r"\{([^{}]*)\}", word):
            if field not in TEMPLATE_FIELDS:
                raise PackError(
                    f"helpers.yaml helpers.{name}: unknown field {{{field}}} (known: {', '.join(TEMPLATE_FIELDS)})"
                )
    return entry


def check(data) -> None:
    """pack.yaml helpers: the helpers file beside the pack. Read, checked, and kept on the pack as _helpers."""
    name = data.get("helpers")
    data["_helpers"] = {"groups": {}, "helpers": {}}
    if name is None:
        return
    if not isinstance(name, str) or os.path.isabs(name) or ".." in name.split("/"):
        raise PackError("helpers is a file beside pack.yaml")
    path = os.path.join(data["_dir"], name)
    from .pack import consulted

    consulted(path)
    if not os.path.isfile(path):
        raise PackError(f"helpers: missing {name}")
    from . import pack_local

    raw = pack_local.read(path, data["_dir"]) or {}
    if not isinstance(raw, dict) or set(raw) - {"groups", "helpers"}:
        raise PackError(f"{name} takes groups and helpers")
    groups = {}
    for group, entry in (raw.get("groups") or {}).items():
        if not isinstance(entry, dict) or set(entry) - GROUP_KEYS:
            raise PackError(f"{name} groups.{group} takes label and status")
        groups[group] = {
            "name": group,
            "label": str(entry.get("label") or group),
            "status": _command(entry["status"], f"groups.{group}.status") if entry.get("status") else None,
        }
    helpers = {key: _helper(key, entry, groups) for key, entry in (raw.get("helpers") or {}).items()}
    for key, entry in helpers.items():
        for other in entry["depends_on"] + entry["composite"]:
            if other not in helpers or other == key:
                raise PackError(f"helpers.yaml helpers.{key}: no helper {other}")
    for key in helpers:
        _order(helpers, [key])
    data["_helpers"] = {"groups": groups, "helpers": helpers}


def _order(helpers, names) -> list:
    """These helpers and everything they need, dependencies first. A cycle is a pack error."""
    done = []
    path = []

    def visit(name):
        if name in done:
            return
        if name in path:
            raise PackError(f"helpers.yaml: {' → '.join(path[path.index(name) :] + [name])} is a cycle")
        path.append(name)
        entry = helpers[name]
        for other in entry["depends_on"] + entry["composite"]:
            visit(other)
        path.pop()
        done.append(name)

    for name in names:
        visit(name)
    return done


def _registry(pack) -> dict:
    return (pack or {}).get("_helpers") or {"groups": {}, "helpers": {}}


def _folder() -> str:
    from .paths import records

    return os.path.join(records(), "helpers")


def _record_path(name: str) -> str:
    return os.path.join(_folder(), f"{name}.json")


def _read(path: str) -> dict:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, data)


def _alive(pid) -> bool:
    try:
        os.kill(int(pid or 0), 0)
    except (OSError, ValueError):
        return False
    return int(pid or 0) > 0


def _live(name: str) -> dict:
    record = _read(_record_path(name))
    if record.get("status") == "running" and _alive(record.get("pid")):
        return record
    return {}


def _fill(words, pack, name, verb, choice) -> list:
    from .paths import records, root, workspace

    values = {
        "pack": pack["_dir"],
        "workspace": workspace(),
        "root": root(),
        "records": records(),
        "verb": verb,
        "choice": choice,
        "helper": name,
    }
    filled = []
    for word in words:
        for field, value in values.items():
            word = word.replace("{" + field + "}", str(value))
        filled.append(word)
    return filled


def _caller_allowed(entry) -> None:
    lane = os.environ.get("COCKPIT_LANE") or ""
    if lane and entry["who"] == "human":
        raise CockpitError(f"helper {entry['name']} is the human's")
    if not lane and entry["who"] == "lane":
        raise CockpitError(f"helper {entry['name']} is a lane's")


def _exec(argv, log) -> tuple:
    """Run one command; (code, data or text). An exit outside the contract counts as failed."""
    env = {**os.environ, "COCKPIT_HELPER_RUN": "1"}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, env=env, check=False, timeout=3600)
        code, out, err = done.returncode, done.stdout or "", done.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, out, err = 1, "", str(exc)
    log.write(f"$ {' '.join(argv)}\n{out}{err}exit {code}\n")
    log.flush()
    if code not in CODES:
        code = 1
    data = None
    if out.strip().startswith(("{", "[")):
        try:
            data = json.loads(out)
        except ValueError:
            data = None
    return code, data if data is not None else (out.strip() or err.strip())


def options(pack, name: str) -> list:
    """The choices a helper's {choice} takes: listed in the pack, or what its options command prints."""
    entry = _entry(pack, name)
    found = entry["options"]
    if found is None:
        return []
    if isinstance(found, list):
        return list(found)
    words = _fill(found["argv"], pack, name, "options", "")
    try:
        done = subprocess.run(words, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if done.returncode != 0:
        return []
    if found["parse"] == "json":
        try:
            value = json.loads(done.stdout or "[]")
        except ValueError:
            return []
        items = value if isinstance(value, list) else []
        return [str(item.get("id") if isinstance(item, dict) else item) for item in items if item]
    return [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]


def _entry(pack, name: str) -> dict:
    entry = _registry(pack)["helpers"].get(name)
    if entry is None:
        raise CockpitError(f"no helper {name}")
    return entry


def _steps(pack, name: str, verb: str) -> list:
    """The helpers a verb runs, in order. Starting runs what it depends on first; stopping a composite stops its
    members last-started first; a composite's own step is its members."""
    helpers = _registry(pack)["helpers"]
    if verb in ("stop", "down"):
        entry = helpers[name]
        members = entry["composite"] or [name]
        return list(reversed(_order(helpers, members))) if entry["composite"] else [name]
    return [step for step in _order(helpers, [name]) if not helpers[step]["composite"]]


def run(pack, name: str, verb: str, choice: str = "", background: bool = False, run_id: str = "") -> dict:
    """Run a helper's verb. A dependency that does not come up stops its dependents with exit 3."""
    entry = _entry(pack, name)
    if verb not in entry["verbs"]:
        raise CockpitError(f"helper {name} takes {', '.join(entry['verbs'])}, not {verb}")
    _caller_allowed(entry)
    takes_choice = any("{choice}" in word for word in entry["argv"])
    if takes_choice and choice not in options(pack, name):
        raise CockpitError(
            f"helper {name}: pick one of {', '.join(options(pack, name)) or 'its options (none listed)'}"
        )
    if choice and not takes_choice:
        raise CockpitError(f"helper {name} takes no choice")
    live = _live(name)
    if live and live.get("id") != run_id:
        return {
            "name": name,
            "verb": verb,
            "code": 2,
            "state": "working",
            "run": live["id"],
            "already": True,
            "warn": entry["warn"],
        }
    run_id = run_id or time.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    os.makedirs(_folder(), exist_ok=True)
    log_path = os.path.join(_folder(), f"{name}.log")
    if background:
        from .paths import PLUGIN_ROOT

        argv = [
            sys.executable,
            os.path.join(PLUGIN_ROOT, "bin", "cockpit"),
            "helper",
            "run",
            name,
            verb,
            "--run-id",
            run_id,
        ]
        if choice:
            argv += ["--choice", choice]
        child = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        _write(
            _record_path(name),
            {
                "id": run_id,
                "verb": verb,
                "choice": choice,
                "pid": child.pid,
                "status": "running",
                "started": int(time.time()),
                "log": log_path,
            },
        )
        return {"name": name, "verb": verb, "code": 2, "state": "working", "run": run_id, "warn": entry["warn"]}
    record = {
        "id": run_id,
        "verb": verb,
        "choice": choice,
        "pid": os.getpid(),
        "status": "running",
        "started": int(time.time()),
        "log": log_path,
    }
    _write(_record_path(name), record)
    helpers = _registry(pack)["helpers"]
    steps = []
    down = set()
    with open(log_path, "w", encoding="utf-8") as log:
        for step in _steps(pack, name, verb):
            needs = [other for other in helpers[step]["depends_on"] if other in down]
            if needs and verb not in ("stop", "down"):
                steps.append(
                    {"helper": step, "code": 3, "state": "skipped", "out": f"dependency down: {', '.join(needs)}"}
                )
                log.write(f"skipped {step}: dependency down: {', '.join(needs)}\n")
                down.add(step)
                continue
            words = _fill(helpers[step]["argv"], pack, step, verb, choice if step == name else "")
            code, data = _exec(words, log)
            steps.append({"helper": step, "code": code, "state": CODES[code], "out": data})
            if code in (1, 3):
                down.add(step)
    target = [step for step in steps if step["helper"] == name]
    if target:
        code = target[0]["code"]
    else:  # a composite: ok when every member is, dependency down when a member was skipped for one
        codes = [step["code"] for step in steps]
        code = 0 if all(item == 0 for item in codes) else 1 if 1 in codes else max(codes)
    tail = open(log_path, encoding="utf-8").read().strip().splitlines()[-3:]
    record.update({"status": "done", "code": code, "steps": steps, "ended": int(time.time()), "tail": tail})
    _write(_record_path(name), record)
    return {
        "name": name,
        "verb": verb,
        "code": code,
        "state": CODES[code],
        "run": run_id,
        "steps": steps,
        "tail": tail,
        "warn": entry["warn"],
    }


def _parse_status(command, text) -> list:
    if command["parse"] == "json":
        try:
            value = json.loads(text or "[]")
        except ValueError:
            return []
        if isinstance(value, dict):
            value = value.get("rows") or []
        rows = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict) and item.get("name") and str(item.get("state") or "").lower() in STATES:
                rows.append(
                    {
                        "name": str(item["name"]),
                        "state": str(item["state"]).lower(),
                        "detail": str(item.get("detail") or ""),
                    }
                )
        return rows
    rows = []
    for line in (text or "").splitlines():
        match = STATUS_LINE.match(line.strip())
        if match:
            rows.append(
                {
                    "name": match.group("name").strip(),
                    "state": match.group("state").lower(),
                    "detail": (match.group("detail") or "").strip(),
                }
            )
    return rows


def _helper_of(helpers, row_name: str) -> str:
    lowered = row_name.strip().lower()
    for name, entry in helpers.items():
        for prefix in entry["status_names"]:
            if lowered == prefix.lower() or lowered.startswith(prefix.lower()):
                return name
    return ""


def status(pack, group: str = "") -> dict:
    """Each group's status rows (matched to their helper) and each helper's last run."""
    registry = _registry(pack)
    if group and group not in registry["groups"]:
        raise CockpitError(f"no helper group {group}")
    groups = []
    for name, entry in registry["groups"].items():
        if group and name != group:
            continue
        found = {"name": name, "label": entry["label"], "rows": [], "error": ""}
        if entry["status"]:
            words = _fill(entry["status"]["argv"], pack, name, "status", "")
            try:
                done = subprocess.run(words, capture_output=True, text=True, check=False, timeout=60)
                text, code, err = done.stdout or "", done.returncode, (done.stderr or "").strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                text, code, err = "", 1, str(exc)
            found["rows"] = [
                {**row, "helper": _helper_of(registry["helpers"], row["name"])}
                for row in _parse_status(entry["status"], text)
            ]
            if code not in (0, 2):
                found["error"] = err or f"status exit {code}"
        groups.append(found)
    helpers = []
    for name, entry in registry["helpers"].items():
        if group and entry["group"] != group:
            continue
        last = _read(_record_path(name))
        if last.get("status") == "running" and not _alive(last.get("pid")):
            last = {**last, "status": "ended", "code": 1}
        helpers.append(
            {
                "name": name,
                "label": entry["label"],
                "group": entry["group"],
                "verbs": entry["verbs"],
                "who": entry["who"],
                "warn": entry["warn"],
                "self": entry["self"],
                "depends_on": entry["depends_on"],
                "composite": entry["composite"],
                "takes_choice": any("{choice}" in word for word in entry["argv"]),
                "last": {
                    key: last.get(key) for key in ("id", "verb", "choice", "status", "code", "started", "ended", "tail")
                }
                if last
                else None,
            }
        )
    return {"groups": groups, "helpers": helpers}


def problems(pack) -> list:
    """Doctor's lines: a helper or status command whose program is missing or not executable."""
    found = []
    registry = _registry(pack)
    commands = [(f"helper {name}", entry["argv"]) for name, entry in registry["helpers"].items() if entry["argv"]]
    commands += [
        (f"helper group {name}", entry["status"]["argv"])
        for name, entry in registry["groups"].items()
        if entry["status"]
    ]
    commands += [
        (f"helper {name} options", entry["options"]["argv"])
        for name, entry in registry["helpers"].items()
        if isinstance(entry["options"], dict)
    ]
    import shutil

    for label, words in commands:
        program = _fill(words[:1], pack, "", "", "")[0]
        if os.path.isabs(program):
            if not (os.path.isfile(program) and os.access(program, os.X_OK)):
                found.append(f"{label}: {program} is not an executable file")
        elif shutil.which(program) is None:
            found.append(f"{label}: {program} is not on PATH")
    return found
