# Updating cockpit

Hermes's own `plugins update` runs its security scan on every update, and a kernel built on subprocess reads as "caution"
there with no way to accept it short of turning scanning off for every plugin. Cockpit therefore updates itself, from the
Settings page or the shell. Applying an update is a human act: a lane's call is refused.

```sh
cockpit update            # what is installed, and what the last check saw
cockpit update check      # git fetch origin; how many commits the checkout is behind (housekeeping does this hourly)
cockpit update apply      # fast-forward; the kernel's dependencies when they changed; no stale bytecode;
                          # the Desktop bundle time when the UI changed; Hermes's install record; a gateway restart;
                          # then, on stderr, the one line left to you
cockpit update apply --to <commit>      # the same, stopping at that commit instead of the repository's head
cockpit update rollback                 # back to the commit the last update came from; then what follows an update
cockpit update rollback --to <commit>   # back to that commit, when it is behind the installed one
cockpit update rehome <url> [--branch <name>] [--dry-run]   # follow another repository that holds the installed tree
cockpit update rehome --undo            # take that move back, while no update was applied since
```

`apply` and `rollback` also take `--no-restart`, which leaves the gateway as it is.

The Settings page shows the installed commit, the branch it is installed from (`installed from`, also `installed.follows`
in `cockpit update`), the repository's state and two buttons, Check now and Update now; the Inbox
carries a row while the repository is ahead. A checkout with local edits is refused. After an update the gateway is asked to restart
(it drains running jobs first). Hermes refuses that while a session is live; the update then says in capitals that the
gateway did not restart, and the Inbox keeps a row until it has: the pages are answered by the gateway, which runs the
code it loaded when it started. Restart it yourself with `hermes gateway restart` once nothing is running.

What is left to you comes as one line for this machine's shell, from `cockpit update apply` (its last lines) and from the
Settings page and the Inbox row after Update now, with a copy button: the plugin's launcher by its real path
(`~/.hermes/bin/cockpit` where setup linked it, the checkout's `bin/cockpit` otherwise, `py -3 "…\bin\cockpit"` on
Windows), then `setup --rerender` (the
seats on the new kernel), `doctor`, and the Desktop started again when its UI changed (on macOS a command; elsewhere the
line ends on a reminder). The steps are joined with `&&`, so the line stops at the first failure.

## Dependencies

When an update changes `pyproject.toml` or `requirements.lock` and the plugin has its own `.venv`, the dependencies are
refreshed. A tree that carries `requirements.lock` is installed from it with `pip install --require-hashes`, so every
downloaded file must match the hash the lock records, and then the plugin itself with `--no-deps`, so nothing is
resolved on the spot. A tree without the lock file is installed with `pip install -e .`, as before. A failed install is
reported on the update's result (`pip failed: …`) and the update stands.

## `--to`

`--to` takes a hash, a tag or any name git resolves. The commit must lie on the repository's line between the installed
commit and its head: one that origin does not have, or one behind the checkout, is refused with the reason. It passes the
same pre-flight, and afterwards the page and the Inbox row count what is still ahead.

## Requiring a signed tag

By default an update is the head of the branch the checkout follows, and what vouches for it is the one remote it came
from. An installation can ask for more: **name signers, and from then on an update is a tag one of them signed, and
nothing else.** It is off until you turn it on, in one of two ways:

- a tracked file `UPDATE-SIGNERS` at the root of the **installed** tree, in the format of ssh's allowed signers (one
  `<principal> <key type> <public key>` per line). It is read from the installed commit, never from the tree an update
  would bring: a candidate cannot vouch for itself. A release that changes the file must itself be signed by a signer
  the installed file names, and the new file counts from the next update on;
- the environment variable `COCKPIT_UPDATE_SIGNERS`, naming such a file, or a GPG keyring folder (a `GNUPGHOME` that
  holds the public keys you accept). It wins over the tracked file. A name that leads nowhere refuses every check and
  update, so a typing error is not an open door. Set it where the update runs: your shell for `cockpit update`, and the
  gateway's environment for the hourly check and the Settings page.

With signers named:

- `cockpit update check` fetches the branch and the tags and offers the furthest tag ahead that verifies
  (`git verify-tag` against those signers). The record names the tag and counts the commits beyond it that no signed
  tag covers (`unsigned_ahead`); those are not an update and raise no Inbox row.
- `cockpit update apply` moves to that tag; `--to <tag>` moves to the tag named, which must verify too. A commit hash
  is not accepted for `--to` in this mode.
- An unsigned head, a plain tag, a tag signed with a key that is not listed, and a signature of the other kind (PGP
  with ssh signers, ssh with a keyring) are refused, each with the reason. The checkout stays where it was.

The pre-flight below still runs on the tag's commit. `rollback` is not affected: it only goes back to commits this
installation already ran. To sign a release tag with an ssh key:
`git -c gpg.format=ssh -c user.signingkey=~/.ssh/release.pub tag -s v1.2.3 -m v1.2.3`.

## The pre-flight

