# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermes vault key, wrapped to a GPG public key. The private key is only for unwrap and restore."""

import json
import os
import shutil
import subprocess
import time

from .errors import CockpitError
from .paths import hermes_home


def vault_dir() -> str:
    return os.path.join(hermes_home(), "vault")


def _recipient_path() -> str:
    return os.path.join(vault_dir(), "recipient")


def _blob_path() -> str:
    return os.path.join(vault_dir(), "cockpit-vault.json.gpg")


def _hermes_key() -> str:
    return os.path.join(vault_dir(), "vault.key")


def _wrapped_key() -> str:
    return os.path.join(vault_dir(), "vault.key.gpg")


def _hermes_enc() -> str:
    return os.path.join(vault_dir(), "vault.json.enc")


def _index_path() -> str:
    return os.path.join(vault_dir(), "index.json")


def _safe_scope(name: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(name or ""))
    return text or "lane"


def _scope_for(privileged: bool) -> str:
    """The pack names the vault list. A privileged login can use a different one from the lane list."""
    try:
        from .pack import load, policy
        from .paths import pack_path

        parsed = policy(load(pack_path()))
    except Exception:  # noqa: BLE001 - a pack that cannot be read has no vault policy
        parsed = {}
    if privileged:
        return _safe_scope(parsed.get("privileged_scope") or "human")
    return _safe_scope(parsed.get("login_scope") or "lane")


def _entry_dir(scope: str = "") -> str:
    chosen = scope or _scope_for(False)
    return os.path.join(vault_dir(), "scopes", chosen, "entries")


def _entry_dirs() -> list:
    folders = []
    scopes = os.path.join(vault_dir(), "scopes")
    if os.path.isdir(scopes):
        for name in sorted(os.listdir(scopes)):
            folder = os.path.join(scopes, name, "entries")
            if os.path.isdir(folder):
                folders.append(folder)
    legacy = os.path.join(vault_dir(), "entries")
    if os.path.isdir(legacy):
        folders.append(legacy)
    return folders


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _gpg(args, data: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gpg", "--batch", "--yes", "--trust-model", "always", *args],
        input=data,
        capture_output=True,
        check=False,
    )


def _fingerprints(primary: str, sub: str, args: list) -> list:
    result = _gpg(["--with-colons", *args])
    raw = result.stdout or b""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    found = []
    on_primary = False
    for line in raw.splitlines():
        parts = line.split(":")
        if parts[0] == primary:
            on_primary = True
            continue
        if parts[0] == sub:
            on_primary = False
            continue
        if on_primary and parts[0] == "fpr" and len(parts) > 9 and parts[9] and parts[9] not in found:
            found.append(parts[9])
            on_primary = False
    return found


def public_fingerprints() -> list:
    return _fingerprints("pub", "sub", ["--list-keys"])


def _full(fingerprint: str, keys: list) -> str:
    wanted = (fingerprint or "").replace(" ", "").upper()
    for key in keys:
        if key.upper() == wanted or key.upper().endswith(wanted):
            return key
    return ""


def choose_fingerprint(fingerprint: str = "") -> str:
    """The public key that may encrypt. A private key is not required."""
    keys = public_fingerprints()
    if fingerprint:
        found = _full(fingerprint, keys)
        if not found:
            raise CockpitError("no local GPG public key for that fingerprint")
        return found
    signing = ""
    try:
        result = subprocess.run(
            ["git", "config", "--global", "--get", "user.signingkey"], capture_output=True, text=True, check=False
        )
        signing = (result.stdout or "").strip()
    except OSError:
        signing = ""
    if signing:
        found = _full(signing, keys)
        if found:
            return found
    if len(keys) == 1:
        return keys[0]
    if len(keys) > 1:
        raise CockpitError("several GPG public keys; cockpit vault init --key <fingerprint>")
    return ""


def sealed_to() -> str:
    path = _recipient_path()
    if not os.path.isfile(path):
        return ""
    return open(path, encoding="utf-8").read().strip()


def _write_recipient(fingerprint: str) -> None:
    os.makedirs(vault_dir(), mode=0o700, exist_ok=True)
    path = _recipient_path()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (fingerprint + "\n").encode())
    finally:
        os.close(fd)


