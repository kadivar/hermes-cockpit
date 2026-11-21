# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`cockpit demo gate`: the outbox gate shown working on this machine, with no account anywhere.

It builds a sandbox under the temp folder (sandbox.py): one repo with a bare remote, the starter pack written by
`cockpit init`, the forge and the tracker both kept in files. Then it plays one ticket through the gate, running the
real commands as child processes and printing each with what came of it: a lane commits, its own `git push` is refused
by the egress hook, it writes an intent instead, the intent is verified and endorsed, and only the human's publish
moves the branch to the remote. A pull request and a tracker comment follow the same way.

It never touches the bound workspace, the Hermes home or a real remote: every COCKPIT_* path of the child shell is
inside the sandbox, and it refuses to run when one is not.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import sandbox
from .errors import CockpitError
from .paths import PLUGIN_ROOT

TICKET = "DEMO-1"
REPO = "app"
LANE = "worker-1"
ORG = "demo"
BRANCH = f"work/{TICKET}"


class Demo:
    """One run: the sandbox, the child shells, and the lines printed."""

    def __init__(self, say=print, ask=input, yes: bool = False):
        self.say, self.ask, self.yes = say, ask, yes
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="cockpit-demo-"))
        self.cockpit = [sys.executable, os.path.join(PLUGIN_ROOT, "bin", "cockpit")]
        self.step = 0
        # the child shell: this one's, without anything that names a workspace, a pack or a lane
        self.env = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("COCKPIT_") and name != "PYTEST_CURRENT_TEST"
        }

    # ---- the sandbox
    def build(self) -> None:
        pack = os.path.join(self.base, "ws", "cockpit-pack", "pack.yaml")
        self.made = sandbox.shell(self.base, self.env.__setitem__, lambda name: self.env.pop(name, None), pack)
        self.forge_root = os.path.join(self.base, "forge")
        self.remote = os.path.join(self.forge_root, ORG, f"{REPO}.git")
        os.makedirs(os.path.dirname(self.remote))
        sandbox.repos(self.made["root"], (REPO,), remote=lambda _name: self.remote)
        self.repo = os.path.join(self.made["root"], "repos", REPO)
        lost = sandbox.outside(self.base, self.env)
        if lost:
            raise CockpitError(f"the demo's shell would reach outside its sandbox ({', '.join(lost)}): nothing was run")
        done = self.run(
            [
                *self.cockpit,
                "init",
                self.made["workspace"],
                "--no-production",
                "--write",
                "--no-bind",
                "--pack",
                os.path.dirname(pack),
                "--tracker",
                "command",
                "--project",
                TICKET.split("-", maxsplit=1)[0],
            ],
            quiet=True,
        )
        if done.returncode != 0:
            raise CockpitError(f"the demo could not write its pack: {(done.stderr or done.stdout).strip()[-400:]}")
        self._local(pack)
        checked = self.run([*self.cockpit, "pack", "check"], quiet=True)
        if checked.returncode != 0:
            raise CockpitError(f"the demo's pack does not load: {(checked.stderr or checked.stdout).strip()[-400:]}")

    def _local(self, pack: str) -> None:
        """The pack init wrote, with the forge and the tracker kept in files inside the sandbox."""
        import yaml

        raw = yaml.safe_load(open(pack, encoding="utf-8"))
        raw["forge"] = {
            **(raw.get("forge") or {}),
            "kind": "local",
            "org": ORG,
            "human_login": "you",
            "local": {"root": self.forge_root},
        }
        tracker = {key: value for key, value in (raw.get("tracker") or {}).items() if key in ("project", "url")}
        raw["tracker"] = {**tracker, "kind": "local", "local": {"root": os.path.join(self.base, "tracker")}}
        with open(pack, "w", encoding="utf-8") as handle:
            yaml.safe_dump(raw, handle, sort_keys=False)
        # the starter pack holds an intent whose lane did not load the skill for it; no lane session runs here to load one
        skills = os.path.join(os.path.dirname(pack), "skills.yaml")
        told = yaml.safe_load(open(skills, encoding="utf-8")) or {}
        told["intent"] = {}
        with open(skills, "w", encoding="utf-8") as handle:
            yaml.safe_dump(told, handle, sort_keys=False)
        # init looks for repos beside the workspace; the sandbox keeps its one under the root, as the fixtures do
        with open(os.path.join(os.path.dirname(pack), "repos.yaml"), "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                {"repos": [{"name": REPO, "path": f"repos/{REPO}", "base": "main", "gates": []}]},
                handle,
                sort_keys=False,
            )

    # ---- running and saying
    def run(self, argv, lane: bool = False, stdin: str = "", quiet: bool = False, cwd: str = ""):
        env = {**self.env, **({"COCKPIT_LANE": LANE} if lane else {})}
        if lane:
            env.pop("COCKPIT_HUMAN", None)
        lost = sandbox.outside(self.base, env)
        if lost:
            raise CockpitError(f"the demo's shell would reach outside its sandbox ({', '.join(lost)}): nothing was run")
        done = subprocess.run(
            argv, input=stdin, capture_output=True, text=True, env=env, cwd=cwd or self.base, check=False, timeout=300
        )
        if not quiet:
            self.say("    $ " + ("COCKPIT_LANE=" + LANE + " " if lane else "") + self._short(argv))
            for line in (done.stdout + done.stderr).strip().splitlines()[-8:]:
                self.say("      " + line.replace(self.base, "<sandbox>"))
        return done

    def _short(self, argv) -> str:
        import shlex

        words = ["cockpit", *argv[2:]] if argv[:2] == self.cockpit else list(argv)
        return shlex.join(words).replace(self.base, "<sandbox>")

    def head(self, text: str) -> None:
        self.step += 1
        self.say(f"\n{self.step}. {text}")

    def must(self, done, what: str) -> None:
        if done.returncode != 0:
            raise CockpitError(f"the demo stopped at step {self.step} ({what}): exit {done.returncode}")

    def git(self, *argv, where: str = "") -> str:
        done = subprocess.run(
            ["git", *argv],
            capture_output=True,
            text=True,
            env={**self.env, **sandbox.AUTHOR},
            cwd=where or self.repo,
            check=False,
        )
        if done.returncode != 0:
            raise CockpitError(f"the demo's git {' '.join(argv[:2])} failed: {done.stderr.strip()[-200:]}")
        return done.stdout.strip()

    def remote_sha(self) -> str:
        done = subprocess.run(
            ["git", "--git-dir", self.remote, "rev-parse", "--verify", "-q", BRANCH],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        return done.stdout.strip()

    def gate(self, kind: str, summary: str, flags: list, reason: str) -> str:
        """One intent through the gate as far as the human: written by the lane, verified, endorsed. Its id."""
        intent = self.gate_new(kind, summary, flags)
        self.must(self.run([*self.cockpit, "outbox", "verify", intent]), "outbox verify")
        self.must(self.run([*self.cockpit, "outbox", "endorse", intent, "low", reason]), "outbox endorse")
        return intent

    # ---- the play
    def play(self) -> None:
        say = self.say
        say("cockpit demo gate: one ticket through the outbox gate, in a sandbox.")
        say(f"sandbox: {self.base}")
        say(
            "No Hermes, no forge account, no tracker: the remote is a bare git repository, the forge and the tracker are files."
        )

        self.head(f"A lane ({LANE}) commits a change for {TICKET} in its own worktree.")
        tree = os.path.join(self.env["COCKPIT_WT"], TICKET, REPO)
        self.git("worktree", "add", "-q", "-b", BRANCH, tree, "main")
        with open(os.path.join(tree, "change.txt"), "w", encoding="utf-8") as handle:
            handle.write(f"the change for {TICKET}\n")
        self.git("add", "change.txt", where=tree)
        self.git("commit", "-q", "-m", f"{TICKET}: the change", where=tree)
        sha = self.git("rev-parse", BRANCH)
        say(
            f"    committed {sha[:10]} on {BRANCH}; the remote does not have the branch: {self.remote_sha() or 'nothing there'}"
        )

        self.head("The lane tries to push it itself. The egress hook, which sees every tool call of a lane, refuses.")
        call = {"tool": "terminal", "tool_input": {"command": f"git push origin {BRANCH}"}}
        hook = self.run(
            [sys.executable, os.path.join(PLUGIN_ROOT, "hooks", "egress.py")],
            lane=True,
            stdin=json.dumps(call),
            quiet=True,
            cwd=tree,
        )
        say(f"    $ COCKPIT_LANE={LANE} git push origin {BRANCH}")
        try:
            refusal = json.loads(hook.stdout or "{}").get("message") or ""
        except ValueError:
            refusal = ""
        if hook.returncode != 2 or not refusal:
            raise CockpitError(
                f"the demo stopped at step {self.step}: the hook did not refuse the push (exit {hook.returncode})"
            )
        say(f"      REFUSED (hook exit 2): {refusal}")
        say(f"      the remote still has no {BRANCH}: {self.remote_sha() or 'nothing there'}")

        self.head("So the lane writes what it wants done as an intent in the outbox. Nothing leaves yet.")
        push = self.gate_new("push-branch", f"push {TICKET}", ["--repo", REPO, "--branch", BRANCH])

        self.head("The intent is checked against the rules (cockpit outbox verify).")
        self.must(self.run([*self.cockpit, "outbox", "verify", push]), "outbox verify")

        self.head("A reviewer endorses it. You are standing in for the gatekeeper here.")
        self.must(
            self.run([*self.cockpit, "outbox", "endorse", push, "low", "one file, matches the ticket"]),
            "outbox endorse",
        )

        self.head("A dry run shows exactly what a publish would do, and does none of it.")
        self.must(self.run([*self.cockpit, "publish", "--id", push, "--dry-run"]), "publish --dry-run")
        say(f"      the remote still has no {BRANCH}: {self.remote_sha() or 'nothing there'}")

        self.head("Publishing is the human's act: on a real board it is your click in the Inbox.")
        if self.yes:
            say("    (--yes: not waiting for Enter)")
        else:
            self.ask("    Press Enter to publish, as the human: ")

        self.head("cockpit publish, by the human.")
        self.must(self.run([*self.cockpit, "publish", "--id", push]), "publish")

        self.head("The remote now has the branch, at the lane's commit.")
        there = self.remote_sha()
        say(f"    $ git --git-dir <sandbox>/forge/{ORG}/{REPO}.git rev-parse {BRANCH}")
        say(f"      {there}")
        if there != sha:
            raise CockpitError(
                f"the demo stopped at step {self.step}: the remote has {there or 'nothing'}, the lane committed {sha}"
            )
        say("      the same commit: the only way out was through the gate.")

        self.head("A pull request and a tracker comment go the same way, to the forge and the tracker kept in files.")
        say(
            "    (the starter pack also holds an intent whose lane did not load the skill for it; no lane session runs here,"
        )
        say("     so that one rule is left out of the sandbox's pack)")
        body = os.path.join(self.env["COCKPIT_WORKSPACE"], "pr.md")
        with open(body, "w", encoding="utf-8") as handle:
            handle.write(f"Ticket {TICKET}\n\nOne file, as the ticket asks.\n")
        opened = self.gate(
            "open-pr",
            f"open the pull request for {TICKET}",
            ["--repo", REPO, "--branch", BRANCH, "--title", f"{TICKET}: the change", "--body-file", body],
            "matches the pushed branch",
        )
        self.must(self.run([*self.cockpit, "publish", "--id", opened]), "publish open-pr")
        from .forges.local import LocalForge
        from .trackers.local import LocalTracker

        forge = LocalForge({"forge": {"org": ORG, "human_login": "you"}}, root=self.forge_root)
        pull = forge.pr(REPO, 1)
        say(
            f'      read back from the local forge: pull request #{pull["number"]} "{pull["title"]}", {pull["head"]["ref"]} at {pull["head"]["sha"][:10]}'
        )
        tracker = LocalTracker({}, root=os.path.join(self.base, "tracker"))
        tracker.seed(TICKET, "The demo's ticket")
        note = self.gate(
            "tracker-comment",
            f"say on {TICKET} that the pull request is open",
            ["--issue", TICKET, "--body", "The pull request is open: one file, as asked."],
            "says what happened",
        )
        self.must(self.run([*self.cockpit, "publish", "--id", note]), "publish tracker-comment")
        row = tracker.comments(TICKET)[-1]
        say(
            f'      read back from the local tracker: comment {row["id"]} on {TICKET} by {row["author"]}: "{row["text"]}"'
        )
        say(
            "\nThat is the gate: a lane proposes, a reviewer endorses, a human publishes, and every write is read back."
        )

    def gate_new(self, kind: str, summary: str, flags: list) -> str:
        new = self.run(
            [*self.cockpit, "outbox", "new", TICKET, kind, "--card", "t_demo", "--summary", summary, *flags], lane=True
        )
        self.must(new, f"outbox new {kind}")
        return self._intent(kind)

    def _intent(self, kind: str) -> str:
        from .paths import DEFAULT_RECORDS

        folder = os.path.join(self.env["COCKPIT_WORKSPACE"], DEFAULT_RECORDS, "outbox", TICKET)
        name = sorted(item for item in os.listdir(folder) if item.endswith(f"-{kind}.json"))[-1][: -len(".json")]
        return f"{TICKET}/{name}"


def gate(keep: bool = False, yes: bool = False, say=print, ask=input) -> int:
    """Run the gate demonstration. 0 when every step did what it shows; the sandbox is removed unless keep."""
    demo = Demo(say=say, ask=ask, yes=yes)
    try:
        demo.build()
        demo.play()
    finally:
        if keep:
            say(f"\nthe sandbox is kept for you to look at: {demo.base}")
        else:
            shutil.rmtree(demo.base, ignore_errors=True)
    return 0
