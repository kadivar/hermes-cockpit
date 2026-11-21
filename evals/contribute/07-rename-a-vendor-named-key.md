# 07 · Rename a vendor named key

## Prompt

> The pack key `tracker.auth_env` should be called `tracker.credentials_env`. Rename it everywhere.

## Expected classification

triage → compatibility rule: one name for one thing. The rename is whole, keeps no alias, and is declared as a
breaking change.

## A good result has every one of these

- [ ] The new name is read; the old one is an ordinary unknown key, and a test proves both on the fixture packs.
- [ ] The registry (`kernel/cockpitlib/pack_keys.py`), both fixture packs, `starter/`, the docs and the generated
      references carry the new name only.
- [ ] `CHANGELOG.md` lists the old name under "Removed" and `UPDATE-CHANGES.json` declares the key.
- [ ] The result says, in one line, what an existing pack must change.

## Any one of these fails the scenario

- Keeps the old name as an alias, or reads both.
- Adds a special error message that tells the history of the name.
- Leaves the old name in a fixture pack, a doc or a generated file.