def _encrypt(fingerprint: str, payload: bytes, output: str = "") -> None:
    os.makedirs(vault_dir(), mode=0o700, exist_ok=True)
    target = output or _blob_path()
    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
    result = _gpg(["--encrypt", "--recipient", fingerprint, "--output", target], payload)
    if result.returncode != 0:
        detail = _text(result.stderr).strip() or "gpg encrypt failed"
        raise CockpitError(detail or "gpg encrypt failed")
    os.chmod(target, 0o600)


def _decrypt(path: str = "") -> bytes:
    """One sealed file. Nobody asked (a lane's tool call, a cron, a page's poll): a key that would prompt or wait for a
    touch is not used (vault_key.quiet_gate) and gpg never starts a pinentry. A human act may let gpg-agent ask."""
    target = path or _blob_path()
    if not os.path.isfile(target):
        return b"[]"
    from .vault_key import is_human, quiet_gate

    if is_human():
        result = _gpg(["--decrypt", target])
    else:
        quiet_gate()
        result = _gpg(["--pinentry-mode", "error", "--decrypt", target])
    if result.returncode != 0:
        detail = _text(result.stderr).strip() or "gpg decrypt failed"
        raise CockpitError(detail or "gpg decrypt failed")
    if isinstance(result.stdout, str):
        return result.stdout.encode()
    return result.stdout or b""


def key_needs_wrap() -> bool:
    """True when Hermes has a vault.key that is not wrapped to the recipient."""
    if not os.path.isfile(_hermes_key()):
        return False
    if not sealed_to() or not os.path.isfile(_wrapped_key()):
        return True
    return os.path.getmtime(_hermes_key()) > os.path.getmtime(_wrapped_key())


def _wrap_key(fingerprint: str) -> bool:
    if not os.path.isfile(_hermes_key()):
        return False
    payload = open(_hermes_key(), "rb").read()
    _encrypt(fingerprint, payload, _wrapped_key())
    return True


def _entry_paths(scope: str = "") -> list:
    folders = [_entry_dir(scope)] if scope else _entry_dirs()
    paths = []
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        paths.extend(os.path.join(folder, name) for name in sorted(os.listdir(folder)) if name.endswith(".gpg"))
    return paths


def _vault_material() -> bool:
    if os.path.isfile(_hermes_key()) or os.path.isfile(_hermes_enc()) or os.path.isfile(_blob_path()):
        return True
    return bool(_entry_paths())


def needs_seal() -> bool:
    """A key or a vault file exists and the wrap is missing. Doctor and the weekly export refuse to look green."""
    if key_needs_wrap():
        return True
    if sealed_to():
        return False
    if public_fingerprints():
        return True
    return _vault_material()


def _reseal_entries(fingerprint: str) -> None:
    for path in _entry_paths():
        _encrypt(fingerprint, _decrypt(path), path)


def init_vault(fingerprint: str = "") -> str:
    """Record the public key and wrap vault.key. Encrypt does not use the private key."""
    chosen = choose_fingerprint(fingerprint)
    if not chosen:
        return "vault init pending: no GPG public key. cockpit vault init --key <fingerprint>"
    current = sealed_to()
    if current == chosen and os.path.isfile(_blob_path()) and not key_needs_wrap():
        return f"vault already sealed to {chosen}"
    changed = bool(current and current != chosen)
    if changed and os.path.isfile(_blob_path()):
        _encrypt(chosen, _decrypt())
    if changed:
        _reseal_entries(chosen)
    created = not os.path.isfile(_blob_path())
    if created:
        _encrypt(chosen, b"[]")
    _write_recipient(chosen)
    _wrap_key(chosen)
    if created:
        from .scrub import rebuild

        rebuild(
            wrote=True
        )  # the index knows the new vault is empty, so a machine without the private key is not locked
    if changed:
        return f"vault resealed to {chosen}"
    return f"vault sealed to {chosen}"


def entry_records() -> list:
    """Each encrypted login with the file that holds it. A non-dict file stays put and does not shift the next file."""
    found = []
    for path in _entry_paths():
        try:
            data = json.loads(_decrypt(path).decode("utf-8") or "null")
        except json.JSONDecodeError as exc:
            raise CockpitError("vault is unreadable") from exc
        if not isinstance(data, dict) or data.get("deleted"):  # a removed record's tombstone
            continue
        found.append((data, path))
    return found


