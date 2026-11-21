# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the fictional legacy install a fixture's migrate.yaml describes, in the test's temp home and workspace."""

import json
import os
import sqlite3
import time

import yaml


def build(pack, spec, origin: str) -> dict:
    """Profiles, root config, soul, env, crons, records, editor hooks, slot bindings, an unmapped legacy card and the
    exporter's logins. Returns what a test checks against."""
    from cockpitlib.kanban import db_path
    from cockpitlib.paths import hermes_home, workspace

    home = hermes_home()
    legacy = spec["legacy"]
    for name in legacy["profiles"]["replace"] + legacy["profiles"]["remove"]:
        folder = os.path.join(home, "profiles", name)
        os.makedirs(os.path.join(folder, "memories"), exist_ok=True)
        open(os.path.join(folder, "config.yaml"), "w", encoding="utf-8").write(f"model: {{default: legacy-{name}}}\n")
        open(os.path.join(folder, "SOUL.md"), "w", encoding="utf-8").write(f"legacy soul {name}\n")
    config = {
        "plugins": {"enabled": [*legacy["plugins"]["disable"], *legacy["plugins"]["keep"], "cockpit"]},
        "hooks": {
            hook["event"]: [{"command": hook["command"]}, {"command": "/usr/bin/true"}]
            for hook in legacy["shell_hooks"]
        },
    }
    for dotted in legacy["root"]["config_drop"]:
        node = config
        *parents, last = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = "legacy"
    open(os.path.join(home, "config.yaml"), "w", encoding="utf-8").write(yaml.safe_dump(config, sort_keys=False))
    soul = (
        "kept before\n"
        + "".join(
            f"{block['start']}\nlegacy concierge text\n{block['end']}\n" for block in legacy["root"]["soul_blocks"]
        )
        + "kept after\n"
    )
    open(os.path.join(home, "SOUL.md"), "w", encoding="utf-8").write(soul)
    open(os.path.join(home, ".env"), "w", encoding="utf-8").write(
        "".join(f"{key}=x\n" for key in legacy["root"]["env_drop"]) + "KEEP_ME=1\n"
    )
    jobs = [
        {"id": f"j{index}", "name": name}
        for index, name in enumerate(legacy["crons"]["retire"] + legacy["crons"]["replace"])
    ]
    jobs.append({"id": "other", "name": "someone-elses-job"})
    from cockpitlib.setup import CRON_JOBS

    own = dict((name, script) for name, _default, script in CRON_JOBS)
    jobs += [
        {"id": f"own-{name}", "name": name, "script": own[name]} for name in legacy["crons"]["replace"] if name in own
    ]  # cockpit's own
    os.makedirs(os.path.join(home, "cron"), exist_ok=True)
    json.dump({"jobs": jobs}, open(os.path.join(home, "cron", "jobs.json"), "w", encoding="utf-8"))
    for path in legacy["editor_hooks"]:
        full = os.path.join(workspace(), path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w", encoding="utf-8").write('{"hooks": "legacy"}\n')
    records = []
    for row in spec["records"]["map"]:
        source = os.path.join(workspace(), row["from"])
        if row.get("kind") == "file":
            os.makedirs(os.path.dirname(source), exist_ok=True)
            open(source, "w", encoding="utf-8").write(f"legacy notes {pack['name']}\n")
        elif row.get("kind") == "intents":
            ticket = f"{pack['tracker']['project']}-501"
            os.makedirs(os.path.join(source, ticket), exist_ok=True)
            json.dump(
                {
                    "id": f"{ticket}/001-tracker-comment",
                    "ticket": ticket,
                    "type": "tracker-comment",
                    "status": "pending",
                    "summary": "old",
                    "payload": {"body": "kept", "legacy_channel": "x"},
                    "lane_mood": "calm",
                },
                open(os.path.join(source, ticket, "001-tracker-comment.json"), "w", encoding="utf-8"),
            )
            json.dump(
                {
                    "id": f"{ticket}/002-deploy",
                    "ticket": ticket,
                    "type": "deploy-now",
                    "status": "pending",
                    "summary": "old",
                    "payload": {},
                },
                open(os.path.join(source, ticket, "002-deploy.json"), "w", encoding="utf-8"),
            )
            json.dump(
                {
                    "id": f"{ticket}/003-ship-log",
                    "ticket": ticket,
                    "type": "ship-log",
                    "status": "published",
                    "agent_summary": "shipped the log",
                    "risk_hint": "low",
                    "payload": {},
                    "receipt": {"url": "https://relay.test/log/3"},
                },
                open(os.path.join(source, ticket, "003-ship-log.json"), "w", encoding="utf-8"),
            )  # closed, a type cockpit lacks, old field names
            json.dump(
                {
                    "type": "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "kept body"}]}],
                },
                open(os.path.join(source, ticket, "001-body.json"), "w", encoding="utf-8"),
            )  # the comment body kept beside 001: not an intent
        else:
            os.makedirs(os.path.join(source, f"{pack['tracker']['project']}-502"), exist_ok=True)
            open(os.path.join(source, f"{pack['tracker']['project']}-502", "plan.md"), "w", encoding="utf-8").write(
                "legacy plan\n"
            )
        records.append(row)
    for row in spec["slots"]["bindings"]:
        path = os.path.join(workspace(), row["from"].replace("{n}", "1"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(
            f"{pack['tracker']['project']}-503\n" if row["to"] == "ticket" else "worker-1\n"
        )
    from cockpitlib.kanban import place_card

    place_card(
        pack["board"],
        f"{pack['tracker']['project']}-505: work",
        "worker-2",
        "blocked",
        reason="waiting",
        kind="work",
        ticket=f"{pack['tracker']['project']}-505",
        pack=pack,
    )  # makes the board
    connection = sqlite3.connect(db_path(pack["board"]))
    rewrite = (
        spec["board"]["rewrite"][0]["pattern"].split(" ")[0].replace("\\S+", "x").replace("(", "").replace(")", "")
    )
    title = f"{pack['tracker']['project']}-504: " + ("relay-work" if pack["name"] == "acme" else "tide sweep")
    connection.execute(
        "insert into tasks (id, title, body, assignee, status, created_at) values (?, ?, ?, ?, 'ready', ?)",
        ("t_legacy01", title, f"run {rewrite} 7 when done", "worker-1", int(time.time())),
    )
    connection.commit()
    connection.close()
    logins = os.path.join(
        os.environ["COCKPIT_ROOT"], "relay-logins.jsonl" if pack["name"] == "acme" else "tide-logins.jsonl"
    )
    rows = [
        {
            "scope": "lane",
            "lane": "tester-1",
            "origin": origin,
            "email": f"qa1@{pack['name']}.test",
            "secret": "pw-one",
            "identifier_type": "email",
        },
        {
            "scope": "lane",
            "lane": "tester-1",
            "origin": origin,
            "email": f"qa2@{pack['name']}.test",
            "secret": "pw-two",
            "otp": "JBSWY3DPEHPK3PXP",
        },
    ]
    open(logins, "w", encoding="utf-8").write("".join(json.dumps(row) + "\n" for row in rows))
    return {"soul": soul, "logins": len(rows), "card": "t_legacy01"}
