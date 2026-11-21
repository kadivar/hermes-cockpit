# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Board writes through Hermes's own kanban functions.

Runs inside Hermes's environment (see cockpitlib.hermes_runtime): the standard library and hermes_cli only, never cockpitlib.
stdin: {"board": slug, "ops": [{"op": name, ...}]}. stdout: {"results": [...]}, one result per op, in order.
"""

import json
import sys

from hermes_cli import kanban_db
from hermes_cli.kanban_db_connect import connect

CREATE_KEYS = (
    "title",
    "body",
    "assignee",
    "created_by",
    "workspace_kind",
    "workspace_path",
    "branch_name",
    "priority",
    "parents",
    "idempotency_key",
    "skills",
    "model_override",
    "provider_override",
    "reasoning_effort",
    "initial_status",
    "max_runtime_seconds",
)


def _create(conn, op):
    """Create, then block with a reason when one is given, so the block carries that reason and kind."""
    task_id = kanban_db.create_task(conn, **{key: op[key] for key in CREATE_KEYS if key in op})
    block = op.get("block")
    if block:
        kanban_db.block_task(conn, task_id, reason=block.get("reason"), kind=block.get("kind"))
    return task_id


def _block(conn, op):
    # a guarded block (a parked card just unblocked to fail it) never ends a run a dispatcher claimed in between
    if op.get("require_ready_unclaimed") and not _unclaimed_ready(conn, op["id"]):
        return False
    return kanban_db.block_task(conn, op["id"], reason=op.get("reason"), kind=op.get("kind"))


def _unblock(conn, op):
    return kanban_db.unblock_task(conn, op["id"])


def _unclaimed_ready(conn, task_id) -> bool:
    """The card is ready and no dispatcher holds its claim, read on the connection that writes next."""
    columns = {row[1] for row in conn.execute("pragma table_info(tasks)")}
    lock = "claim_lock" if "claim_lock" in columns else "null"
    row = conn.execute(f"select status, {lock} from tasks where id = ?", (task_id,)).fetchone()
    return row is not None and row[0] == "ready" and row[1] is None


def _schedule(conn, op):
    """Park a ready, unclaimed card in `scheduled` (waiting on time; the dispatcher does not start it) until an unblock.

    Hermes's schedule_task also takes a running card (it ends the run and forgets the worker's pid while the worker goes
    on), and the card was read a moment ago: one the dispatcher claimed since is refused here, on the same connection,
    just before the write (schedule_task opens its own write transaction and refuses to nest in ours). A Hermes without
    that state answers False and the card stays as it was."""
    schedule = getattr(kanban_db, "schedule_task", None)
    if schedule is None or not _unclaimed_ready(conn, op["id"]):
        return False
    return bool(schedule(conn, op["id"], reason=op.get("reason")))


def _complete(conn, op):
    return kanban_db.complete_task(
        conn, op["id"], result=op.get("result"), summary=op.get("summary"), force=bool(op.get("force"))
    )


def _reclaim(conn, op):
    return kanban_db.reclaim_task(conn, op["id"], reason=op.get("reason"))


def _comment(conn, op):
    return kanban_db.add_comment(conn, op["id"], op["author"], op["body"])


def _link(conn, op):
    return kanban_db.link_tasks(conn, op["parent"], op["child"])


def _assign(conn, op):
    return kanban_db.assign_task(conn, op["id"], op.get("profile"))


def _edit(conn, op):
    return kanban_db.edit_task(conn, op["id"], body=op.get("body"))


def _archive(conn, op):
    return kanban_db.archive_task(conn, op["id"])


def _promote(conn, op):
    ok, _reason = kanban_db.promote_task(conn, op["id"], actor=op.get("actor") or "cockpit", reason=op.get("reason"))
    return ok


def _delete(conn, op):
    return kanban_db.delete_task(conn, op["id"])


def _specify(conn, op):
    return kanban_db.specify_triage_task(conn, op["id"])


OPS = {
    "specify": _specify,
    "delete": _delete,
    "assign": _assign,
    "edit": _edit,
    "archive": _archive,
    "promote": _promote,
    "create": _create,
    "block": _block,
    "unblock": _unblock,
    "schedule": _schedule,
    "complete": _complete,
    "reclaim": _reclaim,
    "comment": _comment,
    "link": _link,
}


def main() -> int:
    request = json.load(sys.stdin)
    conn = connect(board=request["board"])
    results = []
    try:
        for op in request.get("ops") or []:
            results.append(OPS[op["op"]](conn, op))
    finally:
        conn.close()
    print(json.dumps({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
