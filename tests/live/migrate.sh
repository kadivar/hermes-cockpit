#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: a real setup of a pack on a fresh Hermes home, then the migrator's plan, apply, verify and rollback
# against that home (the fixture's migrate.yaml names an invented legacy pipeline, so plan and apply find little).
# Usage: migrate.sh <plugin-root> <pack-name> <out-dir>
set -u
here=$(cd "$(dirname "$0")" && pwd)
"$here/home.sh" "$@" > /dev/null
home=$(ls -d "$3"/run.*/hermes); base=$(dirname "$home")
export COCKPIT_WORKSPACE=$base/ws COCKPIT_ROOT=$base/root COCKPIT_HERMES_HOME=$home COCKPIT_PACK=$1/packs/$2/pack.yaml
export COCKPIT_WT=$base/root/wt COCKPIT_VOLUMES=$base/root/volumes COCKPIT_HUMAN=1
cockpit=$1/bin/cockpit
echo "== migrate plan"; "$cockpit" migrate plan; echo "exit $?"
echo "== migrate apply"; out=$("$cockpit" migrate apply); echo "$out"
stamp=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshot"])')
echo "== migrate verify"; "$cockpit" migrate verify; echo "exit $?"
echo "== migrate rollback $stamp"; "$cockpit" migrate rollback "$stamp" | head -5; echo "exit $?"
