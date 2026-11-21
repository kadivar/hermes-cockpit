#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: cockpit's plugin API against a real Hermes board on a fresh temp home.
# Usage: api.sh <plugin-root> <pack-name> <out-dir>
set -u
plugin=$1; name=$2; out=$3
rm -rf "$out"; mkdir -p "$out"
base=$(mktemp -d "$out/run.XXXX")
ws=$base/ws; root=$base/root; home=$base/hermes
mkdir -p "$ws/homes/acme" "$ws/homes/bravo" "$home"
for repo in api web; do
  git init -q -b main "$root/repos/$repo"; echo hello > "$root/repos/$repo/README"; git -C "$root/repos/$repo" add README
  GIT_AUTHOR_NAME=Dev GIT_AUTHOR_EMAIL=dev@example.test GIT_COMMITTER_NAME=Dev GIT_COMMITTER_EMAIL=dev@example.test git -C "$root/repos/$repo" commit -qm init
done
printf 'fixture-a\nfixture-b\n' > "$home/known-providers"
cp -r "$plugin/packs/$name" "$base/pack"
export COCKPIT_WORKSPACE=$ws COCKPIT_ROOT=$root COCKPIT_HERMES_HOME=$home HERMES_HOME=$home COCKPIT_PACK=$base/pack/pack.yaml
export COCKPIT_WT=$root/wt COCKPIT_VOLUMES=$root/volumes COCKPIT_HUMAN=1
unset PYTEST_CURRENT_TEST COCKPIT_LANE
"$plugin/.venv/bin/python" - "$base/pack/pack.yaml" "$name" <<'PY'
import sys, yaml
path, name = sys.argv[1:]
plugin, kind, title, flow, lane = {"acme": ("ledger-view", "ledger-close", "{ticket}: ledger close", "ledger", "reviewer"),
                                   "bravo": ("trace-tap", "trace-sample", "{ticket}: trace sample", "trace", "tester")}[name]
raw = yaml.safe_load(open(path))
raw["plugins"][plugin].update(card_kinds={kind: {"title": title, "flow": flow, "role": "analyst"}},
                              kickoff_modes={kind: {"lane_kind": "analyst", "capacity_bucket": "question", "title_kind": kind, "preflight": []}})
raw["kickoff"] = {"lanes": {kind: lane}}
import os
raw["skills_dir"] = os.path.join(os.path.dirname(path), "skills")
open(path, "w").write(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
print("plugin mode", kind, "->", lane)
PY
echo "== setup"; "$plugin/bin/cockpit" setup >/dev/null; echo "exit $?"
echo "== api"; PYTHONPATH=$plugin/kernel:$plugin "$plugin/.venv/bin/python" - "$name" <<'PY'
import sys
from cockpitlib import api
from cockpitlib.kanban import open_card_rows
from cockpitlib.registry import kickoff_modes
name = sys.argv[1]
pack = api._pack()
kind = {"acme": "ledger-close", "bravo": "trace-sample"}[name]
ticket = f"{pack['tracker']['project']}-701"
api.require(api.API_VERSION)
first = api.start_card("rework", ticket, body=f"unit 1 ({name})", policy="release", idempotency_key=f"{name}-701")
print("release card", first["card_id"], first["lane"], first["title"])
try:
    api.start_card("rework", ticket, policy="release", idempotency_key=f"{name}-701")
except Exception as exc:
    print("second start refused:", exc)
plugged = api.start_card(kind, f"{pack['tracker']['project']}-702")
print("plugin card", plugged["card_id"], plugged["lane"], plugged["title"], "lane_kind", kickoff_modes(pack)[kind]["lane_kind"])
card = plugged["card_id"]
api.block(card, f"which window ({name})?", "needs_input")
api.unblock(card)
api.block(card, f"which window ({name})?", "needs_input")
rows = {row["id"]: row for row in open_card_rows(pack["board"], pack)}
print("after the same ask twice:", rows[card]["status"], "|", rows[card]["block_reason"], "| owner", rows[card]["owner"], "| flow", rows[card]["flow"])
print("answer:", api.answer(card, "the last full week")["ok"])
print("now:", {row["id"]: row["status"] for row in open_card_rows(pack["board"], pack)}[card])
from cockpitlib.kanban import place_card
a = place_card(pack["board"], f"{pack['tracker']['project']}-703: work", "worker-1", kind="work", idempotency_key=f"{name}-703")
b = place_card(pack["board"], f"{pack['tracker']['project']}-703: work", "worker-1", kind="work", idempotency_key=f"{name}-703")
print("same idempotency key, Hermes create_task twice:", a, b, "one card" if a == b else "TWO CARDS")
print("board cards:", [(c["ticket"], c["kind"], c["flow"], c["status"]) for c in api.board_cards(pack=pack)])
PY
echo "== hermes kanban list"; hermes kanban --board "$(PYTHONPATH=$plugin/kernel "$plugin/.venv/bin/python" -c 'from cockpitlib import api; print(api._pack()["board"])')" list 2>&1 | head -12
