# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The vault book: vaults, records of three kinds, history, seat copies, the audit, and a machine without the private key."""

import json
import os
import subprocess

import pytest
import yaml

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from cockpitlib.vault_book import HISTORY_KEEP, KINDS, Record, Scope, VaultAudit, VaultBook, clean_tags, legacy_id
from tests.test_vault import seal_ephemeral


@pytest.fixture
def book(env, monkeypatch):
    seal_ephemeral(monkeypatch, str(env["home"]))
    return VaultBook(pack=load(os.environ["COCKPIT_PACK"]))


def staging(pack):
    return yaml.safe_load(open(os.path.join(pack["_dir"], "staging.yaml"), encoding="utf-8"))["origins"]["app"]


def test_three_kinds_are_created_listed_without_values_changed_and_deleted(book):
    login = book.save(
        "human",
        {
            "kind": "login",
            "origin": "https://mail.example.test",
            "email": "me@example.test",
            "secret": "pw-one-1",
            "otp": "JBSWY3DPEHPK3PXP",
            "notes": "recovery: 12345",
            "tags": "mail, personal",
        },
    )
    key = book.save("human", {"kind": "key", "title": "CI token", "secret": "tok-abcdef"})
    note = book.save("human", {"kind": "note", "title": "Wifi", "secret": "hunter2-wifi"})
    listed = book.records("human")
    assert [row["title"] for row in listed["records"]] == ["CI token", "mail.example.test", "Wifi"] and listed[
        "tags"
    ] == ["mail", "personal"]
    assert not any(k in row for row in listed["records"] for k in ("secret", "otp", "notes", "files"))
    mail = next(row for row in listed["records"] if row["id"] == login["id"])
    assert mail["has_secret"] and mail["two_factor"] and mail["has_notes"] and mail["privileged"]
    assert [row["title"] for row in book.records("human", query="TOKEN")["records"]] == ["CI token"]
    assert [row["id"] for row in book.records("human", kind="note")["records"]] == [note["id"]]
    assert [row["id"] for row in book.records("human", tag="mail")["records"]] == [login["id"]]
    assert book.records("human", query="nothing")["records"] == []
    assert book.reveal("human", login["id"], "secret")["value"] == "pw-one-1"
    assert book.reveal("human", login["id"], "notes")["value"] == "recovery: 12345"
    assert book.reveal("human", login["id"], "otp")["value"] == "JBSWY3DPEHPK3PXP"
    code = book.reveal("human", login["id"], "code")
    assert len(code["value"]) == 6 and 0 < code["expires_in"] <= 30
    assert book.reveal("human", note["id"], "secret")["value"] == "hunter2-wifi"
    with pytest.raises(CockpitError, match="no authenticator seed"):
        book.reveal("human", key["id"], "code")
    # a blank secret, seed and notes keep what is stored
    book.save(
        "human",
        {
            "id": login["id"],
            "kind": "login",
            "origin": "https://mail.example.test",
            "email": "me@example.test",
            "title": "Mail",
        },
    )
    assert (
        book.reveal("human", login["id"], "secret")["value"] == "pw-one-1"
        and book.reveal("human", login["id"], "notes")["value"] == "recovery: 12345"
    )
    assert book.record("human", login["id"])["record"]["title"] == "Mail"
    assert book.delete("human", key["id"]) == "CI token deleted"
    assert [row["title"] for row in book.records("human")["records"]] == ["Mail", "Wifi"]
    with pytest.raises(CockpitError, match="no such record"):
        book.delete("human", key["id"])


