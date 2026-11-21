# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two parsers that read text someone else wrote, under generated input: the fence's shell reader never raises, ends
within a bound, and never lets through a line one of the kernel's own deny rules matches; the pack loader answers a
damaged pack with a pack or a PackError and nothing else. The cases come from a seeded generator, so a failure names
the seed and the case and is the same on every machine; CASES and SEED can be raised from the environment for a longer
hunt (FUZZ_CASES=200000 FUZZ_SEED=7 scripts/test tests/<this file>)."""

import os
import random
import re
import shutil
import time

import pytest
import yaml

from cockpitlib import egress
from cockpitlib import pack as packs
from cockpitlib.errors import PackError
from tests.support.both_packs import PACKS

CASES = int(os.environ.get("FUZZ_CASES") or 2000)
SEED = int(os.environ.get("FUZZ_SEED") or 20240229)
BOUND = 2.0  # seconds for one input of a few kilobytes: the readers are linear, this only catches a blow-up
LIMIT = 4096

WORDS = (
    "git",
    "push",
    "remote",
    "add",
    "config",
    "commit",
    "--no-verify",
    "-n",
    "checkout",
    "-b",
    "merge",
    "tag",
    "branch",
    "-C",
    "/tmp/x",
    "-c",
    "core.hooksPath=/dev/null",
    "cockpit",
    "publish",
    "apply",
    "setup",
    "update",
    "rollback",
    "rehome",
    "check",
    "outbox",
    "list",
    "hermes",
    "kanban",
    "comment",
    "--author",
    "cron",
    "create",
    "kanban.db",
    "vault",
    "gh",
    "pr",
    "api",
    "-X",
    "POST",
    "sudo",
    "env",
    "X=1",
    "HUSKY=0",
    "sh",
    "bash",
    "eval",
    "exec",
    "command",
    "nohup",
    "time",
    "xargs",
    "find",
    "/",
    "~",
    "rg",
    "grep",
    "echo",
    "printf",
    "cat",
    "ls",
    "rm",
    "-rf",
    "curl",
    "https://example.test/x",
    "docker",
    "exec",
    "python3",
    "-m",
    "pytest",
    "npm",
    "test",
    "true",
    "false",
    "if",
    "then",
    "fi",
    "for",
    "do",
    "done",
    "while",
    "case",
    "esac",
    "function",
    "security",
    "find-generic-password",
    "origin",
    "HEAD",
    "main",
    "--force",
    "-f",
    "--",
    "-",
)
MARKS = (
    ";",
    "&&",
    "||",
    "|",
    "&",
    "$(",
    ")",
    "`",
    "'",
    '"',
    "\\",
    "\n",
    "\r\n",
    "\t",
    " ",
    "  ",
    "<<EOF",
    "<<'EOF'",
    "EOF",
    "<<<",
    "#",
    "{",
    "}",
    "(",
    ">",
    ">>",
    "<",
    "2>&1",
    "$",
    "${",
    "$((",
    "))",
    "[[",
    "]]",
    "!",
    "*",
    "?",
    "~",
    "=",
    "\\\n",
    "\x00",
    "\x1b[0m",
    " ",
    " ",
    "﻿",
    "é",
    "漢",
    "\U0001f600",
    "\x7f",
)


def _shell_text(rng: random.Random) -> str:
    """One hostile shell text: words a deny rule knows, the shell's own marks, quotes left open, deep nesting, long runs."""
    kind = rng.random()
    if kind < 0.06:  # a long run of one thing
        return (rng.choice(WORDS + MARKS) * rng.randint(1, LIMIT))[:LIMIT]
    if kind < 0.12:  # wrappers nested deeper than any reader follows
        depth = rng.randint(1, 60)
        inner = " ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 4)))
        for _ in range(depth):
            wrap = rng.choice(
                ("sh -c '{}'", 'bash -c "{}"', "$({})", "`{}`", "eval {}", "sudo env X=1 {}", "( {} )", "{{ {}; }}")
            )
            inner = wrap.format(inner)
        return inner[:LIMIT]
    parts = []
    for _ in range(rng.randint(1, 60)):
        roll = rng.random()
        parts.append(
            rng.choice(WORDS)
            if roll < 0.55
            else rng.choice(MARKS)
            if roll < 0.9
            else "".join(chr(rng.randint(1, 0x2FFF)) for _ in range(rng.randint(1, 8)))
        )
        parts.append(rng.choice(("", " ", " ", " ", "\t", "\n")))
    return "".join(parts)[:LIMIT]


