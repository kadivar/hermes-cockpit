# Personal values

## Goal

One pack that every teammate uses unchanged. What differs between two people (a home folder, a login, a branch
prefix, an address) is not written into the pack: the pack asks for it by name, and each person answers in one file of
their own that stays out of version control.

## The pack lines

There is no key. Two tokens are filled in the **values** of every YAML file of the pack (`pack.yaml`, `repos.yaml`,
`skills.yaml`, `egress.yaml`, `staging.yaml`, the helpers file, the accounts manifest, `migrate.yaml` and
`platform/map.yaml`), and a third in a soul:

| Token | Becomes | Where |
|---|---|---|
| `{home}` | your home folder | any string value of a pack YAML file |
| `{local.<name>}` | the value `pack.local.yaml` gives `<name>` | any string value of a pack YAML file |
| `{{HOME}}` | your home folder | a soul, beside `{{LANE}}` and `{{RECORDS}}` (see [seats-and-souls.md](seats-and-souls.md)) |

`pack.local.yaml` sits beside `pack.yaml`. It is optional, and a missing one is an empty one. Its top level maps names
to values:

```yaml
forge_login: dev-one
branch_prefix: dev-one
checkouts: "{home}/src"
slots: 2
protected: [main, release]
```

## The script contract

There is no script: the contract is the reader in `kernel/cockpitlib/pack_local.py`, which every read of a pack YAML
file goes through.

- **A name** is lowercase letters, digits and underscores, starting with a letter. A value is any YAML value. A text in
  it may use `{home}`; it may not use `{local.…}` (a personal value is written out, it never names another one).
- **Inside a longer text** the value is inserted as text, so it must be a text or a number:
  `branch_prefix: "{local.forge_login}/work"`.
- **Alone as the whole value** it keeps its type: `slots: "{local.slots}"` is the number 2, and
  `protected_branches: "{local.protected}"` is the list. Quote the token: YAML reads a bare `{` as the start of a
  mapping. An editor that holds the file against a schema under `kernel/schema/` marks a token where a number or a
  list is expected; `cockpit pack check` is the judge.
- **Only these exact tokens are touched.** `{ticket}`, `{slot}`, `{pack}`, `{workspace}`, `{root}`, `{n:03d}`, a
  quantifier such as `\d{12}` and every other brace form stay as written, and so does every key of a mapping.
- **A name the local file does not set** stops the pack from loading, and says where it was asked for:
  `repos.yaml, repos[0].path: {local.checkouts} is not set: add "checkouts: …" to pack.local.yaml beside the pack`.
  The kernel never guesses a value. A local file that is not a mapping, or holds a name of another form, is refused by
  its name, whether or not the pack uses it.
- **A pack that uses neither token and has no local file** is read exactly as before.
- **`migrate.yaml`** already gives `{home}` a meaning of its own (the runtime's home, in an exporter's command), so
  there only `{local.<name>}` is filled.
- **A regular expression gets the value as it is.** `egress.yaml` holds patterns, and a home folder put into one is
  not escaped: a dot in a user name matches any character there. Write a pattern so that this does no harm (a deny that
  matches one character more is still a deny), and keep a home folder out of a pattern that allows.
- **The local file is not a place for a secret.** It is a plain file that `cockpit pack effective` prints; a credential
  belongs in the vault.

## A copy-paste example

`pack.yaml`:

```yaml
branch_prefix: "{local.branch_prefix}"
forge:
  org: example-org
  human_login: "{local.forge_login}"
skills_dir: "{home}/src/team-skills"
```

`repos.yaml`:

```yaml
repos:
  - name: api
    path: "{local.checkouts}/api"
```

The accounts manifest (`accounts.yaml`):

```yaml
accounts:
  - origin: https://staging.example.test
    identifier: "{local.test_account}"
    owner: tester-1
```

`pack.local.yaml`, one per person, never committed:

```yaml
forge_login: dev-one
branch_prefix: dev-one
checkouts: "{home}/src"
test_account: dev-one@example.test
```

`cockpit init` writes `pack.local.example.yaml` (copy it to `pack.local.yaml`) and a `.gitignore` that names
`pack.local.yaml`. In a pack written by hand, add that line to the pack folder's `.gitignore` yourself.

## How to test it

```sh
cockpit pack check                       # the first name that is not set, with its file and key
cockpit pack check --all                 # every one the checks reach, file by file
cockpit pack effective | grep -n "src"   # the values in force, filled in
cockpit pack explain forge.human_login
```

`cockpit pack effective` prints the filled values, so its output differs between two people where the pack asks for a
personal value and nowhere else. A snapshot cut for a replay copies the pack folder with `pack.local.yaml` in it: see
[operations/replay.md](../operations/replay.md).
