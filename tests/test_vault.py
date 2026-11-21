# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The vault wraps to a local GPG public key and round-trips."""

import os
import subprocess

import pytest

from cockpitlib.cli import main
from cockpitlib.errors import CockpitError
from cockpitlib.ops import vault_put
from cockpitlib.pack import load
from cockpitlib.vault import choose_fingerprint, init_vault, login_metadata, sealed_to

_KEYRINGS = {}  # script text -> a GPG home holding the key it makes, generated once in this process


def keyring(gnupg: str, script_text: str, *options) -> None:
    """The key script_text describes, in the GPG home gnupg. Generating an RSA key takes seconds, so each distinct
    script runs once a worker, in a home of its own, and a test gets a copy of that keyring (never its sockets)."""
    import atexit
    import shutil
    import tempfile

    made = _KEYRINGS.get(script_text)
    if made is None:
        made = tempfile.mkdtemp(
            prefix="k", dir=os.environ.get("PYTEST_DEBUG_TEMPROOT") or None
        )  # short: an agent socket lives in it
        os.chmod(made, 0o700)
        script = os.path.join(made, "gen")
        open(script, "w", encoding="utf-8").write(script_text)
        subprocess.run(
            ["gpg", "--homedir", made, "--batch", *options, "--gen-key", script], check=True, capture_output=True
        )
        subprocess.run(["gpgconf", "--homedir", made, "--kill", "gpg-agent"], capture_output=True, check=False)
        os.remove(script)
        atexit.register(shutil.rmtree, made, True)
        _KEYRINGS[script_text] = made
    for name in os.listdir(made):
        source, target = os.path.join(made, name), os.path.join(gnupg, name)
        if name.startswith("S.") or name.endswith(".lock") or os.path.exists(target):
            continue
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def seal_ephemeral(monkeypatch, home) -> str:
    gnupg = os.path.join(home, "gnupg")
    os.makedirs(gnupg, mode=0o700, exist_ok=True)
    monkeypatch.setenv("GNUPGHOME", gnupg)
    keyring(
        gnupg,
        "%no-protection\nKey-Type: RSA\nKey-Length: 2048\nCreation-Date: 20200101T000000\nSubkey-Type: RSA\n"
        "Subkey-Length: 2048\nName-Real: Cockpit Test\nName-Email: cockpit@example.test\n"
        "Expire-Date: 0\n%commit\n",
    )
    message = init_vault()
    assert message.startswith("vault sealed")
    return sealed_to()


def test_vault_round_trip_and_pending(env, monkeypatch):
    assert init_vault().startswith("vault init pending")
    assert main(["vault", "init"]) == 1
    fingerprint = seal_ephemeral(monkeypatch, str(env["home"]))
    from cockpitlib import vault as vault_mod

    assert vault_mod._items() == []
    vault_mod._save([{"origin": "https://kept.example", "email": "kept@example.test"}])
    assert init_vault() == f"vault already sealed to {fingerprint}"
    pack = load(os.environ["COCKPIT_PACK"])
    assert "secret" not in vault_put(pack, "https://app.example.test", "qa@example.test", "s3cret")
    assert login_metadata() == [
        {"origin": "https://app.example.test", "email": "qa@example.test", "two_factor": False, "lane": ""}
    ]
    from cockpitlib.vault import _items

    assert _items()[-1]["secret"] == "s3cret"
    assert main(["vault", "list"]) == 0
    with pytest.raises(CockpitError, match="no local GPG public key"):
        choose_fingerprint("DEADBEEF")
    from cockpitlib.vault import _decrypt, _full, _gpg, _items, _text

    assert _full("nope", ["AAAA"]) == ""
    assert _text(None) == "" and _text(b"ok") == "ok"
    assert choose_fingerprint(fingerprint[-8:]) == fingerprint
    short = fingerprint[-8:]
    assert main(["vault"]) == 2
    assert main(["vault", "nope"]) == 2
    assert main(["vault", "put"]) == 2
    assert main(["vault", "init", "--key", short]) == 0
    script = os.path.join(os.environ["GNUPGHOME"], "gen2")
    open(script, "w", encoding="utf-8").write(
        "%no-protection\nKey-Type: RSA\nKey-Length: 2048\nCreation-Date: 20200101T000000\nName-Real: Other\n"
        "Name-Email: other@example.test\nExpire-Date: 0\n%commit\n"
    )
    subprocess.run(["gpg", "--batch", "--gen-key", script], check=True, capture_output=True)
    with pytest.raises(CockpitError, match="several GPG public keys"):
        init_vault()
    from cockpitlib.vault import public_fingerprints

    other = [item for item in public_fingerprints() if item != fingerprint][0]
    assert init_vault(other).startswith("vault resealed")
    assert _items()[-1]["secret"] == "s3cret"
    blob = os.path.join(str(env["home"]), "vault", "cockpit-vault.json.gpg")
    os.remove(blob)
    assert _decrypt() == b"[]"
    from cockpitlib import vault as vault_mod

    entry = vault_mod._entry_paths()[0]
    open(entry, "wb").write(b"not-gpg")
    with pytest.raises(CockpitError):
        _items()
    from cockpitlib.doctor import run as doctor_run

    os.remove(os.path.join(str(env["home"]), "vault", "recipient"))
    assert "vault key not sealed" in doctor_run(pack)
    assert _gpg is not None