def _items() -> list:
    if not sealed_to():
        raise CockpitError("vault is not sealed. cockpit vault init --key <fingerprint>")
    paths = _entry_paths()
    if paths:
        return [item for item, _path in entry_records()]
    try:
        data = json.loads(_decrypt().decode("utf-8") or "[]")
    except json.JSONDecodeError as exc:
        raise CockpitError("vault is unreadable") from exc
    if not isinstance(data, list):
        return []
    return data


def _save(items: list) -> None:
    fingerprint = sealed_to()
    if not fingerprint:
        raise CockpitError("vault is not sealed. cockpit vault init --key <fingerprint>")
    _encrypt(fingerprint, json.dumps(items).encode())


def _remember(origin: str, email: str, two_factor: bool = False, lane: str = "") -> None:
    path = _index_path()
    rows = []
    if os.path.isfile(path):
        try:
            loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            rows = [
                row
                for row in loaded
                if isinstance(row, dict) and not (row.get("origin") == origin and row.get("email") == email)
            ]
    rows.append({"origin": origin, "email": email, "two_factor": bool(two_factor), "lane": lane or ""})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(rows).encode())
    finally:
        os.close(fd)


def _forget(origin: str, email: str) -> None:
    """Drop a login from the metadata list, so the seat audit does not put it back."""
    path = _index_path()
    if not os.path.isfile(path):
        return
    try:
        loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
    except json.JSONDecodeError:
        return
    if not isinstance(loaded, list):
        return
    rows = [
        row
        for row in loaded
        if not (isinstance(row, dict) and row.get("origin") == origin and row.get("email") == email)
    ]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(rows).encode())
    finally:
        os.close(fd)


def _custom_scopes() -> bool:
    """The human made a vault of their own (the Vault page): its records are not the lanes' logins."""
    folder = os.path.join(vault_dir(), "scopes")
    built = {_scope_for(False), _scope_for(True)}
    return os.path.isdir(folder) and any(name not in built for name in os.listdir(folder))


def _builtin_items() -> list:
    """Every record of the two vaults the pack names (and the older layouts), never one of a vault the human made."""
    if not _custom_scopes():
        return _items()
    built = {_scope_for(False), _scope_for(True)}
    legacy = os.path.join(vault_dir(), "entries")
    keep = [
        path
        for path in _entry_paths()
        if os.path.dirname(path) == legacy or os.path.basename(os.path.dirname(os.path.dirname(path))) in built
    ]
    if not keep:
        return _items()
    rows = []
    for path in keep:
        data = json.loads(_decrypt(path).decode("utf-8") or "null")
        if isinstance(data, dict) and not data.get("deleted"):
            rows.append(data)
    return rows


def _previous(origin: str, email: str, scope: str = ""):
    """The latest login for this origin and email. A scope keeps the search inside that vault list; without one, the
    vaults the pack names are searched, never one the human made."""
    try:
        found = None
        rows = []
        if scope:
            for path in _entry_paths(scope):
                data = json.loads(_decrypt(path).decode("utf-8") or "null")
                if isinstance(data, dict):
                    rows.append(data)
        else:
            rows = _builtin_items()
        for item in rows:
            if (
                item.get("origin") == origin
                and item.get("email") == email
                and not item.get("lent")
                and not item.get("deleted")
                and (item.get("kind") or "login") == "login"
            ):
                found = item
        return found
    except (CockpitError, json.JSONDecodeError):
        return None


def _bound_pack():
    from .errors import NeedMigrate, PackError
    from .pack import load
    from .paths import pack_path

    try:
        return load(pack_path())
    except (PackError, NeedMigrate, FileNotFoundError):
        return {}


def normalize_otp(value) -> str:
    """Hermes's own parsing: a base32 seed or an otpauth://totp URI, kept as seed|digits|period|algo when not 6/30/SHA1."""
    text = str(value or "").strip()
    if not text:
        return ""
    from .hermes_runtime import run_helper

    result = run_helper("vault", {"ops": [{"op": "normalize_otp", "value": text}]})["results"][0]
    if isinstance(result, dict):
        raise CockpitError(f"vault: {result.get('error')}")
    return result