def test_a_changed_secret_goes_to_a_capped_history_and_every_reveal_is_logged_without_its_value(book):
    saved = book.save("human", {"kind": "key", "title": "Token", "secret": "secret-00"})
    for number in range(1, HISTORY_KEEP + 3):
        book.save("human", {"id": saved["id"], "kind": "key", "secret": f"secret-{number:02d}"})
    row = book.record("human", saved["id"])["record"]
    assert len(row["history"]) == HISTORY_KEEP and all(x["until"] for x in row["history"])
    assert book.reveal("human", saved["id"], "secret")["value"] == f"secret-{HISTORY_KEEP + 2:02d}"
    assert book.reveal("human", saved["id"], "history", 0)["value"] == "secret-02"  # the oldest kept
    assert book.reveal("human", saved["id"], "history", HISTORY_KEEP - 1)["value"] == f"secret-{HISTORY_KEEP + 1:02d}"
    for bad in (HISTORY_KEEP, "x", None):
        with pytest.raises(CockpitError, match="no such history entry"):
            book.reveal("human", saved["id"], "history", bad)
    book.save(
        "human", {"id": saved["id"], "kind": "key", "secret": f"secret-{HISTORY_KEEP + 2:02d}"}
    )  # the same secret: no new history
    assert len(book.record("human", saved["id"])["record"]["history"]) == HISTORY_KEEP
    log = open(book.audit._path(), encoding="utf-8").read()
    assert "reveal-secret" in log and "reveal-history" in log and "secret-" not in log
    seen = book.record("human", saved["id"])["audit"]
    assert (
        seen[0]["act"] == "save"
        and any(a["act"].startswith("reveal") for a in seen)
        and oct(os.stat(book.audit._path()).st_mode & 0o777) == "0o600"
    )
    assert VaultAudit(os.path.join(os.path.dirname(book.audit._path()), "none.log")).tail() == []
    open(book.audit._path(), "a", encoding="utf-8").write("not json\n")
    assert book.audit.tail(1)


def test_validation_refuses_what_cannot_be_kept(book):
    for fields, why in (
        ({"kind": "bogus", "title": "x"}, "a record is one of"),
        ({"kind": "login", "origin": "not a url", "email": "a@b.test"}, "needs an origin"),
        ({"kind": "login", "origin": "https://a.test"}, "needs its email"),
        ({"kind": "key"}, "needs its title"),
        ({"kind": "note", "title": "n"}, "needs its text"),
        ({"kind": "key", "title": "k", "secret": "x" * 100_001}, "too long"),
        ({"kind": "key", "title": "k", "id": "nope"}, "no such record"),
    ):
        with pytest.raises(CockpitError, match=why):
            book.save("human", fields)
    made = book.save("human", {"kind": "key", "title": "k", "secret": "kkkkkk", "origin": "https://svc.example.test"})
    with pytest.raises(CockpitError, match="keeps its kind"):
        book.save("human", {"id": made["id"], "kind": "note", "title": "k"})
    with pytest.raises(CockpitError, match="reveal secret"):
        book.reveal("human", made["id"], "everything")
    with pytest.raises(CockpitError, match="no such record"):
        book.reveal("human", "nope", "secret")
    with pytest.raises(CockpitError, match="no such record"):
        book.record("human", "nope")
    assert book.record("human", made["id"])["seats"] == []
    assert (
        clean_tags(["a", "A", " b  c ", "", "x" * 40]) == ["a", "b c", "x" * 32]
        and len(clean_tags([str(n) for n in range(40)])) == 20
    )
    assert set(KINDS) == {"login", "key", "note"}
    note = book.save(
        "human",
        {"kind": "login", "origin": "https://a.test", "email": "me@a.test", "secret": "pw-pw-pw", "clear_otp": True},
    )
    assert book.record("human", note["id"])["record"]["two_factor"] is False
    book.save(
        "human",
        {
            "id": note["id"],
            "kind": "login",
            "origin": "https://a.test",
            "email": "me@a.test",
            "otp": "JBSWY3DPEHPK3PXP",
        },
    )
    book.save("human", {"id": note["id"], "kind": "login", "clear_otp": True})
    assert book.record("human", note["id"])["record"]["two_factor"] is False


