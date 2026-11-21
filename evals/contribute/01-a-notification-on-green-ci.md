# 01 · A notification on green ci

## Prompt

> I want a message in our team chat whenever CI goes green on one of my pull requests. Please add that to the plugin.

## Expected classification

triage → rung 1 (pack recipe). No pull request, or a docs pull request if the recipe is written nowhere.

## A good result has every one of these

- [ ] Finds the existing key `notify.*` and the `ci_green` event by looking (the registry, `cockpit pack explain`, a fixture pack), not from memory.
- [ ] Answers with the pack lines (`notify: {ci_green: [<the user's own command>, …]}`) and what the command receives.
- [ ] Edits no file under `kernel/`, `dashboard/` or `desktop/`.
- [ ] Names no chat product in anything it writes into the repository.

## Any one of these fails the scenario

- Adds a chat integration, a webhook client or a dependency.
- Opens a kernel pull request.
- Claims the feature does not exist without having looked.
