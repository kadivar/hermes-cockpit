# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Progress for a respawned card. Tool output never enters the note."""

import os

from .pack import plugin_root
from .store import append_line, dump_json

NORMAL = {"completed", "blocked", "review_requested", "done"}
MAX_CHARS = 6000


def hook_path() -> str:
    return os.path.join(plugin_root(), "hooks", "resume-context.sh")


def hook_installed() -> bool:
    return os.path.isfile(hook_path())


def resume_registered(text: str) -> bool:
    """True only when the resume hook is the host pre-model call, not a mention elsewhere."""
    in_hooks = False
    in_pre = False
    for line in (text or "").splitlines():
        if line.startswith("hooks:"):
            in_hooks = True
            in_pre = False
            continue
        if in_hooks and line and not line[0].isspace():
            in_hooks = False
            in_pre = False
        if not in_hooks:
            continue
        if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":"):
            in_pre = line.strip() == "pre_llm_call:"
            continue
        if in_pre and "resume-context.sh" in line:
            return True
    return False


def hook_registered() -> bool:
    """The host pre-model call lists the resume hook. A file on disk is not registration."""
    from .paths import hermes_home

    path = os.path.join(hermes_home(), "config.yaml")
    if not os.path.isfile(path):
        return False
    return resume_registered(open(path, encoding="utf-8").read())


def _clip(text, limit) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def unfinished(runs) -> list:
    """Runs that ended abnormally since the last run that ended on purpose."""
    pending = []
    for run in runs or []:
        if not run.get("ended"):
            continue
        if (run.get("outcome") or "") in NORMAL:
            pending = []
            continue
        pending.append(run)
    return pending


def _heartbeat_text(row) -> str:
    """The heartbeat note on a row. A bare timestamp is not a note."""
    beat = row.get("heartbeat")
    if isinstance(beat, str) and beat.strip():
        return beat.strip()
    kind = row.get("kind") or ""
    if not kind:
        kind = row.get("type") or ""
    if kind != "heartbeat":
        return ""
    payload = row.get("payload")
    if isinstance(payload, dict):
        return str(payload.get("note") or payload.get("text") or "").strip()
    if isinstance(payload, str):
        return payload.strip()
    return ""


def _narration_text(row) -> str:
    return str(row.get("text") or row.get("note") or "").strip()


def events_from_transcript(path: str) -> list:
    """Narration, heartbeat notes, and commands from a transcript. A finished run contributes nothing."""
    if not path or not os.path.isfile(path):
        return []
    events = []
    outcome = ""
    for line in open(path, encoding="utf-8"):
        text = line.strip()
        if not text:
            continue
        try:
            import json

            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("outcome"):
            outcome = row.get("outcome") or ""
        if row.get("command"):
            events.append({"command": row.get("command"), "exit": row.get("exit")})
            continue
        if row.get("output") or row.get("type") == "tool_result":
            events.append({"output": row.get("output") or "tool"})
            continue
        beat = _heartbeat_text(row)
        narration = _narration_text(row)
        if beat:
            events.append({"text": beat})
        if narration and narration != beat:
            events.append({"text": narration})
    if outcome in NORMAL:
        return []
    return events


def note_from_transcript(path: str) -> str:
    return progress_note(events_from_transcript(path))


def _first_turn(data) -> bool:
    """The host says this is the first turn. A later turn does not replay the dead run."""
    extra = data.get("extra") if isinstance(data, dict) and isinstance(data.get("extra"), dict) else {}
    if "is_first_turn" in extra:
        return bool(extra.get("is_first_turn"))
    if isinstance(data, dict) and "is_first_turn" in data:
        return bool(data.get("is_first_turn"))
    history = extra.get("conversation_history")
    if not isinstance(history, list):
        return False
    return len(history) <= 1


def _dead_run(path: str) -> bool:
    """A crash has no ending. A rate limit or a reclaim names itself. A run that ended on purpose does not."""
    outcome = ""
    for line in open(path, encoding="utf-8"):
        text = line.strip()
        if not text:
            continue
        try:
            import json

            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not row.get("outcome"):
            continue
        outcome = str(row.get("outcome") or "")
    if outcome in NORMAL:
        return False
    if not outcome:
        return True
    lowered = outcome.lower()
    return "rate" in lowered or "reclaim" in lowered or "crash" in lowered


