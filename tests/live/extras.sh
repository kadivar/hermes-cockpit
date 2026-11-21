#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: a real setup of a pack, then Hermes's own view of each home's extra plugins, provider plugins and skills.
# Usage: extras.sh <plugin-root> <pack-dir> <out-dir>
set -u
here=$(dirname "$0")
plugin=$1; pack=$2; out=$3
rm -rf "$out"; mkdir -p "$out"
base=$(mktemp -d "$out/run.XXXX")
ws=$base/ws; root=$base/root; home=$base/hermes
mkdir -p "$ws/homes/acme" "$ws/homes/bravo" "$home"
for repo in api web; do
  git init -q "$root/repos/$repo"; echo hello > "$root/repos/$repo/README"; git -C "$root/repos/$repo" add README
  GIT_AUTHOR_NAME=Dev GIT_AUTHOR_EMAIL=dev@example.test GIT_COMMITTER_NAME=Dev GIT_COMMITTER_EMAIL=dev@example.test git -C "$root/repos/$repo" commit -qm init
done
printf 'fixture-a\nfixture-b\n' > "$home/known-providers"
export COCKPIT_WORKSPACE=$ws COCKPIT_ROOT=$root COCKPIT_HERMES_HOME=$home COCKPIT_PACK=$pack/pack.yaml
export COCKPIT_WT=$root/wt COCKPIT_VOLUMES=$root/volumes COCKPIT_HUMAN=1
unset PYTEST_CURRENT_TEST COCKPIT_LANE
echo "== setup"; "$plugin/bin/cockpit" setup >/dev/null; echo "exit $?"
echo "== doctor"; "$plugin/bin/cockpit" doctor; echo "exit $?"
echo "== hermes plugins list (enabled rows, non-cockpit)"
for seat in root $(ls "$home/profiles"); do
  args=(); [ "$seat" = root ] || args=(--profile "$seat")
  rows=$(HERMES_HOME=$home hermes "${args[@]}" plugins list 2>&1 | grep -E "│ (ledger-view|trace-tap) " | sed -E 's/ +/ /g' | tr '\n' ';')
  echo "$seat: ${rows:-none}"
done
echo "== providers Hermes resolves per seat, and seat skills"
runtime=$(hermes --print-runtime-command --module x | python3 -c 'import json,sys; print(json.load(sys.stdin)[0])')
for seat in $(ls "$home/profiles"); do
  provider=$(HERMES_HOME=$home/profiles/$seat PYTHONPATH= "$runtime" -I -c "
import sys; sys.path.insert(0, '$HOME/.hermes/hermes-agent')
import providers
print(','.join(sorted(p.name for p in providers.list_providers() if providers.provider_source(p.name) == 'user')) or 'none')" 2>/dev/null)
  skills=$(ls "$home/profiles/$seat/skills" 2>/dev/null | grep -E "house-style|bench-notes" | tr '\n' ',')
  echo "$seat: user providers=${provider:-error} skills=${skills:-none}"
done
