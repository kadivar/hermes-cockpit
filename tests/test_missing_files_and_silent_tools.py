# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quiet branches of the recorder, its DevTools socket, the standup note, the worktree pass, the self-update, the
quota gate, the usage readers, the plan reader, the connector child, the browser facts and the vault: what each does when
a file is missing, a tool does not answer, or the input has a shape nobody planned for."""

import base64
import builtins
import hashlib
import io
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import types

import pytest

from cockpitlib.errors import CockpitError
from cockpitlib.pack import load
from cockpitlib.test_flow import evidence_dir


def _pack():
    return load(os.environ["COCKPIT_PACK"])


def _done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, stdout=out, stderr=err)


# ---------- record: names and folders ----------


def _first_run(ticket: str) -> str:
    """The ticket's first run folder, by the bound pack's own pattern."""
    from cockpitlib.paths import qa
    from cockpitlib.test_flow import next_run_dir

    folder = next_run_dir(_pack(), os.path.join(qa(), ticket))
    os.makedirs(folder)
    return folder


def test_a_session_name_with_other_characters_is_refused():
    from cockpitlib import record

    with pytest.raises(CockpitError, match="--session takes"):
        record._session_name("not a name!", "")
    assert record._session_name(" tester-1-ACME-1 ", "") == "tester-1-ACME-1"


def test_the_video_path_needs_a_name_an_existing_run_and_a_real_videos_folder(env, monkeypatch):
    from cockpitlib import record
    from cockpitlib.paths import qa

    pack = _pack()
    run = _first_run("ACME-771")
    with pytest.raises(CockpitError, match="--out names the video"):
        record.video_path(pack, "  ")
    kept = evidence_dir(pack)
    absent = os.path.join(qa(), "ACME-771", "test_run_009", kept, "videos", "s1-save-repro.mp4")
    with pytest.raises(CockpitError, match="test_run_009 is not a test run folder of ACME-771"):
        record.video_path(pack, absent)
    # the videos folder swapped for a link while the path was being checked
    elsewhere = os.path.join(str(env["root"]), "elsewhere")
    os.makedirs(elsewhere)
    real = os.makedirs

    def linked(path, *args, **kwargs):
        if str(path).endswith(os.path.join(kept, "videos")):
            real(os.path.dirname(path), exist_ok=True)
            os.symlink(elsewhere, path)
            return
        real(path, *args, **kwargs)

    monkeypatch.setattr(os, "makedirs", linked)
    with pytest.raises(CockpitError, match="may not be a link"):
        record.video_path(pack, os.path.join(run, kept, "videos", "s1-save-repro.mp4"))
    assert os.listdir(elsewhere) == []


def test_a_free_name_is_only_made_for_a_video_name(env, tmp_path):
    from cockpitlib import record

    with pytest.raises(CockpitError, match="not a video name: notes.txt"):
        record.free_name(str(tmp_path / "notes.txt"))


# ---------- record: finding the browser ----------


def test_the_devtools_port_file_is_read_only_when_it_names_a_port_and_a_browser_path(tmp_path):
    from cockpitlib import record

    assert record._devtools_port(str(tmp_path)) is None
    (tmp_path / "DevToolsActivePort").write_text("soon\n/devtools/browser/B\n", encoding="utf-8")
    assert record._devtools_port(str(tmp_path)) is None
    (tmp_path / "DevToolsActivePort").write_text("9333\n/somewhere/else\n", encoding="utf-8")
    assert record._devtools_port(str(tmp_path)) is None
    (tmp_path / "DevToolsActivePort").write_text("9333\n/devtools/browser/B\n", encoding="utf-8")
    assert record._devtools_port(str(tmp_path)) == (9333, "/devtools/browser/B")


def test_a_port_nobody_answers_on_is_not_live(monkeypatch):
    from cockpitlib import record

    def refused(url, timeout=3.0):
        raise OSError("connection refused")

    monkeypatch.setattr(record, "_get_json", refused)
    assert record._live(9333) is False
    monkeypatch.setattr(record, "_get_json", lambda url, timeout=3.0: {"webSocketDebuggerUrl": "ws://127.0.0.1:9333/x"})
    assert record._live(9333) is True


def test_the_external_browser_port_is_the_packs_then_the_seats_then_chromes_default(env):
    from cockpitlib import record
    from cockpitlib.lanes import profile_dir

    assert record._seat_cdp_port("") is None
    assert record.browser_port({}, "", "s", external=True) == 9222
    os.makedirs(profile_dir("tester-1"))
    with open(os.path.join(profile_dir("tester-1"), "config.yaml"), "w", encoding="utf-8") as handle:
        handle.write("browser:\n  cdp_url: http://127.0.0.1:9555/\n")
    assert record._seat_cdp_port("tester-1") == 9555
    assert record.browser_port({}, "tester-1", "s", external=True) == 9555
    assert record.browser_port({"human_browser_port": 9333}, "tester-1", "s", external=True) == 9333
    with open(os.path.join(profile_dir("tester-1"), "config.yaml"), "w", encoding="utf-8") as handle:
        handle.write("browser:\n  cdp_url: https://browser.example.test:9555\n")
    assert record._seat_cdp_port("tester-1") is None  # only a loopback endpoint is a seat's own browser


def test_the_page_to_record_is_a_real_tab_and_a_browser_without_one_is_refused(monkeypatch):
    from cockpitlib import record

    answer = {"pages": []}

    def listed(url, timeout=3.0):
        if isinstance(answer["pages"], Exception):
            raise answer["pages"]
        return answer["pages"]

    monkeypatch.setattr(record, "_get_json", listed)
    answer["pages"] = OSError("refused")
    with pytest.raises(CockpitError, match="port 9333 does not answer: refused"):
        record.page_target(9333)
    answer["pages"] = [{"type": "service_worker", "webSocketDebuggerUrl": "ws://x"}, "junk"]
    with pytest.raises(CockpitError, match="has no page to record"):
        record.page_target(9333)
    answer["pages"] = [
        {"type": "page", "webSocketDebuggerUrl": "ws://a", "url": "about:blank"},
        {"type": "page", "webSocketDebuggerUrl": "ws://b", "url": "https://app.example.test/orders", "title": "Orders"},
    ]
    assert record.page_target(9333) == {"ws": "ws://b", "url": "https://app.example.test/orders", "title": "Orders"}
    assert record.page_target(9333, "orders")["ws"] == "ws://b"
    with pytest.raises(CockpitError, match="no tab whose URL holds 'reports'"):
        record.page_target(9333, "reports")


# ---------- record: processes ----------


def test_a_pid_that_is_no_number_is_not_alive_and_a_zombie_is_not_either(monkeypatch):
    from cockpitlib import record

    assert record._alive(None) is False
    assert record._alive("soon") is False
    assert record._alive(os.getpid()) is True
    real = builtins.open

    def procfs(path, *args, **kwargs):
        if str(path).startswith("/proc/"):
            return io.StringIO(f"{os.getpid()} (python) Z 1 1")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", procfs)
    assert record._alive(os.getpid()) is False


def test_killing_a_recorder_skips_a_dead_one_and_survives_a_group_that_is_gone(monkeypatch):
    from cockpitlib import record

    asked = []

    def gone(pid, sig):
        asked.append((pid, sig))
        raise ProcessLookupError("no such group")

    monkeypatch.setattr(os, "killpg", gone)
    record._kill(None)
    assert asked == []
    record._kill(os.getpid())
    assert asked == [(os.getpid(), signal.SIGTERM)]


def test_a_recording_without_a_card_lives_while_its_recorder_runs():
    from cockpitlib import record

    assert record._card_open({"pid": os.getpid()}) is True
    assert record._card_open({"pid": None, "card": "", "board": "b"}) is False


# ---------- record: state, status, sweep ----------


def _state_dir() -> str:
    from cockpitlib import record

    os.makedirs(record._state_dir(), exist_ok=True)
    return record._state_dir()


def test_status_reads_one_session_and_skips_a_state_file_that_is_not_json(env):
    from cockpitlib import record

    folder = _state_dir()
    frames = os.path.join(folder, "one.frames")
    os.makedirs(frames)
    for name in ("000000.jpg", "000001.jpg", "ready"):
        open(os.path.join(frames, name), "wb").close()
    record._write_json(
        os.path.join(folder, "one.json"),
        {"session": "one", "out": "/x/one.mp4", "frames": frames, "pid": None, "started": time.time()},
    )
    record._write_json(
        os.path.join(folder, "two.json"),
        {"session": "two", "out": "/x/two.mp4", "frames": "", "pid": None, "started": time.time()},
    )
    open(os.path.join(folder, "torn.json"), "w", encoding="utf-8").write("{")
    assert sorted(row["session"] for row in record.status()["recordings"]) == ["one", "two"]
    only = record.status("one")["recordings"]
    assert [(row["session"], row["out"], row["running"], row["frames"]) for row in only] == [
        ("one", "/x/one.mp4", False, 2)
    ]


def test_the_sweep_keeps_fresh_frames_of_an_unreadable_state_and_removes_orphans(env, monkeypatch):
    from cockpitlib import record

    folder = _state_dir()
    for name in ("torn.frames", "orphan.frames", "vanishing.frames"):
        os.makedirs(os.path.join(folder, name))
    open(os.path.join(folder, "torn.json"), "w", encoding="utf-8").write("{")
    real = os.path.getmtime

    def mtime(path):
        if str(path).endswith("vanishing.frames"):
            raise FileNotFoundError(path)
        return real(path)

    monkeypatch.setattr(os.path, "getmtime", mtime)
    assert record.sweep() == {"stopped": [], "removed": ["orphan.frames"]}
    assert sorted(name for name in os.listdir(folder) if name.endswith(".frames")) == [
        "torn.frames",
        "vanishing.frames",
    ]


# ---------- record: start ----------


class _Child:
    def __init__(self, code):
        self.pid, self.code = 424242, code

    def poll(self):
        return self.code


def _start_ready(env, monkeypatch, ticket: str, child):
    """A test kickoff card's start on its run folder, the browser and the recorder process stood in.
    Returns (pack, session, out, seen)."""
    from cockpitlib import record
    from tests.test_browser_standard import _on_card, _test_kickoff

    pack = _pack()
    card = _test_kickoff(pack, ticket, chrome=False)
    _on_card(monkeypatch, pack, card)
    run = _first_run(ticket)
    session = f"tester-1-{ticket}"
    seen = {"card": card}
    monkeypatch.setattr(record, "browser_port", lambda pack, lane, session, external: 9333)
    monkeypatch.setattr(
        record,
        "page_target",
        lambda port, url_contains="": {
            "ws": "ws://127.0.0.1:9333/p",
            "url": "https://app.example.test/",
            "title": "App",
        },
    )
    monkeypatch.setattr(record.time, "sleep", lambda seconds: None)

    def spawn(argv, stdin=None, stdout=None, stderr=None, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        seen["state"] = json.load(open(record._state_file(session), encoding="utf-8"))
        child.spawned(stdout)
        return child

    monkeypatch.setattr(record.subprocess, "Popen", spawn)
    return pack, session, os.path.join(run, evidence_dir(pack), "videos", "s2-save-button-repro.mp4"), seen


def test_start_refuses_a_long_screen_line_and_a_cap_outside_its_range(env):
    from cockpitlib import record

    pack = _pack()
    with pytest.raises(CockpitError, match="--on-screen says in one line"):
        record.start(pack, "tester-1-ACME-772", "x", "record 1", "word " * 80)
    for seconds in (2, 601):
        with pytest.raises(CockpitError, match="--max-seconds is 5 to 600"):
            record.start(pack, "tester-1-ACME-772", "x", "record 1", "the editor", max_seconds=seconds)


def test_a_new_start_clears_what_a_dead_recording_of_the_session_left(env):
    from cockpitlib import record
    from cockpitlib.paths import hermes_home

    for name in ("tester", "tester-1"):
        os.makedirs(os.path.join(hermes_home(), "profiles", name))
    assert record._profiles() == ["tester-1", "tester"]  # the longest name first: tester-1-ACME-1 is tester-1's session
    folder = _state_dir()
    stale = os.path.join(folder, "tester-1-ACME-775.frames")
    os.makedirs(stale)
    record._write_json(
        record._state_file("tester-1-ACME-775"), {"session": "tester-1-ACME-775", "pid": None, "frames": stale}
    )
    with pytest.raises(CockpitError, match="--out names the video"):
        record.start(_pack(), "tester-1-ACME-775", "", "record 1", "the editor")
    assert os.listdir(folder) == []


def test_a_recorder_that_exits_before_it_attaches_is_reported_with_its_last_line(env, monkeypatch):
    from cockpitlib import record

    class Exited(_Child):
        def spawned(self, log):
            log.write("starting\nrecorder: the target closed the handshake\n")
            log.flush()

    pack, session, out, seen = _start_ready(env, monkeypatch, "ACME-773", Exited(1))
    with pytest.raises(CockpitError, match="did not attach to the page: recorder: the target closed the handshake"):
        record.start(pack, session, out, "record 1", "the editor")
    assert seen["kwargs"]["start_new_session"] is True
    assert seen["state"]["out"] == out and seen["state"]["card"] == seen["card"] and seen["state"]["lane"] == "tester-1"
    assert os.listdir(_state_dir()) == []  # nothing of the recording stays
    assert not os.path.exists(out)


def test_a_recorder_that_never_gets_ready_is_stopped(env, monkeypatch):
    from cockpitlib import record

    class Hanging(_Child):
        def spawned(self, log):
            pass

    pack, session, out, _seen = _start_ready(env, monkeypatch, "ACME-774", Hanging(None))
    monkeypatch.setattr(record, "START_WAIT", 0.0)
    killed = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(CockpitError, match="did not attach to the page: no answer from the browser"):
        record.start(pack, session, out, "record 1", "the editor")
    assert killed == [(424242, signal.SIGTERM)]
    assert record._log_tail("no-such-session") == ""


# ---------- record: the detached recorder ----------

JPEG = base64.b64encode(b"\xff\xd8 a frame \xff\xd9").decode()


def _recorder(monkeypatch, tmp_path, failing=(), polls=(), started=None, max_seconds=60):
    """run_recorder against a scripted socket; returns (the socket, frames.json, the frames folder)."""
    from cockpitlib import cdp_ws, record

    frames = tmp_path / "frames"
    frames.mkdir()
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "frames": str(frames),
                "ws": "ws://127.0.0.1:9333/p",
                "started": started or time.time(),
                "max_seconds": max_seconds,
            }
        ),
        encoding="utf-8",
    )
    handlers = {}
    monkeypatch.setattr(record.signal, "signal", lambda number, handler: handlers.__setitem__(number, handler))
    made = []

    class Scripted:
        def __init__(self, url):
            self.url, self.calls, self.sent, self.closed, self.polls = url, [], [], False, list(polls)
            made.append(self)

        def call(self, method, params=None, timeout=10.0):
            self.calls.append(method)
            if method in failing:
                raise failing[method]
            return {"data": JPEG} if method == "Page.captureScreenshot" else {}

        def poll(self, timeout=0.5):
            step = self.polls.pop(0) if self.polls else "term"
            if step == "term":
                handlers[signal.SIGTERM](signal.SIGTERM, None)
                return None
            return step

        def send(self, message):
            self.sent.append(message)

        def close(self):
            self.closed = True

    monkeypatch.setattr(cdp_ws, "Socket", Scripted)
    record.run_recorder(str(state))
    return made[0], json.loads((frames / "frames.json").read_text(encoding="utf-8")), frames


def test_the_recorder_keeps_frames_fills_idle_time_with_screenshots_and_ends_on_a_signal(monkeypatch, tmp_path):
    from cockpitlib import record

    monkeypatch.setattr(record, "IDLE_SHOT", 0.0)
    frame = {"method": "Page.screencastFrame", "params": {"data": JPEG, "sessionId": 7}}
    wire, listed, frames = _recorder(monkeypatch, tmp_path, polls=[None, frame, {"method": "Page.loadEventFired"}])
    assert listed["why"] == "terminated"
    # the first screenshot, an idle one, the screencast frame, two more idle ones (an event that is no frame, the signal), the last screen
    assert [item["file"] for item in listed["frames"]] == [f"{n:06d}.jpg" for n in range(6)]
    assert (frames / "000002.jpg").read_bytes() == base64.b64decode(JPEG)
    assert wire.sent == [{"id": 0, "method": "Page.screencastFrameAck", "params": {"sessionId": 7}}]
    assert wire.calls[:2] == ["Page.captureScreenshot", "Page.startScreencast"] and wire.calls[-2:] == [
        "Page.stopScreencast",
        "Page.captureScreenshot",
    ]
    assert wire.closed and (frames / "ready").exists() and (frames / "done").exists()


def test_the_recorder_stops_at_its_time_cap_and_a_browser_that_left_costs_only_the_last_frame(monkeypatch, tmp_path):
    from cockpitlib import cdp_ws

    wire, listed, frames = _recorder(
        monkeypatch,
        tmp_path,
        failing={"Page.stopScreencast": cdp_ws.Closed("the target closed the connection")},
        started=time.time() - 100,
        max_seconds=5,
    )
    assert listed["why"] == "time cap" and len(listed["frames"]) == 1
    assert wire.calls == ["Page.captureScreenshot", "Page.startScreencast", "Page.stopScreencast"]
    assert wire.closed and (frames / "done").exists()


def test_a_recorder_whose_page_does_not_answer_says_so_and_still_ends_cleanly(monkeypatch, tmp_path, capsys):
    wire, listed, frames = _recorder(
        monkeypatch,
        tmp_path,
        failing={"Page.captureScreenshot": TimeoutError("Page.captureScreenshot: no answer within 10 s")},
    )
    assert listed["why"] == "browser: Page.captureScreenshot: no answer within 10 s" and listed["frames"] == []
    assert "recorder: Page.captureScreenshot: no answer" in capsys.readouterr().out
    assert wire.closed and (frames / "done").exists() and not (frames / "ready").exists()


# ---------- record: encode and verify ----------

GOOD_PROBE = json.dumps(
    {"streams": [{"codec_name": "h264", "pix_fmt": "yuv420p", "r_frame_rate": "8/1"}], "format": {"duration": "2.5"}}
)


def _tools(monkeypatch, encode=None, probe=GOOD_PROBE, decode=None):
    """ffmpeg and ffprobe stood in at subprocess.run: the encode writes its output file, the probe answers `probe`."""
    from cockpitlib import record

    ran = []

    def run(argv, **kwargs):
        ran.append(argv)
        if argv[0] == "ffprobe":
            return _done(0, probe)
        if "null" in argv:
            return decode or _done(0)
        if encode is None or encode.returncode == 0:
            open(argv[-1], "wb").write(b"mp4 bytes")
        return encode or _done(0)

    monkeypatch.setattr(record, "_tool", lambda name: name)
    monkeypatch.setattr(record.subprocess, "run", run)
    return ran


def test_a_tool_off_the_path_is_taken_from_hermes_own_tools_or_named_as_missing(env, monkeypatch):
    from cockpitlib import record
    from cockpitlib.paths import hermes_home

    monkeypatch.setattr(record.shutil, "which", lambda name: None)
    bundled = os.path.join(hermes_home(), "tools", "ffmpeg-7.1", "bin")
    os.makedirs(bundled)
    open(os.path.join(bundled, "ffmpeg"), "w").close()
    assert record._tool("ffmpeg") == os.path.join(bundled, "ffmpeg")
    with pytest.raises(CockpitError, match="ffprobe not found"):
        record._tool("ffprobe")


def test_a_recording_without_a_frame_writes_no_video(tmp_path):
    from cockpitlib import record

    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "000000.jpg").write_bytes(b"")  # a frame that was never written out
    with pytest.raises(CockpitError, match="the recording has no frames"):
        record.encode({"frames": str(frames), "out": str(tmp_path / "s1-x-repro.mp4")})


def test_a_failed_encode_and_a_video_that_does_not_play_leave_nothing_behind(env, monkeypatch, tmp_path):
    from cockpitlib import record

    frames = tmp_path / "frames"
    frames.mkdir()
    for name in ("000000.jpg", "000001.jpg"):
        (frames / name).write_bytes(b"\xff\xd8 frame")
    out = tmp_path / "videos" / "s1-save-repro.mp4"
    out.parent.mkdir()
    state = {"frames": str(frames), "out": str(out)}
    ran = _tools(monkeypatch, encode=_done(1, err="Unknown encoder 'libx264'"))
    with pytest.raises(CockpitError, match="ffmpeg could not encode the video: Unknown encoder 'libx264'"):
        record.encode(state)
    # the frames were listed from the folder (the recorder left no frames.json), each held at least one frame's time
    concat = (frames / "frames.ffconcat").read_text(encoding="utf-8").splitlines()
    assert concat[0] == "ffconcat version 1.0" and concat.count("file '000001.jpg'") == 2
    assert ran[0][0] == "ffmpeg" and os.listdir(out.parent) == []
    _tools(
        monkeypatch,
        probe=json.dumps(
            {
                "streams": [{"codec_name": "vp9", "pix_fmt": "yuv420p", "r_frame_rate": "8/1"}],
                "format": {"duration": "2"},
            }
        ),
    )
    with pytest.raises(CockpitError, match=r"the video does not play \(ffprobe: .*vp9.*\); it was not kept"):
        record.encode(state)
    assert os.listdir(out.parent) == []


def test_a_video_is_never_placed_when_no_name_is_free(monkeypatch, tmp_path):
    from cockpitlib import record

    def taken(source, target):
        raise FileExistsError(target)

    monkeypatch.setattr(os, "link", taken)
    monkeypatch.setattr(record, "free_name", lambda path: path)
    with pytest.raises(CockpitError, match="no free name for the video next to"):
        record._place(str(tmp_path / "part.mp4"), str(tmp_path / "s1-x-repro.mp4"))


def test_the_probe_reads_what_ffprobe_says_and_nothing_from_an_answer_it_cannot_parse(monkeypatch):
    from cockpitlib import record

    _tools(monkeypatch, probe="ffprobe: moov atom not found")
    assert record._probe("/x.mp4") == {"codec": None, "pix_fmt": None, "rate": None, "duration": 0.0}
    _tools(monkeypatch, probe=json.dumps({"streams": [{"codec_name": "h264"}], "format": {"duration": "N/A"}}))
    assert record._probe("/x.mp4") == {"codec": "h264", "pix_fmt": None, "rate": None, "duration": 0.0}


def test_a_video_that_probes_well_must_also_decode_whole(monkeypatch, tmp_path):
    from cockpitlib import record

    video = tmp_path / "s1-x-repro.mp4"
    video.write_bytes(b"mp4")
    _tools(monkeypatch, decode=_done(1, err="Invalid NAL unit size"))
    assert record.playable(str(video)) == "decode: Invalid NAL unit size"
    _tools(monkeypatch, decode=_done(0, err="error while decoding MB 3 4"))
    assert record.playable(str(video)) == "decode: error while decoding MB 3 4"
    _tools(monkeypatch)
    assert record.playable(str(video)) == ""


def test_a_legacy_video_needs_a_stream_a_duration_and_a_whole_decode(monkeypatch, tmp_path):
    from cockpitlib import record

    video = tmp_path / "old.mov"
    assert record._mov_playable(str(video)) == "empty file"
    video.write_bytes(b"")
    assert record._mov_playable(str(video)) == "empty file"
    video.write_bytes(b"mov")
    _tools(monkeypatch, probe=json.dumps({"streams": [], "format": {"duration": "3"}}))
    assert record._mov_playable(str(video)).startswith("ffprobe: ")
    legacy = json.dumps(
        {
            "streams": [{"codec_name": "prores", "pix_fmt": "yuv422p10le", "r_frame_rate": "30/1"}],
            "format": {"duration": "3"},
        }
    )
    _tools(monkeypatch, probe=legacy, decode=_done(1, err="truncated"))
    assert record._mov_playable(str(video)) == "decode: truncated"
    _tools(monkeypatch, probe=legacy)
    assert record._mov_playable(str(video)) == ""


def test_the_gates_verdict_is_not_cached_when_the_tools_are_missing_and_survives_a_cache_it_cannot_write(
    env, monkeypatch, tmp_path
):
    from cockpitlib import record
    from cockpitlib.paths import watch_dir

    cache = os.path.join(watch_dir(), "record-playable.json")
    assert record.accepted(str(tmp_path / "gone.mp4")) == "empty file"
    video = tmp_path / "s1-x-repro.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(record.shutil, "which", lambda name: None)
    assert "ffprobe not found" in record.accepted(str(video))
    assert not os.path.exists(cache)  # a missing tool is not the file's fault: asked again next time
    _tools(monkeypatch)

    def full(path, data):
        raise OSError("No space left on device")

    monkeypatch.setattr(record, "_write_json", full)
    assert record.accepted(str(video)) == ""
    assert not os.path.exists(cache)


# ---------- cdp_ws: frames ----------


def test_a_large_frame_carries_its_size_in_eight_bytes_and_a_partial_frame_waits():
    from cockpitlib import cdp_ws

    payload = os.urandom(70000)
    frame = cdp_ws.encode_frame(payload, mask=False)
    assert frame[1] == 127 and cdp_ws.decode_frame(frame) == (True, 1, payload, len(frame))
    masked = cdp_ws.encode_frame(payload)
    assert cdp_ws.decode_frame(masked) == (True, 1, payload, len(masked))
    assert cdp_ws.decode_frame(frame[:9]) is None  # the eight size bytes are not all there
    assert (
        cdp_ws.decode_frame(cdp_ws.encode_frame(b"x" * 300, mask=False)[:3]) is None
    )  # nor the two of a middle-sized one
    assert cdp_ws.decode_frame(cdp_ws.encode_frame(b"hi")[:4]) is None  # nor the mask key


# ---------- cdp_ws: the connection ----------


class _Wire:
    """The target's end of the socket: answers the handshake, then hands out what the test queued."""

    def __init__(self, status="HTTP/1.1 101 Switching Protocols", accept="", answer=True, broken=False):
        self.status, self.accept, self.answer, self.broken = status, accept, answer, broken
        self.sent, self.incoming, self.closed = [], [], False

    def sendall(self, data):
        if data.startswith(b"GET "):
            self.request = data.decode()
            key = re.search(r"Sec-WebSocket-Key: (\S+)", self.request).group(1)
            accept = (
                self.accept
                or base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                ).decode()
            )
            if self.answer:
                self.incoming.append(
                    f"{self.status}\r\nUpgrade: websocket\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode()
                )
            return
        if self.broken:
            raise BrokenPipeError("the pipe is gone")
        self.sent.append(data)

    def recv(self, size):
        if not self.incoming:
            return b""
        item = self.incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def settimeout(self, seconds):
        pass

    def close(self):
        self.closed = True
        if self.broken:
            raise OSError("already closed")

    def says(self, *messages):
        from cockpitlib.cdp_ws import encode_frame

        for message in messages:
            self.incoming.append(
                message
                if isinstance(message, (bytes, BaseException))
                else encode_frame(json.dumps(message).encode(), mask=False)
            )