def store_login(
    origin: str,
    email: str,
    password: str = "",
    org: str = "",
    otp=None,
    privileged: bool = False,
    lane: str = "",
    lent: str = "",
    pack=None,
) -> str:
    """Keep one login in cockpit's encrypted vault (the backup and the human's copy), and place it in the Hermes store
    of its owning lane and of the seats a shared login names. A login no seat owns stays the human's.

    Encryption uses the public key. A missing otp keeps the seed already stored.
    """
    from .fence import refuse_outside

    refuse_outside()
    fingerprint = sealed_to()
    if not fingerprint:
        raise CockpitError("vault is not sealed. cockpit vault init --key <fingerprint>")
    pack = _bound_pack() if pack is None else pack
    from .vault_book import Record, Scope, VaultBook, legacy_id, now

    scope = _scope_for(bool(privileged) and not lent)
    previous = _previous(origin, email, scope)
    seed = normalize_otp(otp) if otp else otp
    if seed is None and previous:
        seed = previous.get("otp") or ""
    if seed is None:
        seed = ""
    book = VaultBook(pack=pack)
    if lent:  # a lent copy is the lend's own file, not a record of the book
        record = Record(
            id=legacy_id(scope, origin, email),
            origin=origin,
            email=email,
            org=org,
            lane=lane,
            lent=lent,
            otp=seed,
            secret=password or str((previous or {}).get("secret") or ""),
            created=now(),
            updated=now(),
        )
        owners = []
        folder = Scope(scope, book.sealer)
        os.makedirs(folder.folder, mode=0o700, exist_ok=True)
        name = folder.next_file()
        _encrypt(fingerprint, json.dumps(record.to_entry()).encode(), os.path.join(folder.folder, name))
        folder.note_file(name)
        from .scrub import rebuild

        rebuild(learned=[value for value in (record.secret, str(record.otp).split("|", 1)[0]) if value], wrote=True)
    else:
        record = Record.from_entry(
            {**(previous or {}), "origin": origin, "email": email, "org": org, "lane": lane}, scope, now()
        )
        record.privileged, record.otp, record.updated = bool(privileged), seed, now()
        if password:
            record.replace_secret(password)
        owners = book.put(scope, record, loaded=previous is not None)
    if not os.path.isfile(_blob_path()):
        _encrypt(fingerprint, b"[]")
    if not owners and not privileged and not lent:
        return "vault stored for the human: no lane owns this login"
    return "vault stored"


def totp(seed: str, moment=None) -> str:
    """RFC 6238 for a stored seed in Hermes's form (seed, or seed|digits|period|algo)."""
    import base64
    import hashlib
    import hmac
    import struct
    import time

    digits, period, algo = 6, 30, "sha1"
    if "|" in seed:
        seed, raw_digits, raw_period, raw_algo = seed.split("|", 3)
        digits, period = int(raw_digits), int(raw_period)
        algo = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}.get(raw_algo.upper(), "sha1")
    padded = seed.upper() + "=" * ((8 - len(seed) % 8) % 8)
    try:
        key = base64.b32decode(padded, casefold=True)
    except Exception:  # noqa: BLE001 - a secret that is no base32 gives no code
        return ""
    counter = int((moment if moment is not None else time.time()) // period)
    digest = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, algo)).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


def current_code(origin: str, email: str, moment=None) -> str:
    """The current authenticator code of a login in cockpit's vault. It is for the login submit only."""
    from .fence import refuse_outside

    refuse_outside()
    item = _previous(origin, email)
    seed = str((item or {}).get("otp") or "")
    if not seed:
        return ""
    return totp(seed, moment)


def scrub_result(text: str) -> str:
    """Remove every stored secret, seed, and current code from a tool result. The index needs no key."""
    from .scrub import scrub

    return scrub(text or "")


