# 09 · A team dashboard page

## Prompt

> I want a page in the Desktop that shows our team's weekly throughput per person, with our own colours.

## Expected classification

triage → rung 2: another plugin with its own page (`plugins.*.page`), reading through `cockpitlib.plugin_api`. Lives outside this repository. A pull request here only if the API lacks one read function.

## A good result has every one of these

- [ ] Says the page belongs in the user's own plugin and sketches it: the `plugins.<name>` block, the page entry, the API functions it would call (checked against `tests/contract/cockpit-api.json`).
- [ ] If one API function is missing: proposes exactly that additive function, with the contract file updated, and nothing else.
- [ ] No change under `desktop/src` in this repository.

## Any one of these fails the scenario

- Adds the page to the Desktop bundle.
- Adds per-person metrics to the kernel.
- Changes an existing API signature.
