# Pinning a pack's defaults

A default is the kernel's choice, and a release may change one. A pack that wants a value to stay what it is writes
the value out: a key the pack sets is never decided by a default. When a release plans to change a default, it goes
in three steps, so that no installation sees a change it did not ask for:

1. **Announce.** The key is listed with the value its default will become and why. Nothing changes for any pack.
2. **Pin.** Each installation writes today's value into its own pack. Its settings read the same; only their source
   moves from the default to the pack.
3. **Change.** A later release changes the default. A pack that pinned is not affected; a pack that did not is
   refused the update (see below) until it pins or the release declares the key.

No default is listed today.

## The command

```sh
cockpit pack pin            # the lines to add, for every value this pack takes from a default that will change
cockpit pack pin --json     # the same as data: file, key, value, the planned default and why
cockpit pack pin --all      # every value this pack takes from any default
```

It prints and never writes: the pack is yours to edit. The output is one YAML document per pack file, with the key's
meaning and what its default will become as comments above it. For a release that planned a shorter wait before a
pull request counts as stale, it would read:

```yaml
# pack.yaml: add these lines; a block the file already has takes the keys printed under it
hours:
  # How long a watched PR may go without activity before it is called stale.
  # its default will become 48: a shorter wait
  pr_stale_hours: 72
```

Add each key under the block the file already has (`hours:` above), then:

```sh
cockpit pack check                 # the pack still loads
cockpit pack pin                   # prints nothing: no default that will change decides anything here
cockpit pack effective --sources   # the same values as before, their source now [pack]
```

`cockpit pack effective --sources` also marks, in its text, each line whose value comes from a default that will change.
Its `--json` carries no such mark: that is what two kernels are compared by.

`--all` is for a pack that wants no default at all to decide for it. A key inside a list item, or under a block the pack
does not have, is printed as a comment and not as a line, because adding the block could itself change something.

## Which defaults will change

`kernel/cockpitlib/pending_defaults.json` lists them: the key, the value its default will become, and one line on why.
The list is data. No code reads it to change what a key means; `pack pin` and the mark in the dump are its only readers.
The list is empty when no change is planned, and `cockpit pack pin` then prints nothing; `--all` still prints every
value a default decides.

## What protects a pack that did not pin

The update pre-flight ([update.md](update.md)) runs the incoming kernel against the live pack and refuses an update
that changes any setting's value without declaring it. A release that moves a default therefore cannot land on a pack
that still takes that default, unless the release declares the key and the adopter has read that it does.
