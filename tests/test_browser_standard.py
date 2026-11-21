# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The browser model for every cockpit consumer: Hermes 0.23's built-in browser is every lane's; the external browser
(Chrome MCP, the human's or the agents' own-CDP Chrome) is only a test kickoff's option; `cockpit record` makes the
failure videos of a test kickoff. Both fixture packs."""

import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time

import pytest

from cockpitlib.errors import CockpitError, Conflict
from cockpitlib.pack import load
from tests.support import words

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def _remote(pack) -> str:
    from cockpitlib.environments import environments

    return next(item["name"] for item in environments(pack) if not item["slot"])


def _test_kickoff(pack, ticket: str, chrome: bool) -> str:
    from cockpitlib.kickoff import start
    from cockpitlib.plan import init
    from cockpitlib.settings import load as load_settings
    from cockpitlib.settings import save as save_settings

    save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 3}})
    init(ticket, "plan", "go")
    return start(pack, "test", ticket=ticket, chrome=chrome, environment=_remote(pack))["card_id"]


def _on_card(monkeypatch, pack, card: str, lane: str = "tester-1") -> None:
    monkeypatch.setenv("COCKPIT_LANE", lane)
    monkeypatch.setenv("HERMES_KANBAN_TASK", card)
    monkeypatch.setenv("HERMES_KANBAN_BOARD", str(pack["board"]))
    monkeypatch.delenv("COCKPIT_TICKET", raising=False)


# ---------- kickoff: the external browser is a test kickoff's option only ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_only_a_test_kickoff_may_choose_the_external_browser_and_never_a_supervisor_card(env, pack_file, monkeypatch):
    from cockpitlib.kanban import board_cards, card_entry
    from cockpitlib.kickoff import start
    from cockpitlib.paths import watch_dir

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-401"
    for mode in ("intake", "analyst", "review", "rework"):
        with pytest.raises(Conflict, match="test kickoff's option only"):
            start(pack, mode, ticket=ticket, prompt="why", chrome=True)
    with pytest.raises(Conflict, match="never a supervisor card's"):
        start(pack, "test", ticket=ticket, chrome=True, policy="release", environment=_remote(pack))
    assert not os.path.isfile(os.path.join(watch_dir(), "shared-chrome.json"))  # a refusal lends nothing
    card = _test_kickoff(pack, ticket, chrome=True)
    assert card_entry(pack["board"], card)["browser"] == "external"
    body = next(row["body"] for row in board_cards(pack["board"]) if row["id"] == card)
    assert "browser lent for" in body and "browser: external" in body
    assert json.load(open(os.path.join(watch_dir(), "shared-chrome.json"), encoding="utf-8"))["ticket"] == ticket
    plain = _test_kickoff(pack, f"{pack['tracker']['project']}-402", chrome=False)
    assert "browser" not in card_entry(pack["board"], plain)


def test_the_kickoff_page_offers_the_external_browser_on_the_test_flow_only():
    source = open(os.path.join(ROOT, "desktop", "src", "app.js"), encoding="utf-8").read()
    built = open(os.path.join(ROOT, "desktop", "plugin.js"), encoding="utf-8").read()
    for text in (source, built):
        assert "['intake', 'test', 'analyst'].includes(mode)" not in text.replace('"', "'")
        assert "mode === 'test' && chrome" in text.replace('"', "'") or "chrome && mode === 'test'" in text.replace(
            '"', "'"
        )


# ---------- the fence: Chrome MCP only on an external-option test kickoff card ----------


@pytest.mark.parametrize("pack_file", PACKS)
def test_chrome_mcp_runs_only_on_a_test_kickoff_card_started_with_the_external_browser(env, pack_file, monkeypatch):
    from cockpitlib.egress import check_tool
    from cockpitlib.kanban import mark_card, place_card
    from tests.support.boards import set_body

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-411"
    external = _test_kickoff(pack, ticket, chrome=True)
    for tool in ("mcp__chrome__click", "mcp__chrome_devtools__take_snapshot", "mcp__chrome_mcp__navigate_page"):
        monkeypatch.delenv("COCKPIT_LANE", raising=False)
        assert check_tool(tool, {"uid": "1"}) == ""  # the human's own session: untouched
        _on_card(monkeypatch, pack, external)
        assert check_tool(tool, {"uid": "1"}) == "", tool
    # the browser_exec session rule stays: a lane's built-in browser runs in its own named session
    assert check_tool("browser_exec", {"code": "new_tab('https://x.test')", "session": f"tester-1-{ticket}"}) == ""
    # a tester inside the dev flow, a test kickoff without the choice, a worker card that says "browser lent"
    chain = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready", kind="tester", ticket=ticket, pack=pack)
    plain = _test_kickoff(pack, f"{pack['tracker']['project']}-412", chrome=False)
    worker = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", ticket=ticket, pack=pack)
    set_body(pack["board"], worker, "browser lent for 4h\n")
    for card in (chain, plain, worker):
        _on_card(monkeypatch, pack, card)
        refused = check_tool("mcp__chrome__click", {"uid": "1"})
        assert "test kickoff only" in refused and "browser_exec with session" in refused, card
    # a supervisor card (policy release) never, even when it names the choice
    release = place_card(
        pack["board"],
        f"{ticket}: chrome-qa",
        "tester-1",
        "ready",
        kind="test",
        ticket=ticket,
        pack=pack,
        scope="release",
        body="policy: release\nbrowser lent for 4h\n",
    )
    mark_card(pack["board"], release, browser="external")
    _on_card(monkeypatch, pack, release)
    assert "supervisor card never uses it" in check_tool("mcp__chrome__click", {"uid": "1"})
    # the loan ends: the external card is refused too; other MCP servers are not the external browser
    _on_card(monkeypatch, pack, external)
    from cockpitlib.paths import watch_dir

    path = os.path.join(watch_dir(), "shared-chrome.json")
    record = json.load(open(path, encoding="utf-8"))
    json.dump({**record, "at": 1, "until": 1}, open(path, "w", encoding="utf-8"))
    assert "expired" in check_tool("mcp__chrome__click", {"uid": "1"})
    assert check_tool("mcp__docs__search", {"q": "x"}) == ""


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_human_browser_port_answers_only_the_external_test_kickoff_card(env, pack_file, monkeypatch):
    from cockpitlib.egress import check_bound
    from cockpitlib.kanban import place_card
    from tests.support.boards import set_body

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    port = pack.get("human_browser_port")
    if not port:
        pytest.skip("this fixture pack lends no human browser port")
    ticket = f"{pack['tracker']['project']}-421"
    external = _test_kickoff(pack, ticket, chrome=True)
    _on_card(monkeypatch, pack, external)
    assert check_bound(f"curl http://127.0.0.1:{port}/json/version") == ""
    worker = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", ticket=ticket, pack=pack)
    set_body(pack["board"], worker, "browser lent for 4h\n")
    _on_card(monkeypatch, pack, worker, lane="worker-1")
    assert check_bound(f"curl http://127.0.0.1:{port}/json/version") == "blocked"


def test_the_lane_rules_name_hermes_0_23s_browser_and_no_0_22_tool():
    from cockpitlib.browser_card import chrome_mcp

    gone = (
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_vision",
        "browser_console",
    )
    for name in sorted(os.listdir(os.path.join(ROOT, "souls"))):
        text = open(os.path.join(ROOT, "souls", name), encoding="utf-8").read()
        assert not [tool for tool in gone if tool in text], name
    common = open(os.path.join(ROOT, "souls", "_common.md"), encoding="utf-8").read()
    for phrase in ("browser_exec", "new_tab(", "session", "browser_vault", "test kickoff"):
        assert phrase in common, phrase
    tester = open(os.path.join(ROOT, "souls", "tester.md"), encoding="utf-8").read()
    for phrase in ("cockpit record start", "cockpit record stop", "-repro.mp4", "· clip", "README.md"):
        assert phrase in tester, phrase
    inbox = open(os.path.join(ROOT, "desktop", "src", "views", "inbox.js"), encoding="utf-8").read()
    assert "browser_vision" not in inbox
    assert chrome_mcp("mcp__chrome__click") and chrome_mcp("mcp__chrome_devtools__click")
    assert not chrome_mcp("mcp__chromecast__play") and not chrome_mcp("browser_exec")


# ---------- cockpit record ----------


class FakeTarget:
    """A page target on loopback that speaks enough CDP for a recording: /json/list, /json/version, a page socket
    that answers captureScreenshot and pushes screencast frames until stopScreencast."""

    def __init__(self, frames):
        from cockpitlib.cdp_ws import decode_frame, encode_frame

        self.decode, self.encode = decode_frame, encode_frame
        self.frames = [base64.b64encode(frame).decode() for frame in frames]
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.methods = []
        self.acks = 0
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.alive:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        lines = head.decode().split("\r\n")
        path = lines[0].split()[1]
        headers = {line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip() for line in lines[1:] if ":" in line}
        if headers.get("upgrade", "").lower() == "websocket":
            accept = base64.b64encode(
                hashlib.sha1((headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode()
            conn.sendall(
                f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode()
            )
            self._socket(conn, rest)
            return
        page = f"ws://127.0.0.1:{self.port}/devtools/page/P1"
        body = json.dumps(
            [
                {
                    "type": "page",
                    "url": "about:blank",
                    "title": "",
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/P0",
                },
                {"type": "page", "url": "https://app.test/editor", "title": "Editor", "webSocketDebuggerUrl": page},
            ]
            if path.startswith("/json/list")
            else {"webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/browser/B"}
        )
        conn.sendall(
            f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}".encode()
        )
        conn.close()

    def _socket(self, conn, buffer):
        lock = threading.Lock()
        pushing = {"on": False}

        def send(message):
            with lock:
                conn.sendall(self.encode(json.dumps(message).encode(), mask=False))

        def push():
            number = 0
            while pushing["on"]:
                send(
                    {
                        "method": "Page.screencastFrame",
                        "params": {"data": self.frames[number % len(self.frames)], "sessionId": number, "metadata": {}},
                    }
                )
                number += 1
                time.sleep(0.15)

        while True:
            frame = self.decode(buffer)
            if frame is None:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    return
                if not chunk:
                    pushing["on"] = False
                    return
                buffer += chunk
                continue
            _fin, opcode, payload, used = frame
            buffer = buffer[used:]
            if opcode == 8:
                pushing["on"] = False
                return
            message = json.loads(payload)
            method = message.get("method")
            self.methods.append(method)
            result = {}
            if method == "Page.captureScreenshot":
                result = {"data": self.frames[0]}
            elif method == "Page.startScreencast":
                pushing["on"] = True
                threading.Thread(target=push, daemon=True).start()
            elif method == "Page.stopScreencast":
                pushing["on"] = False
            elif method == "Page.screencastFrameAck":
                self.acks += 1
            send({"id": message.get("id"), "result": result})

    def close(self):
        self.alive = False
        self.server.close()


def _jpegs(folder) -> list:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=321x241:rate=1",
            "-frames:v",
            "3",
            "-q:v",
            "4",
            os.path.join(folder, "f%02d.jpg"),
        ],
        check=True,
    )
    return [open(os.path.join(folder, f"f{n:02d}.jpg"), "rb").read() for n in (1, 2, 3)]


def _session_browser(lane: str, session: str, port: int) -> None:
    """Lay out the DevToolsActivePort Hermes 0.23's launcher leaves for a named browser_exec session of this seat."""
    from cockpitlib.lanes import profile_dir

    home = os.path.normcase(os.path.realpath(profile_dir(lane)))
    os.makedirs(home, exist_ok=True)
    digest = hashlib.sha256(f"{home}\0bu-named-{session}".encode()).hexdigest()[:16]
    folder = os.path.join(home, "cache", "browser", "chromium", f"{digest}-4242-99")
    os.makedirs(folder)
    open(os.path.join(folder, "DevToolsActivePort"), "w", encoding="utf-8").write(f"{port}\n/devtools/browser/B\n")


