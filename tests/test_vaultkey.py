# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The key behind the vault book: a passphrase key unlocks and locks through gpg-agent, a security key is never used in
the background, and the book never prompts. Also the compatibility guarantees for older kernels and records."""

import io
import json
import os
import subprocess

import pytest

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from cockpitlib.vault_book import VaultBook
from cockpitlib.vault_key import CODES, VaultKey, VaultLocked, _failure
from tests.test_vault import seal_ephemeral

PASSPHRASE = "correct horse battery"


@pytest.fixture
def locked_book(env, monkeypatch):
    """A vault sealed to a passphrase key, its agent told never to prompt (pinentry-program /bin/false)."""
    gnupg = os.path.join(str(env["home"]), "gnupg-test")
    os.makedirs(gnupg, mode=0o700)
    monkeypatch.setenv("GNUPGHOME", gnupg)
    open(os.path.join(gnupg, "gpg-agent.conf"), "w", encoding="utf-8").write("pinentry-program /bin/false\n")
    from tests.test_vault import keyring

    keyring(
        gnupg,
        "Key-Type: RSA\nKey-Length: 2048\nSubkey-Type: RSA\nSubkey-Length: 2048\nName-Real: Locked\n"
        f"Name-Email: locked@example.test\nExpire-Date: 0\nPassphrase: {PASSPHRASE}\n%commit\n",
        "--pinentry-mode",
        "loopback",
    )
    from cockpitlib.vault import init_vault

    assert init_vault().startswith("vault sealed")
    yield VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    subprocess.run(["gpgconf", "--kill", "gpg-agent"], check=False, capture_output=True)


def test_a_passphrase_key_stays_shut_until_the_human_unlocks_it_and_shuts_again_on_lock(
    locked_book, monkeypatch, capsys
):
    book = locked_book
    key = book.sealer.key
    state = key.state()
    assert (state["secret"], state["protected"], state["cached"], state["quiet"], state["needs"]) == (
        "disk",
        True,
        False,
        False,
        "passphrase",
    )
    page = book.state()
    assert page["locked"] and "unlock it with its passphrase" in page["reason"] and page["key"]["ttl"]["idle"] > 0
    # adding needs only the public key; opening a value, or editing (which reads the stored record), waits for the unlock
    made = book.save("human", {"kind": "key", "title": "Token", "secret": "token-123"})
    with pytest.raises(VaultLocked, match="locked: unlock it first") as stopped:
        book.reveal("human", made["id"], "secret")
    assert stopped.value.needs == "passphrase"
    with pytest.raises(VaultLocked):
        book.save("human", {"id": made["id"], "kind": "key", "secret": "token-456"})
    with pytest.raises(VaultLocked, match="wrong passphrase") as wrong:
        book.unlock("not it")
    assert wrong.value.needs == "passphrase"
    with pytest.raises(VaultLocked, match="type the passphrase"):
        book.unlock("")
    assert book.unlock(PASSPHRASE) == "vault unlocked"
    assert key.state()["cached"] and key.state()["quiet"] and not book.state()["locked"]
    assert book.reveal("human", made["id"], "secret")["value"] == "token-123"
    assert book.lock() == "vault locked" and not key.state()["quiet"]
    with pytest.raises(VaultLocked):
        book.reveal("human", made["id"], "secret")
    log = open(book.audit._path(), encoding="utf-8").read()
    assert '"act": "unlock"' in log and '"act": "lock"' in log and PASSPHRASE not in log
    # the command line says the same; unlock reads the passphrase from stdin when no terminal is attached
    from cockpitlib.cli import main

    assert main(["vault", "status"]) == 0 and "passphrase, locked" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSPHRASE + "\n"))
    assert main(["vault", "unlock"]) == 0 and "vault unlocked" in capsys.readouterr().out
    assert main(["vault", "status"]) == 0 and "passphrase, cached" in capsys.readouterr().out
    assert main(["vault", "lock"]) == 0 and main(["vault", "status", "x"]) == 2


def test_a_locked_key_never_breaks_a_lane_write_and_the_index_waits_for_the_unlock(locked_book):
    """Finding 1: store_login on a machine whose key is locked appends, as before; nothing prompts, nothing raises."""
    from cockpitlib.vault import _encrypt, sealed_to, store_login

    book = locked_book
    store_login("https://a.example.test", "me@a.test", "first-aa", privileged=True, pack=book.pack)
    store_login("https://a.example.test", "me@a.test", "second-aa", privileged=True, pack=book.pack)
    scope = book.scope("human")
    assert scope.files() == ["0000.gpg", "0001.gpg"] and [len(r["files"]) for r in scope.rows()] == [2]
    # another kernel wrote a file the index has not seen: it waits, counted, until the key opens
    _encrypt(
        sealed_to(),
        json.dumps({"kind": "key", "id": "feedfacecafe", "title": "outside", "secret": "outside-1"}).encode(),
        os.path.join(scope.folder, "0002.gpg"),
    )
    listed = book.records("human")
    assert listed["unread"] == 1 and [r["title"] for r in listed["records"]] == ["a.example.test"]
    book.unlock(PASSPHRASE)
    listed = book.records("human")
    assert listed["unread"] == 0 and sorted(r["title"] for r in listed["records"]) == ["a.example.test", "outside"]
    # unlocked, an edit rewrites in place and keeps the superseded file's secret in the history
    row = next(r for r in scope.rows() if r["title"] == "a.example.test")
    book.save("human", {"id": row["id"], "kind": "login", "secret": "third-aa"})
    assert [book.reveal("human", row["id"], "history", n)["value"] for n in (0, 1)] == ["first-aa", "second-aa"]


def test_a_failing_quiet_read_falls_back_to_the_saved_index(env, monkeypatch):
    seal_ephemeral(monkeypatch, str(env["home"]))
    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    made = book.save("human", {"kind": "key", "title": "Token", "secret": "token-123"})
    from cockpitlib.vault import _encrypt, sealed_to

    scope = book.scope("human")
    _encrypt(sealed_to(), b"{broken", os.path.join(scope.folder, "0001.gpg"))
    assert [r["id"] for r in scope.rows()] == [made["id"]] and scope.unread() == 1


def fake_runner(listing: str, keyinfo: str, decrypt=(0, b"plain", b""), calls=None):
    def run(args, data=b"", timeout=20):
        if calls is not None:
            calls.append((args, data))
        if args[0] == "gpg-connect-agent":
            return subprocess.CompletedProcess(
                args, 0, keyinfo.encode() if args[1].startswith("KEYINFO") else b"OK\n", b""
            )
        if args[0] == "gpgconf":
            return subprocess.CompletedProcess(
                args, 0, b"default-cache-ttl:24:0:x:3:3:N:600::900\nmax-cache-ttl:24:2:x:3:3:N:7200::\nbad\n", b""
            )
        if "--list-secret-keys" in args:
            return subprocess.CompletedProcess(args, 0 if listing else 2, listing.encode(), b"")
        return subprocess.CompletedProcess(args, decrypt[0], decrypt[1], decrypt[2])

    return run


CARD = (
    "sec:u:4096:1:AAAA:1::::::scESC:::D2760001240103040006123456780000:::\ngrp:::::::::GRIPSEC:\n"
    "ssb:u:4096:1:BBBB:1::::::e:::D2760001240103040006123456780000:::\ngrp:::::::::GRIPENC:\n"
)
DISK = "sec:u:4096:1:AAAA:1::::::scESC:::+:::\ngrp:::::::::GRIPSEC:\nssb:u:4096:1:BBBB:1::::::e:::+:::\ngrp:::::::::GRIPENC:\n"


def test_a_security_key_is_never_used_in_the_background_but_a_human_act_may_wait_for_its_touch(env, monkeypatch):
    seal_ephemeral(monkeypatch, str(env["home"]))
    calls = []
    key = VaultKey(fake_runner(CARD, "S KEYINFO GRIPENC T D2760001 OPENPGP.2 - - - - -\nOK\n", calls=calls))
    state = key.state()
    assert (state["secret"], state["quiet"], state["needs"], state["grip"]) == ("card", False, "card", "GRIPENC")
    from cockpitlib.vault_book import GpgSealer

    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]), sealer=GpgSealer(key))
    page = book.state()
    assert not page["locked"] and "security key" in page["reason"] and page["key"]["ttl"] == {"idle": 900, "max": 7200}
    book.sealer.check_human()
    assert not book.sealer.quiet()
    assert key.open("x.gpg") == b"plain"
    assert any("--pinentry-mode" in args and "error" in args for args, _ in calls), "a read never prompts"
    assert key.lock() == "vault locked: the security key asks for its PIN again" and any(
        a[1] == "SCD RESET" for a, _ in calls
    )
    # unlock hands the PIN over loopback, on stdin, never on the command line
    calls.clear()
    assert key.unlock("123456") == "vault unlocked"
    args, data = next((a, d) for a, d in calls if "--passphrase-fd" in a)
    assert data == b"123456\n" and "123456" not in " ".join(args) and "loopback" in args
    touch = VaultKey(
        fake_runner(
            CARD, "S KEYINFO GRIPENC T x y - - -\n", decrypt=(2, b"", b"[GNUPG:] ERROR pkdecrypt_failed 67108926\n")
        )
    )
    with pytest.raises(VaultLocked, match="not touched in time") as late:
        touch.open("x.gpg")
    assert late.value.needs == "touch"


def test_what_the_key_says_maps_to_what_the_human_reads(env, monkeypatch):
    for code, (message, needs) in CODES.items():
        found = _failure(f"[GNUPG:] ERROR pkdecrypt_failed {67108864 + code}\n")
        assert (str(found), found.needs) == (message, needs)
    assert _failure("[GNUPG:] ERROR pkdecrypt_failed 67109000\n").needs == "unlock"
    assert _failure("[GNUPG:] NO_SECKEY ABCD\n[GNUPG:] DECRYPTION_FAILED\n").needs == "elsewhere"
    assert _failure("[GNUPG:] NO_SECKEY ABCD\n[GNUPG:] ERROR pkdecrypt_failed x\n").needs == "elsewhere"
    assert str(_failure("")) == "the vault file could not be opened"
    assert VaultKey._run(["sleep", "5"], b"", 0.2).returncode == 124
    assert VaultKey._run(["/no/such/gpg"]).returncode == 127
    # no secret key, an unsealed vault, a key without an encryption subkey
    monkeypatch.setenv("GNUPGHOME", str(env["home"]))
    assert VaultKey().state()["needs"] == "unsealed"
    with pytest.raises(VaultLocked, match="not sealed"):
        VaultKey().probe()
    seal_ephemeral(monkeypatch, str(env["home"]))
    assert VaultKey(fake_runner("", "")).state()["needs"] == "elsewhere"
    assert VaultKey(fake_runner("sec:u:1:1:A:1::::::sc:::+:::\ngrp:::::::::G:\n", "")).state()["secret"] == "none"
    disk = VaultKey(fake_runner(DISK, "S KEYINFO GRIPENC D - - - C - - -\n"))
    assert disk.state()["quiet"] and disk.lock() == "vault key has no passphrase: it stays open on this machine"
    assert VaultKey(fake_runner("", "")).lock() == "nothing to lock: the private key is not on this machine"
    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    from cockpitlib.vault_book import GpgSealer

    for runner, why in (
        (fake_runner("", ""), "not on this machine"),
        (fake_runner(DISK, "S KEYINFO GRIPENC D - - - P - - -\n"), "locked"),
    ):
        with pytest.raises(VaultLocked, match=why):
            GpgSealer(VaultKey(runner)).check_human()
    monkeypatch.setattr("cockpitlib.vault.sealed_to", lambda: "")
    with pytest.raises(VaultLocked, match="not sealed"):
        GpgSealer(VaultKey(fake_runner("", ""))).check_human()
    assert book


def test_a_terminal_unlock_lets_gpg_agent_ask(env, monkeypatch, capsys):
    seal_ephemeral(monkeypatch, str(env["home"]))
    assert VaultKey().unlock_here() == "vault unlocked"
    with monkeypatch.context() as patched:
        patched.setattr("cockpitlib.vault_key.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a, 2))
        with pytest.raises(VaultLocked, match="did not open"):
            VaultKey().unlock_here()
    monkeypatch.setattr("sys.stdin", type("Tty", (io.StringIO,), {"isatty": lambda self: True})())
    from cockpitlib.cli import main

    assert main(["vault", "unlock"]) == 0 and "vault unlocked" in capsys.readouterr().out


def test_an_unknown_key_another_kernel_wrote_survives_every_rewrite(env, monkeypatch):
    """Finding 2: a label (lend picks the admin login by it) or any key this kernel does not know is kept."""
    seal_ephemeral(monkeypatch, str(env["home"]))
    from cockpitlib.vault import _encrypt, entry_records, sealed_to, store_login

    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    scope = book.scope("human")
    os.makedirs(scope.folder, mode=0o700)
    _encrypt(
        sealed_to(),
        json.dumps(
            {
                "origin": "https://admin.test",
                "email": "root@admin.test",
                "secret": "admin-1",
                "privileged": True,
                "label": "acme-admin",
                "identifier_type": "email",
            }
        ).encode(),
        os.path.join(scope.folder, "0000.gpg"),
    )
    store_login("https://admin.test", "root@admin.test", "admin-2", privileged=True, pack=book.pack)
    row = book.records("human")["records"][0]
    book.save("human", {"id": row["id"], "kind": "login", "title": "Admin", "tags": "ops"})
    book.move("human", row["id"], "lane")
    book.move("lane", row["id"], "human")
    ((item, _path),) = entry_records()
    assert (item["label"], item["identifier_type"], item["secret"], item["privileged"]) == (
        "acme-admin",
        "email",
        "admin-2",
        True,
    )
    from cockpitlib.lend import _labelled_login
    from cockpitlib.vault import _items

    book.save("human", {"kind": "note", "title": "Not a login", "secret": "note body"})
    assert _labelled_login(_items())["email"] == "root@admin.test"
    assert (
        _labelled_login([{"privileged": True, "kind": "note", "title": "x"}]) == {}
    )  # finding 3: a note is never lent


def test_a_vault_the_human_made_never_answers_for_a_lane_login(env, monkeypatch):
    """Finding 3: the lookups without a scope (demo password, the lane's 2FA code) read only the pack's vaults."""
    seal_ephemeral(monkeypatch, str(env["home"]))
    from cockpitlib.vault import _builtin_items, _previous, current_code, human_secret, store_login

    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    store_login("https://lab.test", "qa@lab.test", "lane-pass", pack=book.pack)
    book.create_vault("zz-mine")
    book.save(
        "zz-mine",
        {
            "kind": "login",
            "origin": "https://lab.test",
            "email": "qa@lab.test",
            "secret": "my-own",
            "otp": "JBSWY3DPEHPK3PXP",
        },
    )
    assert human_secret("https://lab.test", "qa@lab.test", pack=book.pack) == "lane-pass"
    assert current_code("https://lab.test", "qa@lab.test") == ""
    assert _previous("https://lab.test", "qa@lab.test")["secret"] == "lane-pass"
    with pytest.raises(CockpitError, match="already holds that login"):
        book.save(
            "zz-mine", {"kind": "login", "origin": "https://lab.test", "email": "qa@lab.test", "secret": "again-1"}
        )
    # only a vault of the human's own, and none of the pack's: the older read path stands
    book.delete("zz-mine", book.records("zz-mine")["records"][0]["id"])
    import shutil

    shutil.rmtree(book.scope("lane").root)
    assert _builtin_items() == [] or all(i.get("deleted") is None for i in _builtin_items())


def test_an_older_kernel_never_overwrites_a_file_after_a_delete(env, monkeypatch):
    """Finding 5: an older kernel names the next file by counting; tombstones keep that count equal to the next number."""
    seal_ephemeral(monkeypatch, str(env["home"]))
    from cockpitlib.vault import _entry_paths

    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    made = [book.save("human", {"kind": "key", "title": t, "secret": f"{t}-secret"})["id"] for t in "abc"]
    book.delete("human", made[0])
    book.move("human", made[1], "lane")
    paths = _entry_paths("human")
    older_next = f"{len(paths):04d}.gpg"
    assert older_next not in [os.path.basename(p) for p in paths] and book.scope("human").next_file() == older_next


def test_logins_in_the_older_single_file_store_move_into_the_vaults_when_the_human_rereads(env, monkeypatch):
    """Finding 6: a blob-only install shows the logins after Re-read; until then the book refuses to write over it."""
    seal_ephemeral(monkeypatch, str(env["home"]))
    from cockpitlib.vault import _entry_paths, _save, human_secret

    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    _save(
        [
            {"origin": "https://lab.test", "email": "qa@lab.test", "secret": "blob-lane", "lane": "tester-1"},
            {"origin": "https://admin.test", "email": "root@admin.test", "secret": "blob-admin", "privileged": True},
            {"origin": "https://lab.test", "email": "qa@lab.test", "secret": "blob-lent", "lent": "t_1"},
        ]
    )
    open(os.path.join(os.path.dirname(book.audit._path()), "index.json"), "w", encoding="utf-8").write(
        json.dumps([{"origin": "https://lab.test", "email": "qa@lab.test", "two_factor": False, "lane": "tester-1"}])
    )
    assert book.state()["legacy"] and human_secret("https://admin.test", "root@admin.test") == "blob-admin"
    for call in (
        lambda: book.save("human", {"kind": "key", "title": "k", "secret": "kkkkkk"}),
        lambda: book.delete("human", "x"),
        lambda: book.move("human", "x", "lane"),
    ):
        with pytest.raises(CockpitError, match="older single-file store"):
            call()
    assert book.reindex() == "vault index: 2 records (3 moved from the older single-file store)"
    assert not book.state()["legacy"] and len(_entry_paths()) == 3
    assert human_secret("https://admin.test", "root@admin.test") == "blob-admin"
    assert human_secret("https://lab.test", "qa@lab.test", pack=book.pack) == "blob-lane"
    assert [r["title"] for r in book.records("lane")["records"]] == ["lab.test"]
    open(os.path.join(os.path.dirname(book.audit._path()), "index.json"), "w", encoding="utf-8").write("{bad")
    assert book._legacy_pending() is False


def test_unlock_and_lock_routes(env, monkeypatch):
    from tests.test_routes import _client

    seal_ephemeral(monkeypatch, str(env["home"]))
    client = _client()
    page = client.get("/vaults").json()
    assert page["key"]["secret"] == "disk" and page["key"]["quiet"] and page["legacy"] is False
    assert (
        client.post("/vault-unlock", json={"secret": "anything"}).json()["out"] == "vault unlocked"
    )  # a key without passphrase opens
    assert client.post("/vault-lock", json={}).json()["out"].startswith("vault key has no passphrase")
    assert client.post("/vault-reindex", json={}).json()["out"] == "vault index: 0 records"
    refused = client.post("/vault-unlock", json={})
    assert refused.status_code == 400 and "type the passphrase" in refused.text


def test_the_edges_of_folding_and_moving_the_older_store(env, monkeypatch):
    seal_ephemeral(monkeypatch, str(env["home"]))
    from cockpitlib.vault import _blob_path, _encrypt, _index_path, _save, sealed_to
    from cockpitlib.vault_key import _text

    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    assert _text("as is") == "as is" and _text(None) == ""
    # a blob-only store: an unreadable index is no pending move; junk in the blob is skipped; a broken blob says so
    _save([{"origin": "https://lab.test", "email": "qa@lab.test", "secret": "blob-1"}, "junk"])
    open(_index_path(), "w", encoding="utf-8").write("{bad")
    assert book._legacy_pending() is False
    open(_index_path(), "w", encoding="utf-8").write('[{"origin": "https://lab.test"}]')
    assert book._migrate_blob() == 1
    _encrypt(sealed_to(), b"{broken", _blob_path())
    with pytest.raises(CockpitError, match="unreadable"):
        book._migrate_blob()
    # a superseded file that does not open stays where it is; the record still saves in place
    scope = book.scope("lane")
    row = scope.rows()[0]
    _encrypt(
        sealed_to(),
        json.dumps({"origin": "https://lab.test", "email": "qa@lab.test", "secret": "newer"}).encode(),
        os.path.join(scope.folder, "0001.gpg"),
    )
    row = scope.rows()[0]
    assert row["files"] == ["0000.gpg", "0001.gpg"]
    real = scope._read
    monkeypatch.setattr(
        scope, "_read", lambda name: (_ for _ in ()).throw(VaultLocked("locked")) if name == "0000.gpg" else real(name)
    )
    record = scope.load(row)
    record.replace_secret("newest")
    scope.write(record, row, loaded=True)
    assert scope._document()["rows"][0]["files"] == ["0000.gpg", "0001.gpg"]