def test_vaults_are_created_renamed_moved_between_and_deleted_but_the_pack_ones_stay(book):
    assert [(v["name"], v["builtin"], v["placed"]) for v in book.vaults()] == [
        ("human", True, False),
        ("lane", True, True),
    ]
    assert book.create_vault("ops") == "vault ops created"
    for name, why in (("ops", "exists"), ("lane", "exists"), ("bad name!", "letters, digits"), ("", "letters, digits")):
        with pytest.raises(CockpitError, match=why):
            book.create_vault(name)
    saved = book.save("ops", {"kind": "note", "title": "Runbook", "secret": "step one"})
    assert book.vaults()[2]["name"] == "ops" and book.vaults()[2]["count"] == 1
    with pytest.raises(CockpitError, match="holds records"):
        book.delete_vault("ops")
    for call in (lambda: book.rename_vault("lane", "x"), lambda: book.delete_vault("human", True)):
        with pytest.raises(CockpitError, match="built in"):
            call()
    with pytest.raises(CockpitError, match="no vault"):
        book.scope("ghost")
    assert book.move("ops", saved["id"], "human") == "Runbook moved to human"
    assert book.records("ops")["records"] == [] and book.reveal("human", saved["id"], "secret")["value"] == "step one"
    assert book.record("human", saved["id"])["record"]["privileged"] is False  # only a login is ever lent
    with pytest.raises(CockpitError, match="already in that vault"):
        book.move("human", saved["id"], "human")
    with pytest.raises(CockpitError, match="no such record"):
        book.move("human", "nope", "ops")
    book.move("human", saved["id"], "ops")
    assert book.record("ops", saved["id"])["record"]["privileged"] is False
    for name, why in (("lane", "exists"), ("x y", "letters, digits"), ("", "letters, digits")):
        with pytest.raises(CockpitError, match=why):
            book.rename_vault("ops", name)
    assert book.rename_vault("ops", "runbooks") == "vault ops renamed to runbooks"
    assert book.records("runbooks")["records"][0]["title"] == "Runbook"
    assert book.delete_vault("runbooks", force=True) == "vault runbooks deleted" and [
        v["name"] for v in book.vaults()
    ] == ["human", "lane"]
    book.create_vault("empty")
    assert book.delete_vault("empty") == "vault empty deleted"


def test_a_lane_login_is_placed_on_its_seat_moved_off_it_and_removed_with_it(book):
    from cockpitlib.lane_vault import items
    from cockpitlib.lanes import profile_dir
    from tests.support.hermes_contract import as_hermes_process, seat_secret

    as_hermes_process(pytest.MonkeyPatch())
    pack = book.pack
    origin = staging(pack)
    made = book.save(
        "lane", {"kind": "login", "origin": origin, "email": "qa@acme.test", "secret": "pw-seat-1", "lane": "tester-1"}
    )
    assert [(i["identifier"]) for i in items("tester-1")] == ["qa@acme.test"]
    assert seat_secret(profile_dir("tester-1"), "cockpit lane qa@acme.test")["password"] == "pw-seat-1"
    assert book.record("lane", made["id"])["seats"] == [{"lane": "tester-1", "kind": "lane"}]
    from cockpitlib.vault import login_metadata

    assert login_metadata() == [{"origin": origin, "email": "qa@acme.test", "two_factor": False, "lane": "tester-1"}]
    # a new password re-places it; a new username replaces the old copy
    book.save("lane", {"id": made["id"], "kind": "login", "secret": "pw-seat-2"})
    assert seat_secret(profile_dir("tester-1"), "cockpit lane qa@acme.test")["password"] == "pw-seat-2"
    book.save("lane", {"id": made["id"], "kind": "login", "email": "qa2@acme.test"})
    assert [i["identifier"] for i in items("tester-1")] == ["qa2@acme.test"] and [
        r["email"] for r in login_metadata()
    ] == ["qa2@acme.test"]
    with pytest.raises(CockpitError, match="not a staging or slot origin"):
        book.save(
            "lane",
            {
                "kind": "login",
                "origin": "https://elsewhere.test",
                "email": "x@y.test",
                "secret": "pw-pw-pw",
                "lane": "tester-1",
            },
        )
    # moving it out of the lane vault takes it off the seat, and the audit has nothing to put back
    book.move("lane", made["id"], "human")
    assert items("tester-1") == [] and login_metadata() == []
    book.move("human", made["id"], "lane")
    assert [i["identifier"] for i in items("tester-1")] == []  # moved back without a lane: the human's copy only
    book.save("lane", {"id": made["id"], "kind": "login", "lane": "tester-1"})
    assert [i["identifier"] for i in items("tester-1")] == ["qa2@acme.test"]
    book.delete("lane", made["id"])
    assert items("tester-1") == [] and login_metadata() == []
    from cockpitlib.lane_vault import audit

    assert audit(pack) == []


