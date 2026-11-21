# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""store writes a record whole or not at all, with the bytes the plain write gave.

A record is replaced in one step from a synced temp file beside it: a reader sees the old file or the new, a failed
write leaves the old one and no temp file, an existing file keeps its mode, and what lands is byte for byte what
`json.dump` or `handle.write` wrote before (an adopter's replay compares records byte for byte).
"""

import errno
import io
import json
import os
import stat

import pytest

from cockpitlib import store


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _bytes(path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


DATA = {"b": [1, 2.5, None, True], "a": {"z": "é ü", "y": "line\nbreak"}, "c": ""}


def test_a_kernel_record_keeps_its_form_and_a_new_one_is_private(tmp_path):
    path = str(tmp_path / "deep" / "er" / "001-pr-open.json")
    store.write_json(path, DATA)
    assert _bytes(path) == (json.dumps(DATA, indent=2, sort_keys=True) + "\n").encode("utf-8")
    assert _mode(path) == 0o600 and store.read_json(path) == DATA
    assert os.listdir(os.path.dirname(path)) == ["001-pr-open.json"]  # no temp file stays behind


@pytest.mark.parametrize(
    "dumps", ({}, {"indent": 1}, {"indent": 2}, {"indent": 1, "sort_keys": True}, {"ensure_ascii": False})
)
def test_a_dumped_record_is_byte_for_byte_what_json_dump_wrote(tmp_path, dumps):
    path = str(tmp_path / "record.json")
    plain = io.StringIO()
    json.dump(DATA, plain, **dumps)
    store.dump_json(path, DATA, **dumps)
    assert _bytes(path) == plain.getvalue().encode("utf-8")


def test_a_text_is_written_as_given_in_the_encoding_named_or_the_one_open_would_use(tmp_path):
    path = str(tmp_path / "made" / "note.md")
    store.write_text(path, "no newline é")
    assert _bytes(path) == "no newline é".encode()
    store.write_text(path, "plain\n", encoding=None)
    with open(path) as handle:
        assert handle.read() == "plain\n"
    store.write_text(path, "é", encoding="latin-1")
    assert _bytes(path) == b"\xe9"
    store.write_bytes(path, b"\x00\x01")
    assert _bytes(path) == b"\x00\x01"


def test_a_new_file_gets_the_mode_open_would_give_and_an_existing_file_keeps_its_own(tmp_path):
    path = str(tmp_path / "state")
    old = os.umask(0o022)
    try:
        store.write_text(path, "ready\n")
        assert _mode(path) == 0o644
        os.chmod(path, 0o640)
        store.write_text(path, "down\n")
        assert _mode(path) == 0o640
        store.write_json(path, {})  # the kernel's own form does not narrow a file that is there
        assert _mode(path) == 0o640
        secret = str(tmp_path / "login.json")
        store.dump_json(secret, ["x"], mode=0o600)
        assert _mode(secret) == 0o600 and _bytes(secret) == b'["x"]'
    finally:
        os.umask(old)


def test_a_link_is_written_through_and_stays_a_link(tmp_path):
    real, link = str(tmp_path / "real.json"), str(tmp_path / "link.json")
    store.dump_json(real, [1])
    os.symlink(real, link)
    store.dump_json(link, [2])
    assert os.path.islink(link) and _bytes(real) == b"[2]"


def test_a_write_that_fails_leaves_the_old_record_and_no_temp_file(tmp_path, monkeypatch):
    path = str(tmp_path / "record.json")
    store.dump_json(path, {"kept": 1})
    with pytest.raises(TypeError):
        store.dump_json(path, {"bad": object()})
    with pytest.raises(TypeError):
        store.write_json(path, {"bad": object()})

    def refuse(*_args):
        raise OSError(errno.EIO, "the disk said no")

    replace, write = os.replace, os.write
    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        store.dump_json(path, {"new": 2})
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "write", refuse)
    with pytest.raises(OSError):
        store.write_text(path, "half")
    monkeypatch.setattr(os, "write", write)
    assert store.read_json(path) == {"kept": 1} and os.listdir(tmp_path) == ["record.json"]


@pytest.mark.skipif(os.geteuid() == 0, reason="the superuser writes a read-only file")
def test_a_file_made_read_only_is_not_replaced_behind_its_mode(tmp_path):
    path = str(tmp_path / "loan.json")
    store.dump_json(path, {"tabs": []})
    os.chmod(path, 0o444)
    with pytest.raises(PermissionError):
        store.dump_json(path, {"tabs": ["mine"]})
    with pytest.raises(PermissionError):
        store.write_json(path, {})
    assert store.read_json(path) == {"tabs": []} and os.listdir(tmp_path) == ["loan.json"]
    os.chmod(path, 0o644)
    store.dump_json(path, {"tabs": ["mine"]})
    assert store.read_json(path) == {"tabs": ["mine"]}


def test_a_filesystem_that_cannot_sync_still_gets_the_write_and_a_failed_sync_is_an_error(tmp_path, monkeypatch):
    path = str(tmp_path / "record.json")
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(errno.EINVAL, "no sync here")))
    store.dump_json(path, [1])
    assert store.read_json(path) == [1]
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(errno.EIO, "lost")))
    with pytest.raises(OSError):
        store.dump_json(path, [2])
    assert store.read_json(path) == [1] and os.listdir(tmp_path) == ["record.json"]


def test_an_exclusive_write_makes_the_file_once_and_never_replaces_one(tmp_path):
    path = str(tmp_path / "queue" / "row-1.json")
    store.dump_json(path, {"first": True}, exclusive=True)
    with pytest.raises(FileExistsError):
        store.dump_json(path, {"second": True}, exclusive=True)
    with pytest.raises(FileExistsError):
        store.write_text(path, "third", exclusive=True)
    assert store.read_json(path) == {"first": True} and os.listdir(os.path.dirname(path)) == ["row-1.json"]


def test_an_exclusive_write_holds_where_the_filesystem_has_no_hard_links(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "link", lambda *_args: (_ for _ in ()).throw(OSError(errno.ENOTSUP, "no links")))
    path = str(tmp_path / "row.json")
    store.dump_json(path, [1], exclusive=True)
    with pytest.raises(FileExistsError):
        store.dump_json(path, [2], exclusive=True)
    assert store.read_json(path) == [1] and os.listdir(tmp_path) == ["row.json"]


def test_a_line_is_appended_whole_with_its_newline_and_the_folder_is_made(tmp_path):
    path = str(tmp_path / "logs" / "reads")
    store.append_line(path, "first")
    store.append_line(path, "second\n")
    store.append_line(path, "")
    store.append_line(path, "two\nlines\n")
    assert _bytes(path) == b"first\nsecond\n\ntwo\nlines\n"


def test_the_receipt_log_gets_one_stripped_line_per_call(bare):
    from cockpitlib.paths import receipt_log

    store.log("NEW TASK-100/001-pr-open by change   \n")
    store.log("ACK TASK-100/001-pr-open")
    assert _bytes(receipt_log()) == b"NEW TASK-100/001-pr-open by change\nACK TASK-100/001-pr-open\n"


def test_a_copy_lands_whole_under_its_new_name(tmp_path):
    source, target = str(tmp_path / "draft.md"), str(tmp_path / "outbox" / "001-body.md")
    store.write_bytes(source, b"body \xc3\xa9\n")
    store.copy_file(source, target)
    assert _bytes(target) == b"body \xc3\xa9\n" and store.read_json(str(tmp_path / "missing.json")) is None
