# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No stored secret goes out in a tool call or comes back in a result.

The index (~/.hermes/vault/scrub.index, a protected path) holds a salted hash, a length, and a prefix hash for each
password and seed: those of every seat's Hermes store and of cockpit's own encrypted vault. Finding a secret in text
needs only the index, so masking works while the GPG key is locked. The index is rebuilt when a secret is stored or
restored and when a seat's store changes (a lane that ran Hermes's save_login). Current authenticator codes are
masked from the seeds in the seat stores, where Hermes's own code can read them.
"""

import hashlib
import json
import os
import secrets
import time

from .paths import hermes_home
from .store import dump_json

MIN_LEN = 6
SCAN_LIMIT = 2_000_000
MASK = "[secret]"


def index_path() -> str:
    from .vault import vault_dir

    return os.path.join(vault_dir(), "scrub.index")


def seat_homes() -> list:
    """Every home with a Hermes store: each profile and the root."""
    homes = [hermes_home()]
    folder = os.path.join(hermes_home(), "profiles")
    if os.path.isdir(folder):
        homes += [
            os.path.join(folder, name)
            for name in sorted(os.listdir(folder))
            if os.path.isdir(os.path.join(folder, name))
        ]
    return homes


def _hash(salt: str, value: str) -> str:
    return hashlib.sha256((salt + value).encode("utf-8")).hexdigest()[:32]


def _entry(salt: str, value: str) -> dict:
    return {"len": len(value), "hash": _hash(salt, value), "prefix": _hash(salt, value[:MIN_LEN])}


def _hermes_bridge():
    """Hermes's own vault functions when this process is Hermes's (the plugin's hooks); else None."""
    try:
        import agent.vault_store  # noqa: F401
    except ImportError:
        return None
    import importlib.util

    from .paths import PLUGIN_ROOT

    spec = importlib.util.spec_from_file_location(
        "cockpit_hermes_vault", os.path.join(PLUGIN_ROOT, "hermes_bridge", "vault.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seat_sources(salt: str) -> list:
    homes = [home for home in seat_homes() if os.path.isfile(os.path.join(home, "vault", "vault.json.enc"))]
    if not homes:
        return []
    side = _hermes_bridge()
    if side is not None:
        return side.fingerprints(homes, salt, MIN_LEN)
    from .hermes_runtime import run_helper

    return run_helper("vault", {"ops": [{"op": "fingerprints", "homes": homes, "salt": salt, "min_len": MIN_LEN}]})[
        "results"
    ][0]


def _gpg_mtime() -> float:
    from .vault import _blob_path, _entry_paths

    paths = [_blob_path(), *_entry_paths()]
    return max((os.path.getmtime(path) for path in paths if os.path.isfile(path)), default=0.0)


def _gpg_source(salt: str, previous: dict, learned=(), wrote: bool = False) -> dict:
    """Cockpit's own vault. While the private key is locked the vault cannot be read back, so the index keeps the last
    readable hashes and learns a secret at the moment cockpit stores it (`learned`: the plaintext values just written, the
    only way a value enters that vault). `wrote`: cockpit itself just wrote the vault and `learned` is all it added (an
    init's empty vault adds nothing). A change nobody taught it marks the source locked."""
    from .errors import CockpitError
    from .vault import _items, sealed_to

    mtime = _gpg_mtime()
    if not sealed_to() or not mtime:
        return {"source": "gpg", "mtime": mtime, "entries": [], "locked": False}
    try:
        items = _items()
    except CockpitError:
        kept = dict(previous or {"entries": []})
        fresh = [_entry(salt, value) for value in learned if len(str(value or "")) >= MIN_LEN]
        if fresh or wrote:
            entries = list(kept.get("entries") or []) + [
                entry for entry in fresh if entry not in (kept.get("entries") or [])
            ]
            if kept.get(
                "locked"
            ):  # something entered the vault untaught before this write (a restore): the index stays behind, and says so
                return {**kept, "source": "gpg", "entries": entries, "locked": True, "mtime_now": mtime}
            return {"source": "gpg", "mtime": mtime, "entries": entries, "locked": False}
        kept.update({"source": "gpg", "locked": True, "mtime_now": mtime})
        return kept
    entries = []
    for item in items:
        held = [
            (item or {}).get("secret"),
            (item or {}).get("otp"),
            *[row.get("secret") for row in (item or {}).get("history") or [] if isinstance(row, dict)],
        ]
        for raw in held:
            value = str(raw or "").split("|", 1)[0]
            if len(value) >= MIN_LEN:
                entries.append(_entry(salt, value))
    return {"source": "gpg", "mtime": mtime, "entries": entries, "locked": False}


def load() -> dict:
    try:
        data = json.load(open(index_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def rebuild(previous=None, learned=(), wrote=False) -> dict:
    """Write the index again from every store. Called after a secret is stored, restored, or imported; `learned` carries the
    values just stored in cockpit's own vault, for a machine whose private key is elsewhere, and `wrote` says cockpit's own
    write added nothing else."""
    previous = load() if previous is None else previous
    salt = previous.get("salt") or secrets.token_hex(16)
    old_gpg = next((source for source in previous.get("sources") or [] if source.get("source") == "gpg"), {})
    sources = [*_seat_sources(salt), _gpg_source(salt, old_gpg, learned, wrote)]
    index = {"salt": salt, "min_len": MIN_LEN, "built": int(time.time()), "sources": sources}
    path = index_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    dump_json(path, index, mode=0o600)
    return index


def _stale(index: dict) -> bool:
    known = {source.get("source"): source.get("mtime") for source in index.get("sources") or []}
    for home in seat_homes():
        path = os.path.join(home, "vault", "vault.json.enc")
        if os.path.isfile(path) and known.get(path) != os.path.getmtime(path):
            return True
        if not os.path.isfile(path) and path in known:
            return True
    return known.get("gpg", 0.0) != _gpg_mtime() and not any(
        source.get("locked") for source in index.get("sources") or []
    )


def current() -> dict:
    """The index, rebuilt first when a store changed since it was written. No store at all is an empty index."""
    index = load()
    if not index or _stale(index):
        has_store = (
            any(os.path.isfile(os.path.join(home, "vault", "vault.json.enc")) for home in seat_homes()) or _gpg_mtime()
        )
        if not has_store and not index:
            return {}
        index = rebuild(index)
    return index


def locked() -> bool:
    """Cockpit's vault changed while its key was locked, so the index may miss what was added."""
    for source in load().get("sources") or []:
        if source.get("source") == "gpg" and source.get("locked") and source.get("mtime_now") != source.get("mtime"):
            return True
    return False


def spans(text: str, index=None) -> list:
    """Where stored secrets sit in the text: (start, end) pairs."""
    index = current() if index is None else index
    if not text or not index:
        return []
    salt = index["salt"]
    width = int(index.get("min_len") or MIN_LEN)
    by_prefix = {}
    for source in index.get("sources") or []:
        for entry in source.get("entries") or []:
            by_prefix.setdefault(entry["prefix"], []).append((int(entry["len"]), entry["hash"]))
    if not by_prefix:
        return []
    found = []
    body = text[:SCAN_LIMIT]
    for start in range(0, len(body) - width + 1):
        candidates = by_prefix.get(_hash(salt, body[start : start + width]))
        if not candidates:
            continue
        for length, digest in candidates:
            if _hash(salt, body[start : start + length]) == digest:
                found.append((start, start + length))
    return found


def holds_secret(texts) -> bool:
    index = current()
    return bool(index) and any(spans(text, index) for text in texts if isinstance(text, str))


def _codes() -> list:
    side = _hermes_bridge()
    if side is None:
        return []
    homes = [home for home in seat_homes() if os.path.isfile(os.path.join(home, "vault", "vault.json.enc"))]
    return side.codes(homes)


def scrub(text: str) -> str:
    """The text with every stored secret and every current authenticator code masked."""
    import re

    if not isinstance(text, str) or not text:
        return text
    merged = []
    for start, end in sorted(spans(text)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            continue
        merged.append((start, end))
    cleaned = text
    for start, end in reversed(merged):
        cleaned = cleaned[:start] + MASK + cleaned[end:]
    for code in _codes():
        cleaned = re.sub(rf"(?<!\d){re.escape(code)}(?!\d)", MASK, cleaned)
    return cleaned
