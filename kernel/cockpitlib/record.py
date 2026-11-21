# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit record`: one reproduction video of a failed test scenario, from the browser the test kickoff drives.

start attaches to the page of a browser session over CDP (the card's Hermes built-in browser session, or the external
browser's tab when the human started the test kickoff with it), and a detached recorder keeps Page.startScreencast
frames under watch/record/. stop ends it, encodes the frames to H.264 .mp4 (yuv420p, +faststart, a constant 8 fps by
holding each frame until the next), keeps the file only when ffprobe and a full decode accept it, and writes the
section of the README.md beside the video.

Only a test kickoff card records (a tester phase inside another flow and every supervisor card do not), only into its
own ticket's run folder `qa/<ticket>/<run>/<evidence folder>/videos/<scenario>-<slug>-repro.mp4`, and never over a file: a
taken name gets -take2, -take3.
"""

import base64
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

from .errors import CockpitError
from .store import append_line, dump_json

FPS = 8
MAX_SECONDS = 180
MAX_SECONDS_CAP = 600
SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")  # Hermes 0.23 browser_exec's session names
VIDEO = re.compile(
    r"^(?P<scenario>[A-Za-z0-9]{1,16})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+){0,11})-repro(?:-take(?P<take>\d+))?\.mp4$"
)
KERNEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START_WAIT = 15.0
IDLE_SHOT = 1.0  # seconds without a screencast frame before the recorder takes a screenshot instead
STOP_WAIT = 20.0


# ---------- who may record, and where ----------


def _allowed(pack) -> dict:
    """The card facts of a lane allowed to record; the human (no lane) records on any ticket's run folder."""
    lane = os.environ.get("COCKPIT_LANE") or ""
    if not lane:
        return {"lane": "", "ticket": "", "external": False, "card": "", "board": ""}
    from .browser_card import current

    here = current(pack)
    if here.get("release"):
        raise CockpitError(
            "cockpit record is not for supervisor cards (policy release): a failure video belongs to a "
            "test kickoff the human started"
        )
    if not here.get("test_kickoff"):
        raise CockpitError(
            "cockpit record runs only on a test kickoff card (`<ticket>: test`): a test phase inside a dev "
            "or another flow records no video, its screenshots are the evidence"
        )
    ticket = here.get("ticket") or ""
    external = bool(here.get("external"))
    if external:
        # the external browser only while the kickoff's loan for this ticket still runs (as the fence's external_refusal)
        from .browser_card import loan_refusal

        loan = loan_refusal(pack, ticket)
        if loan:
            raise CockpitError(f"cockpit record on the external browser: {loan}")
    return {
        "lane": lane,
        "ticket": ticket,
        "external": external,
        "card": here.get("card") or "",
        "board": str((pack or {}).get("board") or ""),
    }


def _session_name(session: str, lane: str, ticket: str = "") -> str:
    """A lane's session is exactly "<lane>-<ticket>" of its card (tester-1-TASK-1 is not tester's); the human names any."""
    session = str(session or "").strip()
    if not SESSION.match(session):
        raise CockpitError("--session takes the card's browser session name (letters, digits, - and _, up to 64)")
    if lane and (not ticket or session != f"{lane}-{ticket}"):
        raise CockpitError(
            f'--session is this card\'s own browser session ("{lane}-{ticket or "<ticket>"}"), not {session}'
        )
    return session


def video_path(pack, out: str, ticket: str = "") -> dict:
    """{path, ticket, run, scenario, slug} for --out: a file named <scenario>-<slug>-repro.mp4 in
    the videos folder of a run's evidence (qa/<ticket>/<run>/<testflow.evidence_dir>/videos/), the run folder by the
    pack's pattern. A taken name
    moves to the next -takeN; nothing is ever overwritten."""
    from .paths import qa, workspace
    from .test_flow import evidence_dir, run_folders

    kept = evidence_dir(pack)
    raw = str(out or "").strip()
    if not raw or "\0" in raw:
        raise CockpitError(f"--out names the video: qa/<ticket>/<run>/{kept}/videos/<scenario>-<slug>-repro.mp4")
    full = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(workspace(), raw))
    if not os.path.isabs(raw) and not os.path.exists(os.path.dirname(full)):
        relative = os.path.realpath(os.path.join(os.getcwd(), raw))
        full = relative if os.path.exists(os.path.dirname(relative)) else full
    root = os.path.realpath(qa())
    if not full.startswith(root + os.sep):
        raise CockpitError(f"--out must be under the records' qa/<ticket>/<run>/{kept}/videos/ ({raw})")
    parts = os.path.relpath(full, root).split(os.sep)
    if len(parts) != 5 or parts[2:4] != [kept, "videos"]:
        raise CockpitError(f"--out must be qa/<ticket>/<run>/{kept}/videos/<file> ({raw})")
    owner, run, name = parts[0], parts[1], parts[4]
    if ticket and owner != ticket:
        raise CockpitError(f"{owner} is not this card's ticket ({ticket})")
    if run not in run_folders(pack, os.path.join(root, owner)):
        raise CockpitError(
            f"{run} is not a test run folder of {owner}: record into the run the results are written to "
            f"(cockpit test run-dir {owner} names the next one)"
        )
    match = VIDEO.match(name)
    if not match:
        raise CockpitError(f"the video is named <scenario>-<slug>-repro.mp4, e.g. s3-save-button-repro.mp4 ({name})")
    folder = os.path.join(root, owner, run, kept, "videos")
    os.makedirs(folder, exist_ok=True)
    if os.path.islink(folder) or os.path.realpath(folder) != folder:
        raise CockpitError("the videos folder may not be a link")
    path = free_name(os.path.join(folder, name))
    return {"path": path, "ticket": owner, "run": run, "scenario": match.group("scenario"), "slug": match.group("slug")}