def _within(started: float, what: str, case: int, text: str) -> None:
    took = time.perf_counter() - started
    assert took < BOUND, f"{what} took {took:.1f}s on case {case} of seed {SEED}: {text[:200]!r}"


def test_the_shell_reader_never_raises_and_ends_within_a_bound_for_any_text():
    rng = random.Random(SEED)
    entries = ("commit", "checkout -b", "merge", "tag", "branch", "push", "rebase", "reset --hard")
    for case in range(CASES):
        text = _shell_text(rng)
        started = time.perf_counter()
        try:
            argvs = egress._argvs(text)
            moved = egress.git_moves(text, entries)
            said = egress.check(text)
        except Exception as exc:  # noqa: BLE001 - any exception at all is the failure this test looks for
            raise AssertionError(
                f"the shell reader raised {type(exc).__name__}: {exc} on case {case} of seed {SEED}: {text!r}"
            ) from exc
        _within(started, "the shell reader", case, text)
        assert isinstance(argvs, list) and all(isinstance(argv, list) and argv for argv in argvs), (case, text)
        assert isinstance(moved, str) and isinstance(said, str), (case, text)


def test_none_and_other_shapes_are_read_as_text_or_refused_and_never_raise():
    for value in (None, "", 0, 3.5, b"git push", ["git", "push"], {"command": "git push"}, object()):
        assert isinstance(egress._argvs(value), list)
        assert isinstance(egress.git_moves(value, ("push",)), str)
        assert isinstance(egress.check(value), str)
    assert egress.check(None) == "unreadable tool call"


@pytest.mark.parametrize("lane", ("worker-1", "tester-1", "gatekeeper", ""))
def test_a_lanes_tool_call_never_raises_and_a_line_a_kernel_deny_matches_is_never_allowed(bare, monkeypatch, lane):
    if lane:
        monkeypatch.setenv("COCKPIT_LANE", lane)
    rng = random.Random(SEED + len(lane))
    denied = 0
    for case in range(CASES // 4):
        text = _shell_text(rng)
        started = time.perf_counter()
        try:
            said = egress.check_tool("terminal", {"command": text})
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"check_tool raised {type(exc).__name__}: {exc} on case {case} of seed {SEED}: {text!r}"
            ) from exc
        _within(started, "check_tool", case, text)
        assert isinstance(said, str), (case, text)
        rule = next((pattern for pattern in egress.KERNEL_DENY if re.search(pattern, text)), "")
        if rule:
            denied += 1
            assert said != "", (
                f"allowed although the kernel deny {rule!r} matches, on case {case} of seed {SEED}: {text!r}"
            )
    assert denied > CASES // 40, (
        "the generator no longer writes lines the kernel denies: the property was not exercised"
    )


@pytest.mark.parametrize(
    "name,shape",
    (
        ("terminal", None),
        ("terminal", "git push"),
        ("terminal", ["git", "push"]),
        ("terminal", {"command": None}),
        ("terminal", {"command": ["git", "push"]}),
        ("terminal", {"command": {"a": 1}}),
        ("", {}),
        (None, None),
        ("write_file", {"path": None, "content": 7}),
        ("browser_navigate", {"url": ["x"]}),
        ("execute_code", {"code": 5}),
        ("patch", {"path": {"x": 1}}),
        ("search_files", {"path": 3}),
        ("x" * 5000, {"x" * 5000: "y" * 5000}),
    ),
)
def test_a_tool_call_of_the_wrong_shape_is_answered_and_never_raises(bare, monkeypatch, name, shape):
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert isinstance(egress.check_tool(name, shape), str)


