# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A workspace that is nobody's: a folder with a workspace, a root of repos with bare remotes, an empty Hermes home, and
the shell that points cockpit at them. The test suite's fixtures and `cockpit demo` are both made of it.

Nothing here reads or writes outside the folder it is given. `shell` only names the paths, through the `setenv` it is
handed: a test's monkeypatch, or the environment of a child process.
"""

import os
import shutil
import subprocess

# Every repo made here starts on main, the base branch of the fixtures, and its commits and tags are not signed, whatever
# this machine's git says (a global commit.gpgsign/tag.gpgsign would need the owner's key in every git call).
GIT_CONFIG = (("init.defaultBranch", "main"), ("commit.gpgsign", "false"), ("tag.gpgsign", "false"))
# The names that say where cockpit reads and writes: a sandbox sets every one, to a path inside itself.
PATHS = (
    "COCKPIT_WORKSPACE",
    "COCKPIT_ROOT",
    "COCKPIT_HERMES_HOME",
    "COCKPIT_PACK",
    "COCKPIT_WT",
    "COCKPIT_CURSOR_HOOKS",
    "COCKPIT_VOLUMES",
    "GNUPGHOME",
)
AUTHOR = {
    "GIT_AUTHOR_NAME": "Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.test",
    "GIT_COMMITTER_NAME": "Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.test",
}


def plain_git(setenv) -> None:
    """Name GIT_CONFIG above in a shell, over the machine's global git config."""
    setenv("GIT_CONFIG_COUNT", str(len(GIT_CONFIG)))
    for index, (key, value) in enumerate(GIT_CONFIG):
        setenv(f"GIT_CONFIG_KEY_{index}", key)
        setenv(f"GIT_CONFIG_VALUE_{index}", value)


def repos(root: str, names, remote=None) -> None:
    """Under root, a repo per name at repos/<name> with one commit on main, and a bare origin it has pushed to and
    fetched from, as a forge would be: remotes/<name>.git, or where `remote(name)` says."""
    git = {**os.environ, **AUTHOR}
    plain_git(git.__setitem__)

    def run(*argv):
        subprocess.run(["git", *argv], check=True, capture_output=True, env=git)

    for name in names:
        repo = os.path.join(root, "repos", name)
        os.makedirs(repo)
        run("init", repo)
        with open(os.path.join(repo, "README"), "w", encoding="utf-8") as handle:
            handle.write("hello\n")
        run("-C", repo, "add", "README")
        run("-C", repo, "commit", "-m", "init")
        origin = remote(name) if remote else os.path.join(root, "remotes", f"{name}.git")
        run("init", "--bare", "-q", origin)
        run("-C", repo, "remote", "add", "origin", origin)
        run("-C", repo, "push", "-q", "origin", "main")
        run("-C", repo, "fetch", "-q", "origin")
        run("-C", repo, "config", "user.email", "dev@example.test")
        run("-C", repo, "config", "user.name", "Dev")


def copy_repos(template: str, root: str, names) -> None:
    """A copy of repos made under template, under root; each origin is the copy's, not the template's."""
    shutil.copytree(template, root, symlinks=True)
    for name in names:
        for told in (
            os.path.join(root, "repos", name, ".git", "config"),
            os.path.join(root, "repos", name, ".git", "FETCH_HEAD"),
        ):
            if os.path.isfile(told):
                text = open(told, encoding="utf-8").read()
                open(told, "w", encoding="utf-8").write(text.replace(template, root))


def shell(base: str, setenv, delenv, pack: str, homes=(), path: str = "") -> dict:
    """Under base, a workspace (ws), a root (root, not made) and a Hermes home (hermes), named in a shell with the pack:
    {workspace, root, home}. `homes` are seat home folders made in the workspace; `path` goes first on PATH."""
    plain_git(setenv)
    workspace, root, home = os.path.join(base, "ws"), os.path.join(base, "root"), os.path.join(base, "hermes")
    os.mkdir(workspace)
    for name in homes:
        os.makedirs(os.path.join(workspace, "homes", name))
    os.mkdir(home)
    with open(os.path.join(home, "known-providers"), "w", encoding="utf-8") as handle:
        handle.write("fixture-a\nfixture-b\n")
    setenv("COCKPIT_WORKSPACE", workspace)
    setenv("COCKPIT_ROOT", root)
    setenv("COCKPIT_HERMES_HOME", home)
    setenv("COCKPIT_PACK", pack)
    setenv("COCKPIT_WT", os.path.join(root, "wt"))
    setenv("COCKPIT_CURSOR_HOOKS", os.path.join(base, "cursor", "hooks.json"))
    setenv("COCKPIT_VOLUMES", os.path.join(root, "volumes"))
    setenv("COCKPIT_HUMAN", "1")
    keyring = os.path.join(home, "gnupg-none")  # never the machine's keyring: nothing sealed is the start state
    os.mkdir(keyring, mode=0o700)
    setenv("GNUPGHOME", keyring)
    setenv("COCKPIT_CHAT_ARGV", "/bin/echo cockpit-chat")
    if path:
        setenv("PATH", path + os.pathsep + os.environ.get("PATH", ""))
    delenv("COCKPIT_LANE")
    return {"workspace": workspace, "root": root, "home": home}


def outside(base: str, env: dict) -> list:
    """The path names of a shell that are unset or lead out of the sandbox: any one is a reason not to run in it."""
    real = os.path.realpath(base)
    found = []
    for name in PATHS:
        value = env.get(name) or ""
        if not value or not (os.path.realpath(value) + os.sep).startswith(real + os.sep):
            found.append(name)
    return found