def _run_dir(pack, ticket: str) -> str:
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import next_run_dir

    folder = next_run_dir(pack, os.path.join(qa(), ticket))
    os.makedirs(folder)
    return folder


@pytest.mark.parametrize("pack_file", PACKS)
def test_record_refuses_every_card_but_a_test_kickoff_and_keeps_to_its_run_folder(env, pack_file, monkeypatch):
    from cockpitlib import record
    from cockpitlib.kanban import place_card
    from cockpitlib.paths import qa, workspace

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-431"
    card = _test_kickoff(pack, ticket, chrome=False)
    run = _run_dir(pack, ticket)
    videos = os.path.join(run, words.evidence(pack), "videos")
    good = os.path.relpath(os.path.join(videos, "s3-save-button-repro.mp4"), workspace())
    chain = place_card(pack["board"], f"{ticket}: tester", "tester-1", "ready", kind="tester", ticket=ticket, pack=pack)
    release = place_card(
        pack["board"],
        f"{ticket}: chrome-qa",
        "tester-1",
        "ready",
        kind="test",
        ticket=ticket,
        pack=pack,
        scope="release",
    )
    worker = place_card(pack["board"], f"{ticket}: work", "worker-1", "ready", ticket=ticket, pack=pack)
    for other, lane, why in (
        (chain, "tester-1", "only on a test kickoff card"),
        (worker, "worker-1", "only on a test kickoff card"),
        (release, "tester-1", "not for supervisor cards"),
    ):
        _on_card(monkeypatch, pack, other, lane=lane)
        with pytest.raises(CockpitError, match=why):
            record.start(pack, f"{lane}-{ticket}", good, "order 1", "the editor")
    _on_card(monkeypatch, pack, card)
    session = f"tester-1-{ticket}"
    for out, why in (
        ("../outside.mp4", "under the records"),
        (os.path.join(qa(), ticket, "x.mp4"), words.evidence(pack) + "/videos"),
        (os.path.join(videos, "save-button.mp4"), "named <scenario>-<slug>-repro.mp4"),
        (
            os.path.join(qa(), ticket, "notarun", words.evidence(pack), "videos", "s3-x-repro.mp4"),
            "not a test run folder",
        ),
        (
            os.path.join(
                qa(),
                f"{pack['tracker']['project']}-999",
                os.path.basename(run),
                words.evidence(pack),
                "videos",
                "s3-x-repro.mp4",
            ),
            "not this card's ticket",
        ),
    ):
        with pytest.raises(CockpitError, match=why):
            record.video_path(pack, out, ticket)
    with pytest.raises(CockpitError, match="own browser session"):
        record.start(pack, f"tester-2-{ticket}", good, "order 1", "the editor")
    with pytest.raises(CockpitError, match="record-id"):
        record.start(pack, session, good, "x" * 121, "the editor")
    with pytest.raises(CockpitError, match="no live built-in browser"):
        record.start(pack, session, good, "order 1", "the editor")
    # never over a file: a taken name moves to -take2, -take3
    first = record.video_path(pack, good, ticket)["path"]
    assert first.endswith("s3-save-button-repro.mp4")
    open(first, "wb").write(b"old")
    assert record.video_path(pack, good, ticket)["path"].endswith("s3-save-button-repro-take2.mp4")
    open(first.replace(".mp4", "-take2.mp4"), "wb").write(b"old")
    assert record.video_path(pack, good, ticket)["path"].endswith("s3-save-button-repro-take3.mp4")
    assert open(first, "rb").read() == b"old"


