# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seat logins through Hermes's own vault store, one store per seat home (<home>/vault).

Runs inside Hermes's environment (see cockpitlib.hermes_runtime): the standard library and Hermes's modules only, never
cockpitlib. A secret never leaves this process: listing returns metadata, and the scrub index gets salted hashes.
The plugin's own hooks also import fingerprints() and codes() directly, since they run in Hermes's process.
stdin: {"ops": [{"op": name, ...}]}. stdout: {"results": [...]}, one result per op, in order.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

# cockpit marks the items it places: "cockpit lane <email>", "cockpit shared <email>", "cockpit lent <card> <email>".
MARK = "cockpit "


def _store(home):
    from agent.vault_store import VaultStore

    return VaultStore(base_dir=Path(home) / "vault")


def _vault_file(home) -> str:
    return os.path.join(home, "vault", "vault.json.enc")


def _list(op):
    if not os.path.isfile(_vault_file(op["home"])):
        return []
    return [item.to_dict() for item in _store(op["home"]).list_items()]


def _add(op):
    """Place one login. A cockpit item for the same origin, identifier, and label is replaced, not doubled."""
    from agent.vault_store import normalize_origin

    store = _store(op["home"])
    origin = normalize_origin(op["origin"])
    for item in store.list_items():
        if item.label == op["label"] and item.origin == origin and item.identifier == op["identifier"]:
            store.remove_item(item.id)
    secret = {
        "identifier_type": op.get("identifier_type") or "email",
        "identifier": op["identifier"],
        "password": op["password"],
    }
    if op.get("otp_secret"):
        secret["otp_secret"] = op["otp_secret"]
    return store.add_item("login", op["label"], secret, origin=origin).id


def _remove(op):
    if not os.path.isfile(_vault_file(op["home"])):
        return False
    return _store(op["home"]).remove_item(op["id"])


def _secret(op):
    """The password of the login item for an origin and identifier: for the human's own page only (cockpitlib fences
    the caller). A lent copy is not the login. Nothing when the store does not hold it."""
    if not os.path.isfile(_vault_file(op["home"])):
        return None
    from agent.vault_store import normalize_origin

    store = _store(op["home"])
    origin = normalize_origin(op["origin"]) if op.get("origin") else ""
    wanted = str(op.get("identifier") or "").strip().lower()
    for item in store.list_items():
        if item.kind != "login" or str(item.identifier or "").strip().lower() != wanted:
            continue
        if origin and item.origin != origin:
            continue
        if str(item.label or "").startswith(MARK + "lent "):
            continue
        return str(store.resolve_secret(item.id).get("password") or "") or None
    return None


def _secrets(home):
    """(value, seed) per item: the password and the TOTP seed. Never returned to the caller."""
    store = _store(home)
    found = []
    for item in store.list_items():
        secret = store.resolve_secret(item.id)
        for key in ("password", "otp_secret"):
            value = str(secret.get(key) or "")
            if value:
                found.append((value.split("|", 1)[0] if key == "otp_secret" else value, key == "otp_secret"))
    return found


def _hash(salt, value):
    return hashlib.sha256((salt + value).encode("utf-8")).hexdigest()[:32]


def fingerprints(homes, salt, min_len):
    """Per seat home: the store's mtime and a salted hash, a length, and a prefix hash for each secret."""
    sources = []
    for home in homes:
        path = _vault_file(home)
        if not os.path.isfile(path):
            continue
        entries = []
        seeds = 0
        for value, seed in _secrets(home):
            seeds += 1 if seed else 0
            if len(value) >= min_len:
                entries.append({"len": len(value), "hash": _hash(salt, value), "prefix": _hash(salt, value[:min_len])})
        sources.append({"source": path, "mtime": os.path.getmtime(path), "entries": entries, "seeds": seeds})
    return sources


def codes(homes, at=None):
    """The current authenticator codes of every seat store, to mask them in a result."""
    from agent.vault_store import totp_now

    found = []
    for home in homes:
        if not os.path.isfile(_vault_file(home)):
            continue
        store = _store(home)
        for item in store.list_items():
            seed = str(store.resolve_secret(item.id).get("otp_secret") or "")
            if seed:
                found.append(totp_now(seed, at=at))
    return found


def _fingerprints(op):
    return fingerprints(op["homes"], op["salt"], int(op["min_len"]))


def _codes(op):
    return codes(op["homes"], op.get("at"))


def _normalize_otp(op):
    from agent.vault_store import normalize_otp_secret

    return normalize_otp_secret(op["value"])


def _totp(op):
    from agent.vault_store import totp_now

    return totp_now(op["seed"], at=op.get("at"))


OPS = {
    "list": _list,
    "add": _add,
    "remove": _remove,
    "secret": _secret,
    "fingerprints": _fingerprints,
    "codes": _codes,
    "normalize_otp": _normalize_otp,
    "totp": _totp,
}


def main() -> int:
    request = json.load(sys.stdin)
    results = []
    for op in request.get("ops") or []:
        try:
            results.append(OPS[op["op"]](op))
        except Exception as exc:  # noqa: BLE001 - Hermes's VaultError and the like: the op answers, the batch goes on
            results.append({"error": str(exc)})
    print(json.dumps({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
