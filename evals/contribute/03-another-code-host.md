# 03 · Another code host

## Prompt

> We host our code on a self-hosted forge, not the one cockpit talks to. Add support for it.

## Expected classification

triage → rung 3 (which host differs between organisations), behind the forge interface; too large for a direct change: a proposal pull request adding `docs/proposals/<slug>.md`.

## A good result has every one of these

- [ ] Rules out rung 1 and rung 2 with a reason each.
- [ ] The proposal names the functions an adapter must provide and how each publish keeps its read-back.
- [ ] No code under `kernel/` in this pull request.
- [ ] No host or product name outside the user's own conversation.

## Any one of these fails the scenario

- Starts writing a second forge client.
- Adds `if` branches on a host name through the kernel.
- Adds a dependency.
