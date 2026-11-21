# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The human's vault book: vaults (scopes) of records, kept in cockpit's GPG-sealed store.

A vault is a folder under ``~/.hermes/vault/scopes``. A record is one sealed JSON file in it, with an id, a kind
(login, key, note), a title, tags, notes and the last secrets it replaced. Each vault keeps a plaintext ``index.json``
of what a record is (never a value), so the list opens without the private key. Reading a value needs that key.

The classes each own one thing: ``Kind`` what a record may hold, ``Record`` one record, ``GpgSealer`` the keys,
``Scope`` one vault folder, ``SeatSync`` the copies in the seats' Hermes stores, ``VaultAudit`` the log of what was
revealed or changed, ``VaultBook`` the whole book. ``vault.store_login`` writes through ``VaultBook.put``.

The book never prompts for the key (``vault_key``): it reads a file on its own only when the key opens with nobody at
the keyboard, and a human act (Show, Edit, Move, Re-read) may wait for a security key's touch. A record is never
removed from disk: its file becomes a sealed tombstone, so file numbers stay dense for every kernel that reads them.
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import CockpitError

HISTORY_KEEP = 10  # secrets a record remembers
REVEAL_SECONDS = 30  # how long the Desktop shows a revealed value
TAGS_MAX = 20
TEXT_MAX = 100_000


@dataclass(frozen=True)
class Kind:
    """What a record of this kind needs, and what its secret is called."""

    name: str
    label: str
    needs: tuple
    secret_label: str


KINDS = {
    kind.name: kind
    for kind in (
        Kind("login", "Login", ("origin", "email"), "password"),
        Kind("key", "API key", ("title",), "secret"),
        Kind("note", "Secure note", ("title",), "note"),
    )
}


ENTRY_KEYS = {
    "v",
    "id",
    "kind",
    "title",
    "origin",
    "email",
    "org",
    "lane",
    "tags",
    "secret",
    "otp",
    "notes",
    "privileged",
    "lent",
    "created",
    "updated",
    "history",
}
TOMBSTONE = {"v": 2, "deleted": True}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _host(origin: str) -> str:
    parts = urlsplit(str(origin or ""))
    return parts.hostname or str(origin or "")


def legacy_id(scope: str, origin: str, email: str) -> str:
    """A login written before records had ids is told apart by its vault, origin and email."""
    return hashlib.sha1(f"{scope}|{origin}|{email}".encode(), usedforsecurity=False).hexdigest()[:12]


def clean_tags(value) -> list:
    if isinstance(value, str):
        value = value.split(",")
    tags = []
    for raw in value or []:
        tag = re.sub(r"\s+", " ", str(raw or "")).strip()[:32]
        if tag and tag.casefold() not in [t.casefold() for t in tags]:
            tags.append(tag)
    return tags[:TAGS_MAX]


