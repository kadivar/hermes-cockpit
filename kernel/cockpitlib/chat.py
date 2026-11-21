# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One terminal per ticket, held by this process. Closing the modal leaves it running."""

import base64
import fnmatch
import glob
import json
import os
import re
import threading
import time
import uuid
from datetime import UTC, datetime

from .paths import qa_of, root, workspace, worktree_of, wt
from .store import dump_json, write_text

_LOCK = threading.Lock()
_TERMS = {}


def _agent_home() -> str:
    """The pack's coding-tool home, when that directory exists."""
    try:
        from .pack import agent_launch, load
        from .paths import pack_path

        home = agent_launch(load(pack_path())).get("home") or ""
    except Exception:  # noqa: BLE001 - no readable pack means no agent home
        return ""
    if home and os.path.isdir(home):
        return home
    return ""


def _filled(text: str, ticket: str) -> str:
    return (
        text.replace("{ticket}", ticket)
        .replace("{wt}", wt())
        .replace("{workspace}", workspace())
        .replace("{root}", root())
    )


def chat_cwd(ticket: str) -> str:
    """own is the bound workspace. A ticket coding tool starts in the pack's providers.chat.cwd when that folder exists, else
    in the pack's agent home."""
    if ticket in ("", "own"):
        return workspace()
    spec = _providers().get("chat")
    wanted = _filled(spec["cwd"], ticket) if isinstance(spec, dict) and isinstance(spec.get("cwd"), str) else ""
    if wanted and os.path.isdir(wanted):
        return wanted
    home = _agent_home()
    if home:
        return home
    folder = worktree_of(ticket)
    if os.path.isdir(folder):
        return folder
    return root()


def _clip(buf, base):
    if len(buf) <= 1_000_000:
        return buf, base
    cut = len(buf) - 600_000
    del buf[:cut]
    return buf, base + cut


_PROVIDERS = {}


def _providers() -> dict:
    """The pack's providers, parsed again only when the pack file's text changes (Live asks for every transcript)."""
    try:
        from .pack import load
        from .paths import pack_path

        path = pack_path()
        key = (path, open(path, "rb").read(), load)
        if key not in _PROVIDERS:
            _PROVIDERS.clear()
            _PROVIDERS[key] = load(path).get("providers") or {}
        providers = _PROVIDERS[key]
    except Exception:  # noqa: BLE001 - a provider table that cannot be read is empty
        return {}
    return providers if isinstance(providers, dict) else {}


def _command_of(entry) -> list:
    command = entry.get("command") if isinstance(entry, dict) else None
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        return []
    return list(command)


def _coding_spec():
    """The pack coding command and the glob that names each ticket's lane runs."""
    coding = _providers().get("coding") or {}
    if not isinstance(coding, dict):
        return [], ""
    command = _command_of(coding)
    pattern = coding.get("transcript_glob") or ""
    if not isinstance(pattern, str) or any(part == ".." for part in pattern.split("/")):
        pattern = ""
    return command, pattern


def _lane_glob() -> str:
    """providers.coding.lane_transcript_glob: where the coding tool keeps one card's run, with {home}, and {card} or
    {card_slug} (the card id with every run of other characters as one '-', as Cursor names a project folder)."""
    coding = _providers().get("coding") or {}
    text = coding.get("lane_transcript_glob") if isinstance(coding, dict) else ""
    if not isinstance(text, str) or not text or any(part == ".." for part in text.split("/")):
        return ""
    text = text.replace("{home}", os.path.expanduser("~"))
    return text if os.path.isabs(text) else ""