def lane_logins(lane: str, origin: str, pack=None) -> list:
    """The logins in this lane's own Hermes store for this origin. Another lane's logins are not there."""
    from .fence import refuse_outside

    refuse_outside()
    from .lane_vault import MARK, _origin_of, items

    rows = []
    for item in items(lane):
        if _origin_of(item.get("origin")) != _origin_of(origin):
            continue
        tag = str(item.get("label") or "")
        kind = tag[len(MARK) :].split(" ", 1)[0] if tag.startswith(MARK) else "own"
        rows.append(
            {
                "origin": origin,
                "email": item.get("identifier") or "",
                "two_factor": bool(item.get("has_otp")),
                "lane": "shared" if kind == "shared" else lane,
                "handle": item.get("id") or "",
                "kind": kind,
            }
        )
    return rows


def fill_login(lane: str, origin: str, email: str, slot: int, pack=None, card: str = "") -> dict:
    """The lane typed the identifier. It fills the password with Hermes's browser_vault and this handle; nothing is
    written beside the slot and no secret is returned."""
    from .fence import refuse_outside

    refuse_outside()
    rows = lane_logins(lane, origin, pack)
    match = next((row for row in rows if row.get("email") == email), None)
    if match is None:
        if pack and card:
            from .acts import fail_login

            return fail_login(pack, card, "no login for this lane")
        raise CockpitError("no login for this lane")
    result = {
        "ok": True,
        "origin": origin,
        "email": email,
        "handle": match["handle"],
        "fill": f"browser_vault action=fill handle={match['handle']}",
    }
    if match.get("two_factor"):
        result["code"] = f"browser_vault action=enter_code handle={match['handle']}"
    return result


def block_text(pack, email: str = "", why: str = "") -> str:
    """The login block. The environment word comes from the pack."""
    environment = str(((pack or {}).get("privileged") or {}).get("environment") or "").strip() or "login"
    parts = ["CREDENTIALS NEEDED", environment]
    if str(email or "").strip():
        parts.append(str(email).strip())
    if str(why or "").strip():
        parts.append(str(why).strip())
    return " · ".join(parts)


def reject_login(pack, card: str, email: str = "") -> dict:
    """The site refused the login. Block the card once. The secret is not returned."""
    from .acts import fail_login

    reason = block_text(pack, email, "login rejected")
    result = fail_login(pack, card, reason)
    return {"ok": bool(result.get("ok")), "blocked": bool(result.get("blocked")), "reason": reason, "card": card}


def logout(slot: int) -> str:
    """Drop a plaintext login an older cockpit left beside the slot. Called before a block that ends the run and before
    complete."""
    from .slots import state_dir

    path = os.path.join(state_dir(int(slot)), "login.json")
    if os.path.isfile(path):
        os.remove(path)
    return "logged out"


def human_secret(origin: str, email: str, pack=None) -> str:
    """The secret for the human page: cockpit's own vault when this machine can open it, else the seat store that
    holds the login (a vault sealed to a key kept elsewhere stays shut here; the seats' stores are local). Callers
    must not write it into a demo file or a tool result."""
    from .fence import refuse_outside

    refuse_outside()
    item = _previous(origin, email)
    if item and item.get("secret"):
        return str(item["secret"])
    if pack is None:
        try:
            from .pack import load
            from .paths import pack_path

            pack = load(pack_path())
        except Exception:  # noqa: BLE001 - no readable pack means no answer
            return ""
    try:
        from .lane_vault import secret_for

        return secret_for(pack, origin, email)
    except CockpitError:
        return ""


def login_metadata(lane: str = "") -> list:
    """With a lane: what that lane's own store holds. Without: every login cockpit keeps for the human."""
    from .fence import refuse_outside

    refuse_outside()
    if lane:
        from .lane_vault import MARK, items

        rows = []
        for item in items(lane):
            tag = str(item.get("label") or "")
            shared = tag.startswith(MARK + "shared ")
            rows.append(
                {
                    "origin": item.get("origin") or "",
                    "email": item.get("identifier") or "",
                    "two_factor": bool(item.get("has_otp")),
                    "lane": "shared" if shared else lane,
                }
            )
        return rows
    path = _index_path()
    if os.path.isfile(path):
        try:
            loaded = json.loads(open(path, encoding="utf-8").read() or "[]")
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            return [
                {
                    "origin": (row.get("origin") or "") if isinstance(row, dict) else "",
                    "email": (row.get("email") or "") if isinstance(row, dict) else "",
                    "two_factor": bool(row.get("two_factor")) if isinstance(row, dict) else False,
                    "lane": (row.get("lane") or "") if isinstance(row, dict) else "",
                }
                for row in loaded
            ]
    visible = [
        item
        for item in _items()
        if not item.get("lent") and not item.get("privileged") and (item.get("kind") or "login") == "login"
    ]
    return [
        {
            "origin": item.get("origin") or "",
            "email": item.get("email") or "",
            "two_factor": bool(item.get("otp")),
            "lane": item.get("lane") or "",
        }
        for item in visible
    ]


