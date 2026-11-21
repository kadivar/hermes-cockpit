# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The board functions cockpit calls, with Hermes 0.22.2's rules (tests/contract/hermes-kanban.json).

It writes only the columns a test's table has, so a test may build a smaller table.
"""

import json
import secrets
import time

VALID_INITIAL_STATUSES = {"running", "blocked"}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"pragma table_info({table})")}


def _insert(conn, table, values):
    columns = _columns(conn, table)
    kept = {key: value for key, value in values.items() if key in columns}
    names = ", ".join(kept)
    marks = ", ".join("?" for _ in kept)
    return conn.execute(f"insert into {table} ({names}) values ({marks})", tuple(kept.values())).lastrowid


def _event(conn, task_id, kind, payload):
    if "task_events" not in {row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")}:
        return
    _insert(
        conn,
        "task_events",
        {"task_id": task_id, "kind": kind, "payload": json.dumps(payload), "created_at": int(time.time())},
    )


def _status(conn, task_id):
    row = conn.execute("select status from tasks where id = ?", (task_id,)).fetchone()
    return row[0] if row else None


def _open_parent(conn, task_id):
    tables = {row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")}
    if "task_links" not in tables:
        return False
    rows = conn.execute(
        "select tasks.status from task_links join tasks on tasks.id = task_links.parent_id where task_links.child_id = ?",
        (task_id,),
    ).fetchall()
    return any(row[0] != "done" for row in rows)


def _set(conn, task_id, **values):
    columns = _columns(conn, "tasks")
    kept = {key: value for key, value in values.items() if key in columns}
    assignments = ", ".join(f"{key} = ?" for key in kept)
    conn.execute(f"update tasks set {assignments} where id = ?", (*kept.values(), task_id))


def create_task(
    conn,
    *,
    title,
    body=None,
    assignee=None,
    created_by=None,
    workspace_kind=None,
    workspace_path=None,
    branch_name=None,
    priority=0,
    parents=(),
    triage=False,
    idempotency_key=None,
    skills=None,
    model_override=None,
    provider_override=None,
    reasoning_effort=None,
    initial_status="running",
    max_runtime_seconds=None,
    **_rest,
):
    if not title or not title.strip():
        raise ValueError("title is required")
    if initial_status not in VALID_INITIAL_STATUSES:
        raise ValueError(f"initial_status must be one of {sorted(VALID_INITIAL_STATUSES)}")
    if idempotency_key and "idempotency_key" in _columns(conn, "tasks"):
        row = conn.execute(
            "select id from tasks where idempotency_key = ? and status != 'archived'", (idempotency_key,)
        ).fetchone()
        if row:
            return row[0]
    task_id = f"t_{secrets.token_hex(4)}"
    _insert(
        conn,
        "tasks",
        {
            "id": task_id,
            "title": title,
            "body": body,
            "assignee": assignee,
            "status": "ready",
            "priority": priority,
            "created_by": created_by,
            "created_at": int(time.time()),
            "workspace_kind": workspace_kind or "scratch",
            "workspace_path": workspace_path,
            "branch_name": branch_name,
            "idempotency_key": idempotency_key,
            "skills": json.dumps(list(skills)) if skills else None,
            "model_override": model_override,
            "provider_override": provider_override,
            "reasoning_effort": reasoning_effort,
            "max_runtime_seconds": int(max_runtime_seconds) if max_runtime_seconds else None,
        },
    )
    _event(conn, task_id, "created", {"assignee": assignee})
    for parent in parents or ():
        _insert(conn, "task_links", {"parent_id": parent, "child_id": task_id})
    status = "triage" if triage else ("todo" if _open_parent(conn, task_id) else "ready")
    if initial_status == "blocked":
        status = "blocked"
        _event(conn, task_id, "blocked", {"reason": "initial_status", "status": "blocked"})
    _set(conn, task_id, status=status)
    conn.commit()
    return task_id


BLOCK_RECURRENCE_LIMIT = 2


def _block_state(conn, task_id):
    columns = _columns(conn, "tasks")
    kind = (
        conn.execute("select block_kind from tasks where id = ?", (task_id,)).fetchone()[0]
        if "block_kind" in columns
        else None
    )
    count = (
        conn.execute("select block_recurrences from tasks where id = ?", (task_id,)).fetchone()[0]
        if "block_recurrences" in columns
        else 0
    )
    return kind, int(count or 0)


def block_task(conn, task_id, *, reason=None, kind=None, expected_run_id=None):
    """Hermes's rules: a re-block for the same kind after an unblock is a loop, and a loop goes to triage."""
    status = _status(conn, task_id)
    prev_kind, prev_count = _block_state(conn, task_id)
    if status == "blocked":
        if kind is None or expected_run_id is not None or prev_kind is not None:
            return False
        _set(conn, task_id, block_kind=kind, block_recurrences=1)
        _event(conn, task_id, "blocked", {"kind": kind, "reason": reason, "classified_in_place": True})
        conn.commit()
        return True
    if status not in ("running", "ready"):
        return False
    if kind == "dependency":
        _set(conn, task_id, status="todo", block_kind=kind, worker_pid=None)
        _event(conn, task_id, "dependency_wait", {"reason": reason, "kind": kind, "source_status": status})
        conn.commit()
        return True
    count = prev_count + 1 if prev_kind == kind else 1
    payload = {"reason": reason, "kind": kind, "recurrences": count, "source_status": status}
    if count >= BLOCK_RECURRENCE_LIMIT:
        payload["limit"] = BLOCK_RECURRENCE_LIMIT
        _set(conn, task_id, status="triage", block_kind=kind, block_recurrences=count, worker_pid=None)
        _event(conn, task_id, "block_loop_detected", payload)
        conn.commit()
        return True
    _set(conn, task_id, status="blocked", block_kind=kind, block_recurrences=count, worker_pid=None)
    _event(conn, task_id, "blocked", payload)
    conn.commit()
    return True


