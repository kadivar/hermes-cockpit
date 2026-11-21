# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checkpoints ask the advisor seat. The pack names the checkpoints, the answers each one may give, the prompt and how
many calls a ticket gets; the kernel asks, parses the answer, records the verdict and blocks the card on a failure.

When the pack's advisor runs inside the coding tool instead, the kernel cannot see those calls: the worker's finishing
report must then carry the pack's report line.
"""

import json
import os
import re
import subprocess

from .errors import CockpitError
from .paths import qa_of
from .store import append_line, log, write_text

TIMEOUT = 900
DEFAULT_COMMAND = ["hermes", "--profile", "{profile}", "chat", "-Q", "--query-file", "{query_file}"]


def config(pack) -> dict:
    return (pack or {}).get("advisor") or {}


def _seat(pack) -> str:
    from .lanes import seats_from

    names = (seats_from(pack).get("advisor") or []) if (pack or {}).get("seats") else []
    return names[0] if names else "advisor"


def _folder(ticket: str) -> str:
    return qa_of(ticket, "advisor")


def calls(ticket: str) -> list:
    path = os.path.join(_folder(ticket), "calls.jsonl")
    if not os.path.isfile(path):
        return []
    rows = []
    for line in open(path, encoding="utf-8"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _record(ticket: str, row: dict) -> None:
    folder = _folder(ticket)
    os.makedirs(folder, exist_ok=True)
    append_line(os.path.join(folder, "calls.jsonl"), json.dumps(row) + "\n")


def parse(answers: list, reply: str) -> str:
    """The first line that starts with one of the checkpoint's answers names the verdict; anything else is unparsable."""
    for line in (reply or "").splitlines():
        word = line.strip().lstrip("#*>- ").strip()
        for answer in answers:
            if re.match(rf"{re.escape(answer)}\b", word):
                return answer
    return ""