def _connect(monkeypatch, wire, url="ws://127.0.0.1:9333/devtools/page/A?x=1"):
    from cockpitlib import cdp_ws

    monkeypatch.setattr(cdp_ws.socket, "create_connection", lambda address, timeout=None: wire)
    return cdp_ws.Socket(url)


def test_only_a_loopback_devtools_socket_is_opened(monkeypatch):
    from cockpitlib import cdp_ws

    monkeypatch.setattr(
        cdp_ws.socket, "create_connection", lambda address, timeout=None: pytest.fail("no connection is made")
    )
    for url in ("ws://browser.example.test:9222/devtools/page/A", "http://127.0.0.1:9222/devtools/page/A"):
        with pytest.raises(ValueError, match="not a loopback DevTools socket"):
            cdp_ws.Socket(url)


def test_a_handshake_the_target_drops_refuses_or_answers_with_a_wrong_key_is_closed(monkeypatch):
    from cockpitlib import cdp_ws

    with pytest.raises(cdp_ws.Closed, match="closed the handshake"):
        _connect(monkeypatch, _Wire(answer=False))
    with pytest.raises(cdp_ws.Closed, match="refused the WebSocket: HTTP/1.1 403 Forbidden"):
        _connect(monkeypatch, _Wire(status="HTTP/1.1 403 Forbidden"))
    with pytest.raises(cdp_ws.Closed, match="wrong key"):
        _connect(monkeypatch, _Wire(accept="bm90IHRoZSBrZXk="))
    wire = _Wire()
    _connect(monkeypatch, wire)
    assert wire.request.startswith("GET /devtools/page/A?x=1 HTTP/1.1\r\nHost: 127.0.0.1:9333\r\n")