A pack that fails to load stops every lane, so an update is checked against the live pack before the checkout moves.

1. `apply` exports the incoming commit to a temporary folder (always removed).
2. It runs that commit's own `bin/cockpit pack check` there against the bound pack, and refuses the update with the
   check's last line when it fails. The checkout stays where it was.
3. When both the incoming commit and the installed kernel have `cockpit pack effective --json`, the two answers are
   compared and any value that differs refuses the update, unless the incoming tree lists the key under
   `effective_changes` in `UPDATE-CHANGES.json` (a key covers what is under it). Declared changes are printed.

No flag skips it. An installation with no workspace bound has no live pack: it updates and says the pre-flight was
skipped. The check runs on the plugin's present environment, so a commit that needs a new dependency to load the pack is
refused until that dependency is installed; the refusal says so when `pyproject.toml` changes with it.

## What bypasses the pre-flight

`hermes plugins update` and a manual `git pull` (or any other git command) in the plugin folder move the checkout without
the pre-flight, without the dependency refresh and without the one line left to you. Use `cockpit update apply`.

## Rolling back

An update records the commit it came from, and `cockpit update rollback` moves the checkout back to it (`git checkout -B`
of the same branch, so the branch still follows origin); `--to` names another commit, which must be behind the installed
one on the checkout's own history. A checkout with local edits is refused.

A release that older code cannot follow (a record format, say) carries a tracked file `UPDATE-FLOOR` at its root whose
first line is a commit: from then on a rollback goes no further back than that commit, and a floor file that names no
commit refuses every rollback.

The older code meets the live pack first: its own `pack check` must pass, as before an update (the comparison of
effective values is left out, since going back changes them on purpose). Then the same steps follow as after an update:
dependencies, bytecode, the Desktop bundle, Hermes's record, the gateway restart, the one line left to you.

A rollback forgets where the last update came from, so a second one names its commit. Afterwards the record keeps what
was left: the page and the Inbox row still count those commits as ahead, and say they follow a rollback, until the
checkout is brought forward again.

## Moving to another repository

When the project's repository moves (to a new host, or to a repository with a fresh history), an installation follows it
with one command, and not one of its working files changes:

```sh
cockpit update rehome https://example.test/team/cockpit.git --dry-run   # fetch, compare the trees, report; change nothing
cockpit update rehome https://example.test/team/cockpit.git             # the move
cockpit update rehome --undo                                            # the way back
```

It is a human act, like `apply`: a lane's call is refused by the verb and by the kernel's own denies.

**What makes it safe.** The move only happens when the branch over there (the repository's default branch, or
`--branch`) has the very tree that is installed: the two tree hashes are compared and printed, and anything else is
refused. The two histories need not be related. Since the code on disk is already the code over there, the move is made
of refs and configuration alone; no command that writes a working file or the index is run. Afterwards git's status and
every tracked file's time, size and mode are compared with what they were before, and a difference takes the move back.

**What it refuses, changing nothing:** a checkout with local edits or on no branch; a linked worktree of this checkout
that has the target branch checked out; a tree that differs; a URL with a password in it; a remote named `previous` or
`rehome-incoming` that is already there; a Hermes install record that cannot be written.

**What it changes**, each step checked before the next, and all of them taken back when one fails:

1. the remote `origin` is renamed `previous` (its refs stay: they are the way back) and its push URL is set to `DISABLED`,
   so nothing is pushed to the old repository by accident;
2. the new repository becomes `origin`, with its default branch recorded;
3. a local branch named after the new branch is written at the fetched commit, HEAD is pointed at it and its upstream
   is `origin/<branch>` (the old local branch stays where it was);
4. Hermes's install record gets the new source and revision, after `.install-metadata.json` is copied beside itself as
   `.install-metadata.json.before-rehome`;
5. the update record (`watch/plugin-update.json`) is rewritten for the new branch, zero behind, with a `rehomed_from`
   note (the old URL, branch and commit);
6. what `--undo` needs is kept in the checkout's own git config (`cockpit.rehome`).

It ends with the line to run (the seats re-rendered and `doctor`; no restart, since no code changed) and the exact
command that takes it back. From then on `cockpit update check` and `apply` read the new origin.

**The way back.** `cockpit update rehome --undo` puts HEAD on the old branch, restores the remotes (the new one is
removed), the push URL, Hermes's record (this plugin's entry from the snapshot) and the update record. It is allowed only
while the checkout is still at the commit the move left it at: once an update from the new repository is applied, the
old repository no longer has the installed code, and the undo refuses. The remote `previous` stays until you remove it
(`git remote remove previous`); a second move is refused while it is there.

With `--dry-run` the new repository is fetched under a temporary remote name, the trees are compared and reported, and
the temporary remote is removed again: no remote, branch or record is left changed (the fetched objects stay in git's
object store, unreferenced).

## Proving a new kernel reads your records

[replay.md](replay.md) describes `scripts/replay`, which proves that a new kernel reads an installation's real records
exactly as the one running now does.