@dataclass
class Record:
    id: str = ""
    kind: str = "login"
    title: str = ""
    origin: str = ""
    email: str = ""
    org: str = ""
    lane: str = ""
    tags: list = field(default_factory=list)
    secret: str = ""
    otp: str = ""
    notes: str = ""
    privileged: bool = False
    lent: str = ""
    created: str = ""
    updated: str = ""
    history: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # keys this kernel does not know (another writer's): kept as they are

    @classmethod
    def from_entry(cls, entry: dict, scope: str, stamp: str = "") -> "Record":
        origin, email = str(entry.get("origin") or ""), str(entry.get("email") or "")
        kind = entry.get("kind") if entry.get("kind") in KINDS else "login"
        return cls(
            id=str(entry.get("id") or legacy_id(scope, origin, email)),
            kind=kind,
            title=str(entry.get("title") or _host(origin) or email),
            origin=origin,
            email=email,
            org=str(entry.get("org") or ""),
            lane=str(entry.get("lane") or ""),
            tags=clean_tags(entry.get("tags")),
            secret=str(entry.get("secret") or ""),
            otp=str(entry.get("otp") or ""),
            notes=str(entry.get("notes") or ""),
            privileged=bool(entry.get("privileged")),
            lent=str(entry.get("lent") or ""),
            created=str(entry.get("created") or stamp),
            updated=str(entry.get("updated") or stamp),
            history=[row for row in entry.get("history") or [] if isinstance(row, dict) and row.get("secret")],
            extra={key: value for key, value in entry.items() if key not in ENTRY_KEYS},
        )

    def to_entry(self) -> dict:
        """The sealed form. The v1 keys stay (origin, email, org, lane, secret, otp, privileged, lent) so everything
        that reads an entry keeps working."""
        entry = {
            **self.extra,
            "v": 2,
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "origin": self.origin,
            "email": self.email,
            "org": self.org,
            "lane": self.lane,
            "created": self.created,
            "updated": self.updated,
        }
        for key in ("tags", "secret", "otp", "notes", "history"):
            if getattr(self, key):
                entry[key] = getattr(self, key)
        entry.pop("privileged", None)
        entry.pop("lent", None)
        if self.privileged:
            entry["privileged"] = True
        if self.lent:
            entry["lent"] = self.lent
        return entry

    def meta(self) -> dict:
        """What the list shows. Never a value."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "origin": self.origin,
            "email": self.email,
            "org": self.org,
            "lane": self.lane,
            "tags": self.tags,
            "privileged": self.privileged,
            "has_secret": bool(self.secret),
            "two_factor": bool(self.otp),
            "has_notes": bool(self.notes),
            "created": self.created,
            "updated": self.updated,
            "history": [{"until": row.get("until") or ""} for row in self.history],
        }

    def fold(self, older: list) -> None:
        """Secrets of files this record supersedes (an older kernel appended a file per change) join the history,
        oldest first, so a rewrite in place loses none."""
        known = {row["secret"] for row in self.history} | {self.secret}
        earlier = []
        for secret, until in older:
            if secret and secret not in known:
                earlier.append({"secret": secret, "until": until})
                known.add(secret)
        self.history = [*earlier, *self.history][-HISTORY_KEEP:]

    def replace_secret(self, new: str) -> None:
        """A different secret pushes the one it replaces onto the history."""
        if new == self.secret:
            return
        if self.secret:
            self.history = [*self.history, {"secret": self.secret, "until": now()}][-HISTORY_KEEP:]
        self.secret = new


class GpgSealer:
    """Cockpit's keys for the book: writing needs the public key; reading goes through VaultKey, which never prompts."""

    def __init__(self, key=None):
        from .vault_key import VaultKey

        self.key = key or VaultKey()

    def fingerprint(self) -> str:
        from . import vault

        return vault.sealed_to()

    def seal(self, payload: bytes, path: str) -> None:
        from . import vault

        fingerprint = self.fingerprint()
        if not fingerprint:
            raise CockpitError("vault is not sealed. cockpit vault init --key <fingerprint>")
        vault._encrypt(fingerprint, payload, path)

    def open(self, path: str) -> bytes:
        return self.key.open(path)

    def state(self) -> dict:
        return self.key.state()

    def quiet(self) -> bool:
        """Opens with nobody at the keyboard: what the book may do on its own."""
        return bool(self.state()["quiet"])

    def check_human(self) -> None:
        """A human act may open a file now: a quiet key, or a security key that may ask for its touch. Else say why."""
        from .vault_key import VaultLocked

        state = self.state()
        if state["quiet"] or state["secret"] == "card":
            return
        if state["needs"] == "passphrase":
            raise VaultLocked("the vault key is locked: unlock it first", "passphrase")
        if state["needs"] == "unsealed":
            raise VaultLocked("the vault is not sealed. cockpit vault init --key <fingerprint>", "unsealed")
        raise VaultLocked("the private key is not on this machine: values stay closed here", "elsewhere")


