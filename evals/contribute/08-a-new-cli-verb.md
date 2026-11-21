# 08 · A new cli verb

## Prompt

> Add `cockpit pack keys` that lists every key name, one per line, so shell completion can use it.

## Expected classification

triage → check rung 1 first (`cockpit describe --json` and `cockpit pack effective` may already give this). If a verb is still justified: `feature` mode with the CLI recipe.

## A good result has every one of these

- [ ] Shows it looked at `cockpit describe --json` before deciding, and says why that is or is not enough.
- [ ] If it adds the verb: `EXAMPLES`, `FLAGS` (or `ZERO_ARGS`/`SELF_PARSED`), `COMMANDS`, the describe contract, an unknown flag exits 2, and a behaviour test on both fixture packs.
- [ ] The verb reads the registry; it does not keep a second list of keys.
- [ ] Ran `scripts/check` and quotes its last line.

## Any one of these fails the scenario

- Adds a top-level verb where a sub-verb of `pack` fits.
- Leaves the describe contract or the examples stale.
- Hard-codes key names.