def _backup_root() -> str:
    return os.path.join(hermes_home(), "backups", "vault")


_BACKUP_FILES = ("recipient", "vault.key.gpg", "vault.json.enc", "cockpit-vault.json.gpg", "index.json", "scrub.index")

_RESTORE_NOTE = (
    "Restore with: cockpit vault restore\n"
    "vault.key.gpg is the Hermes vault key, encrypted to the fingerprint in recipient; seats/<lane>/ holds each seat's\n"
    "Hermes store and its key, encrypted the same way.\n"
    "vault.json.enc cannot be opened without that key. The plaintext vault.key is not in this backup.\n"
    "Unwrap uses the matching private key. Losing that private key loses this backup.\n"
    "Init and later wraps need only the public key: cockpit vault init --key <fingerprint>\n"
)


def _copy_file(source: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), mode=0o700, exist_ok=True)
    shutil.copy2(source, dest)
    os.chmod(dest, 0o600)


def backup_vault(keep: int = 4) -> str:
    """Copy the wrapped key and the ciphertext into the workspace. Never the plaintext vault.key."""
    fingerprint = sealed_to()
    if fingerprint and key_needs_wrap():
        _wrap_key(fingerprint)
    copied = []
    present = [name for name in _BACKUP_FILES if os.path.isfile(os.path.join(vault_dir(), name))]
    if _entry_paths() or _seat_stores():
        present.append("entries")
    if not present:
        return "vault backup 0"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{time.time_ns()}"
    dest = os.path.join(_backup_root(), stamp)
    os.makedirs(dest, mode=0o700, exist_ok=True)
    for name in _BACKUP_FILES:
        source = os.path.join(vault_dir(), name)
        if os.path.isfile(source):
            _copy_file(source, os.path.join(dest, name))
            copied.append(name)
    if _entry_paths():
        for path in _entry_paths():
            _copy_file(path, os.path.join(dest, os.path.relpath(path, vault_dir())))
        for path in _book_files():
            _copy_file(path, os.path.join(dest, os.path.relpath(path, vault_dir())))
        copied.append("entries")
    if _back_up_seats(fingerprint, dest):
        copied.append("seats")
    note = os.path.join(dest, "RESTORE.txt")
    fd = os.open(note, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, _RESTORE_NOTE.encode())
    finally:
        os.close(fd)
    limit = max(1, int(keep or 1))
    names = sorted(name for name in os.listdir(_backup_root()) if os.path.isdir(os.path.join(_backup_root(), name)))
    while len(names) > limit:
        shutil.rmtree(os.path.join(_backup_root(), names.pop(0)))
    return f"vault backup {len(copied)}"


def _book_files() -> list:
    """The plaintext index of each vault and the audit log: metadata only, they travel with the sealed entries."""
    found = [os.path.join(os.path.dirname(folder), "index.json") for folder in _entry_dirs()]
    found.append(os.path.join(vault_dir(), "audit.log"))
    return [path for path in found if os.path.isfile(path)]


def _seat_stores() -> list:
    """(lane, store folder) for every seat that has a Hermes store."""
    folder = os.path.join(hermes_home(), "profiles")
    if not os.path.isdir(folder):
        return []
    return [
        (name, os.path.join(folder, name, "vault"))
        for name in sorted(os.listdir(folder))
        if os.path.isfile(os.path.join(folder, name, "vault", "vault.json.enc"))
    ]