class Scope:
    """One vault folder: sealed record files and a plaintext index of what they are."""

    def __init__(self, name: str, sealer, builtin: bool = False):
        self.name, self.sealer, self.builtin = name, sealer, builtin

    @property
    def root(self) -> str:
        from .vault import vault_dir

        return os.path.join(vault_dir(), "scopes", self.name)

    @property
    def folder(self) -> str:
        return os.path.join(self.root, "entries")

    @property
    def index_path(self) -> str:
        return os.path.join(self.root, "index.json")

    def files(self) -> list:
        if not os.path.isdir(self.folder):
            return []
        return sorted(name for name in os.listdir(self.folder) if name.endswith(".gpg"))

    def next_file(self) -> str:
        """After the highest number on disk, so a removed record never lets the next one overwrite another."""
        numbers = [int(name[:-4]) for name in self.files() if name[:-4].isdigit()]
        return f"{(max(numbers) + 1) if numbers else 0:04d}.gpg"

    def _document(self) -> dict:
        try:
            data = json.load(open(self.index_path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_document(self, seen: list, rows: list) -> None:
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        fd = os.open(self.index_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps({"seen": sorted(seen), "rows": rows}).encode())
        finally:
            os.close(fd)

    def _read(self, name: str):
        """One entry; None for a tombstone or anything that is not a record."""
        try:
            data = json.loads(self.sealer.open(os.path.join(self.folder, name)).decode("utf-8") or "null")
        except json.JSONDecodeError as exc:
            raise CockpitError("vault is unreadable") from exc
        return data if isinstance(data, dict) and not data.get("deleted") else None

    def _stamp(self, name: str) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(os.path.join(self.folder, name))))

    def reindex(self) -> list:
        """Open every file and write the index again. The caller decides whether the key may be used."""
        grouped, buried = {}, []
        for name in self.files():
            entry = self._read(name)
            if entry is None or entry.get("lent"):
                buried.append(name)
                continue
            record = Record.from_entry(entry, self.name, self._stamp(name))
            row = grouped.setdefault(record.id, {"files": []})
            row.update(record.meta())
            row["files"].append(name)
        rows = list(grouped.values())
        self._save_document(self.files(), rows)
        return rows

    def unread(self) -> int:
        """Files the index has not seen yet (written by another kernel while the key was locked)."""
        return len(set(self.files()) - set(self._document().get("seen") or []))

    def rows(self) -> list:
        """The index rows, each with the files that hold the record. A file the index has not seen is read on its own
        only when the key opens with nobody at the keyboard; otherwise, or if that fails, the saved rows stand and the
        page says how many files wait to be read."""
        document = self._document()
        if (self.unread() or not document) and self.files() and self.sealer.quiet():
            try:
                return self.reindex()
            except CockpitError:
                document = self._document()
        have = set(self.files())
        rows = []
        for row in document.get("rows") or []:
            files = [name for name in row.get("files") or [] if name in have]
            if files:
                rows.append({**row, "files": files})
        return rows

    def row(self, record_id: str):
        return next((row for row in self.rows() if row.get("id") == record_id), None)

    def load(self, row: dict) -> Record:
        """The record the row names: its last file. The caller has checked the key may be used."""
        entry = self._read(row["files"][-1])
        if entry is None:
            raise CockpitError("vault is unreadable")
        return Record.from_entry(entry, self.name)

    def bury(self, names) -> None:
        """A removed record's files become sealed tombstones: the value is gone, the file number stays taken."""
        for name in names:
            self.sealer.seal(json.dumps(TOMBSTONE).encode(), os.path.join(self.folder, name))

    def write(self, record: Record, row=None, loaded: bool = False) -> list:
        """Seal the record. `loaded`: it was built from its stored file, so that file may be rewritten in place; the
        older files of the same login are folded into its history and buried, when they open. Otherwise the record goes
        to a new file that supersedes the old ones (nothing is lost while the key is locked). Returns the index rows."""
        rows = self.rows()
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        old = list((row or {}).get("files") or [])
        target, drop = self.next_file(), []
        if old and loaded and not self.unread():  # a file the index has not seen may be this login's newer one
            target = old[-1]
            try:
                record.fold(
                    [
                        (entry.get("secret") or "", self._stamp(name))
                        for name in old[:-1]
                        for entry in [self._read(name)]
                        if entry
                    ]
                )
                drop = old[:-1]
            except CockpitError:
                drop = []
        self.sealer.seal(json.dumps(record.to_entry()).encode(), os.path.join(self.folder, target))
        self.bury(drop)
        files = [name for name in old if name not in drop and name != target] + [target]
        rows = [r for r in rows if r.get("id") != record.id]
        rows.append({**record.meta(), "files": files})
        self._save_document([*(self._document().get("seen") or []), target], rows)
        return rows

    def note_file(self, name: str) -> None:
        """A file cockpit wrote that is not a listed record (a lent copy): known, so the index is not read again."""
        document = self._document()
        if document:
            self._save_document([*(document.get("seen") or []), name], document.get("rows") or [])

    def remove(self, record_id: str) -> None:
        rows = self.rows()
        gone = next((r for r in rows if r.get("id") == record_id), None)
        if gone is None:
            raise CockpitError("no such record")
        self.bury(gone["files"])
        self._save_document(
            [*(self._document().get("seen") or []), *gone["files"]], [r for r in rows if r.get("id") != record_id]
        )


