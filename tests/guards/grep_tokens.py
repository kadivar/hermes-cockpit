#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fail when the tree names a place it was used in: a denylist word, or text shaped like one team's own data.

Two layers. The word lists (fixture names, vendor names, and a local list of real names) are matched over the product
folders. The shape rules (a ticket key, a pull-request number, a dated note, a board card id, a home path, a machine
name in a file name, a word of one team's product) are matched over every tracked file and its name. An exception is
one exact line in tests/guards/token-allow.txt, with its reason.
"""

import ast
import io
import os
import re
import subprocess
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN = (
    "README.md",
    "docs",
    "SECURITY.md",
    "SUPPORT.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "AGENTS.md",
    ".agents",
    "CONTRIBUTING.md",
    "CONTRIBUTION-TERMS.md",
    "evals",
    ".github",
    "starter",
    "souls",
    "desktop",
    "kernel",
    "dashboard",
    "skills",
    "packs",
    "hooks",
    "bin",
    "prompts",
    "hermes_bridge",
    "scripts",
    "cron",
)
SKIP_FILES = {
    "ui-vendor-names.txt",
    "forbidden-tokens.txt",
    "fence_markers.txt",
    "token-allow.txt",
    "process-words.txt",
}
# Where the fixture packs' names are expected: the packs themselves and the test data that uses them.
FIXTURE_HOMES = ("packs", "desktop/test", "desktop/node_modules")
COMMITTED = ("forbidden-tokens.txt", "ui-vendor-names.txt")
ALLOW = "tests/guards/token-allow.txt"
WORDS = "tests/guards/process-words.txt"

# ---------- the shape rules ----------

# Keys a fixture may carry, and identifiers of public advisories, which are data the scanner reads.
FIXTURE_KEYS = ("TASK", "ACME", "NORTH", "DEMO")
PUBLIC_KEYS = ("CVE", "GHSA")
# Home folders that name nobody: a package manager's, and the stand-ins the tests use.
NEUTRAL_HOMES = ("linuxbrew", "someone", "owner", "vault", "user", "x")
LINE_RULES = (
    ("ticket-key", re.compile(r"\b(?!(?:%s)-)[A-Z]{2,6}-\d{4,6}\b" % "|".join(FIXTURE_KEYS + PUBLIC_KEYS))),
    ("fixture-key", re.compile(r"\b(?:%s)-\d{5,}\b" % "|".join(FIXTURE_KEYS))),
    ("pr-number", re.compile(r"[A-Za-z0-9_]#\d{3,}\b|\(#\d{4}")),
    ("card-id", re.compile(r"\bt_(?!0000000\d\b)[0-9a-f]{8}\b")),
    ("home-path", re.compile(r"(?:/Users|/home)/(?!(?:%s)\b)[A-Za-z0-9][A-Za-z0-9._-]*" % "|".join(NEUTRAL_HOMES))),
)
NAME_RULES = (("host-filename", re.compile(r"(?:^|/)\.coverage\.|-Laptop|\.local\.pid|\.lan\.pid")),)
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
# Never read by the shape rules: other people's text, generated locks, and the bundle (scripts/check proves it is the
# build of the scanned sources).
SHAPE_SKIP = (
    "LICENSE",
    "THIRD-PARTY-NOTICES.md",
    "desktop/plugin.js",
    "desktop/package-lock.json",
    "requirements.lock",
    "requirements-test.lock",
    ALLOW,
    WORDS,
    "tests/guards/forbidden-tokens.txt",
    "tests/guards/ui-vendor-names.txt",
)
SHAPE_SKIP_FOLDERS = ("desktop/node_modules/", "desktop/vendor/", "dashboard/dist/")
# How a file's comments are found. A dated note is looked for in code, never in prose.
PYTHON, SCRIPT, HASHED = "python", "script", "hashed"
# Where a word of one team's product is looked for.
WORD_HOMES = (
    "kernel/",
    "dashboard/",
    "desktop/",
    "hooks/",
    "cron/",
    "hermes_bridge/",
    "scripts/",
    "bin/",
    "souls/",
    "skills/",
    "prompts/",
    "starter/",
    "docs/",
    "tests/",
    ".agents/",
    "README.md",
    "AGENTS.md",
)


def tokens(path):
    found = []
    if not os.path.isfile(path):
        return found
    for line in open(path, encoding="utf-8"):
        text = line.strip()
        if text and not text.startswith("#"):
            found.append(text)
    return found


def files(skip=(), also=(), root=ROOT):
    """Every file the word lists are read over: what git knows under the scanned places (tracked, or new and not
    ignored), so a scratch file git ignores never fails the guard. A folder that is no checkout is walked instead."""
    known = checkout(root)
    if known is not None:
        places = tuple(name for name in SCAN + tuple(also) if name not in skip)
        for name in known:
            inside = any(name == place or name.startswith(place + "/") for place in places)
            skipped = any(name == place or name.startswith(place + "/") for place in skip)
            path = os.path.join(root, name)
            if inside and not skipped and os.path.basename(name) not in SKIP_FILES and os.path.isfile(path):
                yield path
        return
    for name in SCAN + tuple(also):
        if name in skip:
            continue
        path = os.path.join(root, name)
        if os.path.isfile(path):
            yield path
            continue
        for dirpath, dirs, filenames in os.walk(path):
            dirs[:] = [
                folder
                for folder in dirs
                if os.path.relpath(os.path.join(dirpath, folder), root) not in skip
                and folder not in ("__pycache__", ".tmp")
            ]
            for filename in filenames:
                if filename in SKIP_FILES:
                    continue
                yield os.path.join(dirpath, filename)


def lists(root=ROOT):
    """Adopter names stay out of everything but the fixture packs. Vendor names stay out of everything.

    COCKPIT_EXTRA_TOKENS names a local, uncommitted file of real adopter names, checked like the fixture names.
    """
    found = [
        ("forbidden-tokens.txt", os.path.join(root, "tests", "guards", "forbidden-tokens.txt"), FIXTURE_HOMES, ()),
        ("ui-vendor-names.txt", os.path.join(root, "tests", "guards", "ui-vendor-names.txt"), (), ()),
    ]
    extra = os.environ.get("COCKPIT_EXTRA_TOKENS")
    if extra:
        # Real adopter names do not belong in the tests either.
        found.append((os.path.basename(extra), extra, ("desktop/node_modules",), ("tests",)))
    return found


def checkout(root=ROOT):
    """Every file git knows under the root, as paths from it: the tracked ones, and the new ones it does not ignore, so
    a file is read before its first commit. None when the root is not a checkout."""
    done = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted({name for name in done.stdout.split("\0") if name}) if done.returncode == 0 else None


def tracked(root=ROOT) -> list:
    """The files every layer reads (checkout). Nothing when the root is not a checkout."""
    return checkout(root) or []


def allowed(root=ROOT) -> tuple:
    """(entries, problems) of the allowlist: {(rule, path, line): reason}. An entry without a reason is a problem."""
    entries, problems, reason = {}, [], ""
    path = os.path.join(root, ALLOW)
    if not os.path.isfile(path):
        return entries, problems
    for number, raw in enumerate(open(path, encoding="utf-8"), 1):
        text = raw.strip()
        if not text:
            reason = ""
        elif text.startswith("#"):
            continue
        elif text.startswith("reason:"):
            reason = text[len("reason:") :].strip()
        else:
            rule, _, rest = text.partition(" ")
            where, colon, line = rest.partition(":")
            if not colon or not where:
                problems.append(f"allowlist: {ALLOW}:{number} is not `<rule> <path>:<the exact line>`")
            elif not reason:
                problems.append(f"allowlist: {ALLOW}:{number} has no `reason:` line above it")
            else:
                entries[(rule, where, line.strip())] = reason
    return entries, problems


def kind(name: str, text: str) -> str:
    """How a file's comments are found, or "" for a file that has none this guard reads (prose, data)."""
    first = text.split("\n", 1)[0]
    if name.endswith(".py") or (first.startswith("#!") and "python" in first):
        return PYTHON
    if name.endswith((".js", ".mjs", ".css")):
        return SCRIPT
    if name.endswith((".sh", ".yaml", ".yml", ".toml")) or first.startswith("#!"):
        return HASHED
    return ""


def python_notes(text: str) -> list:
    """(line number, text) of every comment and docstring line of a Python file. A file that does not parse has none."""
    found = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                found.append((token.start[0], token.string))
        tree = ast.parse(text)
    except (SyntaxError, tokenize.TokenError, ValueError):
        return found
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            lines = text.splitlines()[first.lineno - 1 : first.end_lineno]
            found.extend((first.lineno + offset, line) for offset, line in enumerate(lines))
    return found


def script_notes(text: str) -> list:
    """(line number, text) of every comment of a JavaScript or CSS file: `//` to the line's end and `/* … */`, read past
    quoted strings. A quote ends at its line's end, so a regular expression holding one cannot swallow the file."""
    found, line, index, quote = [], 1, 0, ""
    while index < len(text):
        char, pair = text[index], text[index : index + 2]
        if char == "\n":
            line += 1
            if quote in ("'", '"'):
                quote = ""
        elif quote:
            if char == "\\":
                index += 1
                line += text[index : index + 1] == "\n"
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif pair == "//":
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            found.append((line, text[index:end]))
            index = end
            continue
        elif pair == "/*":
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            for offset, part in enumerate(text[index:end].split("\n")):
                found.append((line + offset, part))
            line += text.count("\n", index, end)
            index = end
            continue
        index += 1
    return found


def hashed_notes(text: str) -> list:
    """(line number, text) of every `#` comment of a shell, YAML or TOML file: a `#` that opens the line or follows a space."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        match = re.search(r"(?:^|\s)#.*$", line)
        if match:
            found.append((number, match.group(0)))
    return found


NOTES = {PYTHON: python_notes, SCRIPT: script_notes, HASHED: hashed_notes}


def process_words(root=ROOT) -> list:
    """One pattern per word of the list: the word in any letter case, standing alone or opening a longer word."""
    return [re.compile(r"(?<![A-Za-z])" + re.escape(word), re.IGNORECASE) for word in tokens(os.path.join(root, WORDS))]


def shapes(root=ROOT, names=None) -> list:
    """Every shape-rule hit as (rule, path, line number, line): the rules over each tracked file's lines and its name."""
    found = []
    words = process_words(root)
    for name in tracked(root) if names is None else names:
        if name in SHAPE_SKIP or name.startswith(SHAPE_SKIP_FOLDERS):
            continue
        for rule, pattern in LINE_RULES + NAME_RULES:
            if pattern.search(name):
                found.append((rule, name, 0, name))
        if any(pattern.search(name) for pattern in words):
            found.append(("process-word", name, 0, name))
        try:
            text = open(os.path.join(root, name), encoding="utf-8").read()
        except (UnicodeError, OSError):
            continue
        if "\0" in text:
            continue
        lines = text.splitlines()
        wordy = name.startswith(WORD_HOMES)
        for number, line in enumerate(lines, 1):
            for rule, pattern in LINE_RULES:
                if pattern.search(line):
                    found.append((rule, name, number, line.strip()))
            if wordy and any(pattern.search(line) for pattern in words):
                found.append(("process-word", name, number, line.strip()))
        reader = NOTES.get(kind(name, text))
        dated = sorted({number for number, note in reader(text) if DATE.search(note)}) if reader else []
        found.extend(
            ("dated-note", name, number, lines[number - 1].strip()) for number in dated if number <= len(lines)
        )
    return found


def listed(root=ROOT) -> list:
    """Every word-list hit as (rule, path, line number, line, word). The vendor list is matched in any letter case."""
    found = []
    for label, list_path, skip, also in lists(root):
        words = tokens(list_path)
        if not words:
            found.append((label, "", 0, "", "is empty"))
        vendor = label == "ui-vendor-names.txt"
        rule = "vendor" if vendor else label
        wanted = [word.lower() for word in words] if vendor else words
        for path in files(skip, also, root):
            try:
                text = open(path, encoding="utf-8").read()
            except UnicodeError:
                continue
            body = text.lower() if vendor else text
            if not any(word in body for word in wanted):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                seen = line.lower() if vendor else line
                for index, (word, shown) in enumerate(zip(wanted, words), 1):
                    if word in seen:
                        # a private name is never printed: a run's log may be public. Its place in the list names it
                        shown = shown if label in COMMITTED else f"private name {index}"
                        found.append((rule, os.path.relpath(path, root), number, line.strip(), shown))
    return found


def problems(root=ROOT, names=None) -> list:
    """Every line this guard prints, `<rule>: <what> in <path>:<line>`: exceptions taken out, unused exceptions added."""
    entries, told = allowed(root)
    used = set()

    def excepted(rule, path, line):
        used.add((rule, path, line))
        return (rule, path, line) in entries

    for rule, path, number, line, word in listed(root):
        if not path:
            told.append(f"{rule} {word}")
        elif rule != "vendor" or not excepted(rule, path, line):
            # a fixture name or a real name has no exception: the line would carry the name into the allowlist
            told.append(f"{rule}: {word} in {path}:{number}")
    for rule, path, number, line in shapes(root, names):
        if not excepted(rule, path, line):
            told.append(f"{rule}: {line[:160]} in {path}:{number}" if number else f"{rule}: the file name in {path}")
    for rule, path, line in sorted(set(entries) - used):
        told.append(f"allowlist: unused exception `{rule} {path}:{line[:80]}` in {ALLOW}")
    return told


def main() -> int:
    found = problems()
    if found:
        print("\n".join(found))
        return 1
    print("tokens ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