def test_a_call_answers_pings_joins_fragments_and_skips_what_is_not_json_until_its_answer_comes(monkeypatch):
    from cockpitlib import cdp_ws

    wire = _Wire()
    link = _connect(monkeypatch, wire)
    event = json.dumps({"method": "Page.loadEventFired", "params": {}}).encode()
    wire.says(
        cdp_ws.encode_frame(b"hb", opcode=9, mask=False),  # a ping: answered with a pong
        cdp_ws.encode_frame(b"", opcode=10, mask=False),  # a pong nobody asked for
        bytes([0x01, 10]) + event[:10],  # an event in two fragments
        bytes([0x80, len(event) - 10]) + event[10:],
        cdp_ws.encode_frame(b"\xff\xfe not json", mask=False),
        TimeoutError("timed out"),
        {"id": 1, "result": {"frameId": "F"}},
    )
    assert link.call("Page.enable") == {"frameId": "F"}
    sent = [cdp_ws.decode_frame(data) for data in wire.sent]
    assert json.loads(sent[0][2]) == {"id": 1, "method": "Page.enable", "params": {}}
    assert sent[1][1:3] == (10, b"hb")
    assert link.poll() == {"method": "Page.loadEventFired", "params": {}}  # read during the call, kept for poll
    wire.says({"id": 2, "error": {"message": "No frame for given id"}})
    with pytest.raises(RuntimeError, match="Page.navigate: No frame for given id"):
        link.call("Page.navigate", {"url": "about:blank"})
    with pytest.raises(TimeoutError, match="Page.reload: no answer within 0 s"):
        link.call("Page.reload", timeout=0)