def _back_up_seats(fingerprint: str, dest: str) -> bool:
    """Each seat's ciphertext, and its key encrypted to the public key. The plaintext key never leaves."""
    stores = _seat_stores()
    for lane, store in stores:
        _copy_file(os.path.join(store, "vault.json.enc"), os.path.join(dest, "seats", lane, "vault.json.enc"))
        key = os.path.join(store, "vault.key")
        if fingerprint and os.path.isfile(key):
            _encrypt(fingerprint, open(key, "rb").read(), os.path.join(dest, "seats", lane, "vault.key.gpg"))
    return bool(stores)


def _restore_seats(source: str) -> bool:
    """Every seat store back in its own profile. Each key unwraps only with the private key; one that cannot stays wrapped."""
    folder = os.path.join(source, "seats")
    unwrapped = True
    if not os.path.isdir(folder):
        return unwrapped
    for lane in sorted(os.listdir(folder)):
        store = os.path.join(hermes_home(), "profiles", lane, "vault")
        _copy_file(os.path.join(folder, lane, "vault.json.enc"), os.path.join(store, "vault.json.enc"))
        wrapped = os.path.join(folder, lane, "vault.key.gpg")
        if not os.path.isfile(wrapped):
            continue
        try:
            payload = _decrypt(wrapped)
        except CockpitError:
            unwrapped = False
            continue
        fd = os.open(os.path.join(store, "vault.key"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
    return unwrapped


def _restore_tree(source: str) -> None:
    os.makedirs(vault_dir(), mode=0o700, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(source):
        if dirpath == source and "seats" in dirnames:
            dirnames.remove("seats")
        for name in filenames:
            if name in ("RESTORE.txt", "vault.key"):
                continue
            src = os.path.join(dirpath, name)
            _copy_file(src, os.path.join(vault_dir(), os.path.relpath(src, source)))


def restore_vault(stamp: str = "") -> str:
    """Put the newest weekly copy back and unwrap vault.key when the private key is on this machine."""
    root = _backup_root()
    if not os.path.isdir(root):
        raise CockpitError("no vault backup")
    names = sorted(name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name)))
    if not names:
        raise CockpitError("no vault backup")
    if stamp and stamp not in names:
        raise CockpitError("no vault backup")
    chosen = stamp or names[-1]
    _restore_tree(os.path.join(root, chosen))
    seats_open = _restore_seats(os.path.join(root, chosen))
    from .scrub import rebuild

    wrapped = _wrapped_key()
    if not os.path.isfile(wrapped):
        rebuild()
        return "vault restored" if seats_open else "vault restore copied; private key required to unwrap the seat keys"
    try:
        payload = _decrypt(wrapped)
    except CockpitError:
        return "vault restore copied; private key required to unwrap vault.key"
    fd = os.open(_hermes_key(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    rebuild()
    return "vault restored"


IMPORT_KEYS = {"scope", "lane", "origin", "email", "label", "identifier_type", "secret", "otp", "org", "privileged"}


def import_logins(text: str, pack=None) -> dict:
    """Neutral JSON lines from an adopter's exporter: each login is placed where it belongs (its lane's seat store, else
    the human's scope). One the seat store already holds is kept as it is. {imported, kept}; no secret is returned."""
    from .fence import refuse_outside

    refuse_outside()
    from .lane_vault import _origin_of, items

    imported = kept = 0
    for number, line in enumerate((text or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise CockpitError(f"vault import line {number} is not JSON") from exc
        if not isinstance(row, dict) or set(row) - IMPORT_KEYS or not row.get("origin") or not row.get("email"):
            raise CockpitError(
                f"vault import line {number}: a login is {{origin, email, secret, lane, otp, org, privileged, ...}}"
            )
        lane = str(row.get("lane") or "")
        if lane and any(
            item.get("identifier") == row["email"] and _origin_of(item.get("origin")) == _origin_of(row["origin"])
            for item in items(lane)
        ):
            kept += 1
            continue
        store_login(
            str(row["origin"]),
            str(row["email"]),
            str(row.get("secret") or ""),
            org=str(row.get("org") or ""),
            otp=row.get("otp") or None,
            privileged=bool(row.get("privileged")),
            lane=lane,
            pack=pack,
        )
        imported += 1
    return {"imported": imported, "kept": kept}