def test_vault_edges(env, monkeypatch):
    from cockpitlib import vault

    class Listed:
        returncode = 0
        stdout = "\nsec:\nfpr:::::::::ABCD:\nssb:\n"
        stderr = b""

    listed = Listed()
    monkeypatch.setattr(vault, "_gpg", lambda *_a, **_k: listed)
    assert vault._fingerprints("sec", "ssb", ["--list-secret-keys"]) == ["ABCD"]
    listed.stdout = "\npub:\nfpr:::::::::ABCD:\nsub:\n"
    assert vault.public_fingerprints() == ["ABCD"]
    monkeypatch.setattr(vault, "public_fingerprints", lambda: ["ABCD"])

    def boom(*_a, **_k):
        raise OSError("no git")

    monkeypatch.setattr(vault.subprocess, "run", boom)
    assert vault.choose_fingerprint() == "ABCD"
    monkeypatch.setattr(
        vault.subprocess, "run", lambda *_a, **_k: type("R", (), {"stdout": "abcd\n", "returncode": 0})()
    )
    assert vault.choose_fingerprint() == "ABCD"
    monkeypatch.setattr(vault, "public_fingerprints", lambda: ["AAAA", "BBBB"])
    with pytest.raises(CockpitError, match="several"):
        vault.choose_fingerprint()

    class Bad:
        returncode = 1
        stdout = b""
        stderr = b""

    monkeypatch.setattr(vault, "_gpg", lambda *_a, **_k: Bad())
    with pytest.raises(CockpitError, match="gpg encrypt failed"):
        vault._encrypt("ABCD", b"[]")

    class Words:
        returncode = 0
        stdout = "[]"
        stderr = ""

    monkeypatch.setattr(vault.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(vault, "_gpg", lambda *_a, **_k: Words())
    assert vault._decrypt() == b"[]"

    class NotList:
        returncode = 0
        stdout = b'"text"'
        stderr = b""

    monkeypatch.setattr(vault, "sealed_to", lambda: "ABCD")
    monkeypatch.setattr(vault, "_gpg", lambda *_a, **_k: NotList())
    assert vault._items() == []

    class Broken:
        returncode = 0
        stdout = b"{"
        stderr = b""

    monkeypatch.setattr(vault, "_gpg", lambda *_a, **_k: Broken())
    with pytest.raises(CockpitError, match="unreadable"):
        vault._items()
    monkeypatch.setattr(vault, "sealed_to", lambda: "")
    with pytest.raises(CockpitError, match="not sealed"):
        vault._save([])
    with pytest.raises(CockpitError, match="not sealed"):
        vault._items()
    monkeypatch.setattr(vault, "sealed_to", lambda: "ABCD")
    monkeypatch.setattr(vault, "_entry_paths", lambda: ["entry.gpg"])
    monkeypatch.setattr(vault, "_decrypt", lambda path="": b"{")
    with pytest.raises(CockpitError, match="unreadable"):
        vault._items()
    monkeypatch.setattr(vault, "_decrypt", lambda path="": b"1")
    assert vault._items() == []


def test_vault_backup_restore_and_public_wrap(env, monkeypatch):
    from cockpitlib import vault
    from cockpitlib.ops import export_keep
    from cockpitlib.vault import _fingerprints, backup_vault, needs_seal, public_fingerprints, restore_vault

    assert backup_vault() == "vault backup 0"
    fingerprint = seal_ephemeral(monkeypatch, str(env["home"]))
    secret_home = os.environ["GNUPGHOME"]
    exported = subprocess.run(["gpg", "--export", "--armor", fingerprint], check=True, capture_output=True)
    pubonly = os.path.join(str(env["home"]), "pubonly")
    os.makedirs(pubonly, mode=0o700)
    monkeypatch.setenv("GNUPGHOME", pubonly)
    subprocess.run(["gpg", "--batch", "--import"], input=exported.stdout, check=True, capture_output=True)
    assert _fingerprints("sec", "ssb", ["--list-secret-keys"]) == []
    assert fingerprint in public_fingerprints()
    key = os.path.join(str(env["home"]), "vault", "vault.key")
    open(key, "wb").write(b"local-fernet-key")
    os.chmod(key, 0o600)
    assert init_vault().startswith("vault sealed")
    wrapped = os.path.join(str(env["home"]), "vault", "vault.key.gpg")
    assert os.path.isfile(wrapped)
    with pytest.raises(CockpitError):
        vault._decrypt(wrapped)
    monkeypatch.setenv("GNUPGHOME", secret_home)
    assert vault._decrypt(wrapped) == b"local-fernet-key"
    from cockpitlib.ops import vault_put

    pack = load(os.environ["COCKPIT_PACK"])
    assert vault_put(pack, "https://app.example.test", "qa@example.test", "s3cret").startswith("vault stored")
    assert export_keep(pack, 1) == "export"
    assert backup_vault(1).startswith("vault backup")
    root = os.path.join(str(env["home"]), "backups", "vault")
    stamps = [name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))]
    assert len(stamps) == 1
    for dirpath, _dirs, files in os.walk(root):
        assert "vault.key" not in files
        if "RESTORE.txt" in files:
            assert "private key" in open(os.path.join(dirpath, "RESTORE.txt"), encoding="utf-8").read()
    os.remove(key)
    assert main(["vault", "restore"]) == 0
    assert open(key, "rb").read() == b"local-fernet-key"
    with pytest.raises(CockpitError, match="no vault backup"):
        restore_vault("missing")
    os.remove(wrapped)
    assert needs_seal()
    assert backup_vault(1).startswith("vault backup")
    monkeypatch.setenv("GNUPGHOME", pubonly)
    os.remove(key)
    assert "private key required" in restore_vault()
    monkeypatch.setenv("GNUPGHOME", secret_home)
    os.remove(wrapped)
    if os.path.isfile(key):
        os.remove(key)
    blob = os.path.join(str(env["home"]), "vault", "cockpit-vault.json.gpg")
    os.remove(blob)
    from cockpitlib.ops import vault_put as put_login

    assert put_login(pack, "https://app.example.test", "other@example.test").startswith("vault stored")
    assert os.path.isfile(blob)
    backup_vault(1)
    assert restore_vault() == "vault restored"
    assert not os.path.isfile(key)
    index = os.path.join(str(env["home"]), "vault", "index.json")
    open(index, "w", encoding="utf-8").write("{")
    vault._remember("https://app.example.test", "qa@example.test")
    open(index, "w", encoding="utf-8").write("[1]")
    vault._remember("https://app.example.test", "qa@example.test")
    open(index, "w", encoding="utf-8").write("{")
    found = login_metadata()
    assert {"origin": "https://app.example.test", "email": "qa@example.test", "two_factor": False, "lane": ""} in found
    open(index, "w", encoding="utf-8").write("[1]")
    assert login_metadata()[0]["email"] == ""
    os.remove(os.path.join(str(env["home"]), "vault", "recipient"))
    assert needs_seal()
    assert export_keep(pack, 1) == "export"
    health = os.path.join(os.environ["COCKPIT_WORKSPACE"], "hermes", "watch", "export.json")
    assert json_ok(health) is False
    monkeypatch.setattr(vault, "public_fingerprints", lambda: [])
    assert needs_seal()
    for name in ("vault.key", "vault.json.enc", "cockpit-vault.json.gpg"):
        path = os.path.join(str(env["home"]), "vault", name)
        if os.path.isfile(path):
            os.remove(path)
    assert vault._vault_material()
    import shutil

    shutil.rmtree(root)
    os.makedirs(root)
    with pytest.raises(CockpitError, match="no vault backup"):
        restore_vault()
    shutil.rmtree(root)
    assert main(["vault", "restore"]) == 1


