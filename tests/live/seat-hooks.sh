#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: a real setup of a pack on a fresh home, then, in each seat, the hooks cockpit registers and the
# pre-tool decisions Hermes's own dispatch makes (seat-hooks.py, seat-pretool.py), under Hermes's interpreter.
# Usage: seat-hooks.sh <plugin-root> <pack-name> <out-dir>
set -u
here=$(cd "$(dirname "$0")" && pwd)
"$here/home.sh" "$@" > /dev/null
home=$(ls -d "$3"/run.*/hermes); base=$(dirname "$home")
export COCKPIT_HERMES_HOME=$home COCKPIT_WORKSPACE=$base/ws COCKPIT_ROOT=$base/root COCKPIT_PACK=$1/packs/$2/pack.yaml
export COCKPIT_WT=$base/root/wt COCKPIT_VOLUMES=$base/root/volumes
run() {   # run a probe script with Hermes's published runtime command
  argv=$(PYTHONPATH="$1/kernel" "$1/.venv/bin/python" -c 'import json,sys; from cockpitlib.hermes_runtime import runtime_argv; print(json.dumps(runtime_argv(sys.argv[1])))' "$2")
  python3 -c 'import json,subprocess,sys; sys.exit(subprocess.run(json.loads(sys.argv[1])).returncode)' "$argv"
}
refused=$(python3 -c "import yaml,sys; print(str(yaml.safe_load(open(sys.argv[1]))['production_hosts'][0]).replace(chr(92), ''))" "$1/packs/$2/egress.yaml")
for seat in $(ls "$home/profiles"); do
  echo "== $seat"
  HERMES_HOME=$home/profiles/$seat COCKPIT_LANE=$seat run "$1" "$here/seat-hooks.py" 2>&1 | tail -2
  HERMES_HOME=$home/profiles/$seat COCKPIT_LANE=$seat REFUSED=$refused run "$1" "$here/seat-pretool.py" 2>&1 | tail -3
done
