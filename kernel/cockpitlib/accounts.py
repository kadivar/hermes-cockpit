# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Staging accounts the pack declares, from creation to renewal.

pack.yaml logins.accounts names a manifest beside the pack:

    command: [bin/accounts]        # create | renew: prints {"password": ..., "otp_secret": ...} on stdout
    accounts:
      - origin: https://app.example.test
        identifier: qa-one@example.test
        owner: tester-1            # a seat that owns it, or
        readers: [tester]          # the seats (names or kinds) it is shared with
        totp: true                 # the command returns a seed
        renew_days: 30             # renewed by `cockpit vault accounts renew` once this old

The command runs with COCKPIT_ACCOUNT_ACTION, _ORIGIN, _IDENTIFIER, and _OWNER set. Its output is a secret: it is
stored and placed, never printed or logged.
"""

import json
import os
import subprocess
import time

from . import pack_local
from .errors import CockpitError, PackError
from .store import dump_json

KEYS = {"origin", "identifier", "owner", "readers", "totp", "renew_days"}


def manifest_path(pack) -> str:
    raw = (((pack or {}).get("logins") or {}).get("accounts")) or ""
    if not raw:
        return ""
    return raw if os.path.isabs(raw) else os.path.join(pack["_dir"], raw)


def manifest(pack) -> dict:
    """The validated manifest, or an empty one when the pack names none."""
    path = manifest_path(pack)
    if not path:
        return {"command": [], "accounts": []}
    from .pack import consulted

    consulted(path)
    if not os.path.isfile(path):
        raise PackError(f"logins.accounts: missing {path}")
    data = pack_local.read(path, pack["_dir"]) or {}
    command = [] if data.get("command") is None else data["command"]
    rows = [] if data.get("accounts") is None else data["accounts"]
    if not isinstance(command, list) or not all(isinstance(word, str) and word for word in command):
        raise PackError("accounts manifest: command must be a list of words")
    if not isinstance(rows, list):
        raise PackError("accounts manifest: accounts must be a list")
    if data.get("verify_command") is not None and not isinstance(data["verify_command"], bool):
        raise PackError(
            "accounts manifest: verify_command is true or false (true: verify also asks the command to check each account)"
        )
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - KEYS or not row.get("origin") or not row.get("identifier"):
            raise PackError("accounts manifest: each account has origin and identifier, and owner or readers")
        if bool(row.get("owner")) == bool(row.get("readers")):
            raise PackError(f"accounts manifest: {row['identifier']} has an owner or readers, not both")
        key = (row["origin"], row["identifier"])
        if key in seen:
            raise PackError(f"accounts manifest: {row['identifier']} is listed twice")
        seen.add(key)
    return {
        "command": command,
        "accounts": rows,
        "verify_command": bool(data.get("verify_command")),
        "_dir": os.path.dirname(path),
    }


def readers(pack, origin: str, identifier: str) -> list:
    """The reader names a manifest account gives, for placement."""
    from .lane_vault import _origin_of

    for row in manifest(pack)["accounts"]:
        if _origin_of(row["origin"]) == _origin_of(origin) and row["identifier"] == identifier:
            return list(row.get("readers") or [])
    return []


def _state_path() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "accounts.json")


def _state() -> dict:
    try:
        data = json.load(open(_state_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    dump_json(_state_path(), state)


def _key(row) -> str:
    return f"{row['origin']} {row['identifier']}"


def _expected_seats(pack, row) -> list:
    from .lane_vault import seats
    from .lanes import seats_from

    if row.get("owner"):
        return [row["owner"]]
    kinds = seats_from(pack)
    found = []
    for name in row.get("readers") or []:
        for lane in kinds.get(name) or [name]:
            if lane in seats(pack) and lane not in found:
                found.append(lane)
    return found


def _held(pack) -> dict:
    """(origin, identifier) -> the seats whose store holds a cockpit placement of it."""
    from .lane_vault import MARK, _origin_of, items_of, seats

    held = {}
    for lane, listed in items_of(seats(pack)).items():
        for item in listed:
            if str(item.get("label") or "").startswith(MARK):
                held.setdefault((_origin_of(item.get("origin")), item.get("identifier")), []).append(lane)
    return held


def rows(pack, now=None) -> list:
    """Each manifest account with what is true now: stored, where it is placed, and whether renewal is due."""
    from .lane_vault import _origin_of

    moment = int(now or time.time())
    state = _state()
    held = _held(pack)
    found = []
    for row in manifest(pack)["accounts"]:
        record = state.get(_key(row)) or {}
        stamp = int(record.get("renewed") or record.get("created") or 0)
        days = int(row.get("renew_days") or 0)
        found.append(
            {
                **row,
                "stored": bool(stamp),
                "seats": sorted(held.get((_origin_of(row["origin"]), row["identifier"])) or []),
                "expected": sorted(_expected_seats(pack, row)),
                "due": bool(stamp and days and moment - stamp > days * 86400),
            }
        )
    return found


def plan(pack, now=None) -> list:
    lines = []
    for row in rows(pack, now):
        if not row["stored"]:
            lines.append(f"add {row['identifier']} for {', '.join(row['expected'])}")
        elif row["seats"] != row["expected"]:
            lines.append(f"place {row['identifier']} for {', '.join(row['expected'])}")
        elif row["due"]:
            lines.append(f"renew {row['identifier']}")
        else:
            lines.append(f"ok {row['identifier']}")
    return lines


def _run_command(pack, action: str, row) -> dict:
    data = manifest(pack)
    command = list(data["command"])
    if not command:
        raise CockpitError("accounts manifest names no command")
    if "/" in command[0] and not os.path.isabs(command[0]):
        command[0] = os.path.join(data["_dir"], command[0])
    env = {
        **os.environ,
        "COCKPIT_ACCOUNT_ACTION": action,
        "COCKPIT_ACCOUNT_ORIGIN": row["origin"],
        "COCKPIT_ACCOUNT_IDENTIFIER": row["identifier"],
        "COCKPIT_ACCOUNT_OWNER": row.get("owner") or "",
    }
    done = subprocess.run(command, capture_output=True, text=True, env=env, check=False, timeout=300)
    if done.returncode != 0:
        # The command's own words, without its output: stdout may hold the secret.
        raise CockpitError(
            f"accounts {action} {row['identifier']} failed: exit {done.returncode} {(done.stderr or '').strip()[-200:]}"
        )
    try:
        answer = json.loads(done.stdout)
    except ValueError as exc:
        raise CockpitError(f"accounts {action} {row['identifier']}: the command printed no JSON") from exc
    if not isinstance(answer, dict) or not answer.get("password"):
        raise CockpitError(f"accounts {action} {row['identifier']}: the command printed no password")
    if row.get("totp") and not answer.get("otp_secret"):
        raise CockpitError(
            f"accounts {action} {row['identifier']}: the account has an authenticator and the command printed no seed"
        )
    return answer


def _store(pack, row, answer) -> None:
    from .vault import store_login

    store_login(
        row["origin"],
        row["identifier"],
        answer["password"],
        otp=answer.get("otp_secret") or None,
        lane=row.get("owner") or "",
        pack=pack,
    )


def apply(pack, now=None) -> list:
    """Create what is missing, place what moved. Renewal waits for `renew`."""
    state = _state()
    done = []
    for row in rows(pack, now):
        if not row["stored"]:
            _store(pack, row, _run_command(pack, "create", row))
            state[_key(row)] = {"created": int(now or time.time())}
            done.append(f"added {row['identifier']}")
            continue
        if row["seats"] != row["expected"]:
            from .lane_vault import audit

            audit(pack, fix=True)
            done.append(f"placed {row['identifier']}")
    _save_state(state)
    return done or ["nothing to apply"]


def renew(pack, now=None, force=False) -> list:
    state = _state()
    done = []
    for row in rows(pack, now):
        if not row["stored"] or not (row["due"] or force):
            continue
        _store(pack, row, _run_command(pack, "renew", row))
        state[_key(row)] = {**(state.get(_key(row)) or {}), "renewed": int(now or time.time())}
        done.append(f"renewed {row['identifier']}")
    _save_state(state)
    return done or ["nothing due"]


def verify(pack) -> list:
    """Each seat holds exactly the manifest accounts meant for it."""
    findings = []
    for row in rows(pack):
        if not row["stored"]:
            findings.append(f"not created: {row['identifier']}")
            continue
        found = [f"missing on {lane}: {row['identifier']}" for lane in sorted(set(row["expected"]) - set(row["seats"]))]
        found += [f"extra on {lane}: {row['identifier']}" for lane in sorted(set(row["seats"]) - set(row["expected"]))]
        findings.extend(found)
        if (
            manifest(pack).get("verify_command") and not found
        ):  # placed right: the manifest's command checks the account itself
            try:
                _run_command(pack, "verify", row)
            except CockpitError as exc:
                findings.append(str(exc))
    return findings