def card_slug(card: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", card or "")


def lane_transcript(card: str) -> str:
    """The newest transcript the coding tool kept for this card's run, or '' (no lane_transcript_glob, or none yet)."""
    template = _lane_glob()
    if not template or not card:
        return ""
    found = [
        path
        for path in glob.glob(template.replace("{card_slug}", card_slug(card)).replace("{card}", card))
        if os.path.isfile(path)
    ]
    return max(found, key=os.path.getmtime) if found else ""


def _lane_match(path: str) -> bool:
    template = _lane_glob()
    return bool(template) and fnmatch.fnmatch(path, template.replace("{card_slug}", "*").replace("{card}", "*"))


def _coding_command() -> list:
    """The pack's coding command for a ticket session. Empty when the pack does not name one."""
    return _coding_spec()[0]


def _chat_spec() -> dict:
    """The pack's chat (providers.chat): command for a new session, resume for one whose transcript exists
    (session_glob names where, with {session}), fork for one that starts from a lane's run ({source})."""
    chat = _providers().get("chat")
    if not isinstance(chat, dict):
        return {}
    spec = {key: _command_of({"command": chat.get(key)}) for key in ("command", "resume", "fork")}
    spec["session_glob"] = chat.get("session_glob") if isinstance(chat.get("session_glob"), str) else ""
    return spec if spec["command"] else {}


def chat_env(ticket: str) -> dict:
    """The pack's providers.chat.env for a chat on this ticket: {PATH} stands for the PATH the chat would have had."""
    spec = _providers().get("chat")
    table = spec.get("env") if isinstance(spec, dict) and isinstance(spec.get("env"), dict) else {}
    return {
        str(key): _filled(str(value), ticket).replace("{PATH}", os.environ.get("PATH", ""))
        for key, value in table.items()
    }


def _chat_command() -> list:
    """The pack's own chat command (providers.chat.command), when it names one."""
    return _chat_spec().get("command") or []


def session_exists(session: str) -> bool:
    """Whether the chat tool kept a transcript of the session, where the pack's session_glob says."""
    pattern = _chat_spec().get("session_glob") or ""
    if not pattern or not session:
        return False
    return any(
        os.path.isfile(path) for path in glob.glob(pattern.replace("{root}", root()).replace("{session}", session))
    )


def _fill(argv: list, session: str, source: str) -> list:
    return [part.replace("{session}", session).replace("{source}", source) for part in argv]


def chat_argv(ticket: str, session: str = "", source: str = "") -> list:
    """What a chat runs for the session: the pack's resume command when the session's transcript exists, its fork
    command for a session that starts from a lane's run, else its command; without a pack chat, _argv's rules."""
    custom = os.environ.get("COCKPIT_CHAT_ARGV") or ""
    if custom:
        return custom.split()
    spec = _chat_spec()
    if not spec:
        return _argv(ticket)
    if session and spec.get("resume") and session_exists(session):
        return _fill(spec["resume"], session, source)
    if source and spec.get("fork"):
        return _fill(spec["fork"], session, source)
    return _fill(spec["command"], session, source)


PRINT_FLAGS = ("-p", "--print")
PRINT_OPTIONS = ("--max-turns", "--output-format", "--input-format")


def interactive(command: list) -> list:
    """The coding command as a conversation: without its print-mode flags, which need a prompt on the command line
    and end after the turns they allow."""
    out = []
    skip = False
    for part in command:
        if skip:
            skip = False
            continue
        if part in PRINT_FLAGS:
            continue
        if part in PRINT_OPTIONS:
            skip = True
            continue
        if any(part.startswith(option + "=") for option in PRINT_OPTIONS):
            continue
        out.append(part)
    return out or list(command)


def _argv(ticket: str = "") -> list:
    """What the chat runs: COCKPIT_CHAT_ARGV, else the pack's chat command, else (on a ticket) the coding command
    made interactive, else the human's shell."""
    custom = os.environ.get("COCKPIT_CHAT_ARGV") or ""
    if custom:
        return custom.split()
    chat = _chat_command()
    if chat:
        return chat
    if ticket not in ("", "own"):
        command = _coding_command()
        if command:
            return interactive(command)
    shell = os.environ.get("SHELL") or "/bin/bash"
    if not os.path.isfile(shell):
        shell = "/bin/bash"
    return [shell, "-i"]


class Term:
    def __init__(self, argv, cwd, cols, rows, fork="", env=None):
        import fcntl
        import pty
        import struct
        import termios

        self.buf = bytearray()
        self.base = 0
        self.lock = threading.Lock()
        self.alive = True
        self.cwd = cwd
        self.argv = list(argv)
        self.fork = fork
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(cwd)
                os.environ["TERM"] = "xterm-256color"
                os.environ.update(env or {})
                if fork:
                    os.environ["COCKPIT_FORK_FROM"] = fork
                os.execvp(argv[0], argv)  # noqa: S606 - the forked child becomes the agent's own command line: an argv list, no shell
            except OSError as exc:
                os.write(2, str(exc).encode())
            os._exit(127)
        self.pid = pid
        self.fd = fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                data = b""
            if not data:
                break
            with self.lock:
                self.buf += data
                self.buf, self.base = _clip(self.buf, self.base)
        self.alive = False
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass

    def read(self, offset: int):
        with self.lock:
            end = self.base + len(self.buf)
            offset = max(offset, self.base)
            return bytes(self.buf[offset - self.base :]), end

    def write(self, data: bytes) -> None:
        if not self.alive:
            return
        os.write(self.fd, data)

    def resize(self, cols: int, rows: int) -> None:
        import fcntl
        import signal
        import struct
        import termios

        if not self.alive:
            return
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            os.kill(self.pid, signal.SIGWINCH)
        except OSError:
            pass

    def kill(self) -> None:
        """Hang the terminal up the way a closed window does, wait for the process, then close the master. An interactive
        shell ignores TERM but leaves on HUP; one that ignores both is killed. The master is closed only once the child is
        gone: on macOS, closing it while the reader thread sits in read() blocks for good."""
        import signal
        import time

        for sig in (signal.SIGHUP, signal.SIGTERM):
            try:
                os.kill(self.pid, sig)
            except OSError:
                pass
        deadline = time.time() + 2.0
        while time.time() < deadline and self._still_running():
            time.sleep(0.02)
        if self._still_running():
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
            deadline = time.time() + 2.0
            while time.time() < deadline and self._still_running():
                time.sleep(0.02)
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.alive = False

    def _still_running(self) -> bool:
        """Reaps the child when it has exited and nobody did yet; the reader thread's own waitpid then finds it gone."""
        try:
            pid, _status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return False
        return pid == 0


def _personal(ticket: str) -> bool:
    return ticket in ("", "own")


def _pattern(ticket: str) -> str:
    _command, template = _coding_spec()
    if not template:
        return ""
    text = template.replace("{root}", root()).replace("{ticket}", ticket)
    if not os.path.isabs(text):
        return ""
    return text


def _allowed(path: str) -> bool:
    """A transcript under the root or the workspace, or one the pack's transcript glob names (a coding tool keeps
    its transcripts in its own home)."""
    real = os.path.realpath(path)
    for base in (os.path.realpath(root()), os.path.realpath(workspace())):
        if real == base or real.startswith(base + os.sep):
            return True
    pattern = _pattern("*")
    if _lane_match(path) or _lane_match(real):
        return True
    return bool(pattern) and (fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(real, pattern))


_TICKET_KEY = re.compile(r"^([A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-[0-9]+)")


def ticket_of_transcript(path: str) -> str:
    """The ticket a transcript belongs to: what stands where the glob says {ticket}. A folder named after the
    checkout ("…-wt-TASK-123-api-service") gives its key; without a {ticket} in the glob, the folder's name."""
    _command, template = _coding_spec()
    prefix = template.split("{ticket}", 1)[0].replace("{root}", root()) if "{ticket}" in template else ""
    for candidate in (path, os.path.realpath(path)):
        if prefix and candidate.startswith(prefix):
            rest = candidate[len(prefix) :]
            match = _TICKET_KEY.match(rest)
            if match:
                return match.group(1)
            head = rest.split(os.sep, 1)[0]
            if head:
                return head
    return os.path.basename(os.path.dirname(path))


def _safe_glob(pattern: str) -> list:
    if not pattern:
        return []
    found = []
    for path in glob.glob(pattern):
        if os.path.isfile(path) and _allowed(path):
            found.append(os.path.realpath(path))
    return found


def _meta(path: str):
    prompt = ""
    card = ""
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return "", ""
    with handle:
        for index, line in enumerate(handle):
            if index > 40:
                break
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                if not prompt:
                    prompt = text[:180]
                continue
            if not isinstance(row, dict):
                continue
            if not card and row.get("card"):
                card = str(row["card"])
            if not prompt:
                prompt = str(row.get("prompt") or row.get("text") or row.get("note") or "")[:180]
    return prompt, card


def _context(path: str) -> str:
    """Lane narration and commands. A tool result stays out of the fork."""
    lines = []
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return ""
    with handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            command = row.get("command") or ""
            if command:
                lines.append(str(command)[:180])
                continue
            if row.get("output") or row.get("type") == "tool_result":
                continue
            note = row.get("text") or row.get("note") or row.get("prompt") or ""
            if note:
                lines.append(str(note)[:300])
    return "\n".join(lines)[:6000]


def _parent_stem(name: str, names) -> str:
    stem = os.path.splitext(name)[0]
    for other in names:
        base = os.path.splitext(other)[0]
        if base and base != stem and stem.startswith(base + "-"):
            return base
    return ""


def _running(path: str) -> bool:
    pidfile = path + ".pid"
    try:
        pid = int(open(pidfile, encoding="utf-8").read().strip() or "0")
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _describe(path: str, ticket: str) -> dict:
    prompt, card = _meta(path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    return {
        "id": os.path.splitext(os.path.basename(path))[0],
        "path": path,
        "ticket": ticket,
        "prompt": prompt,
        "card": card,
        "mtime": mtime,
        "running": _running(path),
    }


def lane_runs(ticket: str) -> list:
    """Lane transcripts the pack names for this ticket, oldest first."""
    if _personal(ticket):
        return []
    rows = []
    paths = _safe_glob(_pattern(ticket))
    names = [os.path.basename(path) for path in paths]
    for path in paths:
        if _parent_stem(os.path.basename(path), names):
            continue
        rows.append(_describe(path, ticket))
    rows.sort(key=lambda row: (row["mtime"], row["id"]))
    return rows


def _pick_run(ticket: str, source: str = "", card: str = ""):
    rows = lane_runs(ticket)
    if source:
        for row in rows:
            if row["id"] == source or row["path"] == source:
                return row
    if card:
        matched = [row for row in rows if row.get("card") == card]
        if matched:
            return matched[-1]
    if rows:
        return rows[-1]
    return None


def _record_path(ticket: str) -> str:
    from .paths import chat_dir

    if _personal(ticket):
        return os.path.join(chat_dir(), "own.json")
    return qa_of(ticket, "chat.json")


def _read_record(ticket: str) -> dict:
    path = _record_path(ticket)
    if not os.path.isfile(path):
        return {}
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_record(ticket: str, record: dict) -> None:
    path = _record_path(ticket)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dump_json(path, record)


def _start_record(ticket: str, run, reset: bool) -> dict:
    old = _read_record(ticket)
    previous = list(old.get("previous") or []) if isinstance(old.get("previous"), list) else []
    if reset and old.get("session"):
        previous.append(
            {
                "session": old.get("session") or "",
                "forked_from": old.get("forked_from") or "",
                "source": old.get("source") or "",
                "created": old.get("created") or "",
            }
        )
    personal = _personal(ticket)
    record = {
        "session": str(uuid.uuid4()),
        "forked_from": "" if personal or not run else run["id"],
        "source": "" if personal or not run else run["path"],
        "created": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "previous": previous,
        "personal": personal,
    }
    _write_record(ticket, record)
    if run and not personal:
        folder = os.path.dirname(_record_path(ticket))
        os.makedirs(folder, exist_ok=True)
        write_text(os.path.join(folder, "fork-context.txt"), _context(run["path"]))
    return record


def _in_pipeline(ticket: str) -> bool:
    return os.path.isdir(worktree_of(ticket))


def coding_sessions(scope: str = "pipeline") -> list:
    """Transcripts the pack's coding tool left behind. Pipeline is a ticket that has a checkout."""
    paths = _safe_glob(_pattern("*"))
    by_dir = {}
    for path in paths:
        by_dir.setdefault(os.path.dirname(path), []).append(os.path.basename(path))
    sessions = []
    children = {}
    for path in paths:
        names = by_dir.get(os.path.dirname(path), [])
        parent = _parent_stem(os.path.basename(path), names)
        if parent:
            children.setdefault((os.path.dirname(path), parent), []).append(path)
            continue
        ticket = ticket_of_transcript(path)
        if scope == "pipeline" and not _in_pipeline(ticket):
            continue
        row = _describe(path, ticket)
        sessions.append(row)
    out = []
    for row in sessions:
        subs = []
        for path in children.get((os.path.dirname(row["path"]), row["id"]), []):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0
            subs.append(
                {
                    "name": os.path.splitext(os.path.basename(path))[0],
                    "path": path,
                    "mtime": int(mtime),
                }
            )
        out.append(
            {
                "id": row["id"],
                "running": row["running"],
                "ticket": row["ticket"],
                "dir": os.path.dirname(row["path"]),
                "prompt": row["prompt"],
                "mtime": int(row["mtime"]),
                "path": row["path"],
                "subagents": subs,
            }
        )
    out += _lane_sessions()
    out.sort(key=lambda row: (-row["mtime"], row["id"]))
    return out


def _lane_sessions() -> list:
    """Each lane's own coding-tool session, when the pack names where the tool keeps them."""
    if not _lane_glob():
        return []
    try:
        from .kanban import board_cards
        from .lane_transcripts import sessions
        from .pack import load
        from .paths import pack_path

        return sessions(board_cards(load(pack_path())["board"]))
    except Exception:  # noqa: BLE001 - no readable pack or board means no sessions
        return []


def coding_tail(path: str, offset: int = 0) -> dict:
    """Entries from a transcript. A path outside the workspace is empty."""
    if not path or not _allowed(path) or not os.path.isfile(path):
        return {"path": path, "offset": offset, "lines": [], "entries": [], "running": False}
    real = os.path.realpath(path)
    try:
        size = os.path.getsize(real)
    except OSError:
        return {"path": path, "offset": offset, "lines": [], "entries": [], "running": False}
    if offset < 0 or offset > size:
        offset = 0
    try:
        handle = open(real, "rb")
    except OSError:
        return {"path": real, "offset": offset, "lines": [], "entries": [], "running": False}
    with handle:
        handle.seek(offset)
        chunk = handle.read()
    if chunk and not chunk.endswith(b"\n"):
        cut = chunk.rfind(b"\n")
        if cut >= 0:
            chunk = chunk[: cut + 1]
    end = offset + len(chunk)
    lines = chunk.decode("utf-8", "replace").splitlines()
    entries = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            entries.append({"kind": "text", "text": text[:700]})
            continue
        if not isinstance(row, dict):
            continue
        role = (
            row.get("role")
            if row.get("role") in ("user", "assistant")
            else row.get("type")
            if row.get("type") in ("user", "assistant")
            else ""
        )
        if role and isinstance(row.get("message"), dict):
            entries.extend(_message_entries({**row, "role": role}))
            continue
        special = _special_entry(row)
        if special:
            entries.append(special)
            continue
        entries.append(
            {
                "kind": str(row.get("kind") or row.get("type") or "text"),
                "text": str(row.get("text") or row.get("prompt") or row.get("note") or ""),
                "ts": str(row.get("ts") or ""),
                "name": str(row.get("name") or ""),
            }
        )
    running = _running(real) or (_lane_match(real) and time.time() - os.path.getmtime(real) < LANE_LIVE_SECONDS)
    return {"path": real, "offset": end, "lines": lines, "entries": entries, "running": running}


# a lane transcript has no pid file: it is live while the tool still writes to it (a long tool call is quiet a while)
LANE_LIVE_SECONDS = 120
TOOL_HINTS = ("command", "description", "path", "file_path", "target_file", "pattern", "query", "url", "glob_pattern")


def _special_entry(row: dict) -> dict:
    """A transcript's own lines besides messages: the final result (with its cost and turns), the session start, a summary."""
    from .render import markdown

    kind = row.get("type")
    when = str(row.get("timestamp") or row.get("ts") or "")
    if kind == "result":
        text = str(row.get("result") or "")
        return {
            "kind": "result",
            "text": text[:3000],
            "html": markdown(text[:12000]),
            "ts": when,
            "name": "",
            "cost": row.get("total_cost_usd"),
            "turns": row.get("num_turns"),
        }
    if kind == "system" and row.get("subtype") == "init":
        return {
            "kind": "system",
            "text": f"session started · model {row.get('model', '')} · tools {len(row.get('tools') or [])}",
            "ts": when,
            "name": "",
        }
    if kind == "summary":
        return {"kind": "system", "text": "summary: " + str(row.get("summary") or "")[:300], "ts": when, "name": ""}
    return {}


def _message_entries(row: dict) -> list:
    """A chat-message line, in either shape the coding tools keep: by `role` (Cursor's agent) or by `type` (a `user`/`assistant` line): text, thinking, tool calls and
    their results, with the line's time."""
    from .render import markdown

    content = row["message"].get("content")
    when = str(row.get("timestamp") or row.get("ts") or "")
    blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
    found = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "thinking" and str(block.get("thinking") or "").strip():
            found.append({"kind": "thinking", "text": str(block["thinking"])[:2000], "ts": when, "name": ""})
        if block.get("type") == "tool_result":
            given = block.get("content")
            text = (
                given
                if isinstance(given, str)
                else "\n".join(str(item.get("text") or "") for item in given or [] if isinstance(item, dict))
            )
            found.append(
                {
                    "kind": "tool_result",
                    "text": text[:3000],
                    "error": bool(block.get("is_error")),
                    "ts": when,
                    "name": "",
                }
            )
        if block.get("type") == "text" and str(block.get("text") or "").strip():
            text = str(block["text"]).strip()
            found.append(
                {
                    "kind": "prompt" if row["role"] == "user" else "text",
                    "text": text,
                    "html": markdown(text),
                    "ts": when,
                    "name": "",
                }
            )
        if block.get("type") == "tool_use":
            given = block.get("input")
            shown = given if isinstance(given, str) else json.dumps(given, ensure_ascii=False, indent=1)
            hint = next((str(given[key]) for key in TOOL_HINTS if isinstance(given, dict) and given.get(key)), "")
            found.append(
                {
                    "kind": "tool_use",
                    "name": str(block.get("name") or "tool"),
                    "summary": (hint or shown)[:240],
                    "input": shown[:8000],
                    "text": "",
                    "ts": when,
                }
            )
    return found


def chat_state(ticket: str, card: str = "") -> dict:
    with _LOCK:
        current = _TERMS.get(ticket)
    record = _read_record(ticket)
    run = None if _personal(ticket) else _pick_run(ticket, "", card)
    best = {}
    if run:
        best = {"session": run["id"], "source": run.get("card") or "lane", "cwd": chat_cwd(ticket)}
    return {
        "has_folder": True,
        "exists": current is not None or bool(record.get("session")),
        "running": current is not None and current.alive,
        "card": card,
        "cwd": current.cwd if current else (chat_cwd(ticket) if record.get("session") else ""),
        "session": record.get("session") or "",
        "forked_source": record.get("forked_from") or "",
        "created": record.get("created") or "",
        "best": best,
        "personal": _personal(ticket),
    }


def open_chat(
    ticket: str, cols: int = 120, rows: int = 36, reset: bool = False, source: str = "", card: str = ""
) -> dict:
    cwd = chat_cwd(ticket)
    with _LOCK:
        current = _TERMS.get(ticket)
        if reset and current is not None:
            current.kill()
            current = None
        record = _read_record(ticket)
        if current is None or not current.alive:
            fresh = reset or not record.get("session")
            run = None
            fork = ""
            if fresh:
                if not _personal(ticket):
                    run = _pick_run(ticket, source, card)
                record = _start_record(ticket, run, reset)
                fork = "" if _personal(ticket) or not run else run["path"]
            elif not _personal(ticket):
                fork = record.get("source") or ""
            source = os.path.splitext(os.path.basename(fork))[0] if fork else ""
            current = Term(
                chat_argv(ticket, record.get("session") or "", source), cwd, cols, rows, fork, chat_env(ticket)
            )
            _TERMS[ticket] = current
            attached = False
        else:
            current.resize(cols, rows)
            attached = True
    data, end = current.read(0)
    return {
        "ticket": ticket,
        "cwd": current.cwd,
        "alive": current.alive,
        "attached": attached,
        "offset": end,
        "replay": base64.b64encode(data).decode(),
        "text": data.decode("utf-8", "replace"),
        "session": record.get("session") or "",
        "forked_from": record.get("forked_from") or "",
    }


def read_chat(ticket: str, offset: int = 0) -> dict:
    with _LOCK:
        current = _TERMS.get(ticket)
    if current is None:
        return {"alive": False, "text": "", "data": "", "offset": offset, "gone": True}
    data, end = current.read(offset)
    return {
        "alive": current.alive,
        "text": data.decode("utf-8", "replace"),
        "data": base64.b64encode(data).decode(),
        "offset": end,
        "gone": False,
    }


def write_chat(ticket: str, payload: bytes) -> None:
    from .errors import CockpitError

    with _LOCK:
        current = _TERMS.get(ticket)
    if current is None or not current.alive:
        raise CockpitError("the chat is not running: open it again")
    current.write(payload)


def resize_chat(ticket: str, cols: int, rows: int) -> None:
    with _LOCK:
        current = _TERMS.get(ticket)
    if current is None:
        return
    current.resize(cols, rows)


def end_chat(ticket: str) -> bool:
    """Stop the ticket's coding session. True when one was running."""
    with _LOCK:
        current = _TERMS.pop(ticket, None)
    if current is None:
        return False
    current.kill()
    return True