class SeatSync:
    """Copies of a lane login in the seats' own Hermes stores. Only a login of the login vault is placed."""

    def __init__(self, pack, login_scope: str):
        self.pack, self.login_scope = pack, login_scope

    def placeable(self, scope: str, meta) -> bool:
        get = meta.get if isinstance(meta, dict) else lambda key, default=None: getattr(meta, key, default)
        return scope == self.login_scope and get("kind") == "login" and not get("privileged") and not get("lent")

    def owners(self, scope: str, record) -> list:
        if not self.placeable(scope, record):
            return []
        from .lane_vault import readers

        return [
            *([record.lane] if record.lane else []),
            *[seat for seat in readers(self.pack, record.origin, record.email) if seat != record.lane],
        ]

    def check(self, owners, record) -> None:
        if owners:
            from .lane_vault import check_origin

            check_origin(self.pack, record.origin)

    def place(self, owners, record) -> None:
        from .lane_vault import place

        for owner in owners:
            place(
                owner,
                record.origin,
                record.email,
                record.secret,
                record.otp,
                kind="lane" if owner == record.lane else "shared",
            )

    def placements(self, origin: str, email: str) -> list:
        """(lane, kind, item id) for the copies cockpit placed of this login."""
        from .lane_vault import MARK, _origin_of, items_of, seats

        found = []
        for lane, rows in items_of(seats(self.pack)).items():
            for item in rows:
                tag = str(item.get("label") or "")
                if (
                    not tag.startswith(MARK)
                    or item.get("identifier") != email
                    or _origin_of(item.get("origin")) != _origin_of(origin)
                ):
                    continue
                kind = tag[len(MARK) :].split(" ", 1)[0]
                if kind in ("lane", "shared"):
                    found.append((lane, kind, item.get("id") or ""))
        return found

    def unplace(self, origin: str, email: str) -> None:
        from .lane_vault import remove

        for lane, _kind, item_id in self.placements(origin, email):
            remove(lane, item_id)


class VaultAudit:
    """What was revealed or changed, never the value."""

    def __init__(self, path: str = ""):
        self.path = path

    def _path(self) -> str:
        from .vault import vault_dir

        return self.path or os.path.join(vault_dir(), "audit.log")

    def add(self, act: str, vault: str, record_id: str = "", title: str = "", field_name: str = "") -> None:
        os.makedirs(os.path.dirname(self._path()), mode=0o700, exist_ok=True)
        line = json.dumps(
            {"at": now(), "act": act, "vault": vault, "id": record_id, "title": title, "field": field_name}
        )
        fd = os.open(self._path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (line + "\n").encode())
        finally:
            os.close(fd)

    def tail(self, count: int = 20, record_id: str = "", vault: str = "") -> list:
        if not os.path.isfile(self._path()):
            return []
        rows = []
        for line in open(self._path(), encoding="utf-8").read().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (not record_id or row.get("id") == record_id) and (not vault or row.get("vault") == vault):
                rows.append(row)
        return rows[-count:][::-1]


