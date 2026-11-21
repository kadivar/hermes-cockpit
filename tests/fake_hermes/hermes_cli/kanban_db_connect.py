# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""connect(board=) opens $HERMES_HOME/kanban/boards/<board>/kanban.db and makes the tables Hermes has."""

import os
import sqlite3

TABLES = (
    "create table if not exists tasks (id text primary key, title text not null, body text, assignee text, "
    "status text not null, priority integer default 0, created_by text, created_at integer not null, started_at integer, "
    "completed_at integer, workspace_kind text not null default 'scratch', workspace_path text, branch_name text, "
    "result text, idempotency_key text, worker_pid integer, skills text, model_override text, provider_override text, "
    "reasoning_effort text, block_kind text, block_recurrences integer not null default 0, claim_lock text, "
    "last_failure_error text, max_runtime_seconds integer)",
    "create table if not exists task_runs (id integer primary key autoincrement, task_id text not null, profile text, "
    "step_key text, status text not null, claim_lock text, claim_expires integer, worker_pid integer, worker_started_at integer, "
    "max_runtime_seconds integer, last_heartbeat_at integer, started_at integer not null, ended_at integer, outcome text, "
    "summary text, metadata text, error text)",
    "create table if not exists task_links (parent_id text not null, child_id text not null)",
    "create table if not exists task_comments (id integer primary key autoincrement, task_id text not null, "
    "author text not null, body text not null, created_at integer not null)",
    "create table if not exists task_events (id integer primary key autoincrement, task_id text not null, run_id integer, "
    "kind text not null, payload text, created_at integer not null)",
)


# Columns Hermes's own migrations add to an older tasks table when it connects.
MIGRATED = (
    ("body", "text"),
    ("assignee", "text"),
    ("priority", "integer default 0"),
    ("created_by", "text"),
    ("created_at", "integer"),
    ("completed_at", "integer"),
    ("workspace_kind", "text default 'scratch'"),
    ("workspace_path", "text"),
    ("result", "text"),
    ("idempotency_key", "text"),
    ("worker_pid", "integer"),
    ("skills", "text"),
    ("block_kind", "text"),
    ("block_recurrences", "integer not null default 0"),
    ("claim_lock", "text"),
    ("last_failure_error", "text"),
)


def connect(db_path=None, *, board=None):
    if db_path is None:
        db_path = os.path.join(os.environ["HERMES_HOME"], "kanban", "boards", board or "default", "kanban.db")
    os.makedirs(os.path.dirname(str(db_path)), exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    for statement in TABLES:
        conn.execute(statement)
    present = {row[1] for row in conn.execute("pragma table_info(tasks)")}
    for name, kind in MIGRATED:
        if name not in present:
            conn.execute(f"alter table tasks add column {name} {kind}")
    conn.commit()
    return conn