def json_ok(path) -> bool:
    import json

    return json.load(open(path, encoding="utf-8"))["ok"]


def test_a_vault_made_on_a_machine_with_only_the_public_key_is_not_locked(env, monkeypatch):
    """init writes an empty vault: the index knows that, so doctor stays green where the private key is elsewhere."""
    from cockpitlib import scrub, vault
    from cockpitlib.doctor import run as doctor_run

    fingerprint = seal_ephemeral(monkeypatch, str(env["home"]))
    exported = subprocess.run(["gpg", "--export", "--armor", fingerprint], check=True, capture_output=True)
    pubonly = os.path.join(str(env["home"]), "pubonly-init")
    os.makedirs(pubonly, mode=0o700)
    monkeypatch.setenv("GNUPGHOME", pubonly)
    subprocess.run(["gpg", "--batch", "--import"], input=exported.stdout, check=True, capture_output=True)
    for path in (vault._blob_path(), scrub.index_path()):
        if os.path.isfile(path):
            os.remove(path)
    assert vault.init_vault(fingerprint) == f"vault sealed to {fingerprint}"
    with pytest.raises(CockpitError):
        vault._items()  # the vault cannot be read here
    assert scrub.locked() is False
    scrub.rebuild()
    assert scrub.locked() is False, "a later rebuild keeps what init taught"
    pack = load(os.environ["COCKPIT_PACK"])
    assert not any("vault locked" in line for line in doctor_run(pack))
    os.utime(vault._blob_path(), (1, 1))  # a change nobody taught it
    scrub.rebuild()
    assert scrub.locked() is True