def free_name(path: str) -> str:
    """path, or its next -takeN when taken (by a file or by a recording still running into it)."""
    folder, name = os.path.split(path)
    match = VIDEO.match(name)
    if not match:
        raise CockpitError(f"not a video name: {name}")
    stem = f"{match.group('scenario')}-{match.group('slug')}-repro"
    take = int(match.group("take") or 1)
    claimed = {state.get("out") for state in _states()}
    candidate = path
    while os.path.exists(candidate) or candidate in claimed:
        take += 1
        candidate = os.path.join(folder, f"{stem}-take{take}.mp4")
    return candidate


# ---------- the browser of a session ----------


def _home_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.expanduser(path)))


def _devtools_port(user_data_dir: str):
    """(port, browser path) from Chromium's DevToolsActivePort, else None."""
    try:
        with open(os.path.join(user_data_dir, "DevToolsActivePort"), encoding="utf-8-sig") as handle:
            port, path = handle.readline().strip(), handle.readline().strip()
    except OSError:
        return None
    if not port.isdigit() or not path.startswith("/devtools/browser/"):
        return None
    return int(port), path


def _get_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as answer:  # noqa: S310 - loopback only: built by this module
        return json.loads(answer.read().decode("utf-8"))


def _live(port: int) -> bool:
    try:
        return bool(_get_json(f"http://127.0.0.1:{port}/json/version", timeout=2).get("webSocketDebuggerUrl"))
    except (OSError, ValueError):
        return False


def builtin_port(lane: str, session: str):
    """The DevTools port of the local Chromium Hermes 0.23 launched for browser_exec session `session` of this seat
    (tests/contract/hermes-browser.json): <home>/cache/browser/chromium/<sha256(home_key NUL key)[:16]>-<owner>/
    DevToolsActivePort, key bu-named-<session> (plus @<home_key> when a gateway serves the profile). The newest live
    one wins; None when the session has no local browser running."""
    from .lanes import profile_dir
    from .paths import hermes_home

    homes = [
        home for home in dict.fromkeys([_home_key(profile_dir(lane)) if lane else "", _home_key(hermes_home())]) if home
    ]
    keys = [f"bu-named-{session}"] + [f"bu-named-{session}@{home}" for home in homes]
    found = []
    for home in homes:
        root = os.path.join(home, "cache", "browser", "chromium")
        for key in keys:
            digest = hashlib.sha256(f"{home}\0{key}".encode()).hexdigest()[:16]
            for folder in glob.glob(os.path.join(glob.escape(root), f"{digest}-*")):
                port = _devtools_port(folder)
                if port:
                    found.append((os.path.getmtime(os.path.join(folder, "DevToolsActivePort")), port[0]))
    for _when, port in sorted(found, reverse=True):
        if _live(port):
            return port
    return None