def test_record_refuses_a_secret_in_its_arguments(bare, monkeypatch):
    from cockpitlib import record

    monkeypatch.setattr("cockpitlib.scrub.holds_secret", lambda texts: any("hunter2" in text for text in texts))
    with pytest.raises(CockpitError, match="secret"):
        record.start(load(os.environ["COCKPIT_PACK"]), "tester-1-TASK-1", "x.mp4", "order 1", "password hunter2 typed")


def test_the_record_cli_checks_its_shape_before_it_runs(bare, capsys):
    from cockpitlib.cli import main

    assert main(["record"]) == 2
    assert main(["record", "start", "--session", "tester-1-TASK-1"]) == 2
    assert "needs --out" in capsys.readouterr().err  # --record-id and --on-screen are optional
    assert main(["record", "stop"]) == 2
    assert main(["record", "start", "--bogus", "x"]) == 2
    assert (
        main(
            [
                "record",
                "start",
                "--session",
                "a",
                "--out",
                "b",
                "--record-id",
                "c",
                "--on-screen",
                "d",
                "--max-seconds",
                "x",
            ]
        )
        == 2
    )
    assert main(["record", "status"]) == 0
    assert json.loads(capsys.readouterr().out) == {"recordings": []}
    assert main(["record", "stop", "--session", "tester-1-TASK-1"]) == 1  # nothing running: the reason, exit 1


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg and ffprobe make and check the video")
@pytest.mark.parametrize("pack_file", PACKS)
def test_record_start_and_stop_make_a_playable_video_and_its_readme_line(env, pack_file, monkeypatch, tmp_path):
    from cockpitlib import record
    from cockpitlib.cli import main
    from cockpitlib.paths import workspace

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-441"
    card = _test_kickoff(pack, ticket, chrome=False)
    run = _run_dir(pack, ticket)
    target = FakeTarget(_jpegs(str(tmp_path)))
    session = f"tester-1-{ticket}"
    _session_browser("tester-1", session, target.port)
    _on_card(monkeypatch, pack, card)
    out = os.path.relpath(os.path.join(run, words.evidence(pack), "videos", "s7-totals-wrong-repro.mp4"), workspace())
    try:
        started = record.start(pack, session, out, "order 4711", "the saved order with the form open", max_seconds=30)
        assert started["tab"] == "https://app.test/editor" and started["recording"] == out
        with pytest.raises(CockpitError, match="is running"):
            record.start(pack, session, out, "order 4711", "again")
        assert record.status(session)["recordings"][0]["running"] is True
        time.sleep(1.5)
        assert main(["record", "stop", "--session", session]) == 0
    finally:
        target.close()
    assert "Page.startScreencast" in target.methods and "Page.stopScreencast" in target.methods and target.acks > 0
    video = os.path.join(workspace(), out)
    assert record.playable(video) == ""
    probe = record._probe(video)
    assert (
        probe["rate"] == "8/1" and probe["pix_fmt"] == "yuv420p" and probe["codec"] == "h264" and probe["duration"] >= 1
    )
    readme = open(os.path.join(os.path.dirname(video), "README.md"), encoding="utf-8").read()
    assert "## s7-totals-wrong-repro.mp4" in readme and "Test record: order 4711" in readme
    assert "On screen at start: the saved order with the form open" in readme and "Scenario: #s7" in readme
    assert record.status()["recordings"] == []  # the frames and the state are gone
    # a second take of the same scenario never replaces the first
    target = FakeTarget(_jpegs(str(tmp_path)))
    shutil.rmtree(os.path.join(os.path.realpath(os.path.join(env["home"], "profiles", "tester-1")), "cache"))
    _session_browser("tester-1", session, target.port)
    try:
        again = record.start(pack, session, out, "order 4712", "a new order, saved")
        assert again["recording"].endswith("s7-totals-wrong-repro-take2.mp4")
        result = record.stop(pack, session)
    finally:
        target.close()
    assert result["video"].endswith("-take2.mp4") and record.playable(os.path.join(workspace(), result["video"])) == ""
    readme = open(os.path.join(os.path.dirname(video), "README.md"), encoding="utf-8").read()
    assert readme.count("## s7-totals-wrong-repro") == 2


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg and ffprobe check the video")
def test_a_video_that_does_not_play_is_refused(tmp_path):
    from cockpitlib import record

    broken = tmp_path / "x.mp4"
    broken.write_bytes(b"\0" * 64)
    assert record.playable(str(broken)) != ""
    assert record.playable(str(tmp_path / "missing.mp4")) == "empty file"


