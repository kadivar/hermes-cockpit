# Prompt overrides

## Goal

Your own text for a named prompt of the kernel, or a prompt of your own that your souls and cards can include by name.

## The pack lines

In `pack.yaml`:

```yaml
prompts:
  plan-format: prompts/plan-format.md      # replaces the kernel's
  handover: prompts/handover.md            # your own
```

`prompts` maps a lowercase name (`[a-z0-9][a-z0-9_-]*`) to a file, absolute or beside `pack.yaml`.

## The script contract

There is no script: the contract is the lookup in `kernel/cockpitlib/prompts.py`.

- **The placeholder** is `{{prompt:name}}`.
- **Lookup:** the pack's file for that name, else the kernel's `prompts/<name>.md` in the plugin. The kernel ships one:
  `plan-format`, the shape of a ticket's plan, which the intake soul includes.
- **Where it is resolved:** in a seat's soul when setup renders it, in a kickoff's prompt text, and in the advisor's
  prompt file. The file's text is inserted with surrounding blank space trimmed.
- **An unknown name** stops the render: `no prompt <name>: name it under prompts in pack.yaml`.
- **A missing file** is not refused when the pack loads. Doctor fails with `prompt <name> missing: <path>`.

## A copy-paste example

`prompts/plan-format.md` in the pack folder:

```markdown
# Plan format

Brief, impacted areas, before, after, files, how it will be tested, plan gate.
```

```yaml
prompts:
  plan-format: prompts/plan-format.md
```

And, to use a prompt of your own in a soul (see [seats-and-souls.md](seats-and-souls.md)):

```markdown
## Handing over

{{prompt:handover}}
```

## How to test it

```sh
cockpit pack check
cockpit doctor                                  # names a prompt file that is missing
cockpit setup --rerender --seat intake
grep -n "how it will be tested" ~/.hermes/profiles/intake/SOUL.md
```

A soul already rendered keeps the old text until it is rendered again.
