#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: the real cockpit CLI writes, endorses and publishes a push to a local bare remote. No forge, no Hermes.
set -u
plugin=$1; name=$2; out=$3
rm -rf "$out"; mkdir -p "$out"
base=$(mktemp -d "$out/run.XXXX"); ws=$base/ws; root=$base/root; home=$base/hermes
mkdir -p "$ws/homes/acme" "$ws/homes/bravo" "$home"
repo=$(python3 -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))['repos'][0]['name'])" "$plugin/packs/$name/repos.yaml")
for r in api web ledger site; do
  git init -q -b main "$root/repos/$r"; echo hello > "$root/repos/$r/README"; git -C "$root/repos/$r" add README
  git -C "$root/repos/$r" -c user.email=dev@example.test -c user.name=Dev commit -qm init
  git init -q --bare "$root/remotes/$r.git"; git -C "$root/repos/$r" remote add origin "$root/remotes/$r.git"; git -C "$root/repos/$r" push -q origin main
  git -C "$root/repos/$r" config user.email dev@example.test; git -C "$root/repos/$r" config user.name Dev
done
printf 'fixture-a\nfixture-b\n' > "$home/known-providers"
export COCKPIT_WORKSPACE=$ws COCKPIT_ROOT=$root COCKPIT_HERMES_HOME=$home COCKPIT_PACK=$plugin/packs/$name/pack.yaml
export COCKPIT_WT=$root/wt COCKPIT_VOLUMES=$root/volumes COCKPIT_HUMAN=1
unset PYTEST_CURRENT_TEST COCKPIT_LANE
project=$(python3 -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))['tracker']['project'])" "$COCKPIT_PACK")
ticket=$project-501
git -C "$root/repos/$repo" checkout -q -b "work/$ticket"; echo change > "$root/repos/$repo/change.txt"; git -C "$root/repos/$repo" add change.txt
git -C "$root/repos/$repo" commit -qm "change for $ticket"; git -C "$root/repos/$repo" checkout -q main
c=$plugin/bin/cockpit
echo "== new"; COCKPIT_LANE=worker-1 $c outbox new "$ticket" push-branch --card t_1 --summary "push $ticket" --repo "$repo" --branch "work/$ticket"; echo "exit $?"
id=$(ls "$ws"/*/outbox/$ticket/ | grep -o '^001-push-branch' | head -1); id="$ticket/$id"
echo "== missing flag"; $c outbox new "$ticket" open-pr --card t_1 --summary x --repo "$repo" --branch "work/$ticket" 2>&1 | head -1; echo "exit ${PIPESTATUS[0]}"
echo "== verify"; $c outbox verify "$id"; echo "exit $?"
echo "== endorse"; $c outbox endorse "$id" low "matches the plan"; echo "exit $?"
echo "== dry run"; $c publish --id "$id" --dry-run | tail -3; echo "exit ${PIPESTATUS[0]}"
echo "== publish"; $c publish --id "$id" | tail -3; echo "exit ${PIPESTATUS[0]}"
echo "== remote now"; git --git-dir "$root/remotes/$repo.git" rev-parse "work/$ticket"; git -C "$root/repos/$repo" rev-parse "work/$ticket"
