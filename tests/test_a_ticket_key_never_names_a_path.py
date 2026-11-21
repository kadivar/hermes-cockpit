# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ticket key names one folder under the records and the worktrees: a path, a dot name or an empty key is refused by
every route that takes one and again by the kernel functions that write or remove under it."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
PATHS = ("..", "../TASK-100", "TASK-100/..", "TASK-100/../..", "a/b", "TASK-100/x", "TASK-100\x00", ".", "TASK-100\\..")
NOT_KEYS = (*PATHS, "task-100", "-TASK-100", "TASK 100", "TASK-100\nx")


def _client():
    from dashboard.cockpit.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _keys(victim) -> tuple:
    return (*NOT_KEYS, str(victim), os.path.join("..", "..", os.path.basename(str(victim))))


@pytest.fixture
def world(env, tmp_path, request, monkeypatch):
    """Records of two tickets, a checkout folder, and a folder outside all of them that must outlive every request."""
    from cockpitlib.paths import outbox, qa, wt

    if "pack_file" in request.fixturenames:  # the records folder is the pack's own
        monkeypatch.setenv("COCKPIT_PACK", request.getfixturevalue("pack_file"))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    for root in (qa(), outbox(), wt()):
        for ticket in ("TASK-100", "TASK-200"):
            os.makedirs(os.path.join(root, ticket), exist_ok=True)
            open(os.path.join(root, ticket, "keep.txt"), "w", encoding="utf-8").write("keep")
    return {"victim": victim, "roots": (qa(), outbox(), wt())}


def _intact(world) -> bool:
    kept = [os.path.join(root, ticket, "keep.txt") for root in world["roots"] for ticket in ("TASK-100", "TASK-200")]
    return all(os.path.isfile(path) for path in [str(world["victim"] / "keep.txt"), *kept])


# every route that reads a ticket from the body, with the rest of a body that would otherwise go through
POSTS = (
    ("/upload", {"name": "note.txt", "text": "a note"}),
    ("/reopen-flow", {"prompt": "again"}),
    ("/fetch", {"repo": "api", "branch": "main"}),
    ("/open-ide", {}),
    ("/pr-treat", {"repo": "api", "number": 1}),
    ("/pr-forget", {"repo": "api", "number": 1}),
    ("/pr-seen", {"repo": "api", "number": 1}),
    ("/pr-rereview", {"repo": "api", "number": 1}),
    ("/ci-mark", {"repo": "api", "sha": "abc", "verdict": "flaky"}),
    ("/ci-forget", {"sha": "abc"}),
    ("/ci-dismiss", {"repo": "api", "sha": "abc"}),
    ("/ticket-archive", {}),
    ("/ticket-halt", {}),
    ("/ticket-resume", {}),
    ("/ticket-delete", {"force": True}),
    ("/refusal-send-back", {"note": "again"}),
    ("/session", {"action": "open", "slot": 1}),
    ("/demo", {"env": "lab"}),
    ("/created", {"name": "ada", "body": {"id": 1}}),
    ("/scripted", {"request": "x"}),
    ("/demo-login", {"user": "qa"}),
    ("/session-login", {"user": "qa"}),
    ("/demo-start", {"slot": 1}),
    ("/kickoff", {"mode": "intake", "prompt": "x"}),
)
GETS = (
    ("/worktrees", {}),
    ("/pr", {"repo": "api", "number": 1}),
    ("/pr-diff", {"repo": "api", "number": 1}),
    ("/ticket", {}),
    ("/demo", {}),
    ("/session-card", {}),
    ("/job-stream", {}),
)
NEEDS_A_KEY = (
    "/upload",
    "/ticket-archive",
    "/ticket-halt",
    "/ticket-resume",
    "/ticket-delete",
    "/refusal-send-back",
    "/demo",
    "/created",
    "/scripted",
    "/session-login",
)


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("path,body", POSTS)
def test_a_route_refuses_a_ticket_that_is_not_a_key(world, pack_file, monkeypatch, path, body):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    client = _client()
    for key in _keys(world["victim"]):
        response = client.post(path, json={**body, "ticket": key, "confirm": key})
        assert response.status_code == 400, f"{path} {key!r} {response.status_code} {response.text}"
        assert "bad ticket" in response.json()["detail"]
    assert _intact(world)


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("path,params", GETS)
def test_a_read_route_refuses_a_ticket_that_is_not_a_key(world, pack_file, monkeypatch, path, params):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    client = _client()
    for key in _keys(world["victim"]):
        response = client.get(path, params={**params, "ticket": key})
        assert response.status_code == 400, f"{path} {key!r} {response.status_code} {response.text}"
    assert _intact(world)