def _prompt(pack, checkpoint: str, ticket: str, note: str) -> str:
    from .plan import show
    from .prompts import resolve

    cfg = config(pack)
    head = ""
    if cfg.get("prompt"):
        head = open(cfg["prompt"], encoding="utf-8").read()
    answers = ((cfg.get("checkpoints") or {}).get(checkpoint) or {}).get("answers") or []
    lines = [
        resolve(pack, head).strip(),
        f"Checkpoint {checkpoint} on {ticket}.",
        f"Answer on the first line with exactly one of: {', '.join(answers)}. Then say why.",
        "",
        "## Plan",
        show(ticket) or "(none)",
        "",
        "## Worker note",
        note or "(none)",
    ]
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def _run(pack, query_file: str, report_file: str, checkpoint: str, ticket: str) -> tuple:
    """(reply, error) from the advisor command."""
    argv = config(pack).get("command") or DEFAULT_COMMAND
    values = {
        "profile": _seat(pack),
        "query_file": query_file,
        "checkpoint": checkpoint,
        "ticket": ticket,
        "report_file": report_file,
    }
    words = []
    for word in argv:
        for name, value in values.items():
            word = word.replace("{" + name + "}", value)
        words.append(word)
    if "/" in words[0] and not os.path.isabs(words[0]) and (pack or {}).get("_dir"):
        words[0] = os.path.join(pack["_dir"], words[0])
    env = {key: value for key, value in os.environ.items() if not key.startswith("HERMES_KANBAN_")}
    env["HERMES_QUIET_TURN_REPORT_FILE"] = report_file
    try:
        done = subprocess.run(words, capture_output=True, text=True, timeout=TIMEOUT, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"advisor did not answer: {exc}"
    report = {}
    if os.path.isfile(report_file):
        try:
            report = json.load(open(report_file, encoding="utf-8"))
        except ValueError:
            report = {}
    reply = str(report.get("reply") or "") if isinstance(report, dict) else ""
    if not reply:
        reply = done.stdout or ""
    if done.returncode != 0 or (isinstance(report, dict) and report.get("exit_code")):
        tail = (str(report.get("error") or "") if isinstance(report, dict) else "") or (
            done.stderr or done.stdout or ""
        ).strip()[-200:]
        return reply, f"advisor failed: {tail or f'exit {done.returncode}'}"
    return reply, ""


def parse_said(answers: list, checkpoint: str, said: str) -> str:
    """The verdict in the line an in-tool advisor left for the worker: `<checkpoint>=<ANSWER>` anywhere in it
    (`ADVISOR: C0=APPROVED ... C2=CLEAN`), else the first line that starts with an answer."""
    for answer in answers:
        if re.search(rf"\b{re.escape(checkpoint)}\s*[=:]\s*{re.escape(answer)}\b", said or ""):
            return answer
    return parse(answers, said)


def advise(pack, checkpoint: str, note: str = "", ticket: str = "", card: str = "", said: str = "") -> dict:
    """Ask the advisor at a checkpoint. {checkpoint, verdict, ok, reason, reply}. A failed or unparsable answer
    blocks the card; the call after max_calls is refused before it is made. `said`: the line an advisor that runs inside the
    coding tool gave the worker; it is recorded as that checkpoint's answer, so the plan gate and the plan see it."""
    from .skill_log import current_card, current_ticket

    cfg = config(pack)
    checkpoints = cfg.get("checkpoints") or {}
    if checkpoint not in checkpoints:
        raise CockpitError(f"no checkpoint {checkpoint}: the pack's advisor has {', '.join(checkpoints) or 'none'}")
    ticket = ticket or current_ticket()
    card = card or current_card()[1]
    if not ticket:
        raise CockpitError("advise needs the ticket (run it from the ticket's card)")
    if cfg.get("in_tool") and not said:
        raise CockpitError(
            "this pack's advisor runs inside the coding tool: put its line in the finishing report, and record it "
            f'with `cockpit advise {checkpoint} --said "<its line>"`'
        )
    answers = checkpoints[checkpoint].get("answers") or []
    if said:
        reply, error, query_file = said, "", ""
        verdict = parse_said(answers, checkpoint, said)
    else:
        limit = int(cfg.get("max_calls") or 0)
        made = calls(ticket)
        if limit and len(made) >= limit:
            raise CockpitError(f"advisor limit: {limit} calls on {ticket} already made")
        folder = _folder(ticket)
        os.makedirs(folder, exist_ok=True)
        number = len(made) + 1
        query_file = os.path.join(folder, f"{number:02d}-{checkpoint}.md")
        report_file = os.path.join(folder, f"{number:02d}-{checkpoint}.report.json")
        write_text(query_file, _prompt(pack, checkpoint, ticket, note))
        reply, error = _run(pack, query_file, report_file, checkpoint, ticket)
        verdict = "" if error else parse(answers, reply)
    reason = error or (
        ""
        if verdict
        else f"the advisor's answer names none of {', '.join(answers)}"
        + (f" for {checkpoint}: record its exact word as `{checkpoint}=<{'|'.join(answers)}>`" if said else "")
    )
    from .time_util import iso

    row = {
        "time": iso(),
        "checkpoint": checkpoint,
        "verdict": verdict,
        "card": card,
        "reason": reason,
        "query": query_file,
    }
    _record(ticket, row)
    from .plan import append, plan_path

    if os.path.isfile(plan_path(ticket)):
        append(ticket, "Advisor", f"{checkpoint}: {verdict or 'no verdict'}" + (f" ({reason})" if reason else ""))
    board = "skipped: no card"
    if card:
        # the board write runs in Hermes's helper; a refusal there (a delegated context may not touch the board) must not
        # lose the answer: the row and the plan line stand, and the result says the board was not written
        from .kanban import BoardWrites

        writes = BoardWrites(pack["board"])
        writes.comment(card, "advisor", f"{checkpoint}: {verdict or 'no verdict'}\n\n{reply.strip()[:4000] or reason}")
        if reason:
            writes.block(card, f"advisor {checkpoint}: {reason}", kind="needs_input")
        try:
            writes.flush()
            board = "written"
        except CockpitError as exc:
            board = f"not written: {exc}"
            log(f"ADVISE {ticket} {checkpoint} on {card}: board {board}")
    return {
        "checkpoint": checkpoint,
        "verdict": verdict,
        "ok": not reason,
        "reason": reason,
        "reply": reply,
        "ticket": ticket,
        "board": board,
    }


def report_refusal(pack, text: str) -> str:
    """When the pack's advisor runs inside the coding tool, a worker's finishing report must carry its report line."""
    pattern = config(pack).get("report_line") or ""
    if not pattern:
        return ""
    if re.search(pattern, text or "", re.M):
        return ""
    return f"the finishing report lacks the advisor line ({pattern})"