# ---------- edges: what makes a card external, the loan, the session, leftovers ----------


def _comment(pack, card: str, text: str) -> None:
    from cockpitlib.kanban import BoardWrites

    writes = BoardWrites(pack["board"])
    writes.comment(card, "tester-1", text)
    writes.flush()


def _set_status(pack, card: str, status: str) -> None:
    import sqlite3

    from cockpitlib.kanban import db_path

    connection = sqlite3.connect(db_path(pack["board"]))
    connection.execute("update tasks set status = ? where id = ?", (status, card))
    connection.commit()
    connection.close()


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_comment_never_makes_a_card_external_and_record_needs_the_running_loan(env, pack_file, monkeypatch):
    from cockpitlib import record
    from cockpitlib.browser_card import facts
    from cockpitlib.egress import check_tool
    from cockpitlib.paths import watch_dir, workspace

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-451"
    plain = _test_kickoff(pack, ticket, chrome=False)
    _comment(pack, plain, "browser lent for 4h\nchrome: shared")  # a lane can write this: it counts for nothing
    assert facts(pack, plain)["external"] is False
    _on_card(monkeypatch, pack, plain)
    assert "test kickoff only" in check_tool("mcp__chrome__click", {"uid": "1"})
    run = _run_dir(pack, ticket)
    out = os.path.relpath(os.path.join(run, words.evidence(pack), "videos", "s1-x-repro.mp4"), workspace())
    with pytest.raises(CockpitError, match="no live built-in browser"):  # the built-in browser, never the external one
        record.start(pack, f"tester-1-{ticket}", out, "order 1", "the editor")
    # a legit external card: no loan, then an expired loan -> refused before anything is recorded
    other = f"{pack['tracker']['project']}-452"
    external = _test_kickoff(pack, other, chrome=True)
    _on_card(monkeypatch, pack, external)
    path = os.path.join(watch_dir(), "shared-chrome.json")
    loan = json.load(open(path, encoding="utf-8"))
    os.remove(path)
    out = os.path.relpath(
        os.path.join(_run_dir(pack, other), words.evidence(pack), "videos", "s1-x-repro.mp4"), workspace()
    )
    with pytest.raises(CockpitError, match="not lent"):
        record.start(pack, f"tester-1-{other}", out, "order 1", "the editor")
    json.dump({**loan, "at": 1, "until": 1}, open(path, "w", encoding="utf-8"))
    with pytest.raises(CockpitError, match="expired"):
        record.start(pack, f"tester-1-{other}", out, "order 1", "the editor")
    assert "expired" in check_tool("mcp__chrome__click", {"uid": "1"})


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_plan_card_follows_only_its_own_open_run_card(env, pack_file, monkeypatch):
    from cockpitlib.acts import post_test_plan
    from cockpitlib.browser_card import facts

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-461"
    old = _test_kickoff(pack, ticket, chrome=True)
    _set_status(pack, old, "done")  # an old finished external test of the ticket
    fresh = _test_kickoff(pack, ticket, chrome=False)
    _on_card(monkeypatch, pack, fresh)
    plan = post_test_plan(pack, ticket, "plain plan\n")["card"]
    assert facts(pack, plan)["test_kickoff"] and facts(pack, plan)["external"] is False
    _set_status(pack, fresh, "done")
    run = _test_kickoff(pack, ticket, chrome=True)
    _on_card(monkeypatch, pack, run)
    plan = post_test_plan(pack, ticket, "external plan\n")["card"]
    assert facts(pack, plan)["external"] is True
    _set_status(pack, run, "done")  # its run card ended: the plan card no longer
    assert facts(pack, plan)["external"] is False