def test_the_diff_pane_reads_a_checkout_by_one_folder_name_never_by_a_path(world):
    client = _client()
    for key in (*PATHS, str(world["victim"])):
        response = client.get("/diff", params={"ticket": key, "repo": "api"})
        assert response.status_code == 400 and "bad ticket" in response.json()["detail"], key
    empty = client.get(
        "/diff", params={"ticket": "TASK-missing", "repo": "api"}
    )  # no such checkout: an empty pane, as before
    assert empty.status_code == 200 and empty.json()["diff"] == ""
    assert _intact(world)


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("path", NEEDS_A_KEY)
def test_a_route_that_writes_under_a_ticket_refuses_an_empty_key(world, pack_file, monkeypatch, path):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    body = dict(dict(POSTS)[path])
    for key in ("", None, [], {"a": 1}, 7):
        response = _client().post(path, json={**body, "ticket": key, "confirm": key, "user": "qa"})
        assert response.status_code == 400, f"{path} {key!r} {response.status_code} {response.text}"
    assert _intact(world)


@pytest.mark.parametrize("pack_file", PACKS)
def test_an_empty_key_confirmed_as_empty_does_not_delete_the_records(world, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    assert _client().post("/ticket-delete", json={"ticket": "", "confirm": "", "force": True}).status_code == 400
    assert _client().post("/ticket-archive", json={"ticket": "", "confirm": ""}).status_code == 400
    assert _intact(world)


def test_a_chat_is_named_by_one_folder_name_never_by_a_path(world):
    client = _client()
    for key in (*PATHS, str(world["victim"]), 7, ["own"]):
        for path, body in (("/chat-open", {}), ("/chat-write", {"text": "x"}), ("/chat-resize", {}), ("/chat-end", {})):
            response = client.post(path, json={**body, "ticket": key})
            assert response.status_code == 400 and "bad ticket" in response.json()["detail"], (
                f"{path} {key!r} {response.text}"
            )
        if isinstance(key, str):
            assert client.get("/chat-read", params={"ticket": key}).status_code == 400
            assert client.get("/chat-state", params={"ticket": key}).status_code == 400
    assert (
        client.post("/chat-resize", json={"ticket": "a-name"}).status_code == 200
    )  # a chat no ticket key names is still a chat
    assert client.post("/chat-end", json={}).status_code == 200
    assert _intact(world)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_chat_routes_still_take_the_humans_own_chat(world, pack_file, monkeypatch):
    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    client = _client()
    assert client.get("/chat-state", params={"ticket": "own"}).status_code == 200
    assert client.get("/chat-state").status_code == 200
    assert client.get("/chat-read", params={"ticket": "own"}).status_code == 200
    assert client.get("/job-stream", params={"ticket": "all"}).status_code == 200
    assert client.get("/job-stream").status_code == 200
    assert client.get("/worktrees").status_code == 200
    assert client.get("/demo").status_code == 200


BAD_REPOS = ("../../x", "..", "/abs", "a/../b", "api\x00", "a b", "api/", "./api")


@pytest.mark.parametrize(
    "path,body",
    (
        ("/pr-forget", {"number": 1}),
        ("/pr-seen", {"number": 1}),
        ("/pr-treat", {"number": 1}),
        ("/pr-rereview", {"number": 1}),
        ("/ci-mark", {"sha": "abc", "verdict": "flaky"}),
        ("/ci-dismiss", {"sha": "abc"}),
        ("/fetch", {"branch": "main"}),
        ("/demo-start", {"slot": 1}),
        ("/platform-verdict", {"number": 1, "text": "fine"}),
        ("/platform-seen", {"number": 1}),
        ("/platform-unseen", {"number": 1}),
    ),
)
def test_a_route_refuses_a_repository_that_is_a_path(world, path, body):
    client = _client()
    for repo in BAD_REPOS:
        response = client.post(path, json={**body, "ticket": "TASK-100", "repo": repo})
        assert response.status_code == 400 and "bad repo" in response.json()["detail"], (
            f"{path} {repo!r} {response.text}"
        )
    assert _intact(world)


@pytest.mark.parametrize("path", ("/diff", "/pr", "/pr-diff", "/platform-change"))
def test_a_read_route_refuses_a_repository_that_is_a_path(world, path):
    client = _client()
    for repo in BAD_REPOS:
        assert client.get(path, params={"ticket": "TASK-100", "repo": repo, "number": 1}).status_code == 400, (
            f"{path} {repo!r}"
        )


@pytest.mark.parametrize(
    "path",
    ("/pr-forget", "/pr-seen", "/pr-treat", "/pr-rereview", "/platform-verdict", "/platform-seen", "/platform-unseen"),
)
def test_a_route_refuses_a_number_that_is_not_a_number(world, path):
    client = _client()
    for number in ("1/../../x", "../x", "1.json", -1, 1.5, True, [1]):
        response = client.post(path, json={"ticket": "TASK-100", "repo": "api", "number": number, "text": "fine"})
        assert response.status_code == 400 and "bad number" in response.json()["detail"], (
            f"{path} {number!r} {response.text}"
        )


@pytest.mark.parametrize("path", ("/ci-mark", "/ci-forget", "/ci-dismiss"))
def test_a_route_refuses_a_commit_that_is_not_hexadecimal(world, path):
    client = _client()
    for sha in ("../../../x", "abc/../x", "zz", 7, "a" * 65):
        response = client.post(path, json={"ticket": "TASK-100", "repo": "api", "sha": sha, "verdict": "flaky"})
        assert response.status_code == 400 and "bad sha" in response.json()["detail"], f"{path} {sha!r} {response.text}"


def test_a_repository_in_a_group_and_a_number_sent_as_text_are_still_read(world):
    client = _client()
    assert client.get("/pr", params={"ticket": "TASK-100", "repo": "group/api", "number": 1}).status_code == 200
    assert client.post("/pr-seen", json={"ticket": "TASK-100", "repo": "api", "number": "12"}).status_code < 500
    assert client.post("/pr-forget", json={"ticket": "TASK-100", "repo": "api", "number": "12"}).json()["removed"] == []


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_kernel_removes_nothing_for_a_ticket_that_is_not_a_key(world, pack_file, monkeypatch):
    from cockpitlib.acts import archive_ticket, delete_ticket, remove_worktrees

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    for key in (*_keys(world["victim"]), "", None, 7):
        with pytest.raises(CockpitError, match="bad ticket"):
            delete_ticket(pack, key, force=True)
        with pytest.raises(CockpitError, match="bad ticket"):
            archive_ticket(pack, key)
    for key in (
        *PATHS,
        str(world["victim"]),
        "",
        None,
        7,
    ):  # the collector removes whatever folder it listed: any one folder name
        with pytest.raises(CockpitError, match="bad ticket"):
            remove_worktrees(pack, key)
    assert _intact(world)


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_kernel_writes_nothing_for_a_ticket_that_is_not_a_key(world, pack_file, monkeypatch):
    from cockpitlib.acts import cleanup_settings, keep_created, save_demo, snapshot_settings
    from cockpitlib.paths import qa, records

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    before = sorted(os.listdir(qa())), sorted(os.listdir(records())), sorted(os.listdir(world["victim"]))
    for key in (*_keys(world["victim"]), "", None):
        for write in (
            lambda: save_demo(key, {"env": "lab"}),
            lambda: keep_created(key, "ada", {"id": 1}, pack),
            lambda: snapshot_settings(key, {"a": 1}),
            lambda: cleanup_settings(key),
        ):
            with pytest.raises(CockpitError, match="bad ticket"):
                write()
    assert (sorted(os.listdir(qa())), sorted(os.listdir(records())), sorted(os.listdir(world["victim"]))) == before


def test_a_key_with_a_line_break_after_it_is_not_a_key():
    from cockpitlib.intents import check_ticket

    assert check_ticket("TASK-100", "") == "TASK-100"
    for key in ("TASK-100\n", "TASK-100 ", " TASK-100", b"TASK-100", ["TASK-100"]):
        with pytest.raises(CockpitError, match="bad ticket"):
            check_ticket(key, "")


def test_a_ticket_folder_linked_out_of_the_records_is_not_removed(world, env):
    from cockpitlib.acts import delete_ticket, remove_worktrees
    from cockpitlib.paths import qa, wt

    pack = load(os.environ["COCKPIT_PACK"])
    os.symlink(str(world["victim"]), os.path.join(qa(), "TASK-300"))
    os.symlink(str(world["victim"]), os.path.join(wt(), "TASK-400"))
    with pytest.raises(CockpitError, match="leads outside"):
        delete_ticket(pack, "TASK-300", force=True)
    with pytest.raises(CockpitError, match="leads outside"):
        remove_worktrees(pack, "TASK-400")
    assert _intact(world)


def test_an_intent_id_that_is_a_path_is_no_intent(world):
    from cockpitlib.intents import load as load_intent

    outside = world["victim"] / "001-push-branch.json"
    outside.write_text('{"id": "x"}', encoding="utf-8")
    for iid in (
        f"../../../../{world['victim'].name}/001-push-branch",
        "TASK-100/../../x",
        "../TASK-100/001-push-branch",
        "TASK-100/",
        "/001-push-branch",
        "TASK-100/a\x00b",
        f"{world['victim']}/001-push-branch",
    ):
        with pytest.raises(FileNotFoundError, match="no intent"):
            load_intent(iid)
    client = _client()
    for path in ("/hold", "/confirm", "/drop", "/ack", "/verify"):
        assert client.post(path, json={"id": "TASK-100/../../x", "reason": "r"}).status_code == 400, path


def test_a_record_path_never_leaves_its_folder(world):
    from cockpitlib import ci_watch, halt, pr_watch
    from cockpitlib.acts import change_detail, forget_pr, mark_seen, mark_unseen, pr_state, write_verdict

    for bad in ("../x", "TASK-100/..", "/abs"):
        for build in (
            lambda: halt.path(bad),
            lambda: ci_watch.record_path(bad, "api", "abc"),
            lambda: pr_watch.record_path(bad, "api", 1),
            lambda: pr_state(bad, "api", 1),
        ):
            with pytest.raises(CockpitError, match="bad ticket"):
                build()
    for repo in ("../../../x", "/abs/x", "a\x00b"):
        for build in (
            lambda: pr_watch.record_path("TASK-100", repo, 1),
            lambda: pr_watch.record_path("", repo, 1),
            lambda: ci_watch.record_path("TASK-100", repo, "abc"),
            lambda: forget_pr("TASK-100", repo, 1),
            lambda: change_detail(repo, 1),
            lambda: write_verdict(repo, 1, "fine"),
            lambda: mark_seen({}, repo, 1),
            lambda: mark_unseen(repo, 1),
        ):
            with pytest.raises(CockpitError, match="bad repo"):
                build()
    assert pr_watch.record_path("TASK-100", "group/api", 1).endswith(
        os.path.join("TASK-100", "pr", "group", "api-1.json")
    )
    assert halt.path("").endswith(os.path.join("qa", "halt.json"))
    assert _intact(world)


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_real_ticket_is_still_deleted_and_archived(world, pack_file, monkeypatch):
    from cockpitlib.paths import outbox, qa, wt

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    client = _client()
    archived = client.post("/ticket-archive", json={"ticket": "TASK-200", "confirm": "TASK-200"})
    assert archived.status_code == 200 and archived.json()["out"] == "archived TASK-200"
    assert not os.path.exists(os.path.join(wt(), "TASK-200")) and os.path.isdir(os.path.join(qa(), "TASK-200"))
    removed = client.post("/ticket-delete", json={"ticket": "TASK-100", "confirm": "TASK-100", "force": True})
    assert removed.status_code == 200 and removed.json()["out"] == "deleted TASK-100"
    assert not any(os.path.exists(os.path.join(root, "TASK-100")) for root in (qa(), outbox(), wt()))
    assert os.path.isdir(os.path.join(qa(), "TASK-200")) and os.path.isdir(os.path.join(outbox(), "TASK-200"))
    assert os.path.isfile(world["victim"] / "keep.txt")


@pytest.mark.parametrize("pack_file", PACKS)
@pytest.mark.parametrize("key", ("", None))
def test_no_key_at_all_is_refused_by_everything_that_writes_or_removes(world, pack_file, key, monkeypatch):
    """A read or a listing with no key answers for the records' own level; a write or a removal never does."""
    from cockpitlib import halt, intents, store
    from cockpitlib.acts import (
        archive_ticket,
        delete_ticket,
        halt_ticket,
        keep_created,
        remove_worktrees,
        resume_ticket,
        save_demo,
    )
    from cockpitlib.paths import outbox, qa, wt

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    before = {root: sorted(os.listdir(root)) for root in (qa(), outbox(), wt())}
    for act in (
        lambda: delete_ticket(pack, key, force=True),
        lambda: archive_ticket(pack, key),
        lambda: remove_worktrees(pack, key),
        lambda: keep_created(key, "ada", {"id": 1}, pack),
        lambda: save_demo(key, {"env": "lab"}),
        lambda: halt.write(key, "stop"),
        lambda: halt.clear(key),
        lambda: halt_ticket(pack, key, "stop"),
        lambda: resume_ticket(key),
        lambda: store.ticket_lock(key),
        lambda: intents.reserve_seq(key, "push-branch"),
        lambda: intents.release_seq(key, "001", "push-branch"),
    ):
        with pytest.raises(CockpitError, match="bad ticket"):
            act()
    with pytest.raises(FileNotFoundError, match="no intent"):
        intents.path_of(f"{key or ''}/001-push-branch")
    assert halt.halted(key or "") is None and halt.path(key or "").endswith(os.path.join("qa", "halt.json")), (
        "a read stays tolerant"
    )
    assert {root: sorted(os.listdir(root)) for root in (qa(), outbox(), wt())} == before and _intact(world)


def test_a_marker_at_the_records_own_level_is_still_read(world):
    """A halt.json someone left at the records' own level keeps stopping a creator that names no ticket; it is cleared by hand."""
    from cockpitlib import halt
    from cockpitlib.errors import Conflict
    from cockpitlib.paths import qa

    with open(os.path.join(qa(), "halt.json"), "w", encoding="utf-8") as handle:
        handle.write('{"note": "all stop"}')
    assert halt.halted("") == {"note": "all stop"}
    with pytest.raises(Conflict, match="all stop"):
        halt.refuse("")
    halt.write("TASK-100", "one")
    assert (
        halt.halted("TASK-100") == {"note": "one"}
        and halt.clear("TASK-100")
        and halt.halted("") == {"note": "all stop"}
    )