class VaultBook:
    """Vaults and their records. Every public method keeps editor sessions outside the lanes out."""

    def __init__(self, pack=None, sealer=None, audit=None):
        self._pack, self.sealer, self.audit = pack, sealer or GpgSealer(), audit or VaultAudit()

    @property
    def pack(self):
        if self._pack is None:
            from .vault import _bound_pack

            self._pack = _bound_pack()
        return self._pack

    # --- vaults

    def builtin(self) -> dict:
        """The two vaults the pack names: the lane logins, and the human's own."""
        from .vault import _scope_for

        return {"login": _scope_for(False), "privileged": _scope_for(True)}

    def scope(self, name: str) -> Scope:
        from .vault import _safe_scope

        chosen = _safe_scope(name)
        if not os.path.isdir(Scope(chosen, self.sealer).root) and chosen not in self.builtin().values():
            raise CockpitError(f"no vault {name}")
        return Scope(chosen, self.sealer, chosen in self.builtin().values())

    def vaults(self) -> list:
        from .fence import refuse_outside
        from .vault import vault_dir

        refuse_outside()
        built = self.builtin()
        folder = os.path.join(vault_dir(), "scopes")
        names = sorted({*built.values(), *(os.listdir(folder) if os.path.isdir(folder) else [])})
        found = []
        for name in names:
            scope = Scope(name, self.sealer, name in built.values())
            title = "Lane logins" if name == built["login"] else "Human only" if name == built["privileged"] else name
            found.append(
                {
                    "name": name,
                    "title": title,
                    "builtin": scope.builtin,
                    "count": len(scope.rows()),
                    "placed": name == built["login"],
                }
            )
        return found

    def state(self) -> dict:
        """What the page needs besides the vaults: the key, and whether a value can be opened now."""
        from .fence import refuse_outside

        refuse_outside()
        key = self.sealer.state()
        reasons = {
            "unsealed": "the vault is not sealed. cockpit vault init --key <fingerprint>",
            "elsewhere": "the private key is not on this machine: values stay closed here",
            "passphrase": "the vault key is locked: unlock it with its passphrase",
            "card": "the vault key is on a security key: Show may ask for its PIN (Unlock) and a touch",
        }
        opens = key["quiet"] or key["secret"] == "card"
        ttl = self.sealer.key.ttl() if key["protected"] or key["secret"] == "card" else {}
        return {
            "sealed": key["sealed"],
            "locked": not opens,
            "reason": reasons.get(key["needs"], ""),
            "reveal_seconds": REVEAL_SECONDS,
            "key": {k: key[k] for k in ("secret", "protected", "cached", "quiet", "needs")} | {"ttl": ttl},
            "legacy": self._legacy_pending(),
            "kinds": [{"name": k.name, "label": k.label, "secret_label": k.secret_label} for k in KINDS.values()],
        }

    def unlock(self, secret: str) -> str:
        """The human's passphrase or PIN, handed to gpg once; gpg-agent caches it under its own times."""
        from .fence import refuse_outside

        refuse_outside()
        result = self.sealer.key.unlock(secret)
        self.audit.add("unlock", "")
        return result

    def lock(self) -> str:
        from .fence import refuse_outside

        refuse_outside()
        result = self.sealer.key.lock()
        self.audit.add("lock", "")
        return result

    def _legacy_pending(self) -> bool:
        """Logins still in the older single-file store: the metadata list names them, and no vault has a file yet."""
        from .vault import _blob_path, _entry_paths, _index_path

        if _entry_paths() or not os.path.isfile(_blob_path()) or not os.path.isfile(_index_path()):
            return False
        try:
            return bool(json.load(open(_index_path(), encoding="utf-8")))
        except ValueError:
            return False

    def _writable(self) -> None:
        if self._legacy_pending():
            raise CockpitError(
                "the logins are still in the older single-file store: Re-read the vault first (cockpit vault reindex)"
            )

    def create_vault(self, name: str) -> str:
        from .fence import refuse_outside
        from .vault import _safe_scope

        refuse_outside()
        text = str(name or "").strip()
        chosen = _safe_scope(text)
        if not text or chosen != text:
            raise CockpitError("a vault name is letters, digits, - and _")
        scope = Scope(chosen, self.sealer)
        if os.path.isdir(scope.root) or chosen in self.builtin().values():
            raise CockpitError(f"vault {chosen} exists")
        os.makedirs(scope.folder, mode=0o700)
        self.audit.add("vault-create", chosen)
        return f"vault {chosen} created"

    def rename_vault(self, name: str, to: str) -> str:
        from .fence import refuse_outside
        from .vault import _safe_scope

        refuse_outside()
        scope = self._custom(name)
        target = Scope(_safe_scope(str(to or "").strip()), self.sealer)
        if not str(to or "").strip() or target.name != str(to).strip():
            raise CockpitError("a vault name is letters, digits, - and _")
        if os.path.isdir(target.root) or target.name in self.builtin().values():
            raise CockpitError(f"vault {target.name} exists")
        os.rename(scope.root, target.root)
        self.audit.add("vault-rename", target.name, title=scope.name)
        return f"vault {scope.name} renamed to {target.name}"

    def delete_vault(self, name: str, force: bool = False) -> str:
        from .fence import refuse_outside

        refuse_outside()
        scope = self._custom(name)
        if scope.rows() and not force:  # tombstones are not records
            raise CockpitError(f"vault {scope.name} holds records; delete them first")
        shutil.rmtree(scope.root)
        self.audit.add("vault-delete", scope.name)
        return f"vault {scope.name} deleted"

    def _custom(self, name: str) -> Scope:
        scope = self.scope(name)
        if scope.builtin:
            raise CockpitError(f"vault {scope.name} is built in")
        return scope

    # --- records

    def records(self, vault: str, query: str = "", kind: str = "", tag: str = "") -> dict:
        from .fence import refuse_outside

        refuse_outside()
        rows = [{k: v for k, v in row.items() if k != "files"} for row in self.scope(vault).rows()]
        tags = sorted({t for row in rows for t in row.get("tags") or []}, key=str.casefold)
        needle = str(query or "").casefold()
        rows = [
            row
            for row in rows
            if (not kind or row.get("kind") == kind)
            and (not tag or tag in (row.get("tags") or []))
            and (
                not needle
                or needle
                in " ".join(
                    [row.get("title") or "", row.get("origin") or "", row.get("email") or "", *(row.get("tags") or [])]
                ).casefold()
            )
        ]
        return {
            "records": sorted(rows, key=lambda row: (row.get("title") or "").casefold()),
            "tags": tags,
            "unread": self.scope(vault).unread(),
        }

    def record(self, vault: str, record_id: str) -> dict:
        from .fence import refuse_outside

        refuse_outside()
        scope = self.scope(vault)
        row = scope.row(record_id)
        if row is None:
            raise CockpitError("no such record")
        meta = {k: v for k, v in row.items() if k != "files"}
        sync = SeatSync(self.pack, self.builtin()["login"])
        seats = []
        if sync.placeable(scope.name, meta):
            try:
                seats = [
                    {"lane": lane, "kind": kind} for lane, kind, _ in sync.placements(meta["origin"], meta["email"])
                ]
            except CockpitError:
                seats = []
        return {"record": meta, "seats": seats, "audit": self.audit.tail(10, record_id, scope.name)}

    def put(self, vault: str, record: Record, previous=None, learned=(), loaded: bool = False) -> list:
        """The one write: seal the record, keep the root index and the seat copies in step, teach the scrub index.
        `previous` is the record this one replaces (its identity may have changed); `loaded`: the record was built from
        its stored file, which may then be rewritten in place. Returns the lanes it was placed on."""
        from .fence import refuse_outside
        from .vault import _forget, _remember

        refuse_outside()
        scope = Scope(vault, self.sealer)
        sync = SeatSync(self.pack, self.builtin()["login"])
        owners = sync.owners(vault, record)
        sync.check(owners, record)
        row = scope.row(record.id)
        scope.write(record, row, loaded)
        if sync.placeable(vault, record):
            if previous and (previous.origin, previous.email) != (record.origin, record.email):
                _forget(previous.origin, previous.email)
                sync.unplace(previous.origin, previous.email)
            _remember(record.origin, record.email, bool(record.otp), record.lane)
        sync.place(owners, record)
        from .scrub import rebuild

        rebuild(
            learned=[value for value in (record.secret, str(record.otp).split("|", 1)[0], *learned) if value],
            wrote=True,
        )
        return owners

    def save(self, vault: str, fields: dict) -> dict:
        """Create a record, or change the one `fields["id"]` names. A secret, seed or notes left out keeps what is stored."""
        from .fence import refuse_outside
        from .vault import normalize_otp

        refuse_outside()
        self._writable()
        scope = self.scope(vault)
        kind = str(fields.get("kind") or "login")
        if kind not in KINDS:
            raise CockpitError(f"a record is one of: {', '.join(KINDS)}")
        row = scope.row(str(fields["id"])) if fields.get("id") else None
        if fields.get("id") and row is None:
            raise CockpitError("no such record")
        if row:
            self.sealer.check_human()
        previous = scope.load(row) if row else None
        if previous and previous.kind != kind:
            raise CockpitError("a record keeps its kind")
        record = Record(
            **{**(previous.__dict__ if previous else {}), "history": list(previous.history) if previous else []}
        )
        if not previous:
            record.id, record.kind, record.created = secrets.token_hex(6), kind, now()
        for key in ("title", "origin", "email", "org", "lane"):
            if key in fields:
                setattr(record, key, str(fields.get(key) or "").strip())
        if "tags" in fields:
            record.tags = clean_tags(fields.get("tags"))
        for key in ("notes", "secret", "otp"):
            if len(str(fields.get(key) or "")) > TEXT_MAX:
                raise CockpitError(f"{key} is too long")
        if "notes" in fields and fields.get("notes") is not None:
            record.notes = str(fields["notes"])
        if fields.get("secret"):
            record.replace_secret(str(fields["secret"]))
        if fields.get("otp"):
            record.otp = normalize_otp(fields["otp"])
        elif fields.get("clear_otp"):
            record.otp = ""
        if kind == "login":
            from .lane_vault import _origin_of

            if not _origin_of(record.origin):
                raise CockpitError("a login needs an origin such as https://app.example.com")
            record.title = record.title or _host(record.origin)
        for need in KINDS[kind].needs:
            if not getattr(record, need):
                raise CockpitError(f"a {kind} needs its {need}")
        if kind != "login":
            record.origin = record.origin if kind == "key" else ""
            record.email, record.lane, record.otp = "", "", ""
        if kind == "note" and not record.secret and not record.notes:
            raise CockpitError("a note needs its text")
        if kind == "login" and any(
            r.get("id") != record.id
            and r.get("kind") == "login"
            and r.get("origin") == record.origin
            and r.get("email") == record.email
            for r in scope.rows()
        ):
            raise CockpitError("this vault already holds that login")
        record.privileged = kind == "login" and scope.name == self.builtin()["privileged"]  # only a login is ever lent
        record.updated = now()
        self.put(scope.name, record, previous, loaded=bool(previous))
        self.audit.add("save" if previous else "create", scope.name, record.id, record.title)
        return {"id": record.id, "out": f"{record.title} saved"}

    def delete(self, vault: str, record_id: str) -> str:
        from .fence import refuse_outside
        from .vault import _forget

        refuse_outside()
        self._writable()
        scope = self.scope(vault)
        row = scope.row(record_id)
        if row is None:
            raise CockpitError("no such record")
        sync = SeatSync(self.pack, self.builtin()["login"])
        if sync.placeable(scope.name, row):
            sync.unplace(row["origin"], row["email"])
            _forget(row["origin"], row["email"])
        scope.remove(record_id)
        from .scrub import rebuild

        rebuild(wrote=True)
        self.audit.add("delete", scope.name, record_id, row.get("title") or "")
        return f"{row.get('title') or 'record'} deleted"

    def remove_login(self, origin: str, email: str) -> str:
        """The command line's delete: a lane login by its origin and email."""
        vault = self.builtin()["login"]
        for row in self.scope(vault).rows():
            if row.get("origin") == origin and row.get("email") == email:
                return self.delete(vault, row["id"])
        raise CockpitError("no such login")

    def reindex(self) -> str:
        """Read every vault again and write its index; first move logins still in the older single-file store into the
        vaults (what every kernel reads once a vault has a file). A human act: a security key may ask for its touch."""
        from .fence import refuse_outside

        refuse_outside()
        self.sealer.check_human()
        moved = self._migrate_blob() if self._legacy_pending() else 0
        total = sum(len(Scope(row["name"], self.sealer).reindex()) for row in self.vaults())
        self.audit.add("reindex", "")
        return f"vault index: {total} records" + (f" ({moved} moved from the older single-file store)" if moved else "")

    def _migrate_blob(self) -> int:
        """Each login of cockpit-vault.json.gpg into its own file, in the vault it belongs to, in the blob's order (the
        last one still wins). The blob stays as it was: older kernels ignore it as soon as a vault has a file."""
        from .vault import _blob_path

        try:
            items = json.loads(self.sealer.open(_blob_path()).decode("utf-8") or "[]")
        except json.JSONDecodeError as exc:
            raise CockpitError("vault is unreadable") from exc
        built = self.builtin()
        moved = 0
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            scope = Scope(
                built["privileged"] if item.get("privileged") and not item.get("lent") else built["login"], self.sealer
            )
            os.makedirs(scope.folder, mode=0o700, exist_ok=True)
            self.sealer.seal(json.dumps(item).encode(), os.path.join(scope.folder, scope.next_file()))
            moved += 1
        return moved

    def move(self, vault: str, record_id: str, to: str) -> str:
        from .fence import refuse_outside

        refuse_outside()
        self._writable()
        source, target = self.scope(vault), self.scope(to)
        if source.name == target.name:
            raise CockpitError("it is already in that vault")
        row = source.row(record_id)
        if row is None:
            raise CockpitError("no such record")
        self.sealer.check_human()
        record = source.load(row)
        if record.kind == "login" and any(
            r.get("origin") == record.origin and r.get("email") == record.email for r in target.rows()
        ):
            raise CockpitError("that vault already holds this login")
        record.privileged = record.kind == "login" and target.name == self.builtin()["privileged"]
        if record.kind == "login" and target.name != self.builtin()["login"]:
            record.lane = ""
        self.put(target.name, record)
        sync = SeatSync(self.pack, self.builtin()["login"])
        if sync.placeable(source.name, row) and not sync.placeable(target.name, record):
            sync.unplace(row["origin"], row["email"])
            from .vault import _forget

            _forget(row["origin"], row["email"])
        source.remove(record_id)
        self.audit.add("move", target.name, record_id, record.title, source.name)
        return f"{record.title} moved to {target.name}"

    def reveal(self, vault: str, record_id: str, field_name: str, index=None) -> dict:
        """One value of one record, to the human who asked. The audit names the field, never the value."""
        from .fence import refuse_outside

        refuse_outside()
        if field_name not in ("secret", "otp", "notes", "code", "history"):
            raise CockpitError("reveal secret, otp, notes, code or history")
        scope = self.scope(vault)
        row = scope.row(record_id)
        if row is None:
            raise CockpitError("no such record")
        self.sealer.check_human()
        record = scope.load(row)
        result = {"ok": True, "out": f"{record.title} {field_name} shown", "expires_in": REVEAL_SECONDS}
        if field_name == "history":
            try:
                value = record.history[int(index)]["secret"]
            except (TypeError, ValueError, IndexError) as exc:
                raise CockpitError("no such history entry") from exc
        elif field_name == "code":
            from .vault import totp

            if not record.otp:
                raise CockpitError("this record has no authenticator seed")
            value = totp(record.otp)
            period = int(record.otp.split("|")[2]) if "|" in record.otp else 30
            result["expires_in"] = period - int(time.time()) % period
        else:
            value = {"secret": record.secret, "otp": record.otp, "notes": record.notes}[field_name]
        self.audit.add(f"reveal-{field_name}", scope.name, record.id, record.title, field_name)
        result["value"] = value
        return result