def test_a_target_that_closes_ends_the_read_and_closing_twice_is_harmless(monkeypatch):
    from cockpitlib import cdp_ws

    wire = _Wire()
    link = _connect(monkeypatch, wire)
    wire.says(cdp_ws.encode_frame(b"", opcode=8, mask=False))
    with pytest.raises(cdp_ws.Closed, match="closed the connection"):
        link.poll()
    with pytest.raises(cdp_ws.Closed, match="closed the connection"):
        link.poll()  # nothing more comes: the peer hung up
    link.close()
    assert wire.closed and cdp_ws.decode_frame(wire.sent[-1])[1] == 8
    gone = _Wire(broken=True)
    _connect(monkeypatch, gone).close()  # a socket already gone: no error
    assert gone.closed and gone.sent == []


# ---------- standup_note ----------

DAY = 1_800_000_000.0


def _iso(epoch: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(epoch, datetime.UTC).isoformat()


def _intent(kind, payload=None, receipt=None, at=DAY + 60, status="published"):
    return {"status": status, "type": kind, "created_at": _iso(at), "payload": payload or {}, "receipt": receipt or {}}


def _records(monkeypatch, intents: dict) -> None:
    from cockpitlib import intents as store
    from cockpitlib.paths import outbox, qa

    for ticket in intents:
        os.makedirs(os.path.join(outbox(), ticket), exist_ok=True)
        os.makedirs(os.path.join(qa(), ticket, "pr"), exist_ok=True)
    monkeypatch.setattr(store, "all_intents", lambda ticket=None: intents.get(ticket, []))


def test_a_stamp_that_is_no_time_and_a_record_that_is_no_json_read_as_nothing(tmp_path):
    from cockpitlib import standup_note

    assert standup_note._epoch("last tuesday") == 0.0
    assert standup_note._epoch("2027-01-15T08:00:00Z") == 1800000000.0
    (tmp_path / "torn.json").write_text("{", encoding="utf-8")
    assert standup_note._read_json(str(tmp_path / "torn.json")) is None
    assert standup_note._read_json(str(tmp_path / "absent.json")) is None


def test_the_window_collects_bumps_tests_created_tickets_and_the_small_acts(env, monkeypatch):
    from cockpitlib import standup_note
    from cockpitlib.paths import qa

    pull = "https://forge.example.test/acme/api/pull/7"
    _records(
        monkeypatch,
        {
            "BUMPS-2026W42": [
                _intent("pr-edit", {"repo": "api", "number": 7, "url": pull}),
                _intent("tracker-transition", {"to": "In Review"}),
                _intent("pr-comment", {"repo": "api", "number": 7}),
            ],
            "ACME-1": [
                _intent(
                    "tracker-comment", {"comment_id": "10"}, {"url": "https://tracker.example.test/browse/ACME-1?c=10"}
                ),
                _intent(
                    "tracker-create",
                    {"summary": "Follow-up for the export"},
                    {"url": "https://tracker.example.test/browse/ACME-9"},
                ),
                _intent(
                    "pr-comment", {"repo": "web", "number": 3, "url": "https://forge.example.test/acme/web/pull/3"}
                ),
                _intent("tracker-transition", {"to": "In Review"}),
                _intent("ci-rerun"),
                _intent("ticket-done"),
                _intent("pr-edit", at=DAY - 5),
                _intent("pr-edit", status="queued"),
                {"status": "published", "type": "pr-edit", "created_at": "last tuesday"},
            ],
            "ACME-2": [_intent("tracker-comment", {"body": "a note"})],
        },
    )
    _first_run("ACME-1")
    json.dump(
        {"merged": True, "merged_at": _iso(DAY + 90), "repo": "api", "number": 7, "url": pull},
        open(os.path.join(qa(), "BUMPS-2026W42", "pr", "api-7.json"), "w", encoding="utf-8"),
    )
    open(os.path.join(qa(), "ACME-1", "pr", "list.json"), "w", encoding="utf-8").write("[1, 2]")
    open(os.path.join(qa(), "ACME-1", "pr", "torn.json"), "w", encoding="utf-8").write("{")
    acts = standup_note.collect(DAY, DAY + 3600, _pack())
    assert [(act["what"], act["url"]) for act in acts["BUMPS-2026W42"]["bumps"]] == [
        ("api#7", pull),
        ("tracker-transition", ""),
        ("api#7 merged", pull),
    ]
    assert list(acts["BUMPS-2026W42"]) == ["bumps"]  # a batch's PR comment is no line of its own
    mine = acts["ACME-1"]
    assert [act["what"] for act in mine["tested"]] == ["test results posted on the tracker"]
    assert mine["tested"][0]["url"].endswith("?c=10")
    assert [act["what"] for act in mine["created"]] == ["tracker ticket ACME-9 (Follow-up for the export)"]
    assert [act["what"] for act in mine["other"]] == ["PR comment", "tracker moved to In Review", "CI rerun"]
    assert mine["other"][0]["url"].endswith("/pull/3") and [act["what"] for act in mine["done"]] == ["ticket closed"]
    assert "merged" not in mine  # neither pr file is a watch state
    assert [act["what"] for act in acts["ACME-2"]["other"]] == [
        "tracker comment"
    ]  # no run folder, no comment id: a plain comment


def test_open_work_leaves_bumps_batches_and_ticketless_cards_out(env, monkeypatch):
    from cockpitlib import kanban, pr_watch, standup_note

    _records(monkeypatch, {"BUMPS-2026W42": [], "ACME-1": [], "ACME-4": []})
    cards = [
        {"ticket": "BUMPS-2026W42", "flow": "bumps", "created_at": "2027-01-15T08:00:00"},
        {"ticket": "", "flow": "chat"},
        {"ticket": "ACME-1", "flow": "dev", "created_at": "2027-01-15T08:00:00"},
        {"ticket": "ACME-1", "flow": "dev", "created_at": "2027-01-15T09:00:00"},
    ]
    monkeypatch.setattr(kanban, "board_cards", lambda slug, pack=None: cards)
    asked = []
    monkeypatch.setattr(
        pr_watch,
        "prs_of",
        lambda ticket: asked.append(ticket) or ([{"repo": "api", "number": 4}] if ticket == "ACME-4" else []),
    )
    found = standup_note.open_work(_pack())
    assert found == [
        {"ticket": "ACME-1", "flows": ["dev"], "prs": [], "last_card": "2027-01-15T09:00:00"},
        {"ticket": "ACME-4", "flows": [], "prs": [{"repo": "api", "number": 4}], "last_card": ""},
    ]
    assert asked == ["ACME-1", "ACME-4"]
    assert standup_note.open_work({}) == []


def test_only_touched_unfinished_tickets_with_an_open_pr_wait_on_a_colleague():
    from cockpitlib import standup_note

    open_ = [
        {
            "ticket": "ACME-1",
            "flows": ["dev"],
            "prs": [
                {"repo": "api", "number": 1, "state": "closed"},
                {"repo": "api", "number": 2, "state": "open", "url": "https://forge.example.test/2"},
            ],
        },
        {"ticket": "ACME-2", "flows": ["dev"], "prs": [{"repo": "api", "number": 3}]},
        {"ticket": "ACME-3", "flows": ["dev"], "prs": [{"repo": "api", "number": 4}]},
    ]
    waits = standup_note.waiting(open_, {"ACME-3": " Done "}, touched={"ACME-1", "ACME-3"})
    assert waits == {
        "ACME-1": [
            {"kind": "Review", "what": "api#2 waiting for a review approval", "url": "https://forge.example.test/2"}
        ]
    }


def test_statuses_come_from_a_tracker_that_answers_and_are_empty_from_one_that_cannot(monkeypatch):
    from cockpitlib import standup_note, tracker

    def down(pack, dry_run=False):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(tracker, "tracker_for", down)
    assert standup_note._statuses({}, ["ACME-1"]) == {}
    monkeypatch.setattr(tracker, "tracker_for", lambda pack, dry_run=False: object())
    assert standup_note._statuses({}, ["ACME-1"]) == {}

    class Reader:
        asked = []

        def _status(self, key):
            self.asked.append(key)
            if key == "ACME-2":
                raise RuntimeError("404")
            return "In Review"

    monkeypatch.setattr(tracker, "tracker_for", lambda pack, dry_run=False: Reader())
    assert standup_note._statuses({}, ["ACME-1", "ACME-2", "BUMPS-2026W42"]) == {"ACME-1": "In Review"}
    assert Reader.asked == ["ACME-1", "ACME-2"]


def test_the_draft_falls_back_to_the_titles_it_already_has_when_the_tracker_is_down(env, monkeypatch):
    from cockpitlib import kanban, standup_note, tracker

    _records(
        monkeypatch,
        {
            "ACME-1": [
                _intent("open-pr", {"repo": "api", "number": 5, "url": "https://forge.example.test/acme/api/pull/5"})
            ]
        },
    )
    monkeypatch.setattr(kanban, "board_cards", lambda slug, pack=None: [])
    asked = []

    def titles(pack, keys, refresh=False, now=None):
        asked.append(refresh)
        if refresh:
            raise RuntimeError("the tracker does not answer")
        return {"ACME-1": "Contact is saved blank"}

    monkeypatch.setattr(tracker, "titles", titles)
    monkeypatch.setattr(tracker, "tracker_for", lambda pack, dry_run=False: object())
    made = standup_note.draft(_pack(), DAY, DAY + 3600)
    assert asked == [True, False] and made["titles"] == {"ACME-1": "Contact is saved blank"} and made["statuses"] == {}
    assert (
        '"Contact is saved blank"' in made["markdown"] and "PR opened (api#5)" in made["slack"] and made["items"] == 1
    )


# ---------- cleanup ----------


def test_git_and_lsof_that_cannot_run_are_an_answer_not_a_failure(monkeypatch):
    from cockpitlib import cleanup

    def missing(argv, **kwargs):
        raise FileNotFoundError(f"{argv[0]}: not found")

    monkeypatch.setattr(cleanup.subprocess, "run", missing)
    assert cleanup._git("/nowhere", "status") == (1, "git: not found")
    assert cleanup._cwds() == []


def test_a_file_that_vanishes_during_the_walk_is_skipped(monkeypatch, tmp_path):
    from cockpitlib import cleanup

    (tmp_path / "kept.bin").write_bytes(b"x" * 4096)
    (tmp_path / "ghost.bin").write_bytes(b"x" * 4096)
    old = time.time() - 40 * 86400
    for path in (tmp_path / "kept.bin", tmp_path):
        os.utime(path, (old, old))
    real = os.lstat

    def lstat(path, *args, **kwargs):
        if str(path).endswith("ghost.bin"):
            raise FileNotFoundError(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat)
    assert cleanup._touched(str(tmp_path), time.time() - 86400) == ""  # the fresh file is gone: nothing recent is left
    assert cleanup._size_kb(str(tmp_path)) == 4


def test_sizes_read_in_the_unit_that_fits():
    from cockpitlib.cleanup import human

    assert (human(900), human(4096), human(3 * 1048576 + 524288)) == ("900 KB", "4 MB", "3.5 GB")


def test_a_ticket_folder_stays_for_a_foreign_repo_a_broken_checkout_a_recent_commit_or_a_process_inside(
    env, monkeypatch
):
    from cockpitlib import cleanup
    from cockpitlib.paths import wt

    pack = _pack()
    now = time.time()
    folder = os.path.join(wt(), "ACME-5")
    answers = {}

    def checkout(repo):
        path = os.path.join(folder, repo)
        os.makedirs(path, exist_ok=True)
        open(os.path.join(path, ".git"), "w").close()
        return path

    paths = [checkout("api")]
    monkeypatch.setattr(cleanup, "_touched", lambda folder, cutoff: "")
    monkeypatch.setattr(cleanup, "list_worktrees", lambda ticket: paths)
    monkeypatch.setattr(cleanup, "_git", lambda path, *args, **kwargs: answers[args[0]])

    def reason(cwds=()):
        return cleanup.keep_reason(pack, "ACME-5", 14, set(), {}, list(cwds), now)

    answers["log"] = (128, "fatal: not a git repository")
    assert reason() == "api is not a git checkout (remove by hand)"
    answers["log"] = (0, str(int(now - 3600)))
    assert reason() == "api has a commit within 14 days"
    answers.update(log=(0, str(int(now - 40 * 86400))), status=(0, ""))
    answers["rev-list"] = (0, "0")
    assert reason() == ""
    assert reason([os.path.join(folder, "api", "src")]) == "a process runs inside it"
    assert reason([folder + "-other"]) == ""  # a sibling folder is not inside it
    paths.append(checkout("stranger"))
    assert reason() == "stranger is not a repo of the pack (remove by hand)"


def test_the_inventory_is_empty_without_a_worktree_folder_and_skips_plain_files(env, monkeypatch):
    from cockpitlib import cleanup
    from cockpitlib.paths import wt

    pack = _pack()
    monkeypatch.setattr(cleanup, "_cwds", lambda: [])
    assert cleanup.inventory(pack) == []
    os.makedirs(os.path.join(wt(), "ACME-6"))
    open(os.path.join(wt(), "README.txt"), "w").close()
    found = cleanup.inventory(pack)
    assert [(row["ticket"], row["repos"]) for row in found] == [("ACME-6", [])]
    assert found[0]["keep"].startswith("touched within 14 days")


def test_removing_a_ticket_prunes_only_the_repos_the_pack_can_place(env, monkeypatch, tmp_path):
    from cockpitlib import acts, cleanup

    pack = _pack()
    names = [repo["name"] for repo in pack["repos"]["repos"]]
    here = tmp_path / "source"
    here.mkdir()

    def source(pack, name):
        if name == names[0]:
            raise CockpitError(f"{name} has no source")
        return str(here)

    pruned = []
    monkeypatch.setattr(acts, "remove_worktrees", lambda pack, ticket: [f"{ticket}/api"])
    monkeypatch.setattr(cleanup, "repo_source", source)
    monkeypatch.setattr(cleanup, "_git", lambda folder, *args, **kwargs: pruned.append((folder, args)) or (0, ""))
    assert cleanup.remove(pack, "ACME-7") == ["ACME-7/api"]
    assert pruned == ([(str(here), ("worktree", "prune"))] if len(names) > 1 else [])


def test_a_folder_that_will_not_go_is_kept_with_the_reason(env, monkeypatch):
    from cockpitlib import cleanup
    from cockpitlib.paths import wt

    os.makedirs(os.path.join(wt(), "ACME-8"))
    monkeypatch.setattr(
        cleanup, "inventory", lambda pack, days, now=None: [{"ticket": "ACME-8", "repos": ["api"], "keep": ""}]
    )

    def busy(pack, ticket):
        raise OSError("Directory not empty")

    monkeypatch.setattr(cleanup, "remove", busy)
    result = cleanup.gc(_pack(), 14)
    assert result["removed"] == [] and result["kept"] == [
        {"ticket": "ACME-8", "why": "removal failed: Directory not empty"}
    ]
    assert (
        result["lines"][0] == "keep ACME-8: removal failed: Directory not empty"
        and "0 removed, 1 kept" in result["lines"][-1]
    )


# ---------- self_update ----------


def test_a_git_that_hangs_or_fails_is_a_cockpit_error_in_its_own_words(monkeypatch):
    from cockpitlib import self_update

    def hangs(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(self_update.subprocess, "run", hangs)
    with pytest.raises(CockpitError, match="git fetch timed out"):
        self_update._git("/plugin", "fetch", "-q", "origin")
    monkeypatch.setattr(
        self_update, "_git", lambda root, *args, **kwargs: _done(128, err="fatal: bad revision 'HEAD'\n")
    )
    with pytest.raises(CockpitError, match="fatal: bad revision 'HEAD'"):
        self_update._out("/plugin", "rev-parse", "HEAD")
    monkeypatch.setattr(self_update, "_git", lambda root, *args, **kwargs: _done(1))
    with pytest.raises(CockpitError, match="git rev-parse failed"):
        self_update._out("/plugin", "rev-parse", "HEAD")


def test_the_branch_to_follow_is_origins_default_when_the_checkout_has_no_upstream(monkeypatch):
    from cockpitlib import self_update

    answers = {}
    monkeypatch.setattr(self_update, "_git", lambda root, *args, **kwargs: answers.get(args[0], _done(1)))
    answers["symbolic-ref"] = _done(0, "refs/remotes/origin/main\n")
    assert self_update.remote_branch("/plugin") == "main"
    answers["symbolic-ref"] = _done(1)
    answers["ls-remote"] = _done(0, "0a1b2c3\tHEAD\n")
    assert self_update.remote_branch("/plugin") == "master"


def test_the_branch_to_follow_is_read_from_the_remote_when_no_local_ref_names_it(monkeypatch):
    from cockpitlib import self_update

    answers = {"ls-remote": _done(0, "ref: refs/heads/trunk\tHEAD\n0a1b2c3\tHEAD\n")}
    monkeypatch.setattr(self_update, "_git", lambda root, *args, **kwargs: answers.get(args[0], _done(1)))
    assert self_update.remote_branch("/plugin") == "trunk"


def test_a_folder_that_is_no_checkout_has_a_status_that_says_so_and_cannot_be_updated(env, tmp_path):
    from cockpitlib import self_update

    seen = self_update.status(str(tmp_path))
    assert seen["installed"] is None and seen["error"] == f"{tmp_path} is not a git checkout"
    with pytest.raises(CockpitError, match="is not a git checkout"):
        self_update.apply(str(tmp_path))


def test_the_hourly_check_and_the_inbox_row_never_fail_on_a_checkout_git_cannot_read(env, monkeypatch):
    from cockpitlib import self_update

    def broken(root="", now=None):
        raise CockpitError("fatal: not a git repository")

    monkeypatch.setattr(self_update, "check", broken)
    assert self_update.check_if_due("/plugin", now=1000.0) == "check skipped: fatal: not a git repository"
    self_update._write_check({"behind": 2, "short": "0a1b2c3", "checked_at": 1000.0})

    def unreadable(root, *args):
        raise CockpitError("fatal: not a git repository")

    monkeypatch.setattr(self_update, "_out", unreadable)
    assert self_update.inbox_row() == {}


def test_the_gateway_restart_is_started_detached(monkeypatch):
    from cockpitlib import self_update

    started = []
    monkeypatch.setattr(self_update.subprocess, "Popen", lambda argv, **kwargs: started.append((argv, kwargs)))
    self_update._spawn(["/usr/bin/hermes", "gateway", "restart"])
    argv, kwargs = started[0]
    assert argv == ["/usr/bin/hermes", "gateway", "restart"] and kwargs["start_new_session"] is True
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL


def test_a_gateway_restart_hermes_refuses_is_reported_and_not_called_requested(env, tmp_path, monkeypatch):
    from cockpitlib import self_update
    from tests.test_selfupdate import _plugin_pair

    said = tmp_path / "hermes-stand-in"

    def stand_in(lines, code, sleep=0):
        said.write_text("#!/bin/sh\n" + "".join(f"echo '{line}'\n" for line in lines) + f"sleep {sleep}\nexit {code}\n")
        said.chmod(0o755)
        return [str(said), "gateway", "restart"]

    assert self_update._spawn(
        stand_in(["", "Refusing to restart the gateway: 1 session is live", "more"], 1), wait=5
    ) == ("Refusing to restart the gateway: 1 session is live")
    assert self_update._spawn(stand_in([], 3), wait=5) == "exit 3"
    assert self_update._spawn(stand_in(["restarting"], 0), wait=5) == ""
    assert self_update._spawn(stand_in(["draining"], 1, sleep=3), wait=0.3) == ""  # still at work: it is restarting
    plugin, advance = _plugin_pair(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", plugin)
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "/usr/bin/hermes")
    monkeypatch.setattr(
        self_update, "_spawn", lambda argv, wait=0.0: "Refusing to restart the gateway: 1 session is live"
    )
    advance()
    done = self_update.apply(plugin, restart=True)
    assert done["restart"] == "refused: Refusing to restart the gateway: 1 session is live"
    assert "gateway restart requested" not in done["out"] and "THE GATEWAY DID NOT RESTART" in done["out"]
    assert "run `hermes gateway restart` when no session is live (Refusing to restart the gateway" in done["out"]


def test_hermes_install_record_is_best_effort(monkeypatch):
    from cockpitlib import hermes_runtime, self_update

    answer = {}

    def helper(name, request):
        if isinstance(answer["results"], Exception):
            raise answer["results"]
        return answer

    monkeypatch.setattr(hermes_runtime, "run_helper", helper)
    answer["results"] = RuntimeError("the helper did not start")
    assert self_update._record_hermes_revision("cockpit", "0a1b2c3") == "the helper did not start"
    answer["results"] = [True]
    assert self_update._record_hermes_revision("cockpit", "0a1b2c3") == ""
    answer["results"] = [{"error": "unknown plugin"}]
    assert self_update._record_hermes_revision("cockpit", "0a1b2c3") == "unknown plugin"


def test_an_update_stops_at_a_fetch_that_fails_and_at_a_history_that_diverged(env, tmp_path, monkeypatch):
    from cockpitlib import self_update
    from tests.test_selfupdate import _git, _plugin_pair

    plugin, advance = _plugin_pair(tmp_path)
    monkeypatch.setenv("COCKPIT_PLUGIN_ROOT", plugin)
    monkeypatch.setattr(self_update, "_record_hermes_revision", lambda name, revision: "")
    # the update lands, but no hermes is on the path to restart the gateway with
    monkeypatch.setattr(self_update.shutil, "which", lambda name: None)
    newest = advance()
    done = self_update.apply(plugin, restart=True)
    assert done["changed"] is True and done["to"] == newest[:7] and done["restart"] == "hermes not found"
    assert "gateway restart requested" not in done["out"]
    # a local commit origin does not have, then origin moves on: not a fast-forward
    open(os.path.join(plugin, "local.txt"), "w", encoding="utf-8").write("mine\n")
    _git(plugin, "add", "local.txt")
    _git(plugin, "commit", "-q", "-m", "local only")
    head = _git(plugin, "rev-parse", "HEAD")
    advance(message="third")
    with pytest.raises(CockpitError, match="not a fast-forward"):
        self_update.apply(plugin, restart=False)
    assert _git(plugin, "rev-parse", "HEAD") == head
    _git(plugin, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    with pytest.raises(CockpitError, match="gone.git"):
        self_update.apply(plugin, restart=False)
    assert _git(plugin, "rev-parse", "HEAD") == head


# ---------- quota ----------


def test_a_moment_reads_empty_when_there_is_none_and_a_stamp_without_a_zone_is_utc():
    from cockpitlib import quota

    assert quota.when(0) == "" and quota.when(None) == ""
    assert quota._epoch("after lunch") is None and quota._epoch(None) is None
    assert quota._epoch("2027-01-15T08:00:00") == quota._epoch("2027-01-15T08:00:00Z") == 1800000000.0


def test_an_unreadable_providers_row_says_when_its_last_reading_gates_nothing():
    from cockpitlib import quota

    row = quota._row_unreadable("fixture-a", 2000.0, 1000.0, "HTTP 401", [])
    assert "whose windows have all reset since: nothing gates on it" in row["what"] and "HTTP 401" in row["what"]
    assert [field["label"] for field in row["detail"]["fields"]] == [
        "provider",
        "unreadable since",
        "reader said",
        "last good reading",
    ]
    assert "no reading yet" in quota._row_unreadable("fixture-a", 2000.0, None, "", [])["what"]


def test_a_role_whose_provider_the_pack_does_not_define_has_no_lane_provider(env):
    from cockpitlib import quota, usage

    pack = _pack()
    assert quota.lane_providers(pack)  # the fixture's roles all name a provider
    orphaned = dict(pack, roles={kind: "nobody" for kind in pack["roles"]})
    assert quota.lane_providers(orphaned) == {}
    assert usage.providers_on_key(orphaned) == set()


def test_what_the_provider_said_is_still_returned_when_masking_fails(env, monkeypatch):
    from cockpitlib import quota, scrub

    def broken(text):
        raise RuntimeError("no patterns")

    monkeypatch.setattr(scrub, "scrub", broken)
    said = quota._said(
        _pack(), "card-1", "requeued without counting the rate limit\nUsage limit reached. Resets in 2 hours"
    )
    assert said == "Usage limit reached. Resets in 2 hours"


def test_a_runs_provider_is_read_from_its_limit_message_when_its_metadata_is_not_json(env):
    from cockpitlib import quota

    texts = ("fixture-b reported that your weekly limit was reached", "")
    assert quota._ran_on("{torn", texts, "tester-1", 100.0, {"fixture-a", "fixture-b"}, {}) == "fixture-b"
    assert (
        quota._ran_on("[1]", ("somebody reported that your limit was reached",), "tester-1", 100.0, {"fixture-a"}, {})
        == ""
    )
    assert quota._ran_on('{"hermes_provider": "fixture-a"}', texts, "tester-1", 100.0, {"fixture-b"}, {}) == "fixture-a"


def _board(tmp_path, runs=(), events=()):
    connection = sqlite3.connect(str(tmp_path / "board.db"))
    connection.execute("create table tasks (id text, provider_override text)")
    connection.execute(
        "create table task_runs (id integer primary key, task_id text, profile text, outcome text, error text, "
        "started_at real, ended_at real, metadata text, summary text)"
    )
    connection.execute("create table task_events (id integer primary key, task_id text, kind text, payload text)")
    connection.executemany(
        "insert into task_runs (task_id, profile, outcome, error, started_at, ended_at, metadata, summary) values (?, ?, ?, ?, ?, ?, ?, ?)",
        runs,
    )
    connection.executemany("insert into task_events (task_id, kind, payload) values (?, ?, ?)", events)
    return connection


def test_a_wall_of_an_unknown_seat_or_one_whose_reset_has_passed_holds_nothing(env, tmp_path):
    from cockpitlib import quota

    moment = time.time()
    on_a = json.dumps({"provider": "fixture-a"})
    connection = _board(
        tmp_path,
        runs=[
            (
                "c1",
                "visitor-1",
                "rate_limited",
                "Usage limit reached",
                moment - 7200,
                moment - 7000,
                on_a,
                "",
            ),  # no seat of the pack
            (
                "c2",
                "tester-1",
                "rate_limited",
                "Usage limit reached",
                moment - 7200,
                moment - 6000,
                on_a,
                "",
            ),  # half an hour, long over
        ],
    )
    state = {}
    quota._walls(_pack(), connection, state, {"tester-1": "fixture-a"}, moment)
    assert state["holds"] == {} and state["seen_end"] == pytest.approx(moment - 6000)
    connection.execute(
        "insert into task_runs (task_id, profile, outcome, error, started_at, ended_at, metadata) values (?, ?, ?, ?, ?, ?, ?)",
        ("c3", "tester-1", "rate_limited", "Usage limit reached. Resets in 3 hours", moment - 700, moment - 600, on_a),
    )
    quota._walls(_pack(), connection, state, {"tester-1": "fixture-a"}, moment)
    assert state["holds"]["fixture-a"]["cards"] == ["c3"] and state["holds"]["fixture-a"]["until"] == int(
        moment - 600 + 3 * 3600
    )


def test_who_parked_a_card_is_read_from_its_run_when_its_event_is_torn_or_absent(tmp_path):
    from cockpitlib import quota

    connection = _board(
        tmp_path,
        events=[
            ("c1", "scheduled", "{torn"),
            ("c2", "scheduled", json.dumps({"reason": "cockpit quota: held"})),
            ("c4", "scheduled", "[1]"),
        ],
        runs=[
            ("c1", "tester-1", "scheduled", "", 1.0, 2.0, "", "waiting for the human"),
            ("c1", "tester-1", "scheduled", "", 3.0, 4.0, "", "cockpit quota: budget ceiling"),
        ],
    )
    assert quota._scheduled_reasons(connection, ["c1", "c2", "c3", "c4"]) == {
        "c1": "cockpit quota: budget ceiling",
        "c2": "cockpit quota: held",
        "c3": None,
        "c4": None,
    }
    assert quota._scheduled_reasons(sqlite3.connect(":memory:"), ["c1"]) is None


# ---------- usage ----------


def test_plan_windows_skip_an_answer_that_names_no_provider(env, monkeypatch):
    from cockpitlib import hermes_runtime, usage

    monkeypatch.setattr(usage, "providers_in_use", lambda pack: {"fixture-a"})
    monkeypatch.setattr(
        hermes_runtime,
        "run_helper",
        lambda name, request: {
            "results": [
                {"provider": None, "windows": [{"label": "Stray", "used_percent": 99}]},
                {
                    "provider": "fixture-a",
                    "windows": [{"label": "Current week", "used_percent": 40.4, "resets_at": None}],
                },
            ]
        },
    )
    read = usage.plan_windows(_pack(), now=DAY, fresh=True)
    assert [(window["provider"], window["name"], window["used"]) for window in read["windows"]] == [
        ("fixture-a", "Current week", 40)
    ]
    assert read["error"] == "" and read["unmetered"] == []


def test_a_sessions_length_is_its_recorded_duration_else_its_span_else_nothing():
    from cockpitlib import usage

    assert usage._seconds({"duration_seconds": 12.5, "started_at": 100, "ended_at": 900}) == 12.5
    assert usage._seconds({"started_at": 100, "last_activity_at": 160}) == 60.0
    assert usage._seconds({"started_at": "this morning", "ended_at": 160}) == 0.0


def test_transcripts_are_booked_from_assistant_turns_only_and_bad_lines_and_files_are_skipped(monkeypatch, tmp_path):
    from cockpitlib import chat, usage

    monkeypatch.setattr(usage, "_TRANSCRIPTS", {"key": None, "rows": []})
    monkeypatch.setattr(chat, "_pattern", lambda ticket: "")
    assert usage.transcript_rows() == []
    folder = tmp_path / "project"
    folder.mkdir()
    monkeypatch.setattr(chat, "_pattern", lambda ticket: str(folder / f"{ticket}.jsonl"))
    monkeypatch.setattr(chat, "ticket_of_transcript", lambda path: "ACME-5")
    turn = {
        "type": "assistant",
        "message": {"model": "claude-sonnet", "usage": {"input_tokens": 1000, "output_tokens": 200}},
    }
    lines = [
        '{"type": "assistant", "message": {"usage": ',  # cut off mid-line
        json.dumps({"type": "user", "message": {"usage": {"input_tokens": 5}, "role": "assistant"}}),
        json.dumps({**turn, "timestamp": "a while ago"}),
        json.dumps(turn),
    ]
    (folder / "session-one.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "folder.jsonl").mkdir()
    (folder / "locked.jsonl").write_text(json.dumps(turn) + "\n", encoding="utf-8")
    real = builtins.open

    def guarded(path, *args, **kwargs):
        if str(path).endswith("locked.jsonl"):
            raise PermissionError(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    rows = usage.transcript_rows()
    assert [
        (row["session"], row["ticket"], row["calls"], row["input"], row["output"], row["model"]) for row in rows
    ] == [("session-one", "ACME-5", 2, 2000, 400, "claude-sonnet")]
    assert rows[0]["cost"] == pytest.approx(2 * (1000 * 3.0 + 200 * 15.0) / 1e6)
    assert usage.transcript_rows() is rows  # unchanged files: the cached rows


def test_a_ticketless_lane_session_is_grouped_as_lane_work_and_an_unknown_scope_is_refused(env):
    from cockpitlib import usage

    assert usage._origin({"who": "worker-1", "title": "Refactor the export"}) == "lanes · not tied to a ticket"
    assert usage._origin({"who": "gatekeeper", "title": "Outbox sweep"}) == "gatekeeper · outbox sweeps"
    with pytest.raises(CockpitError, match=r"scope hermes\|all"):
        usage.report(_pack(), scope="everything")


# ---------- vault ----------


def test_the_vault_list_falls_back_to_its_default_names_when_the_pack_cannot_be_read(monkeypatch):
    from cockpitlib import pack, vault

    def unreadable(path):
        raise OSError("no pack here")

    monkeypatch.setattr(pack, "load", unreadable)
    assert vault._scope_for(False) == "lane" and vault._scope_for(True) == "human"


def test_the_human_page_gets_no_secret_when_neither_the_pack_nor_a_seat_store_answers(env, monkeypatch):
    from cockpitlib import lane_vault, pack, vault

    monkeypatch.setattr(vault, "_previous", lambda origin, email, scope="": None)

    def closed(pack, origin, email):
        raise CockpitError("no seat store holds that login")

    monkeypatch.setattr(lane_vault, "secret_for", closed)
    assert vault.human_secret("https://app.example.test", "qa@example.test") == ""
    assert vault.human_secret("https://app.example.test", "qa@example.test", pack=_pack()) == ""

    def unreadable(path):
        raise OSError("no pack here")

    monkeypatch.setattr(pack, "load", unreadable)
    monkeypatch.setattr(
        lane_vault, "secret_for", lambda pack, origin, email: pytest.fail("no pack, no seat store to ask")
    )
    assert vault.human_secret("https://app.example.test", "qa@example.test") == ""


# ---------- the plan's windows, read directly ----------


def test_a_login_file_without_an_access_token_is_no_login(monkeypatch, tmp_path):
    from cockpitlib import plan_windows

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"expiresAt": 1}}), encoding="utf-8")
    read = plan_windows.read(fetch=lambda url, headers, timeout: pytest.fail("nothing is asked without a login"))
    assert read == {"windows": [], "error": "no subscription login on this machine (no access token)"}


def test_the_fetch_answers_json_and_names_what_went_wrong_without_the_request(monkeypatch):
    import urllib.error
    import urllib.request

    from cockpitlib import plan_windows

    answer = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return answer["body"]

    def opened(request, timeout=None):
        answer["request"] = request
        if isinstance(answer["body"], Exception):
            raise answer["body"]
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", opened)
    answer["body"] = b'{"five_hour": {"utilization": 12}}'
    assert plan_windows._fetch(plan_windows.URL, {"Accept": "application/json"}, 5) == {
        "five_hour": {"utilization": 12}
    }
    assert answer["request"].get_method() == "GET" and answer["request"].full_url == plan_windows.URL
    answer["body"] = urllib.error.HTTPError(plan_windows.URL, 401, "Unauthorized", {}, None)
    with pytest.raises(plan_windows.ReadError, match="^HTTP 401$"):
        plan_windows._fetch(plan_windows.URL, {}, 5)
    answer["body"] = urllib.error.URLError("connection refused")
    with pytest.raises(plan_windows.ReadError, match="^URLError: connection refused$"):
        plan_windows._fetch(plan_windows.URL, {}, 5)
    answer["body"] = b"<html>busy</html>"
    with pytest.raises(plan_windows.ReadError, match="^JSONDecodeError$"):
        plan_windows._fetch(plan_windows.URL, {}, 5)


def test_a_limit_without_a_number_is_left_out_and_a_reset_that_is_no_time_reads_as_none():
    from cockpitlib import plan_windows

    assert (
        plan_windows._percent(True) is None
        and plan_windows._percent("12") is None
        and plan_windows._percent(float("nan")) is None
    )
    assert plan_windows._stamp("next week") is None and plan_windows._stamp(1800000000) is None
    found = plan_windows.windows_of(
        {
            "limits": [
                {"kind": "session", "percent": "n/a"},
                "junk",
                {"kind": "weekly_all", "percent": 61, "resets_at": "next week"},
            ]
        }
    )
    assert found == [{"label": "Current week", "used_percent": 61.0, "resets_at": None, "scope": "account"}]


# ---------- connector ----------


def test_recording_the_runtime_never_raises_when_the_home_cannot_be_read(monkeypatch):
    from cockpitlib import connector

    monkeypatch.setitem(
        sys.modules, "hermes_bootstrap", types.SimpleNamespace(__file__="/opt/hermes/hermes_bootstrap.py")
    )
    asked = []

    def nowhere():
        asked.append(True)
        raise RuntimeError("no home")

    monkeypatch.setattr(connector, "_home", nowhere)
    assert connector.record_runtime() is None and asked == [True]


def test_a_connector_child_that_fails_is_reported_in_its_own_words(monkeypatch):
    from cockpitlib import connector

    monkeypatch.setattr(connector, "runtime", lambda: ("/opt/hermes/python3", "/opt/hermes/agent"))
    answer = {}

    def child(argv, **kwargs):
        answer["argv"], answer["input"] = argv, kwargs.get("input")
        if isinstance(answer["done"], Exception):
            raise answer["done"]
        return answer["done"]

    monkeypatch.setattr(connector.subprocess, "run", child)
    answer["done"] = subprocess.TimeoutExpired(["python3"], 180)
    with pytest.raises(CockpitError, match=r"the Hermes jira connector \(GET_ISSUE\): .*timed out"):
        connector.call("jira", "GET_ISSUE", {"key": "ACME-1"})
    assert answer["argv"][:3] == ["/opt/hermes/python3", "-I", "-c"] and answer["argv"][-1] == "/opt/hermes/agent"
    assert json.loads(answer["input"]) == {
        "tool": "connectors__jira__GET_ISSUE",
        "arguments": {"key": "ACME-1"},
        "id": "cockpit-get_issue",
    }
    answer["done"] = _done(1, err="ModuleNotFoundError: No module named 'tools'\n")
    with pytest.raises(CockpitError, match="No module named 'tools'"):
        connector.call("jira", "GET_ISSUE", {})
    answer["done"] = _done(0, out="warming up\n<html>\n")
    with pytest.raises(CockpitError, match="its answer is not JSON"):
        connector.call("jira", "GET_ISSUE", {})
    answer["done"] = _done(0, out='{"response": ["a list"]}\n')
    with pytest.raises(CockpitError, match=r"\(GET_ISSUE\) gave no response"):
        connector.call("jira", "GET_ISSUE", {})
    answer["done"] = _done(0, out='noise\n{"response": {"successful": true, "data": {"key": "ACME-1"}}}\n')
    assert connector.call("jira", "GET_ISSUE", {}) == {"key": "ACME-1"}


# ---------- browser_card ----------


def test_the_test_kinds_are_the_standard_ones_when_the_packs_modes_cannot_be_read(monkeypatch):
    from cockpitlib import browser_card, registry

    def unreadable(pack=None):
        raise RuntimeError("no kickoff modes")

    monkeypatch.setattr(registry, "kickoff_modes", unreadable)
    assert browser_card._test_kinds({}) == ("test", "test-kickoff")


def test_a_plan_card_is_never_its_own_run_card():
    from cockpitlib import browser_card

    assert browser_card._run_card_external({}, "board", "card-1", "ACME-1", "card-1") is False
    assert browser_card._run_card_external({}, "board", "", "ACME-1", "card-1") is False


def test_a_process_whose_card_cannot_be_told_runs_no_card(monkeypatch):
    from cockpitlib import browser_card, skill_log

    def unknown(env=None):
        raise RuntimeError("no pack to read the board from")

    monkeypatch.setattr(skill_log, "current_card", unknown)
    assert browser_card.current({}) == {}
    assert browser_card.run_card_for_plan({}, "ACME-1") == ""


def test_a_loan_to_another_ticket_is_not_this_tickets(env):
    from cockpitlib import browser_card
    from cockpitlib.paths import watch_dir

    os.makedirs(watch_dir(), exist_ok=True)
    assert browser_card.loan_refusal(_pack(), "ACME-1") == "the external browser is not lent to a ticket"
    json.dump(
        {"ticket": "ACME-2", "at": time.time(), "until": time.time() + 3600},
        open(os.path.join(watch_dir(), "shared-chrome.json"), "w", encoding="utf-8"),
    )
    assert browser_card.loan_refusal(_pack(), "ACME-1") == "the external browser is lent to another ticket"


def test_the_human_who_records_has_no_card_and_no_board_to_be_checked_against(monkeypatch):
    from cockpitlib import record

    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    assert record._allowed({"board": "acme"}) == {"lane": "", "ticket": "", "external": False, "card": "", "board": ""}
