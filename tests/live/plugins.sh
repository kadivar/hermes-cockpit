#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# Outside pytest: one real setup of a pack, then show each seat would load register().
# Usage: plugins.sh <plugin-root> <pack-name> <out-dir>
set -u
here=$(dirname "$0")
"$here/home.sh" "$@"
home=$(ls -d "$3"/run.*/hermes)
echo "== plugin per profile (plugins/cockpit target | plugins.enabled has cockpit)"
python3 - "$home" "$1" <<'PY'
import os, sys, yaml
home, plugin = sys.argv[1], os.path.realpath(sys.argv[2])
homes = [("root", home)] + [(name, os.path.join(home, "profiles", name)) for name in sorted(os.listdir(os.path.join(home, "profiles")))]
for name, folder in homes:
    link = os.path.join(folder, "plugins", "cockpit")
    target = os.path.realpath(link) if os.path.lexists(link) else "MISSING"
    data = yaml.safe_load(open(os.path.join(folder, "config.yaml"))) or {}
    enabled = (data.get("plugins") or {}).get("enabled") or []
    print(f"{name:12} {'symlink' if os.path.islink(link) else 'dir    '} -> {'plugin tree' if target == plugin else target} | enabled={'cockpit' in enabled}")
PY
echo "== Hermes's own view per seat (hermes --profile <seat> plugins list)"
for seat in $(ls "$home/profiles"); do
  line=$(HERMES_HOME=$home hermes --profile "$seat" plugins list 2>&1 | grep -E "│ cockpit ")
  echo "$seat: ${line:-cockpit NOT LISTED}"
done