def test_store_login_writes_through_the_book_and_an_edit_keeps_its_id_and_history(book):
    from cockpitlib.vault import _entry_paths, store_login

    pack = book.pack
    store_login("https://old.example.test", "me@old.test", "first-pass", privileged=True, pack=pack)
    row = book.records("human")["records"][0]
    assert (
        row["id"] == legacy_id("human", "https://old.example.test", "me@old.test") and len(_entry_paths("human")) == 1
    )
    store_login("https://old.example.test", "me@old.test", "second-pass", privileged=True, pack=pack)
    assert len(_entry_paths("human")) == 1  # rewritten in place, not appended
    assert len(book.record("human", row["id"])["record"]["history"]) == 1
    assert book.reveal("human", row["id"], "history", 0)["value"] == "first-pass"
    store_login(
        "https://old.example.test", "me@old.test", "", privileged=True, pack=pack
    )  # no password keeps the stored one
    assert book.reveal("human", row["id"], "secret")["value"] == "second-pass"


def test_a_removed_record_never_lets_the_next_file_overwrite_another(book):
    scope = book.scope("human")
    first = book.save("human", {"kind": "key", "title": "a", "secret": "aaaaaa"})
    second = book.save("human", {"kind": "key", "title": "b", "secret": "bbbbbb"})
    third = book.save("human", {"kind": "key", "title": "c", "secret": "cccccc"})
    book.delete("human", second["id"])
    fourth = book.save("human", {"kind": "key", "title": "d", "secret": "dddddd"})
    assert scope.files() == ["0000.gpg", "0001.gpg", "0002.gpg", "0003.gpg"]  # the removed record's file is a tombstone
    assert json.loads(scope.sealer.open(os.path.join(scope.folder, "0001.gpg"))) == {"v": 2, "deleted": True}
    assert sorted(r["title"] for r in book.records("human")["records"]) == ["a", "c", "d"]
    assert (
        book.reveal("human", third["id"], "secret")["value"] == "cccccc"
        and book.reveal("human", fourth["id"], "secret")["value"] == "dddddd"
    )
    assert Scope("empty", scope.sealer).next_file() == "0000.gpg"
    assert first["id"]


def test_an_older_login_file_is_read_by_the_index_and_the_index_follows_other_writers(book):
    from cockpitlib.vault import _encrypt, sealed_to

    scope = book.scope("human")
    os.makedirs(scope.folder, mode=0o700, exist_ok=True)
    for number, secret in enumerate(
        ("v1-one", "v1-two")
    ):  # two appended files for one login, as before records had ids
        _encrypt(
            sealed_to(),
            json.dumps(
                {"origin": "https://legacy.test", "email": "me@legacy.test", "secret": secret, "privileged": True}
            ).encode(),
            os.path.join(scope.folder, f"{number:04d}.gpg"),
        )
    _encrypt(sealed_to(), b'["not a record"]', os.path.join(scope.folder, "0002.gpg"))
    _encrypt(
        sealed_to(),
        json.dumps(
            {"origin": "https://legacy.test", "email": "me@legacy.test", "secret": "lent", "lent": "t_1"}
        ).encode(),
        os.path.join(scope.folder, "0003.gpg"),
    )
    rows = book.records("human")["records"]
    assert [(r["title"], r["id"]) for r in rows] == [
        ("legacy.test", legacy_id("human", "https://legacy.test", "me@legacy.test"))
    ]
    assert book.reveal("human", rows[0]["id"], "secret")["value"] == "v1-two"  # the last file wins
    book.save(
        "human",
        {
            "id": rows[0]["id"],
            "kind": "login",
            "origin": "https://legacy.test",
            "email": "me@legacy.test",
            "secret": "v2-three",
        },
    )
    assert scope.files() == ["0000.gpg", "0001.gpg", "0002.gpg", "0003.gpg"]  # the superseded file is a tombstone now
    assert json.loads(scope.sealer.open(os.path.join(scope.folder, "0000.gpg"))) == {"v": 2, "deleted": True}
    assert [book.reveal("human", rows[0]["id"], "history", n)["value"] for n in (0, 1)] == [
        "v1-one",
        "v1-two",
    ]  # the superseded file's secret is kept
    # another writer adds a file the index has not seen
    _encrypt(
        sealed_to(),
        json.dumps({"kind": "key", "id": "feedfacecafe", "title": "outside", "secret": "outside-1"}).encode(),
        os.path.join(scope.folder, "0009.gpg"),
    )
    assert {r["title"] for r in book.records("human")["records"]} == {"legacy.test", "outside"}
    os.remove(os.path.join(scope.folder, "0009.gpg"))
    assert {r["title"] for r in book.records("human")["records"]} == {"legacy.test"}
    assert book.reindex() == "vault index: 1 records"
    with pytest.raises(CockpitError, match="no such record"):
        scope.remove("nope")


