#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: one setup of a fixture pack on a fresh real Hermes home, then doctor, then a second setup.
# Usage: home.sh <plugin-root> <pack-name> <out-dir>
set -u
plugin=$1; name=$2; out=$3
rm -rf "$out"; mkdir -p "$out"
base=$(mktemp -d "$out/run.XXXX")
ws=$base/ws; root=$base/root; home=$base/hermes
mkdir -p "$ws/homes/acme" "$ws/homes/bravo" "$home"
for repo in api web; do
  git init -q "$root/repos/$repo"
  echo hello > "$root/repos/$repo/README"
  git -C "$root/repos/$repo" add README
  GIT_AUTHOR_NAME=Dev GIT_AUTHOR_EMAIL=dev@example.test GIT_COMMITTER_NAME=Dev GIT_COMMITTER_EMAIL=dev@example.test \
    git -C "$root/repos/$repo" commit -qm init
done
printf 'fixture-a\nfixture-b\n' > "$home/known-providers"
export COCKPIT_WORKSPACE=$ws COCKPIT_ROOT=$root COCKPIT_HERMES_HOME=$home COCKPIT_PACK=$plugin/packs/$name/pack.yaml
export COCKPIT_WT=$root/wt COCKPIT_VOLUMES=$root/volumes COCKPIT_HUMAN=1
unset PYTEST_CURRENT_TEST COCKPIT_LANE
cockpit=$plugin/bin/cockpit
echo "== setup 1"; time "$cockpit" setup; echo "exit $?"
echo "== doctor 1"; "$cockpit" doctor; echo "exit $?"
echo "== jobs after setup 1"; python3 - "$home" <<'PY'
import json, os, sys, glob
for path in [os.path.join(sys.argv[1], "cron", "jobs.json"), *glob.glob(os.path.join(sys.argv[1], "profiles", "*", "cron", "jobs.json"))]:
    data = json.load(open(path))
    for job in data["jobs"]:
        print(os.path.relpath(path, sys.argv[1]), job["name"], job["schedule"], job.get("no_agent"))
PY
echo "== setup 2"; time "$cockpit" setup; echo "exit $?"
echo "== doctor 2"; "$cockpit" doctor; echo "exit $?"
echo "== job count after setup 2"; python3 -c "import json,sys,glob,os; print({p: len(json.load(open(p))['jobs']) for p in glob.glob(os.path.join(sys.argv[1], '**', 'jobs.json'), recursive=True)})" "$home"