# ---------- the pack loader ----------

JUNK = (
    None,
    True,
    False,
    0,
    -1,
    3.5,
    "",
    " ",
    "x",
    "~",
    "null",
    "- a",
    "a: b",
    "{",
    "[",
    "*",
    "&a",
    "!!python/object:os.system",
    "\x00",
    "é漢\U0001f600",
    "x" * 3000,
    "../../etc/passwd",
    "/",
    "$(id)",
    "`id`",
    "(unclosed",
    "[a-",
    "(?P<x",
    "\\",
    "0x10",
    "1e9",
    "2020-01-01",
    "yes",
    "on",
)
FILES = (
    "pack.yaml",
    "egress.yaml",
    "repos.yaml",
    "skills.yaml",
    "staging.yaml",
    "helpers.yaml",
    "accounts.yaml",
    "migrate.yaml",
)
SALT = (
    ":",
    "\t",
    "- ",
    "{",
    "}",
    "[",
    "]",
    "&x ",
    "*x",
    "!!",
    "|",
    ">",
    "#",
    "'",
    '"',
    "\x00",
    "%",
    "@",
    "`",
    "? ",
    "---\n",
    "...\n",
)


def _junk(rng: random.Random, depth: int = 0):
    roll = rng.random()
    if depth < 3 and roll < 0.15:
        return [_junk(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    if depth < 3 and roll < 0.3:
        return {str(_junk(rng, 3)): _junk(rng, depth + 1) for _ in range(rng.randint(0, 4))}
    return rng.choice(JUNK)


def _places(value) -> list:
    """Every place in a YAML value: (the container, its key or index)."""
    found = []
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, inner in list(items):
        found.append((value, key))
        found.extend(_places(inner))
    return found


def _mutated(rng: random.Random, text: str) -> str:
    """One damaged copy of a pack file: a value replaced, removed, wrapped or retyped, a key added; or the text itself
    cut, doubled or salted with marks YAML reads."""
    if rng.random() < 0.2:
        cut = rng.randint(0, len(text))
        salt = rng.choice(SALT)
        return rng.choice(
            (text[:cut], text[:cut] + salt + text[cut:], text[cut:], text + text, salt * rng.randint(1, 50), "")
        )
    data = yaml.safe_load(text)
    places = _places(data)
    if not places:
        return yaml.safe_dump(_junk(rng))
    for _ in range(rng.randint(1, 3)):
        parent, key = rng.choice(places)
        how = rng.random()
        try:
            if how < 0.45:
                parent[key] = _junk(rng)
            elif how < 0.6:
                parent[key] = [parent[key]]
            elif how < 0.7:
                parent[key] = {"x": parent[key]}
            elif how < 0.8:
                parent[key] = str(parent[key])
            elif how < 0.9:
                del parent[key]
            elif isinstance(parent, dict):
                parent[str(rng.choice(JUNK))] = parent.get(key)
            else:
                parent.extend(list(parent))
        except (KeyError, IndexError):
            pass  # an earlier mutation of this case removed the place
    try:
        return yaml.safe_dump(data, allow_unicode=True)
    except (yaml.YAMLError, RecursionError):
        return text


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_damaged_pack_loads_or_is_refused_as_a_pack_error_and_nothing_else(pack_file, tmp_path):
    folder = (
        tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    )  # under packs/, where a fixture pack's @skills resolve
    shutil.copytree(os.path.dirname(pack_file), folder, symlinks=True)
    target = str(folder / "pack.yaml")
    assert isinstance(packs.load(target), dict)
    originals = {name: (folder / name).read_text(encoding="utf-8") for name in FILES if (folder / name).is_file()}
    rng = random.Random(SEED + len(pack_file))
    loaded = refused = 0
    for case in range(CASES // len(PACKS)):
        name = rng.choice(sorted(originals))
        damaged = _mutated(rng, originals[name])
        (folder / name).write_text(damaged, encoding="utf-8")
        packs._LOADED.clear()
        started = time.perf_counter()
        try:
            data = packs.load(target)
            assert isinstance(data, dict)
            loaded += 1
        except PackError:
            refused += 1
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"the pack loader raised {type(exc).__name__}: {exc} on case {case} of seed {SEED}, {name} damaged to:\n"
                f"{damaged[:1500]}"
            ) from exc
        finally:
            (folder / name).write_text(originals[name], encoding="utf-8")
        _within(started, "the pack loader", case, damaged)
    packs._LOADED.clear()
    assert isinstance(packs.load(target), dict)  # the pack is whole again
    assert refused > 50 and loaded > 5, f"{refused} refused, {loaded} loaded: the generator no longer makes both kinds"


# ---------- what the generator found, each held by a case of its own ----------


def test_a_command_with_a_nul_byte_is_checked_like_the_line_a_shell_would_run(bare, monkeypatch):
    # found by the generator: resolving a path with a NUL byte raised ValueError out of the fence
    monkeypatch.setenv("COCKPIT_LANE", "worker-1")
    assert egress.check_tool("terminal", {"command": "ls \x00 /tmp/x\x00y"}) == ""
    from cockpitlib.paths import hermes_home

    hidden = os.path.join(hermes_home(), "va\x00ult", "x")
    assert (
        egress.check_tool("terminal", {"command": f"cat {hidden}"}) != ""
    )  # the path a shell would open is the protected one


def _copy(pack_file, tmp_path):
    folder = tmp_path / "packs" / os.path.basename(os.path.dirname(pack_file))
    shutil.copytree(os.path.dirname(pack_file), folder, symlinks=True)
    return folder


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_pack_file_that_is_not_yaml_is_refused_with_the_file_and_the_line(pack_file, tmp_path):
    # found by the generator: yaml's own error left the loader, from pack.yaml and from every file beside it
    folder = _copy(pack_file, tmp_path)
    for name in ("accounts.yaml", "egress.yaml", "pack.yaml"):
        whole = (folder / name).read_text(encoding="utf-8")
        (folder / name).write_text(whole + "\nbroken: [unclosed\n", encoding="utf-8")
        packs._LOADED.clear()
        with pytest.raises(PackError, match=f"{re.escape(name)}, line \\d+: not valid YAML: "):
            packs.load(str(folder / "pack.yaml"))
        (folder / name).write_text(whole, encoding="utf-8")
    packs._LOADED.clear()
    assert packs.load(str(folder / "pack.yaml"))["name"] == os.path.basename(os.path.dirname(pack_file))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_value_of_a_shape_no_check_expected_is_refused_naming_the_check_that_met_it(pack_file, tmp_path):
    # found by the generator: a list or a text where a check expected a mapping raised TypeError or AttributeError
    folder = _copy(pack_file, tmp_path)
    (folder / "helpers.yaml").write_text("helpers: just text\n", encoding="utf-8")
    packs._LOADED.clear()
    with pytest.raises(PackError) as refused:
        packs.load(str(folder / "pack.yaml"))
    said = str(refused.value)
    assert said.startswith("a value in the pack has a shape helpers.check cannot read (AttributeError: ")
    assert said.endswith("`cockpit pack explain <key>` shows the shape a key takes")
    assert refused.value.exit_code == 2


def test_the_kernels_own_errors_leave_the_loader_as_they_are_and_anything_else_is_a_pack_error(tmp_path):
    from cockpitlib.errors import NeedMigrate

    with pytest.raises(PackError, match="missing pack"):
        packs.load(str(tmp_path / "absent" / "pack.yaml"))
    kept = NeedMigrate()
    assert packs._refusal(kept) is kept
    bare_yaml = packs._refusal(yaml.YAMLError("the stream ended"))
    assert isinstance(bare_yaml, PackError) and str(bare_yaml) == "not valid YAML: the stream ended"
    elsewhere = packs._refusal(RuntimeError("boom"))
    assert isinstance(elsewhere, PackError) and str(elsewhere).startswith(
        "a value in the pack has a shape the loader cannot read (RuntimeError: boom)"
    )