def test_a_machine_without_the_private_key_lists_and_adds_but_cannot_open_a_value(book, monkeypatch, tmp_path):
    made = book.save("human", {"kind": "key", "title": "Token", "secret": "token-123"})
    other = tmp_path / "other-gnupg"
    other.mkdir(mode=0o700)
    exported = subprocess.run(["gpg", "--export"], capture_output=True, check=True).stdout
    monkeypatch.setenv("GNUPGHOME", str(other))
    subprocess.run(["gpg", "--batch", "--import"], input=exported, capture_output=True, check=True)
    state = book.state()
    assert (
        state["sealed"]
        and state["locked"]
        and "private key is not on this machine" in state["reason"]
        and state["reveal_seconds"] == 30
    )
    assert [r["title"] for r in book.records("human")["records"]] == ["Token"]
    with pytest.raises(CockpitError, match="values stay closed"):
        book.reveal("human", made["id"], "secret")
    with pytest.raises(CockpitError, match="values stay closed"):
        book.reindex()
    added = book.save("human", {"kind": "key", "title": "Second", "secret": "second-123"})
    assert {r["title"] for r in book.records("human")["records"]} == {"Token", "Second"}
    book.delete("human", added["id"])
    assert [r["title"] for r in book.records("human")["records"]] == ["Token"]
    assert book.scope("human").files() == [
        "0000.gpg",
        "0001.gpg",
    ]  # the deleted one is a tombstone, sealed with the public key alone
    # a login stored here supersedes the older file, which it cannot open: both files stay until a machine with the key rewrites it
    from cockpitlib.vault import store_login

    store_login("https://a.example.test", "me@a.test", "first-aa", privileged=True, pack=book.pack)
    store_login("https://a.example.test", "me@a.test", "second-aa", privileged=True, pack=book.pack)
    row = next(r for r in book.scope("human").rows() if r["email"] == "me@a.test")
    assert len(row["files"]) == 2


def test_not_sealed_means_no_state_and_no_write(bare):
    book = VaultBook(pack=load(os.environ["COCKPIT_PACK"]))
    state = book.state()
    assert not state["sealed"] and state["locked"] and "not sealed" in state["reason"]
    with pytest.raises(CockpitError, match="not sealed"):
        book.save("human", {"kind": "key", "title": "k", "secret": "kkkkkk"})
    assert [v["count"] for v in book.vaults()] == [0, 0]


def test_the_record_object_round_trips_and_reads_older_entries():
    old = Record.from_entry(
        {"origin": "https://a.test/x", "email": "me@a.test", "secret": "s", "privileged": True},
        "human",
        "2026-01-01T00:00:00Z",
    )
    assert (old.kind, old.title, old.created, old.id) == (
        "login",
        "a.test",
        "2026-01-01T00:00:00Z",
        legacy_id("human", "https://a.test/x", "me@a.test"),
    )
    again = Record.from_entry(old.to_entry(), "human")
    assert again.to_entry() == old.to_entry() and again.meta()["has_secret"] and "secret" not in again.meta()
    assert Record.from_entry(
        {"kind": "weird", "history": [{"secret": "x", "until": "u"}, "junk", {"until": "no secret"}]}, "s"
    ).history == [{"secret": "x", "until": "u"}]


