# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hermes 0.22.2's vault store API (agent/vault_store.py), for tests: the same shapes and rules, stdlib only.

The real store encrypts with a Fernet key; this one keeps a base64 body beside a key file, so tests can run without
the cryptography package. Contract: tests/contract/hermes-vault.json.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

VAULT_KINDS = ("login", "payment", "address")
LOGIN_IDENTIFIER_TYPES = ("email", "phone", "username")
_OTP_ALGOS = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


class VaultError(Exception):
    pass


def normalize_otp_secret(value):
    value = (value or "").strip()
    if not value:
        return ""
    digits, period, algo = 6, 30, "SHA1"
    if value.lower().startswith("otpauth://"):
        parsed = urlparse(value)
        if parsed.netloc.lower() != "totp":
            raise VaultError("only otpauth://totp links are supported (counter-based HOTP is not)")
        qs = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
        value = qs.get("secret", "")
        try:
            digits = int(qs.get("digits", digits))
            period = int(qs.get("period", period))
        except ValueError:
            raise VaultError("otpauth:// digits/period must be integers")  # noqa: B904 - the stand-in raises as the recorded source does
        algo = qs.get("algorithm", algo).upper().replace("-", "")
        if digits not in (6, 7, 8) or period <= 0 or algo not in _OTP_ALGOS:
            raise VaultError("unsupported otpauth:// parameters (digits 6-8, period > 0, SHA1/SHA256/SHA512)")
    seed = re.sub(r"[\s-]", "", value).upper().rstrip("=")
    if not seed or re.search(r"[^A-Z2-7]", seed):
        raise VaultError("authenticator key must be a base32 secret or an otpauth:// URI")
    if (digits, period, algo) == (6, 30, "SHA1"):
        return seed
    return f"{seed}|{digits}|{period}|{algo}"


def totp_now(seed, *, digits=6, period=30, at=None):
    algo = "sha1"
    if "|" in seed:
        seed, d, p, a = seed.split("|", 3)
        digits, period, algo = int(d), int(p), _OTP_ALGOS.get(a.upper(), "sha1")
    key = base64.b32decode(seed + "=" * (-len(seed) % 8), casefold=True)
    counter = int((at if at is not None else time.time()) // period)
    digest = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, algo)).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def normalize_origin(url_or_origin):
    value = (url_or_origin or "").strip()
    if not value:
        raise VaultError("origin is required")
    if "://" not in value:
        raise VaultError(f"origin must include a scheme (got {value!r})")
    parts = urlsplit(value)
    scheme, host = (parts.scheme or "").lower(), (parts.hostname or "").lower()
    if not scheme or not host:
        raise VaultError(f"could not parse origin from {value!r}")
    port = parts.port
    if port is None or port == _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


@dataclass(frozen=True)
class VaultItemMeta:
    id: str
    kind: str
    label: str
    origin: object
    created_at: str
    identifier_type: object = None
    identifier: object = None
    has_otp: bool = False

    def to_dict(self):
        out = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "origin": self.origin,
            "created_at": self.created_at,
        }
        if self.identifier is not None:
            out["identifier"] = self.identifier
            out["identifier_type"] = self.identifier_type
        if self.has_otp:
            out["has_otp"] = True
        return out


class VaultStore:
    def __init__(self, base_dir=None):
        self._base = Path(base_dir) if base_dir is not None else Path(os.environ["HERMES_HOME"]) / "vault"
        self._vault_path = self._base / "vault.json.enc"
        self._key_path = self._base / "vault.key"

    def _ensure(self):
        self._base.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self._key_path.exists():
            fd = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, base64.urlsafe_b64encode(secrets.token_bytes(32)))
            os.close(fd)

    def _read_all(self):
        if not self._vault_path.exists():
            return []
        data = json.loads(base64.b64decode(self._vault_path.read_bytes()).decode("utf-8"))
        return data.get("items", [])

    def _write_all(self, items):
        self._ensure()
        blob = base64.b64encode(json.dumps({"version": 1, "items": items}).encode("utf-8"))
        fd = os.open(self._vault_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, blob)
        os.close(fd)

    def add_item(self, kind, label, secret, origin=None):
        if kind not in VAULT_KINDS:
            raise VaultError(f"unknown vault kind {kind!r} (expected one of {VAULT_KINDS})")
        label = (label or "").strip()
        if not label:
            raise VaultError("label is required")
        secret = dict(secret)
        if not origin:
            raise VaultError("origin is required for login items")
        norm_origin = normalize_origin(origin)
        id_type = secret.pop("identifier_type", None)
        if id_type not in LOGIN_IDENTIFIER_TYPES:
            raise VaultError(f"identifier_type must be one of {LOGIN_IDENTIFIER_TYPES}")
        identifier = str(secret.pop("identifier", "") or "").strip()
        if not identifier or not secret.get("password"):
            raise VaultError("login items require identifier and password")
        otp_secret = normalize_otp_secret(str(secret.get("otp_secret") or ""))
        secret = {"password": secret["password"], **({"otp_secret": otp_secret} if otp_secret else {})}
        record = {
            "id": f"vault_{uuid.uuid4().hex[:12]}",
            "kind": kind,
            "label": label,
            "origin": norm_origin,
            "created_at": datetime.now(UTC).isoformat(),
            "identifier_type": str(id_type),
            "identifier": identifier,
            "secret": secret,
        }
        items = self._read_all()
        items.append(record)
        self._write_all(items)
        return self._meta(record)

    def list_items(self):
        return [self._meta(rec) for rec in self._read_all()]

    def remove_item(self, item_id):
        items = self._read_all()
        remaining = [rec for rec in items if rec.get("id") != item_id]
        if len(remaining) == len(items):
            return False
        self._write_all(remaining)
        return True

    def resolve_secret(self, item_id):
        for rec in self._read_all():
            if rec.get("id") == item_id:
                return dict(rec.get("secret") or {})
        raise VaultError(f"no vault item with id {item_id!r}")

    @staticmethod
    def _meta(rec):
        identifier = rec.get("identifier")
        return VaultItemMeta(
            id=rec["id"],
            kind=rec["kind"],
            label=rec["label"],
            origin=rec.get("origin"),
            created_at=rec.get("created_at", ""),
            identifier_type=rec.get("identifier_type") if identifier else None,
            identifier=identifier or None,
            has_otp=bool((rec.get("secret") or {}).get("otp_secret")),
        )
