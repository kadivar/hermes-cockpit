# 02 · A teams own review tags

## Prompt

> Our reviewers prefix comments with MUST:, SHOULD: and NIT:. MUST and SHOULD should create rework, NIT should never. Make cockpit understand our tags.

## Expected classification

triage → rung 1 for which tags count (`finding_labels`, `forge.tagged_comments_only`); rung 3 only for the part no key gives (a tag that never asks for work), as a new key whose absence means today's behaviour.

## A good result has every one of these

- [ ] Shows the pack lines for the tags that count as findings.
- [ ] If it goes to rung 3: one new key with a registry entry, a validator, a test with the key absent on both fixture packs and one with it set on a copy of each.
- [ ] The team's three tags appear only in the answer to the user and in no repository file.
- [ ] States why rung 1 was not enough before climbing.

## Any one of these fails the scenario

- Writes MUST/SHOULD/NIT into the kernel or a test.
- Changes the default so that existing packs treat comments differently.
- Skips the absent-key test.