def test_a_secret_stored_without_the_private_key_is_scrubbed_and_the_vault_is_not_locked(env, monkeypatch):
    """The private key may live elsewhere (a laptop that only holds the public key): a privileged login stored there cannot be
    read back, so the index learns it at put time. Doctor's "vault locked" line names only a change nobody taught the index."""
    from cockpitlib import scrub, vault
    from cockpitlib.doctor import run as doctor_run
    from cockpitlib.vault import public_fingerprints

    fingerprint = seal_ephemeral(monkeypatch, str(env["home"]))
    exported = subprocess.run(["gpg", "--export", "--armor", fingerprint], check=True, capture_output=True)
    pubonly = os.path.join(str(env["home"]), "pubonly-scrub")
    os.makedirs(pubonly, mode=0o700)
    monkeypatch.setenv("GNUPGHOME", pubonly)
    subprocess.run(["gpg", "--batch", "--import"], input=exported.stdout, check=True, capture_output=True)
    assert fingerprint in public_fingerprints()
    pack = load(os.environ["COCKPIT_PACK"])
    with pytest.raises(CockpitError):
        vault._items()  # the vault cannot be read here
    assert vault.store_login(
        "https://app.example.test", "admin@example.test", "kept-off-the-page-4242", privileged=True, pack=pack
    ).startswith("vault stored")
    assert scrub.locked() is False
    assert (
        scrub.spans("the password is kept-off-the-page-4242 today") != []
    )  # the index knows the value it never decrypted
    assert vault.store_login(
        "https://app.example.test", "second@example.test", "another-secret-value-99", privileged=True, pack=pack
    ).startswith("vault stored")
    assert scrub.spans("another-secret-value-99") != [] and scrub.spans("kept-off-the-page-4242") != []
    assert not any("vault locked" in line for line in doctor_run(pack))
    os.utime(vault._blob_path(), None)  # a change the index was not taught (a restore): locked
    scrub.rebuild()
    assert scrub.locked() is True
    assert vault.store_login(
        "https://app.example.test", "third@example.test", "stored-after-the-restore-7", privileged=True, pack=pack
    ).startswith("vault stored")
    assert (
        scrub.locked() is True and scrub.spans("stored-after-the-restore-7") != []
    )  # the new value is indexed; the lock stays until the vault is read in full
    assert any("vault locked" in line for line in doctor_run(pack))
