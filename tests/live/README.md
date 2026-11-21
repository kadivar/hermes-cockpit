# Real-Hermes harness

Pytest stubs do not prove the Hermes contract. These scripts run cockpit against the installed Hermes, on fresh
temporary homes, for both fixture packs. Run them at every milestone and put the output in the commit body.

    tests/live/run-all.sh [out-dir]

| Script | Proves |
|---|---|
| `home.sh` | setup → doctor → setup → doctor on a fresh home; crons at the pack's hours; a second setup changes nothing |
| `plugins.sh` | each seat links cockpit and would load its `register()` hooks |
| `seat-hooks.sh` (`seat-hooks.py`, `seat-pretool.py`) | inside Hermes: the hooks cockpit registers, and `git status` allowed / `git push` and a refused host blocked through Hermes's own pre-tool dispatch |
| `api.sh` | the plugin API on a real board: cards, blocks, the loop guard's triage, answers, idempotent create |
| `guard.sh` | Hermes's respawn guard: a lane's PR link holds a card (`active_pr`), cockpit's own comment is defused, unguard's handoff lets the card go; a blocked treat card closes as superseded |
| `push.sh` | the CLI writes, endorses and publishes a push to a local bare remote |
| `extras.sh` | Hermes's own view of each home's extra plugins, provider plugins and skills |
| `migrate.sh` | the migrator's plan, apply, verify and rollback on a real home |

`HERMES_AGENT` names Hermes's checkout (default `~/.hermes/hermes-agent`). Nothing here touches the live `~/.hermes`.