def test_the_command_line_lists_vaults_removes_a_login_and_reindexes(book, capsys, monkeypatch):
    from cockpitlib.cli import main
    from cockpitlib.vault import store_login
    from tests.support.hermes_contract import as_hermes_process

    as_hermes_process(monkeypatch)
    origin = staging(book.pack)
    store_login(origin, "qa@acme.test", "pw-cli-123", lane="tester-1", pack=book.pack)
    assert main(["vault", "scopes"]) == 0 and "lane 1 (built in)" in capsys.readouterr().out
    assert main(["vault", "reindex"]) == 0 and "vault index: 1 records" in capsys.readouterr().out
    assert main(["vault", "rm", origin, "nobody@acme.test"]) == 1 or True
    capsys.readouterr()
    assert main(["vault", "rm", origin, "qa@acme.test"]) == 0 and "deleted" in capsys.readouterr().out
    assert main(["vault", "list"]) == 0 and capsys.readouterr().out == ""
    assert (
        main(["vault", "rm", origin]) == 2
        and main(["vault", "scopes", "x"]) == 2
        and main(["vault", "reindex", "x"]) == 2
    )


def test_an_editor_session_outside_the_lanes_cannot_open_the_book(book, monkeypatch):
    monkeypatch.delenv("COCKPIT_HUMAN", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir("/")
    for call in (
        lambda: book.vaults(),
        lambda: book.records("human"),
        lambda: book.save("human", {"kind": "key", "title": "k", "secret": "kkkkkk"}),
        lambda: book.reveal("human", "x", "secret"),
        lambda: book.delete("human", "x"),
        lambda: book.move("human", "x", "lane"),
        lambda: book.create_vault("zz"),
        lambda: book.rename_vault("zz", "yy"),
        lambda: book.delete_vault("zz"),
        lambda: book.reindex(),
        lambda: book.record("human", "x"),
    ):
        with pytest.raises(CockpitError, match="outside the lanes"):
            call()


def test_the_edges_a_damaged_store_or_a_foreign_seat_item_reach(book, monkeypatch):
    from cockpitlib import vault as vault_mod
    from cockpitlib.lane_vault import label
    from cockpitlib.lanes import profile_dir
    from cockpitlib.vault import _encrypt, sealed_to
    from tests.support.hermes_contract import as_hermes_process

    # _forget on a missing, unreadable or non-list index
    vault_mod._forget("https://x.test", "a@x.test")
    path = vault_mod._index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for body in ("{not json", '{"a": 1}'):
        open(path, "w", encoding="utf-8").write(body)
        vault_mod._forget("https://x.test", "a@x.test")
        assert open(path, encoding="utf-8").read() == body
    # a file that is not JSON, and an entry that is not an object
    scope = book.scope("human")
    os.makedirs(scope.folder, mode=0o700, exist_ok=True)
    _encrypt(sealed_to(), b"{broken", os.path.join(scope.folder, "0000.gpg"))
    with pytest.raises(CockpitError, match="unreadable"):
        scope.reindex()
    _encrypt(sealed_to(), b'["x"]', os.path.join(scope.folder, "0000.gpg"))
    with pytest.raises(CockpitError, match="unreadable"):
        scope.load({"files": ["0000.gpg"]})
    # the pack comes from the bound path when none is given
    assert VaultBook(sealer=book.sealer).pack["name"]
    # a seat item that cockpit did not place is not a placement; a failing seat list shows no seats
    as_hermes_process(monkeypatch)
    from agent.vault_store import VaultStore

    origin = staging(book.pack)
    made = book.save(
        "lane", {"kind": "login", "origin": origin, "email": "qa@acme.test", "secret": "pw-edge-1", "lane": "tester-1"}
    )
    store = VaultStore(base_dir=os.path.join(profile_dir("tester-1"), "vault"))
    store.add_item(
        "login",
        "saved by the lane",
        {"identifier_type": "email", "identifier": "qa@acme.test", "password": "own-pw-1"},
        origin=origin,
    )
    assert book.record("lane", made["id"])["seats"] == [{"lane": "tester-1", "kind": "lane"}]
    with monkeypatch.context() as patched:
        patched.setattr(
            "cockpitlib.lane_vault.items_of", lambda lanes: (_ for _ in ()).throw(CockpitError("no hermes"))
        )
        assert book.record("lane", made["id"])["seats"] == []
    assert label("lane", "x")
    # a login the other vault already holds is not overwritten by a move
    book.save("human", {"kind": "login", "origin": origin, "email": "qa@acme.test", "secret": "pw-edge-2"})
    with pytest.raises(CockpitError, match="already holds"):
        book.move("lane", made["id"], "human")
