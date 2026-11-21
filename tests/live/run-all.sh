#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later

# The harness against a real Hermes, outside pytest, for both fixture packs on fresh temp homes:
# setup → doctor → setup → doctor, the seats' plugin hooks through Hermes's own dispatch, the plugin API on a real
# board, Hermes's respawn guard and cockpit's unguard, a push to a local bare remote, the seats' extra plugins and
# skills, and the migrator's cycle.
# Usage: tests/live/run-all.sh [out-dir]   (needs `hermes` on PATH; HERMES_AGENT names Hermes's checkout)
set -u
here=$(cd "$(dirname "$0")" && pwd); plugin=$(cd "$here/../.." && pwd)
out=${1:-$(mktemp -d)}
for pack in acme bravo; do
  for step in home api guard push plugins seat-hooks migrate; do
    echo "######## $pack $step"
    "$here/$step.sh" "$plugin" "$pack" "$out/$pack-$step" 2>&1 | tail -40
  done
  echo "######## $pack extras"
  "$here/extras.sh" "$plugin" "$plugin/packs/$pack" "$out/$pack-extras" 2>&1 | tail -40
done
echo "output under $out"
