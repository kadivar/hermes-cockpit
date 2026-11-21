#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: Hermes's own respawn guard on a real board. A PR link a lane writes in a card comment makes
# check_respawn_guard return active_pr; the same link written by cockpit is defused and does not; cockpit's unguard
# hands a guarded card to another seat of its kind and back, and the guard lets the card go. A blocked treat card is
# closed as superseded with a result.
# Usage: guard.sh <plugin-root> <pack-name> <out-dir>
set -u
plugin=$1; name=$2; out=$3
rm -rf "$out"; mkdir -p "$out"
base=$(mktemp -d "$out/run.XXXX")
ws=$base/ws; root=$base/root; home=$base/hermes
mkdir -p "$ws/homes/acme" "$ws/homes/bravo" "$root" "$home"
printf 'fixture-a\nfixture-b\n' > "$home/known-providers"
cp -r "$plugin/packs/$name" "$base/pack"
"$plugin/.venv/bin/python" - "$base/pack/pack.yaml" <<'PY'
import os, sys, yaml
path = sys.argv[1]
raw = yaml.safe_load(open(path))
raw["skills_dir"] = os.path.join(os.path.dirname(path), "skills")
open(path, "w").write(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
PY
export COCKPIT_WORKSPACE=$ws COCKPIT_ROOT=$root COCKPIT_HERMES_HOME=$home HERMES_HOME=$home COCKPIT_PACK=$base/pack/pack.yaml
export COCKPIT_WT=$root/wt COCKPIT_VOLUMES=$root/volumes COCKPIT_HUMAN=1
unset PYTEST_CURRENT_TEST COCKPIT_LANE
echo "== setup"; "$plugin/bin/cockpit" setup >/dev/null; echo "exit $?"
cat > "$base/guard.py" <<'PY'
import json, sys
from hermes_cli import kanban_db
from hermes_cli.kanban_db_connect import connect
from hermes_cli.kanban_db_dispatch import check_respawn_guard
ask = json.load(sys.stdin)
conn = connect(board=ask["board"])
if ask.get("comment"):
    kanban_db.add_comment(conn, ask["card"], "worker-1", ask["comment"])
print(json.dumps({"guard": check_respawn_guard(conn, ask["card"], lane="ready")}))
PY
PYTHONPATH=$plugin/kernel:$plugin "$plugin/.venv/bin/python" - "$base/guard.py" <<'PY'
import json, sqlite3, subprocess, sys, time
from cockpitlib.hermes_runtime import runtime_argv
from cockpitlib.housekeeping import GUARD_SECONDS, unguard
from cockpitlib.kanban import BoardWrites, db_path, place_card
from cockpitlib.pack import load
from cockpitlib.paths import pack_path
from cockpitlib.settings import load as load_settings, save as save_settings
script = sys.argv[1]
pack = load(pack_path())
save_settings(pack, {"seats": {**load_settings(pack)["seats"], "slots": 2}})
repo = pack["repos"]["repos"][0]["name"]
url = f"https://github.com/{pack['forge']['org']}/{repo}/pull/41"

def guard(card, comment=""):
    done = subprocess.run(runtime_argv(script), input=json.dumps({"board": pack["board"], "card": card, "comment": comment}),
                          capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise SystemExit(done.stderr[-400:])
    return json.loads(done.stdout)["guard"]

ours = place_card(pack["board"], f"{pack['tracker']['project']}-801: work", "worker-1", "ready")
BoardWrites(pack["board"]).comment(ours, "cockpit", f"the human answered: it is {url}")
print("cockpit's own comment with a PR link -> guard:", guard(ours))
card = place_card(pack["board"], f"{pack['tracker']['project']}-802: work", "worker-1", "ready")
print("a lane's comment with a PR link -> guard:", guard(card, f"opened {url}"))
connection = sqlite3.connect(db_path(pack["board"]))
connection.execute("insert into task_events (task_id, kind, payload, created_at) values (?, 'respawn_guarded', ?, ?)",
                   (card, json.dumps({"reason": "active_pr"}), int(time.time()) - GUARD_SECONDS - 5))
connection.commit()
connection.close()
print("unguard handed off:", unguard(pack))
print("after the handoff -> guard:", guard(card))
connection = sqlite3.connect(db_path(pack["board"]))
print("assignee:", connection.execute("select assignee from tasks where id = ?", (card,)).fetchone()[0])
print("last comment:", connection.execute("select body from task_comments where task_id = ? order by id desc limit 1", (card,)).fetchone()[0][:90])
connection.close()
# A treat card still at its plan is closed as superseded: Hermes completes a blocked card given a result.
planning = place_card(pack["board"], f"{pack['tracker']['project']}-803: review the PR", "worker-1", "blocked", reason="patch plan ready: go?")
writes = BoardWrites(pack["board"])
writes.complete(planning, result="superseded: 1 newer comment(s) arrived before the go")
print("blocked treat card closed:", writes.flush()[0])
connection = sqlite3.connect(db_path(pack["board"]))
print("its status and result:", connection.execute("select status, result from tasks where id = ?", (planning,)).fetchone())
connection.close()
PY