def unblock_task(conn, task_id):
    if _status(conn, task_id) not in ("blocked", "scheduled"):
        return False
    status = "todo" if _open_parent(conn, task_id) else "ready"
    _set(conn, task_id, status=status, last_failure_error=None)
    _event(conn, task_id, "unblocked", {"status": status})
    conn.commit()
    return True


def schedule_task(conn, task_id, *, reason=None, expected_run_id=None):
    """Hermes's rules: ready/todo/running/blocked -> scheduled (waiting on time; never dispatched) until unblock_task."""
    if _status(conn, task_id) not in ("todo", "ready", "running", "blocked"):
        return False
    _set(conn, task_id, status="scheduled", claim_lock=None, worker_pid=None)
    _event(conn, task_id, "scheduled", {"reason": reason})
    conn.commit()
    return True


def complete_task(
    conn,
    task_id,
    *,
    result=None,
    summary=None,
    metadata=None,
    created_cards=None,
    expected_run_id=None,
    fire_lifecycle_hook=True,
    force=False,
):
    if _status(conn, task_id) not in ("running", "ready", "blocked", "review") and not force:
        return False
    _set(
        conn, task_id, status="done", result=result, completed_at=int(time.time()), worker_pid=None, block_recurrences=0
    )
    _event(conn, task_id, "completed", {"summary": summary})
    conn.commit()
    return True


def reclaim_task(conn, task_id, *, reason=None, signal_fn=None):
    if _status(conn, task_id) != "running":
        return False
    _set(conn, task_id, status="ready", worker_pid=None)
    _event(conn, task_id, "reclaimed", {"reason": reason})
    conn.commit()
    return True


def add_comment(conn, task_id, author, body):
    if not body or not body.strip():
        raise ValueError("comment body is required")
    if not author or not author.strip():
        raise ValueError("comment author is required")
    comment_id = _insert(
        conn, "task_comments", {"task_id": task_id, "author": author, "body": body, "created_at": int(time.time())}
    )
    _event(conn, task_id, "commented", {"author": author})
    conn.commit()
    return comment_id


def link_tasks(conn, parent_id, child_id, *, expected_child_run_id=None):
    _insert(conn, "task_links", {"parent_id": parent_id, "child_id": child_id})
    _event(conn, child_id, "linked", {"parent": parent_id, "child": child_id})
    conn.commit()
    return True


def assign_task(conn, task_id, profile):
    if _status(conn, task_id) is None:
        return False
    if _status(conn, task_id) == "running":
        raise RuntimeError("task is running under a claim")
    _set(conn, task_id, assignee=profile)
    _event(conn, task_id, "assigned", {"assignee": profile})
    conn.commit()
    return True


def edit_task(
    conn, task_id, *, title=None, body=None, priority=None, result=None, summary=None, metadata=None, board=None
):
    changed = {
        key: value
        for key, value in (("title", title), ("body", body), ("priority", priority), ("result", result))
        if value is not None
    }
    if not changed or _status(conn, task_id) is None:
        return False
    _set(conn, task_id, **changed)
    _event(conn, task_id, "edited", {"fields": sorted(changed)})
    conn.commit()
    return True


def archive_task(conn, task_id, *, signal_fn=None):
    """As Hermes: an archived task's still-active run is reclaimed, and a running worker is terminated."""
    if _status(conn, task_id) in (None, "archived"):
        return False
    _set(conn, task_id, status="archived", worker_pid=None)
    conn.execute(
        "update task_runs set status = 'reclaimed', outcome = 'reclaimed', summary = 'task archived with run still active', "
        "ended_at = ? where task_id = ? and status = 'running'",
        (int(time.time()), task_id),
    )
    _event(conn, task_id, "archived", {})
    conn.commit()
    return True


def promote_task(conn, task_id, *, actor, reason=None, dry_run=False):
    if _status(conn, task_id) not in ("todo", "blocked"):
        return False, "not todo or blocked"
    if _open_parent(conn, task_id):
        return False, "a parent is not done"
    if not dry_run:
        _set(conn, task_id, status="ready")
        _event(conn, task_id, "promoted", {"actor": actor, "reason": reason})
        conn.commit()
    return True, None


def specify_triage_task(conn, task_id, *, title=None, body=None, assignee=None, author=None):
    if _status(conn, task_id) != "triage":
        return False
    _set(conn, task_id, status="todo")
    _event(conn, task_id, "specified", {})
    conn.commit()
    return True


RELATED = (
    ("task_comments", "task_id"),
    ("task_events", "task_id"),
    ("task_runs", "task_id"),
    ("task_attachments", "task_id"),
    ("kanban_notify_subs", "task_id"),
    ("task_links", "parent_id"),
    ("task_links", "child_id"),
)


def delete_task(conn, task_id):
    if conn.execute("delete from tasks where id = ?", (task_id,)).rowcount != 1:
        conn.commit()
        return False
    tables = {row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")}
    for table, column in RELATED:
        if table in tables and column in _columns(conn, table):
            conn.execute(f"delete from {table} where {column} = ?", (task_id,))
    conn.commit()
    return True