def _seat_cdp_port(lane: str):
    """The port of browser.cdp_url in the seat's config.yaml (a seat whose built-in browser attaches to a CDP endpoint)."""
    from .lanes import profile_dir

    if not lane:
        return None
    try:
        import yaml

        config = yaml.safe_load(open(os.path.join(profile_dir(lane), "config.yaml"), encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return None
    url = str(((config.get("browser") or {}) if isinstance(config, dict) else {}).get("cdp_url") or "")
    match = re.match(r"^https?://(?:127\.0\.0\.1|localhost):(\d+)/?$", url.strip())
    return int(match.group(1)) if match else None


def browser_port(pack, lane: str, session: str, external: bool) -> int:
    if external:
        port = (pack or {}).get("human_browser_port") or _seat_cdp_port(lane) or 9222
        return int(port)
    port = builtin_port(lane, session) or _seat_cdp_port(lane)
    if not port:
        raise CockpitError(
            f"no live built-in browser for session {session}: drive it with browser_exec "
            f'(session "{session}") first, then start the recording'
        )
    return int(port)


def page_target(port: int, url_contains: str = "") -> dict:
    """The page to record: the one whose URL holds url_contains, else the most recently active real page."""
    try:
        targets = _get_json(f"http://127.0.0.1:{port}/json/list")
    except (OSError, ValueError) as exc:
        raise CockpitError(f"the browser on port {port} does not answer: {exc}") from exc
    pages = [
        item
        for item in targets
        if isinstance(item, dict) and item.get("type") == "page" and item.get("webSocketDebuggerUrl")
    ]
    if url_contains:
        pages = [item for item in pages if url_contains in str(item.get("url") or "")]
        if not pages:
            raise CockpitError(f"no tab whose URL holds {url_contains!r} in that browser")
    real = [item for item in pages if not str(item.get("url") or "").startswith(("about:", "chrome:", "devtools:"))]
    chosen = (real or pages or [None])[0]
    if not chosen:
        raise CockpitError(f"the browser on port {port} has no page to record")
    return {
        "ws": chosen["webSocketDebuggerUrl"],
        "url": str(chosen.get("url") or ""),
        "title": str(chosen.get("title") or ""),
    }


# ---------- state ----------


def _state_dir() -> str:
    from .paths import watch_dir

    return os.path.join(watch_dir(), "record")


def _state_file(session: str) -> str:
    return os.path.join(_state_dir(), f"{session}.json")


def _states() -> list:
    folder = _state_dir()
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            try:
                found.append(json.load(open(os.path.join(folder, name), encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return found


def _write_json(path: str, data: dict) -> None:
    dump_json(path, data)


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as handle:
            return handle.read().split()[2] != "Z"
    except (OSError, IndexError):
        return True


# ---------- start / stop / status ----------


def _no_secret(*texts) -> None:
    from .scrub import holds_secret

    if holds_secret([str(text) for text in texts if text]):
        raise CockpitError("a secret may not be part of a recording's arguments")


def start(
    pack, session: str, out: str, record_id: str, on_screen: str, max_seconds: int = MAX_SECONDS, url_contains: str = ""
) -> dict:
    who = _allowed(pack)
    lane = who["lane"]
    session = _session_name(session, lane, who["ticket"])
    _no_secret(out, record_id, on_screen, url_contains)
    record_id, on_screen = str(record_id or "").strip(), " ".join(str(on_screen or "").split())
    if len(record_id) > 120:
        raise CockpitError(
            "--record-id names the test record this clip ran on (the new one made for this clip), up to 120"
        )
    if len(on_screen) > 300:
        raise CockpitError("--on-screen says in one line what was on screen when the recording started, up to 300")
    seconds = int(max_seconds or MAX_SECONDS)
    if seconds < 5 or seconds > MAX_SECONDS_CAP:
        raise CockpitError(f"--max-seconds is 5 to {MAX_SECONDS_CAP}")
    if not lane:
        lane = next((name for name in _profiles() if session.startswith(f"{name}-")), "")
    os.makedirs(_state_dir(), exist_ok=True)
    state_path = _state_file(session)
    if os.path.isfile(state_path):
        old = json.load(open(state_path, encoding="utf-8"))
        if _alive(old.get("pid")):
            raise CockpitError(f"a recording of session {session} is running: cockpit record stop --session {session}")
        _discard(old)
    target = video_path(pack, out, who["ticket"])
    port = browser_port(pack, lane, session, who["external"])
    page = page_target(port, url_contains)
    frames = os.path.join(_state_dir(), f"{session}.frames")
    shutil.rmtree(frames, ignore_errors=True)
    os.makedirs(frames)
    state = {
        "session": session,
        "lane": lane,
        "ticket": target["ticket"],
        "run": target["run"],
        "out": target["path"],
        "scenario": target["scenario"],
        "slug": target["slug"],
        "record_id": record_id,
        "on_screen": on_screen,
        "max_seconds": seconds,
        "port": port,
        "ws": page["ws"],
        "url": page["url"],
        "title": page["title"],
        "external": who["external"],
        "frames": frames,
        "started": time.time(),
        "pid": 0,
        "card": who["card"],
        "board": who["board"],
    }
    _write_json(state_path, state)
    log = open(os.path.join(_state_dir(), f"{session}.log"), "w", encoding="utf-8")
    code = f"import sys; sys.path.insert(0, {KERNEL!r}); from cockpitlib.record import run_recorder; run_recorder({state_path!r})"
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
        close_fds=True,
    )
    log.close()
    state["pid"] = child.pid
    _write_json(state_path, state)
    deadline = time.monotonic() + START_WAIT
    ready = os.path.join(frames, "ready")
    while time.monotonic() < deadline and not os.path.exists(ready) and child.poll() is None:
        time.sleep(0.1)
    if not os.path.exists(ready):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        why = _log_tail(session)
        _discard(state)
        raise CockpitError(f"the recorder did not attach to the page: {why or 'no answer from the browser'}")
    return {
        "ok": True,
        "session": session,
        "recording": os.path.relpath(target["path"], _workspace()),
        "tab": page["url"],
        "max_seconds": seconds,
        "stop": f"cockpit record stop --session {session}",
    }


def _profiles() -> list:
    from .paths import hermes_home

    folder = os.path.join(hermes_home(), "profiles")
    names = os.listdir(folder) if os.path.isdir(folder) else []
    return sorted(names, key=len, reverse=True)


def _workspace() -> str:
    from .paths import workspace

    return workspace()


def _log_tail(session: str) -> str:
    try:
        lines = open(os.path.join(_state_dir(), f"{session}.log"), encoding="utf-8").read().strip().splitlines()
    except OSError:
        return ""
    return (lines[-1] if lines else "")[-300:]


def _discard(state: dict) -> None:
    shutil.rmtree(str(state.get("frames") or "/nonexistent-cockpit-frames"), ignore_errors=True)
    for suffix in (".json", ".log"):
        try:
            os.remove(os.path.join(_state_dir(), f"{state.get('session')}{suffix}"))
        except OSError:
            pass


def status(session: str = "") -> dict:
    rows = []
    for state in _states():
        if session and state.get("session") != session:
            continue
        frames = len(glob.glob(os.path.join(glob.escape(str(state.get("frames") or "")), "*.jpg")))
        rows.append(
            {
                "session": state.get("session"),
                "out": state.get("out"),
                "running": _alive(state.get("pid")),
                "seconds": round(time.time() - float(state.get("started") or time.time()), 1),
                "frames": frames,
            }
        )
    return {"recordings": rows}


def stop(pack, session: str) -> dict:
    lane = os.environ.get("COCKPIT_LANE") or ""
    ticket = _allowed(pack)["ticket"] if lane else ""
    session = _session_name(session, lane, ticket)
    path = _state_file(session)
    if not os.path.isfile(path):
        raise CockpitError(f"no recording of session {session} (cockpit record start first)")
    state = json.load(open(path, encoding="utf-8"))
    frames = state["frames"]
    open(os.path.join(frames, "stop"), "w").close()
    deadline = time.monotonic() + STOP_WAIT
    while time.monotonic() < deadline and _alive(state.get("pid")) and not os.path.exists(os.path.join(frames, "done")):
        time.sleep(0.1)
    if _alive(state.get("pid")):
        try:
            os.killpg(int(state["pid"]), signal.SIGTERM)
        except OSError:
            pass
        time.sleep(1.0)
    try:
        result = encode(state)
    finally:
        _discard(state)
    return result


FRAMES_MAX_AGE = 86400


def _card_open(state: dict) -> bool:
    """A recording made on a card lives while that card is open; the human's (no card) while its recorder runs."""
    card, board = str(state.get("card") or ""), str(state.get("board") or "")
    if not card or not board:
        return _alive(state.get("pid"))
    from .kanban import OPEN, board_cards

    row = next((item for item in board_cards(board) if item["id"] == card), None)
    return bool(row) and str(row.get("status") or "") in OPEN


def _kill(pid) -> None:
    if not _alive(pid):
        return
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except (OSError, TypeError, ValueError):
        pass


def sweep(pack=None, now=None) -> dict:
    """Leftovers of recordings (run by the hourly slot-gc): a recorder whose card ended is stopped and its frames,
    state and log removed; a frames folder no recording names, or older than a day, goes too. No video is written."""
    folder = _state_dir()
    if not os.path.isdir(folder):
        return {"stopped": [], "removed": []}
    now = time.time() if now is None else now
    stopped, removed, named = [], [], set()
    for state in _states():
        session = str(state.get("session") or "")
        frames = str(state.get("frames") or "")
        old = float(state.get("started") or now) < now - FRAMES_MAX_AGE
        if _card_open(state) and not old:
            named.add(os.path.realpath(frames))
            continue
        _kill(state.get("pid"))
        _discard(state)
        stopped.append(session)
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not name.endswith(".frames") or os.path.realpath(path) in named or os.path.islink(path):
            continue
        state_path = _state_file(name[: -len(".frames")])
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if os.path.isfile(state_path) and age < FRAMES_MAX_AGE:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(name)
    return {"stopped": stopped, "removed": removed}


# ---------- the detached recorder ----------


def run_recorder(state_path: str) -> None:
    """The background process: screencast frames into the frames folder until stop, the time cap, or SIGTERM."""
    from .cdp_ws import Closed, Socket

    state = json.load(open(state_path, encoding="utf-8"))
    frames = state["frames"]
    stopping = {"why": ""}

    def _term(_signum, _frame):
        stopping["why"] = stopping["why"] or "terminated"

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    index = []

    def _keep(data: str, at: float) -> None:
        name = f"{len(index):06d}.jpg"
        with open(os.path.join(frames, name), "wb") as handle:
            handle.write(base64.b64decode(data))
        index.append({"file": name, "t": at})

    socket = Socket(state["ws"])
    deadline = float(state["started"]) + int(state["max_seconds"])
    try:
        shot = socket.call("Page.captureScreenshot", {"format": "jpeg", "quality": 85})
        if shot.get("data"):
            _keep(shot["data"], time.time())
        socket.call(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 85, "maxWidth": 1600, "maxHeight": 1600, "everyNthFrame": 1},
        )
        open(os.path.join(frames, "ready"), "w").close()
        while not stopping["why"]:
            if os.path.exists(os.path.join(frames, "stop")):
                stopping["why"] = "stopped"
                break
            if time.time() >= deadline:
                stopping["why"] = "time cap"
                break
            event = socket.poll(0.25)
            if not event or event.get("method") != "Page.screencastFrame":
                if not index or time.time() - index[-1]["t"] >= IDLE_SHOT:
                    # a tab Chrome does not paint (hidden, or nothing changed) sends no screencast frame: keep the
                    # timeline with a plain screenshot so the video still shows what was there
                    shot = socket.call("Page.captureScreenshot", {"format": "jpeg", "quality": 85}, timeout=5)
                    if shot.get("data"):
                        _keep(shot["data"], time.time())
                continue
            params = event.get("params") or {}
            _keep(params.get("data") or "", time.time())
            socket.send(
                {"id": 0, "method": "Page.screencastFrameAck", "params": {"sessionId": params.get("sessionId")}}
            )
        try:
            socket.call("Page.stopScreencast", {}, timeout=3)
            last = socket.call("Page.captureScreenshot", {"format": "jpeg", "quality": 85}, timeout=5)
            if last.get("data"):
                _keep(last["data"], time.time())  # the screen as it was when the recording ended
        except (Closed, OSError, RuntimeError, TimeoutError):
            pass
    except (Closed, OSError, RuntimeError, TimeoutError) as exc:
        stopping["why"] = f"browser: {exc}"
        print(f"recorder: {exc}", flush=True)
    finally:
        socket.close()
        _write_json(
            os.path.join(frames, "frames.json"), {"frames": index, "ended": time.time(), "why": stopping["why"]}
        )
        open(os.path.join(frames, "done"), "w").close()


# ---------- encode and verify ----------


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    from .paths import hermes_home

    bundled = sorted(glob.glob(os.path.join(hermes_home(), "tools", "ffmpeg-*", "**", name), recursive=True))
    if bundled:
        return bundled[-1]
    raise CockpitError(f"{name} not found: the video cannot be encoded or checked")


def encode(state: dict) -> dict:
    """Frames → H.264 mp4 at a constant 8 fps; kept only when it plays."""
    frames = state["frames"]
    try:
        listed = json.load(open(os.path.join(frames, "frames.json"), encoding="utf-8"))
    except (OSError, ValueError):
        listed = {
            "frames": [
                {"file": name, "t": os.path.getmtime(os.path.join(frames, name))}
                for name in sorted(os.listdir(frames))
                if name.endswith(".jpg")
            ],
            "ended": time.time(),
        }
    shots = [item for item in listed.get("frames") or [] if os.path.getsize(os.path.join(frames, item["file"])) > 0]
    if not shots:
        raise CockpitError("the recording has no frames: nothing was on screen to record (the video was not written)")
    ended = float(listed.get("ended") or shots[-1]["t"])
    lines = ["ffconcat version 1.0"]
    for number, item in enumerate(shots):
        until = shots[number + 1]["t"] if number + 1 < len(shots) else max(ended, item["t"] + 1.0)
        lines += [f"file '{item['file']}'", f"duration {max(until - item['t'], 1.0 / FPS):.3f}"]
    lines.append(f"file '{shots[-1]['file']}'")
    concat = os.path.join(frames, "frames.ffconcat")
    open(concat, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    out = state["out"]
    temp = os.path.join(os.path.dirname(out), f".{os.path.basename(out)}.part.mp4")
    done = subprocess.run(
        [
            _tool("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat,
            "-vf",
            f"fps={FPS},scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-r",
            str(FPS),
            "-movflags",
            "+faststart",
            temp,
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if done.returncode != 0:
        _remove(temp)
        raise CockpitError(f"ffmpeg could not encode the video: {(done.stderr or '').strip()[-300:]}")
    problem = playable(temp)
    if problem:
        _remove(temp)
        raise CockpitError(f"the video does not play ({problem}); it was not kept")
    final = _place(temp, out)
    _remove(temp)
    probe = _probe(final)
    readme = _readme(state, final, probe, len(shots))
    workspace = _workspace()
    return {
        "ok": True,
        "video": os.path.relpath(final, workspace),
        "readme": os.path.relpath(readme, workspace),
        "duration": probe["duration"],
        "fps": FPS,
        "frames_captured": len(shots),
        "ended_by": listed.get("why") or "stopped",
    }


def _place(temp: str, out: str) -> str:
    """Link temp onto out, never over a file: a link onto a taken name fails, and the next free -takeN is tried."""
    final = out
    for _attempt in range(1000):
        try:
            os.link(temp, final)
            return final
        except FileExistsError:
            final = free_name(final)
    raise CockpitError(f"no free name for the video next to {out}")


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _probe(path: str) -> dict:
    done = subprocess.run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,r_frame_rate:format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        data = json.loads(done.stdout or "{}")
    except ValueError:
        data = {}
    stream = (data.get("streams") or [{}])[0]
    try:
        duration = round(float((data.get("format") or {}).get("duration") or 0), 2)
    except ValueError:
        duration = 0.0
    return {
        "codec": stream.get("codec_name"),
        "pix_fmt": stream.get("pix_fmt"),
        "rate": stream.get("r_frame_rate"),
        "duration": duration,
    }


def playable(path: str) -> str:
    """'' when the file is H.264 yuv420p at 8/1 with a duration and decodes whole; else what is wrong."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return "empty file"
    probe = _probe(path)
    if (
        probe["codec"] != "h264"
        or probe["pix_fmt"] != "yuv420p"
        or probe["rate"] != f"{FPS}/1"
        or probe["duration"] <= 0
    ):
        return f"ffprobe: {probe}"
    decoded = subprocess.run(
        [_tool("ffmpeg"), "-v", "error", "-i", path, "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if decoded.returncode != 0 or decoded.stderr.strip():
        return f"decode: {(decoded.stderr or '').strip()[-200:]}"
    return ""


def _mov_playable(path: str) -> str:
    """A .mov, which `cockpit record` does not write (a screen recording made by hand): any video stream with a
    duration that decodes whole."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return "empty file"
    probe = _probe(path)
    if not probe["codec"] or probe["duration"] <= 0:
        return f"ffprobe: {probe}"
    decoded = subprocess.run(
        [_tool("ffmpeg"), "-v", "error", "-i", path, "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if decoded.returncode != 0 or decoded.stderr.strip():
        return f"decode: {(decoded.stderr or '').strip()[-200:]}"
    return ""


def accepted(path: str) -> str:
    """playable() for a failure video the close gate reads (a .mov by _mov_playable), cached by the file's
    mtime and size in watch/record-playable.json (beside watch/record/, whose .json files are recordings) so a gate that runs on every complete stays cheap."""
    from .paths import watch_dir

    try:
        stat = os.stat(path)
    except OSError:
        return "empty file"
    key = os.path.realpath(path)
    mark = [stat.st_mtime_ns, stat.st_size]
    cache_path = os.path.join(watch_dir(), "record-playable.json")
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    cache = cache if isinstance(cache, dict) else {}
    hit = cache.get(key)
    if isinstance(hit, list) and hit[:2] == mark:
        return str(hit[2])
    try:
        verdict = _mov_playable(path) if path.lower().endswith(".mov") else playable(path)
    except (CockpitError, subprocess.TimeoutExpired) as exc:
        return str(exc) or "the check timed out"  # not cached: a missing ffprobe is not the file's fault
    cache[key] = mark + [verdict]
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        _write_json(cache_path, cache)
    except OSError:
        pass
    return verdict


def _readme(state: dict, video: str, probe: dict, frames: int) -> str:
    """One section per clip in the README.md beside the videos, appended."""
    path = os.path.join(os.path.dirname(video), "README.md")
    fresh = not os.path.isfile(path)
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(float(state["started"])))
    browser = (
        "the external browser (test kickoff option)"
        if state.get("external")
        else f"built-in browser, session {state['session']}"
    )
    lines = []
    if fresh:
        lines += [
            f"# {state['ticket']} {state['run']} · failure videos",
            "",
            "One reproduction video per failed scenario, recorded with `cockpit record`.",
            "",
        ]
    lines += [
        f"## {os.path.basename(video)}",
        "",
        f"- Scenario: #{state['scenario']} ({state['slug'].replace('-', ' ')})",
        f"- Test record: {state.get('record_id') or '(not given)'}",
        f"- On screen at start: {state.get('on_screen') or '(not given)'}",
        f"- Tab at start: {state.get('url') or '?'}",
        f"- Duration: {probe['duration']} s at {FPS} fps ({frames} frames captured), {browser}",
        f"- Recorded: {when}" + (f" by {state['lane']}" if state.get("lane") else ""),
        "",
    ]
    append_line(path, "\n".join(lines) + "\n")
    return path