def hook_context(data, pack=None) -> str:
    """The note a pre-model call inserts on the first turn after a crash, a rate limit, or a reclaim."""
    if not _first_turn(data):
        return ""
    path = transcript_for(data)
    if not path or shown_resume(path):
        return ""
    if not _dead_run(path):
        return ""
    note = note_from_transcript(path)
    if not note:
        return ""
    mark_resume(path)
    write_resume_log(note)
    from .housekeeping import stamp_from_transcript

    stamp_from_transcript(pack or {}, path)
    return note


def _transcripts() -> list:
    """(mtime, path) of every lane transcript: under the workspace and the pack's lane-run glob. A subagent's is left
    out: its note belongs to the run that started it."""
    from .chat import _pattern, _safe_glob
    from .paths import records_name, workspace

    roots = (
        os.path.join(workspace(), records_name(), "watch", "transcripts"),
        os.path.join(workspace(), "transcripts"),
    )
    found = set()
    for root in roots:
        for dirpath, _dirs, names in os.walk(root) if os.path.isdir(root) else []:
            found.update(os.path.join(dirpath, name) for name in names if name.endswith(".jsonl"))
    found.update(path for path in _safe_glob(_pattern("*")) if path.endswith(".jsonl"))
    rows = []
    for path in found:
        if any("subagent" in part for part in path.split(os.sep)):
            continue
        try:
            rows.append((os.path.getmtime(path), path))
        except OSError:
            continue
    return sorted(rows)


def _belongs(path: str, keys: set) -> bool:
    """The transcript is named after the card or session, sits in a folder so named, or its rows say so."""
    parts = set(path.split(os.sep)) | {os.path.splitext(os.path.basename(path))[0]}
    if parts & keys:
        return True
    import json

    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return False
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(row, dict)
                and {str(row.get(key) or "") for key in ("card", "task_id", "session_id", "session")} & keys
            ):
                return True
    return False


def transcript_for(data=None) -> str:
    """This run's transcript: the one of the card Hermes is running (HERMES_KANBAN_TASK) or of the hook's session. With
    a card or a session and no transcript of it, none: another card's note never reaches this one."""
    data = data if isinstance(data, dict) else {}
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    keys = {
        str(value)
        for value in (
            os.environ.get("HERMES_KANBAN_TASK"),
            data.get("task_id"),
            extra.get("task_id"),
            data.get("session_id"),
            extra.get("session_id"),
        )
        if value
    }
    rows = _transcripts()
    if keys:
        rows = [(mtime, path) for mtime, path in rows if _belongs(path, keys)]
    return rows[-1][1] if rows else ""


def latest_transcript() -> str:
    """The newest transcript of this run (see transcript_for). Empty when the lane has none."""
    return transcript_for({})


def shown_resume(key: str) -> bool:
    """True when this run's note was already inserted on an earlier turn."""
    import json

    from .paths import watch_dir

    path = os.path.join(watch_dir(), "resume-shown.json")
    if not key or not os.path.isfile(path):
        return False
    try:
        data = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(data, list):
        return False
    return key in data


def mark_resume(key: str) -> None:
    import json

    from .paths import watch_dir

    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "resume-shown.json")
    shown = []
    if os.path.isfile(path):
        try:
            loaded = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = []
        if isinstance(loaded, list):
            shown = [str(item) for item in loaded]
    if key and key not in shown:
        shown.append(key)
    dump_json(path, shown)


def write_resume_log(note: str) -> None:
    """The resume log lives under the workspace, never in the plugin tree."""
    from .paths import watch_dir

    folder = watch_dir()
    os.makedirs(folder, exist_ok=True)
    append_line(os.path.join(folder, "resume.log"), (note or "") + "\n")


def progress_note(events, max_chars: int = MAX_CHARS) -> str:
    """Narration, heartbeat notes, and commands with exit status. A tool result's text is dropped."""
    lines = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        if event.get("output"):
            continue
        command = event.get("command") or ""
        if command:
            status = event.get("exit")
            suffix = f" exit {status}" if status not in (None, "") else ""
            lines.append(_clip(f"{command}{suffix}", 180))
            continue
        beat = _heartbeat_text(event)
        narration = _narration_text(event)
        if beat:
            lines.append(_clip(beat, 300))
        if narration and narration != beat:
            lines.append(_clip(narration, 300))
    note = "\n".join(lines)
    if len(note) <= max_chars:
        return note
    return note[: max_chars - 1].rstrip() + "…"