def test_the_session_is_the_exact_lane_and_the_cards_ticket():
    from cockpitlib.record import _session_name

    assert _session_name("tester-1-TASK-1", "tester-1", "TASK-1") == "tester-1-TASK-1"
    for session, lane in (
        ("tester-1-TASK-1", "tester"),
        ("tester-1-TASK-2", "tester-1"),
        ("tester-1-TASK-1x", "tester-1"),
    ):
        with pytest.raises(CockpitError, match="own browser session"):
            _session_name(session, lane, "TASK-1")
    assert _session_name("anything-1", "", "") == "anything-1"  # the human names any session


@pytest.mark.parametrize("pack_file", PACKS)
def test_the_sweep_stops_recorders_of_ended_cards_and_removes_old_frames(env, pack_file, monkeypatch):
    from cockpitlib import record

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    pack = load(pack_file)
    ticket = f"{pack['tracker']['project']}-471"
    ended = _test_kickoff(pack, ticket, chrome=False)
    live = _test_kickoff(pack, f"{pack['tracker']['project']}-472", chrome=False)
    folder = record._state_dir()
    os.makedirs(folder, exist_ok=True)
    child = subprocess.Popen(["sleep", "60"], start_new_session=True)
    states = {}
    for name, card, pid in (("tester-1-A", ended, child.pid), ("tester-1-B", live, 0)):
        frames = os.path.join(folder, f"{name}.frames")
        os.makedirs(frames)
        states[name] = {
            "session": name,
            "card": card,
            "board": str(pack["board"]),
            "frames": frames,
            "pid": pid,
            "started": time.time(),
        }
        record._write_json(record._state_file(name), states[name])
    orphan = os.path.join(folder, "tester-1-C.frames")
    os.makedirs(orphan)
    os.utime(orphan, (time.time() - 2 * 86400,) * 2)
    _set_status(pack, ended, "done")
    try:
        record.sweep(pack)
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
    assert not os.path.exists(states["tester-1-A"]["frames"]) and not os.path.exists(record._state_file("tester-1-A"))
    assert os.path.isdir(states["tester-1-B"]["frames"]) and os.path.isfile(record._state_file("tester-1-B"))
    assert not os.path.exists(orphan)
    called = []
    monkeypatch.setattr("cockpitlib.record.sweep", lambda pack: called.append(pack))
    from cockpitlib.ops import slot_gc

    slot_gc(pack)
    assert called  # the hourly slot-gc runs the sweep


def test_a_video_never_lands_on_a_taken_name(tmp_path, monkeypatch):
    from cockpitlib import record

    monkeypatch.setenv("COCKPIT_WORKSPACE", str(tmp_path))  # a taken name also counts the recordings still running
    temp = tmp_path / ".part.mp4"
    temp.write_bytes(b"new")
    out = tmp_path / "s1-x-repro.mp4"
    out.write_bytes(b"old")  # taken between the check and the link
    final = record._place(str(temp), str(out))
    assert final.endswith("s1-x-repro-take2.mp4") and out.read_bytes() == b"old"
    assert open(final, "rb").read() == b"new"
