# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fail-closed command check. Pack denies are appended. Kernel denies cannot be removed."""

import contextlib
import contextvars
import json
import os
import re
import shlex
import threading
import time

from .paths import worktree_of
from .store import dump_json, read_db

_BEFORE_FORGE_CLI = (
    r"\bgit\s+push\b",
    r"\bgit\s+remote\b",
    r"\bgit\s+config\b.*(pushurl|hooksPath)",
    r"--no-verify",
    r"\bHUSKY=0\b",
)
# A forge's writes outside the outbox, through that forge's own CLI: every built-in forge's rules together
# (forges.cli_deny), so the forge a pack chooses takes no rule out.
_AFTER_FORGE_CLI = (
    # Skipping the hooks that guard a commit.
    r"-c\s+core\.hooksPath",
    r"\bHUSKY_SKIP_HOOKS\b",
    # The vault, the keychain, and the board stay out of a lane's reach.
    r"\bsecurity\s+(find-generic-password|find-internet-password|dump-keychain|export)\b",
    r"\bsecret-tool\s+lookup\b",
    r"\bhermes\b(?:\s+(?:-p|--profile)\s+\S+)?\s+vault\s+(add|rm|remove)\b",
    r"\bHERMES_DELEGATED_CHILD_CONTEXT\s*=",
    r"\bhermes\b[^|;&]*\bkanban\s+comment\b[^|;&]*--author\b",
    r"\bkanban\.db\b",
    r"\bhermes\b[^|;&]*\bcron\s+(create|add|edit|remove|rm|delete|pause|resume|run)\b",
    r"\bcockpit\s+publish\b",
    r"\bcockpit\s+apply\b",
    r"\bcockpit\s+setup\b",
    # An update replaces the code every seat runs, and a move says where it comes from: the human's acts.
    r"\bcockpit\s+update\s+(apply|rollback|rehome)\b",
)


def _kernel_deny() -> tuple:
    from .forges import cli_deny

    return _BEFORE_FORGE_CLI + cli_deny() + _AFTER_FORGE_CLI


KERNEL_DENY = _kernel_deny()
WIDE = {"/", "~", "~/", "$HOME", "${HOME}", "$HOME/", "${HOME}/", "/home", "/Users", "/Volumes"}
SEARCHERS = {"find", "rg", "fd", "grep", "du", "tree"}


def wide_root(path: str) -> bool:
    """The machine root, a home folder, or every home: too wide for a search."""
    text = str(path or "").strip().strip("'\"")
    if text in WIDE or text.startswith("/Volumes"):
        return True
    home = os.path.expanduser("~").rstrip("/")
    expanded = os.path.expandvars(os.path.expanduser(text)).rstrip("/") or "/"
    if expanded in ("/", home):
        return True
    parent = os.path.dirname(expanded)
    return parent in ("/home", "/Users") or expanded in ("/home", "/Users")


def _wide_search(command: str) -> bool:
    here = ""
    for segment in re.split(r"&&|\|\||;|\|", command):
        words = segment.split()
        if not words:
            continue
        tool = os.path.basename(words[0])
        if tool == "cd":
            here = words[1] if len(words) > 1 else "~"
            continue
        listing = tool == "ls" and any(
            word.startswith("-") and not word.startswith("--") and "R" in word for word in words[1:]
        )
        recursive = (
            listing
            or tool in SEARCHERS
            or (tool == "grep" and any(word.startswith("-") and "r" in word for word in words[1:]))
        )
        if not recursive:
            continue
        roots = [word for word in words[1:] if not word.startswith("-")]
        if tool in ("grep", "rg") and roots:
            roots = roots[1:]
        roots = roots or ["."]
        for root in roots:
            if wide_root(root) or (root in (".", "./") and here and wide_root(here)):
                return True
    return False


# Writes to the forge or the tracker that skip the outbox: a write verb or a body, aimed at their host.
HTTP_WRITE_FLAGS = (
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "--json",
    "-F",
    "--form",
    "-T",
    "--upload-file",
)


def _http_write(text: str, hosts) -> bool:
    if not hosts:
        return False
    for segment in re.split(r"&&|\|\||;|\|", text):
        words = segment.split()
        if not words:
            continue
        tool = os.path.basename(words[0])
        aimed = any(any(host in word for host in hosts) for word in words[1:])
        if not aimed:
            continue
        if tool == "curl":
            method = re.search(r"(?:-X|--request)\s*=?\s*['\"]?(POST|PUT|PATCH|DELETE)\b", segment, re.IGNORECASE)
            if method or any(
                word == flag or word.startswith(flag + "=") for word in words for flag in HTTP_WRITE_FLAGS
            ):
                return True
        if tool == "wget" and any(
            word.startswith(("--post-data", "--post-file", "--method", "--body-data", "--body-file")) for word in words
        ):
            return True
        if tool in ("http", "https", "xh", "xhs"):
            verbs = [word for word in words[1:] if not word.startswith("-")]
            if verbs and verbs[0].upper() in ("POST", "PUT", "PATCH", "DELETE"):
                return True
            if any(re.match(r"^[^:=@\s/]+(=|:=|@)", word) for word in verbs[1:]):
                return True
    return False


# A write to a staging origin, as a shell line or as script code: (method, literal URL or "").
CODE_FETCH = re.compile(r"fetch\(\s*(['\"`])([^'\"`]+)\1\s*,\s*\{[^}]*?method\s*:\s*['\"`](\w+)['\"`]", re.IGNORECASE)
CODE_CLIENT = re.compile(
    r"\b(?:requests|httpx|axios|session|client)\.(post|put|patch|delete)\(\s*(['\"`])([^'\"`]+)\2", re.IGNORECASE
)
CODE_LOOSE = re.compile(
    r"\b(?:requests|httpx|axios|session|client)\.(post|put|patch|delete)\(\s*(?!['\"`])|"
    r"method\s*:\s*['\"`](POST|PUT|PATCH|DELETE)['\"`]",
    re.IGNORECASE,
)
# Never written by a lane, plan or no plan. The pack adds testflow.never_write.
KERNEL_NEVER_WRITE = (r"(?i)^DELETE\b", r"(?i)/(drop|truncate|purge|wipe)(/|\b)", r"(?i)\bbulk\b")


def http_writes(text: str) -> list:
    found = []
    for segment in re.split(r"&&|\|\||;|\|", text):
        words = [word.strip("'\"") for word in segment.split()]
        if not words:
            continue
        tool = os.path.basename(words[0])
        url = next((word for word in words[1:] if word.startswith(("http://", "https://"))), "")
        method = ""
        if tool == "curl":
            given = re.search(r"(?:-X|--request)\s*=?\s*['\"]?([A-Za-z]+)", segment)
            method = given.group(1).upper() if given else ""
            if not method and any(
                word == flag or word.startswith(flag + "=") for word in words for flag in HTTP_WRITE_FLAGS
            ):
                method = "POST"
        if tool == "wget":
            given = next((word.split("=", 1)[1] for word in words if word.startswith("--method=")), "")
            method = given.upper() or (
                "POST" if any(word.startswith(("--post-data", "--post-file")) for word in words) else ""
            )
        if tool in ("http", "https", "xh", "xhs"):
            rest = [word for word in words[1:] if not word.startswith("-")]
            if rest and rest[0].upper() in ("POST", "PUT", "PATCH", "DELETE"):
                method = rest[0].upper()
            elif any(re.match(r"^[^:=@\s/]+(=|:=|@)", word) for word in rest[1:]):
                method = "POST"
        if method and method not in ("GET", "HEAD", "OPTIONS"):
            found.append((method, url))
    literal = []
    for match in CODE_FETCH.finditer(text):
        literal.append((match.group(3).upper(), match.group(2)))
    for match in CODE_CLIENT.finditer(text):
        literal.append((match.group(1).upper(), match.group(3)))
    loose = len(CODE_LOOSE.findall(text)) - len(literal)
    found += [item for item in literal if item[0] not in ("GET", "HEAD", "OPTIONS")]
    found += [("WRITE", "")] * max(0, loose)
    return found


def _staging_write(texts, pack) -> str:
    """A lane writes to a staging origin only as the accepted test plan lists it: one write, to one literal URL,
    never a delete or a never-write path."""
    origins = ((pack or {}).get("egress") or {}).get("destructive_http") or []
    if not origins or not os.environ.get("COCKPIT_LANE"):
        return ""
    staged = []
    for text in texts:
        aimed = any(re.search(origin, text) for origin in origins)
        for method, url in http_writes(text):
            if (url and any(re.search(origin, url) for origin in origins)) or (not url and aimed):
                staged.append((method, url))
    if not staged:
        return ""
    if len(staged) > 1:
        return "one write to staging per call"
    method, url = staged[0]
    if not url or method == "WRITE":
        return "a write to staging names one literal URL"
    line = f"{method} {url}"
    never = list(KERNEL_NEVER_WRITE) + list((((pack or {}).get("testflow") or {}).get("never_write")) or [])
    if any(re.search(pattern, line) for pattern in never):
        return "never written: " + line
    from .acts import run_listed
    from .errors import CockpitError
    from .skill_log import current_ticket

    try:
        run_listed(current_ticket(), line, pack)
    except CockpitError as exc:
        return f"{exc}: {line}"
    return ""


def forge_hosts(pack) -> list:
    """The forge's hosts (every built-in forge's own, and the host of the forge this pack publishes to) and the pack's
    tracker host. A pack's forge.kind or forge.host adds a host and takes none out."""
    from urllib.parse import urlsplit

    from . import forges
    from .pack import tracker_url

    hosts = forges.default_hosts()
    try:
        chosen = forges.make(pack or {}).hosts()
    except Exception:  # noqa: BLE001 - a pack that names no forge the kernel has: the built-in hosts stay fenced
        chosen = (
            [str(((pack or {}).get("forge") or {}).get("host") or "")]
            if isinstance((pack or {}).get("forge"), dict)
            else []
        )
    hosts += [host for host in chosen if host and host not in hosts]
    tracker = urlsplit(str(tracker_url(pack) or "")).hostname
    if tracker:
        hosts.append(tracker)
    return hosts


COMMIT_VALUE_FLAGS = (
    "-m",
    "-F",
    "-C",
    "-c",
    "-t",
    "--message",
    "--file",
    "--author",
    "--date",
    "--template",
    "--reuse-message",
    "--reedit-message",
    "--fixup",
    "--squash",
    "--cleanup",
    "--trailer",
    "--pathspec-from-file",
)


def _commit_skips_hooks(text: str) -> bool:
    """git commit -n (alone or in a cluster such as -anm): the hooks that guard a commit do not run."""
    import shlex

    for segment in re.split(r"&&|\|\||;|\|", text):
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        if "git" not in [os.path.basename(word) for word in words[:1]] or "commit" not in words:
            continue
        rest = words[words.index("commit") + 1 :]
        skip = False
        for word in rest:
            if skip:
                skip = False
                continue
            if word.startswith("--"):
                skip = word in COMMIT_VALUE_FLAGS
                continue
            if word.startswith("-") and len(word) > 1:
                if "n" in word[1:].split("m", 1)[0] or (
                    "n" in word[1:] and not any(flag in word[1:] for flag in "mFCct")
                ):
                    return True
                skip = word[-1] in "mFCct"
    return False


# The rule behind the last refusal. The verdict stays the bare word `blocked` that every caller compares; the message a lane
# sees names the rule (`explained`), so it takes the allowed route instead of retrying variants of a refused command.
# Per thread: the gateway answers hook calls concurrently, and one call must not show another's rule.
_WHY = threading.local()


def _blocked(why: str) -> str:
    _WHY.text = why
    return "blocked"


def explained(reason: str) -> str:
    """The message for a refusal: `blocked` with the rule that refused it; any other reason as it is."""
    why = getattr(_WHY, "text", "")
    if reason == "blocked" and why:
        return f"blocked: {why}"
    return reason


def check(command: str, extra_deny=(), production_hosts=(), sacred=(), infra_paths=()) -> str:
    """Return a block reason, or '' when the command may run."""
    if command is None:
        return "unreadable tool call"
    text = str(command)
    for pattern in list(KERNEL_DENY) + list(extra_deny or []):
        if re.search(pattern, text):
            return _blocked(f"a denied command (rule {pattern[:80]})")
    behind = _git_behind_options(text)
    if behind:
        return _blocked(behind)
    if _wide_search(text):
        return _blocked("a search of a whole disk or home folder: search one project root")
    if _commit_skips_hooks(text):
        return _blocked("a commit that skips the git hooks")
    for pattern in production_hosts or []:
        if pattern and re.search(pattern, text):
            return _blocked(f"a production host ({pattern[:60]})")
    for path in infra_paths or []:
        if path and str(path) in text:
            return _blocked(f"an infrastructure path ({path})")
    for name in sacred or []:
        if name and re.search(rf"\b(docker|kubectl|helm)\b[\s\S]*\b{re.escape(str(name))}\b", text):
            return _blocked(f"a container of the main stack ({name})")
    return ""


def _git_behind_options(text: str) -> str:
    """Why a git line is refused though the kernel's patterns do not see it, or "": a push, a changed remote, or a
    setting that redirects or disguises a push, read from git's argv."""
    if _git_push(text):
        return "a denied command (git push, behind git's own options)"
    rewired = _git_rewires(text)
    return f"a denied command ({rewired})" if rewired else ""


def kernel_refusal(command, pack=None) -> str:
    """The kernel's own refusal of a command line, or '': its deny list, the forge command line's write rules, a push,
    a changed remote or a push setting behind git's options, a commit that skips its hooks, and an HTTP write to the
    forge or the tracker. No pack list is read, so nothing a pack lists (allowed.reads above all) answers for it."""
    if command is None:
        return "unreadable tool call"
    text = str(command)
    for pattern in KERNEL_DENY:
        if re.search(pattern, text):
            return _blocked(f"a denied command (rule {pattern[:80]})")
    behind = _git_behind_options(text)
    if behind:
        return _blocked(behind)
    if _commit_skips_hooks(text):
        return _blocked("a commit that skips the git hooks")
    if _http_write(text, forge_hosts(pack)):
        return _blocked("a write to the forge over HTTP: publishing goes through the outbox")
    return ""


def pack_rules():
    """Denies from the bound pack. A missing pack leaves only the kernel denies."""
    try:
        from .pack import load
        from .paths import pack_path

        egress = load(pack_path()).get("egress") or {}
    except Exception:  # noqa: BLE001 - a pack that cannot be read adds no rule of its own
        return [], [], [], []
    return (
        list(egress.get("terminal_deny") or []),
        list(egress.get("production_hosts") or []),
        list(egress.get("sacred") or []),
        list(egress.get("infra_paths") or []),
    )


def _segments(command: str) -> list:
    return [part.strip() for part in re.split(r"&&|\|\||;|\|", str(command or "")) if part.strip()]


def _allowed(command: str, reads) -> bool:
    """A line whose every part is an allowed read is past the pack's own denies (check_bound holds it to the kernel's
    first). A later refused command or host in the same line is not."""
    parts = _segments(command)
    allowed = {str(item).strip() for item in (reads or []) if str(item).strip()}
    if not parts or not allowed:
        return False
    return all(part in allowed for part in parts)


def _perl_inplace(word: str) -> bool:
    """perl -i, -i.bak, and clustered flags such as -pi rewrite the file."""
    if word == "-i" or word.startswith("-i"):
        return True
    if len(word) < 2 or not word.startswith("-") or word.startswith("--"):
        return False
    return "i" in word[1:].split(".", 1)[0]


def _editor_target(words: list) -> str:
    """The file an in-place editor rewrites. A filter that only prints is not a write."""
    tool = os.path.basename(words[0])
    if tool == "dd":
        for word in words[1:]:
            if word.startswith("of="):
                return word.split("=", 1)[1]
        return ""
    if tool == "truncate":
        args = [word for word in words[1:] if not word.startswith("-")]
        return args[-1] if args else ""
    if tool not in ("sed", "perl"):
        return ""
    inplace = False
    args = []
    for word in words[1:]:
        if tool == "sed" and (word == "-i" or word.startswith("-i") or word.startswith("--in-place")):
            inplace = True
            continue
        if tool == "perl" and _perl_inplace(word):
            inplace = True
            continue
        if word.startswith("-"):
            continue
        args.append(word)
    if not inplace or not args:
        return ""
    return args[-1]


# A write whose folder the hook cannot follow: a relative target after a directory change that may not have happened (a
# cd that may fail before `;`, cd -, a bare cd, pushd/popd, a cd in a pipe, the background or a subshell), or a variable the
# line redefines. It is refused with its reason.
UNRESOLVED = "\0unresolved:"
_OPERATORS = {";", "&&", "||", "|", "&", "|&", ";;"}
_REDIRECTS = {">", ">>", "&>", "&>>", ">|", "<>"}
_WRAPPERS = {
    "sudo",
    "xargs",
    "env",
    "timeout",
    "nice",
    "ionice",
    "stdbuf",
    "command",
    "builtin",
    "exec",
    "time",
    "nohup",
}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_RUNNERS = _SHELLS | {"tee", "eval"}
_SUBSTITUTION = re.compile(r"\$\(((?:[^()]|\([^()]*\))*)\)|`([^`]*)`")
# shell punctuation inside quotes is data: masked before the line is split, restored in its words afterwards. Inside single
# quotes $ and ` are masked too: no $( ) or backtick there ever runs.
_MASKED = {char: chr(0xE000 + index) for index, char in enumerate(";&|<>()#")}
_LITERAL = {char: chr(0xE010 + index) for index, char in enumerate("$`")}
_UNMASK = {masked: char for table in (_MASKED, _LITERAL) for char, masked in table.items()}
_HARMLESS = re.compile(r"/dev/(?:null|stdout|stderr|fd/\d+)")  # a write there changes no file
_DEPTH = 8  # inner shell lines read inside one another before the line is refused as unreadable


# In code most `>` are arrows, comparisons and markup. A target counts unless it reads as code: a number or bare name
# (`> 0`, `ul > li`). `>` in the lookbehind keeps `=>>` from matching at its second `>`.
CODE_REDIRECT = re.compile(
    r"""(?<![=>-])>>?\s+((?!\S*</?\w+[^<\s]*>)(?=\\*['"~/]|\$(?!\()|\{\w|\.\w|\S*/|[\w-]+(?:\.[\w-]+)*\.[A-Za-z0-9]{1,5}(?:[\s;&|'"]|$))\S+)"""
)


def _legacy_targets(command: str, code: bool = False) -> list:
    """Every path a line writes, as the kernel read it before the shell reader (whitespace after `>`, tee first in a
    segment, a cd followed along the line). Code (execute_code, a browser script) is read this way: it is no shell line."""
    # a line that changes folder can write any bare name relative to it, so it keeps the strict reading
    redirect = CODE_REDIRECT if code and not re.search(r"\bcd\s", command) else r">>?\s+(\S+)"
    found = []
    cwd = ""
    for segment in re.split(r"&&|\|\||;|\|", str(command or "")):
        words = segment.split()
        if not words:
            continue
        tool = os.path.basename(words[0])
        if tool == "cd" and len(words) > 1:
            cwd = _from(cwd, words[1])
            continue
        targets = [match.group(1) for match in re.finditer(redirect, segment)]
        edited = _editor_target(words)
        if edited:
            targets.append(edited)
        args = [word for word in words[1:] if not word.startswith("-")]
        if tool == "tee":
            targets.extend(args)
        elif tool in ("cp", "mv", "install", "rsync", "ln") and args:
            targets.append(args[-1])
        found.extend(_from(cwd, target) for target in targets)
    return found


def _mask(line: str) -> str:
    """The line with every shell operator character inside quotes (or escaped) replaced by a private stand-in."""
    # an arithmetic $(( )) or (( )) holds no redirection or here-document: 1<<2 is a shift
    line = re.sub(
        r"\(\((.*?)\)\)", lambda match: "((" + "".join(_MASKED.get(char, char) for char in match.group(1)) + "))", line
    )
    out, quote, escaped = [], "", False
    for char in line:
        if escaped:
            out.append(_MASKED.get(char, char))
            escaped = False
            continue
        if char == "\\" and quote != "'":
            out.append(char)
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
                out.append(char)
                continue
            out.append((_LITERAL.get(char) if quote == "'" else None) or _MASKED.get(char, char))
            continue
        if char in ("'", '"'):
            quote = char
        if char == "#" and out and not out[-1].isspace() and out[-1] not in ";&|<>(":
            char = _MASKED[char]  # a # inside a word (a#b, $#, ${#x}, $(x)#y) is part of it, not a comment
        out.append(char)
    return "".join(out)


def _tokens(line: str) -> list:
    """The words and operators of one shell line as the shell splits them, a comment ending it. Operator characters that
    were quoted stay masked, so a quoted '>' never reads as a redirection; _plain restores a word."""
    lexer = shlex.shlex(_mask(line), posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    return list(lexer)


def _plain(token: str, literal: bool = False) -> str:
    """A word with its quoted characters restored; with `literal`, a single-quoted $ or ` stays masked."""
    return "".join(char if literal and char in _LITERAL.values() else _UNMASK.get(char, char) for char in token)


def _after_wrappers(words: list) -> int:
    """Where the real command starts behind sudo, xargs, env, timeout -s KILL 5, nice -n 10 ...: past every wrapper, its
    options, an option's value, an assignment and a duration (tee, a shell or eval always start it). -1 when nothing does."""
    for index, word in enumerate(words):
        tool = os.path.basename(word)
        if tool in _RUNNERS:
            return index
        option_value = index > 0 and words[index - 1].startswith("-") and "=" not in words[index - 1]
        if not (
            tool in _WRAPPERS or word.startswith("-") or option_value or re.fullmatch(r"[\w.]+=.*|\d+[smhd]?", word)
        ):
            return index
    return -1


def _tee_targets(words: list) -> list:
    """tee's files when tee is the command, alone or behind a wrapper."""
    index = _after_wrappers(words)
    if index < 0 or os.path.basename(words[index]) != "tee":
        return []
    return [arg for arg in words[index + 1 :] if not arg.startswith("-")]


def _inner_lines(words: list, literal: list) -> list:
    """The shell lines a command runs itself: `sh -c '…'` / `bash -lc -- '…'`, `eval …`, and every $( ) or backtick in a
    word outside single quotes (`literal` is the words with single-quoted $ and ` still masked)."""
    inner = []
    tool = os.path.basename(words[0]) if words else ""
    if tool in _SHELLS:
        rest = [word for word in words[1:] if word != "--"]
        for position in range(len(rest) - 1):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", rest[position]):
                inner.append(rest[position + 1])
                break
    if tool == "eval":
        inner.append(" ".join(words[1:]))
    for word in literal:
        inner.extend(_plain(first or second) for first, second in _SUBSTITUTION.findall(word))
    return [line for line in inner if line.strip()]


def _copy_target(tool: str, words: list) -> str:
    """Where cp, mv, install, rsync or ln writes: its -t / --target-directory folder, else its last argument."""
    if tool not in ("cp", "mv", "install", "rsync", "ln"):
        return ""
    for index, word in enumerate(words):
        if word in ("-t", "--target-directory") and index + 1 < len(words):
            return words[index + 1]
        if word.startswith("--target-directory="):
            return word.split("=", 1)[1]
    args = [word for word in words[1:] if not word.startswith("-")]
    return args[-1] if args else ""


def _lines(text: str) -> list:
    """The token lists of a shell text, one per line as the shell reads it: a backslash-newline continues the line, a
    here-document's body is data until its delimiter (<<- strips leading tabs only). ValueError on an unbalanced quote."""
    return [tokens for tokens, _raw, _inner in _read_lines(text)]


_BACKTICKS = re.compile(r"`([^`]*)`")


def _read_lines(text: str, lenient: bool = False) -> list:
    """One (tokens, raw line, lifted backtick lines) per logical line. Strict: ValueError ends the reading. Lenient (the
    git check): bash runs every complete line before the one with the unbalanced quote, so a line that does not parse is
    kept as (None, raw, []) and the rest are read; backtick groups are lifted out first, so `` echo `git push` `` is one
    inner line rather than words split around the backticks."""
    entries, pending, carry = [], [], ""

    def read(line: str) -> None:
        inner = _BACKTICKS.findall(line) if lenient else []
        source = _BACKTICKS.sub("x", line) if lenient else line
        try:
            tokens = _tokens(source)
        except ValueError:
            if not lenient:
                raise
            entries.append((None, line, inner))
            return
        entries.append((tokens, line, inner))
        pending.extend(
            (_plain(tokens[index + 1]), token == "<<-")
            for index, token in enumerate(tokens[:-1])
            if token in ("<<", "<<-")
        )

    for line in text.split("\n"):
        if pending:
            if (line.lstrip("\t") if pending[0][1] else line) == pending[0][0]:
                pending.pop(0)
            continue
        line, carry = carry + line, ""
        if re.search(r"(?<!\\)(?:\\\\)*\\$", line):
            carry = line[:-1]
            continue
        read(line)
    if carry:
        read(carry)
    return entries


def _simple_commands(tokens: list) -> list:
    """One (items, operator after it) per simple command of a line: $( ), ( ) and { ( } each start a command of their own."""
    segments, current = [], []
    for token in tokens:
        if token in _OPERATORS or token in ("(", ")"):
            segments.append((current, token))
            current = []
        else:
            current.append(token)
    segments.append((current, "\n"))
    return segments


def _command_words(items: list) -> tuple:
    """A simple command's words (still masked) and the files its redirections write."""
    words, targets, index = [], [], 0
    while index < len(items):
        token = items[index]
        if token in _REDIRECTS or token in ("<", "<<", "<<-", "<<<", ">&", "<&"):
            target = items[index + 1] if index + 1 < len(items) else ""
            if target and (token in _REDIRECTS or (token == ">&" and not re.fullmatch(r"\d+-?|-", target))):
                targets.append(_plain(target))  # >&2 duplicates a descriptor; >& file writes the file
            if words and re.fullmatch(r"\d+", words[-1]):
                words.pop()  # the descriptor of 2>, not an argument
            index += 2
            continue
        if token not in ("(", ")"):
            words.append(token)
        index += 1
    return words, targets


# Words the shell reads before a command, not as its name: `{ git push; }`, `if git push; then`, `! git push`.
_KEYWORDS = {
    "{",
    "}",
    "!",
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "while",
    "until",
    "do",
    "done",
    "case",
    "esac",
    "coproc",
    "time",
}
UNREADABLE = "\0unreadable"


def _argvs(text: str, depth: int = 0) -> list:
    """Every command a shell text runs, as argv behind its wrappers (sudo, env, X=1 …) and the shell's own keywords, the
    inner lines of `sh -c`, eval, $( ) and backticks included. A line that does not parse (an unbalanced quote) is kept as
    [UNREADABLE, the line]: the lines before it ran, and the caller decides what an unreadable line means. Nesting past
    _DEPTH yields nothing."""
    if depth > _DEPTH:
        return []
    found = []
    for tokens, raw, lifted in _read_lines(str(text or ""), lenient=True):
        for inner in lifted:
            found.extend(_argvs(inner, depth + 1))
        if tokens is None:
            found.append([UNREADABLE, raw])
            continue
        for items, _after in _simple_commands(tokens):
            words, _targets = _command_words(items)
            plain = [_plain(word) for word in words]
            literal = [_plain(word, literal=True) for word in words]
            while plain and plain[0] in _KEYWORDS:
                plain, literal = plain[1:], literal[1:]
            if not plain:
                continue
            start = max(_after_wrappers(plain), 0)
            # a wrapper's bare flag reads the next word as its value (`env -i git push`, `xargs -0 git push`): git itself
            # is never a value, so the command starts at git when the wrappers would have skipped it
            first_git = next((index for index, word in enumerate(plain) if os.path.basename(word) == "git"), None)
            if first_git is not None and first_git < start:
                start = first_git
            argv = plain[start:]
            found.append(argv)
            for inner in _inner_lines(argv, literal):
                found.extend(_argvs(inner, depth + 1))
    return found


# git's own options before the verb: these take a value (attached, after `=`, or the next word); any other -x/--x is a flag.
_GIT_VALUE_OPTIONS = (
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--config-env",
    "--attr-source",
    "--super-prefix",
    "--list-cmds",
)
# `git tag` / `git branch` with only these read; with a name or one of the moving options they change the repository.
# Only these put tag/branch in list mode with a name beside them; -v, --sort, --format, --abbrev … still create the ref.
_GIT_READ_OPTIONS = {
    "tag": {"-l", "--list", "-n", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged"},
    "branch": {
        "-l",
        "--list",
        "-a",
        "--all",
        "-r",
        "--remotes",
        "--contains",
        "--no-contains",
        "--merged",
        "--no-merged",
        "--points-at",
        "--show-current",
    },
}
_GIT_MOVE_OPTIONS = {
    "tag": {
        "-a",
        "--annotate",
        "-s",
        "--sign",
        "-u",
        "--local-user",
        "-m",
        "--message",
        "-F",
        "--file",
        "-e",
        "--edit",
        "-d",
        "--delete",
        "-f",
        "--force",
        "--cleanup",
        "--create-reflog",
    },
    "branch": {
        "-d",
        "-D",
        "--delete",
        "-m",
        "-M",
        "--move",
        "-c",
        "-C",
        "--copy",
        "-f",
        "--force",
        "-u",
        "--set-upstream-to",
        "--unset-upstream",
        "-t",
        "--track",
        "--no-track",
        "--edit-description",
        "--create-reflog",
        "--recurse-submodules",
    },
}


def _git_argv(argv: list) -> list:
    """The argv from `git` on, or [] for any other command."""
    while (
        argv and os.path.basename(argv[0]) in _WRAPPERS
    ):  # a wrapper that stayed in front (`exec git …` behind another)
        argv = argv[1:]
    return argv if argv and os.path.basename(argv[0]) == "git" else []


def _git_verb(argv: list) -> tuple:
    """git's verb and the arguments after it, behind the global options; ("", []) for any other command or no verb."""
    argv = _git_argv(argv)
    if not argv:
        return "", []
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        index += (
            2 if argv[index] in _GIT_VALUE_OPTIONS else 1
        )  # `-C dir` takes the next word; -Cdir, --git-dir=x, -p do not
    if index >= len(argv):
        return "", []
    return argv[index], argv[index + 1 :]


def _git_push(text: str) -> bool:
    """A push the kernel's pattern does not see, because git's own options stand between `git` and the verb (`git -C dir
    push`, `-c k=v`, `--git-dir=…`, `--no-pager`): the argv is read, behind wrappers and inside inner shell lines. A
    line the fence cannot read is a push when it names git and then push."""
    for argv in _argvs(text):
        if argv[0] == UNREADABLE:
            if re.search(r"(?<![\w/.-])git(?![\w-])[\s\S]*\bpush\b", argv[1]):
                return True
            continue
        if _git_verb(argv)[0] in _GIT_PUSH_VERBS:
            return True
    return False


_GIT_PUSH_VERBS = ("push", "send-pack")  # send-pack is the push itself, without the porcelain
_REMOTE_CHANGES = ("add", "set-url", "rename", "remove", "rm")
_CONFIG_VERBS = {
    "get": "read",
    "list": "read",
    "set": "write",
    "unset": "write",
    "rename-section": "section",
    "remove-section": "section",
    "edit": "edit",
}
_CONFIG_OPTIONS = {
    "--get": "read",
    "--get-all": "read",
    "--get-regexp": "read",
    "--get-urlmatch": "read",
    "--get-color": "read",
    "--get-colorbool": "read",
    "--list": "read",
    "-l": "read",
    "--add": "write",
    "--replace-all": "write",
    "--unset": "write",
    "--unset-all": "write",
    "--rename-section": "section",
    "--remove-section": "section",
    "-e": "edit",
    "--edit": "edit",
}
_CONFIG_VALUE_OPTIONS = ("-f", "--file", "--blob", "-t", "--type", "--default", "--comment")
# The settings that send a push somewhere else, run another program for it, or give it another name; and their sections.
_PUSH_SETTING = re.compile(
    r"(?i)^(alias\..+|core\.(sshcommand|hookspath)|url\..+\.(insteadof|pushinsteadof)|remote\..+\.(url|pushurl))$"
)
_PUSH_SECTION = re.compile(r"(?i)^(alias|url\..+|remote\..+)$")
_UNREADABLE_CHANGE = re.compile(
    r"(?i)(?<![\w/.-])git(?![\w-])[\s\S]*(\bremote\b[\s\S]*(?<![\w.-])(add|set-url|rename|remove|rm)(?![\w.-])|"
    r"\bconfig\b[\s\S]*(\balias\.|sshcommand|hookspath|insteadof|pushurl|\bremote\.\S+\.url\b|--edit\b|-section\b))"
)


def _git_settings(argv: list) -> list:
    """The names of the settings a git command line gives itself before the verb: `-c name=value`, `--config-env
    name=ENV`. [] for any other command."""
    argv = _git_argv(argv)
    names, index = [], 1
    while index < len(argv) and argv[index].startswith("-"):
        word = argv[index]
        value = ""
        if word in ("-c", "--config-env"):
            value = argv[index + 1] if index + 1 < len(argv) else ""
        elif word.startswith("--config-env="):
            value = word.split("=", 1)[1]
        if value:
            names.append(value.split("=", 1)[0])
        index += 2 if word in _GIT_VALUE_OPTIONS else 1
    return names


def _config_write(args: list) -> str:
    """The push setting a `git config` invocation writes, unsets, renames or opens for editing, or "". Reading (--get,
    --list, a name alone) and writing any other setting is none."""
    names, modes, skip = [], set(), False
    for arg in args:
        if skip:
            skip = False
            continue
        name = arg.split("=", 1)[0] if arg.startswith("--") else arg
        if name in _CONFIG_OPTIONS:
            modes.add(_CONFIG_OPTIONS[name])
        elif name in _CONFIG_VALUE_OPTIONS:
            skip = "=" not in arg
        elif not arg.startswith("-"):
            names.append(arg)
    if names and names[0] in _CONFIG_VERBS and "section" not in modes:
        modes.add(_CONFIG_VERBS[names.pop(0)])
    if "edit" in modes:
        return "any setting (--edit)"
    if "section" in modes:
        return next((name for name in names if _PUSH_SECTION.match(name)), "")
    if "write" not in modes and ("read" in modes or len(names) < 2):
        return ""
    return names[0] if names and _PUSH_SETTING.match(names[0]) else ""


def _git_rewires(text: str) -> str:
    """What a git line changes about where or how a push goes, or "": `git remote add|set-url|rename|remove`, a `git
    config` write to a push setting, or an alias given on the command line (`git -c alias.p=push p`), each read from
    git's argv behind its own options, wrappers and inner shell lines. A line the fence cannot read is one when it
    names git and then the change."""
    for argv in _argvs(text):
        if argv[0] == UNREADABLE:
            if _UNREADABLE_CHANGE.search(argv[1]):
                return "git remote or git config on a line the fence cannot read: fix the quoting"
            continue
        if any(name.lower().startswith("alias.") for name in _git_settings(argv)):
            return "git -c alias: an alias on the command line can be a push"
        verb, args = _git_verb(argv)
        if verb == "remote":
            change = next((arg for arg in args if not arg.startswith("-")), "")
            if change in _REMOTE_CHANGES:
                return f"git remote {change}, behind git's own options"
        if verb == "config":
            setting = _config_write(args)
            if setting:
                return f"git config changes {setting[:60]}"
    return ""


def _option_name(arg: str) -> str:
    """`--sort=x` → --sort, `-n5` → -n, a word → ""."""
    if arg.startswith("--"):
        return arg.split("=", 1)[0]
    if arg.startswith("-") and len(arg) > 1:
        return arg[:2]
    return ""


def _has_flag(args: list, flag: str) -> bool:
    """`-b` as its own word, attached (-bname) or clustered (-qb); `--orphan` as a word or `--orphan=x`."""
    for arg in args:
        if arg == "--":  # what follows are paths and names, whatever they look like
            return False
        if arg == flag or (flag.startswith("--") and arg.startswith(flag + "=")):
            return True
        if not flag.startswith("--") and arg.startswith("-") and not arg.startswith("--") and flag[1] in arg[1:]:
            return True
    return False


def _git_mutates(verb: str, args: list) -> bool:
    """`git tag` / `git branch`: a moving option, or a name without a listing option, changes the repository."""
    names = [_option_name(arg) for arg in args]
    if any(name in _GIT_MOVE_OPTIONS[verb] for name in names if name):
        return True
    if any(name in _GIT_READ_OPTIONS[verb] for name in names if name):
        return False
    return any(not name and arg != "--" for name, arg in zip(names, args))


def git_moves(command: str, entries) -> str:
    """The git_deny entry a shell text matches, or "". An entry is a verb (`commit`) or a verb with the flags that make it
    a move (`checkout -b`): the verb is compared exactly (merge-base is not merge), options between `git` and the verb are
    skipped, and `tag`/`branch` alone mean their moving forms. Aliases (`git co`) are not resolved."""
    for argv in _argvs(command):
        if argv[0] == UNREADABLE:  # a line the shell may still run: refused when it names git at all
            if entries and re.search(r"(?<![\w/.-])git(?![\w-])", argv[1]):
                return UNREADABLE
            continue
        verb, args = _git_verb(argv)
        if not verb:
            continue
        for entry in entries or ():
            parts = str(entry).split()
            if not parts or parts[0] != verb:
                continue
            if parts[1:]:
                if any(_has_flag(args, flag) for flag in parts[1:]):
                    return entry
            elif verb in _GIT_MOVE_OPTIONS:
                if _git_mutates(verb, args):
                    return entry
            else:
                return entry
    return ""


def _write_targets(command: str, shell: bool = True, depth: int = 0) -> list:
    """Every path a line writes: a redirection, tee's files, cp/mv/install/rsync/ln's target, an in-place sed or perl, and
    what a `sh -c` / `bash -c` / `eval` argument writes. A shell line is read as the shell reads it: quoted text is data,
    here-documents are data, a comment ends the line. A relative target is read from the folder an earlier cd moved to: a cd
    that runs unconditionally into a folder that exists (or that the line made with mkdir) holds for every later command, a
    cd before `&&` holds along that chain, and any other directory change makes the folder unknown, so a relative target
    after it is UNRESOLVED and refused. Code is read by the older reader, a redirect only when it names a path."""
    text = str(command or "")
    if not shell:
        return _legacy_targets(text, code=True)
    if depth > _DEPTH:
        return [UNRESOLVED + "shell lines nested too deep to read"]
    try:
        lines = _lines(text)
    except ValueError:  # an unbalanced quote: the kernel's earlier reading, and any absolute target the line names
        floor = [match.group(1) for match in re.finditer(r"(?:\d*|&)>>?\s*(/[^\s'\";&|<>]+|~[^\s'\";&|<>]*)", text)]
        return _legacy_targets(text) + floor
    flat = [token for tokens in lines for token in tokens]
    redefined = set(re.findall(r"(?:^|[\s;&|(])(?:export\s+|local\s+|declare\s+(?:-\S+\s+)*)?([A-Za-z_]\w*)=", text))
    # a directory change inside ( ), $( ) or backticks happens in another shell: the line's folder cannot be followed
    moved_inside = bool(re.search(r"(?:\(|`)[^)`]*\b(?:cd|pushd|popd)\b", text)) and any(
        t in ("cd", "pushd", "popd") for t in flat
    )
    cwd = None if moved_inside else ""  # "" = the hook's own folder; None = unknown
    certain = True  # the folder holds for every later command, not only along an && chain
    conditional = False  # this command runs only if an earlier one succeeded or failed
    made = set()  # folders this line makes before it moves there
    found = []
    for tokens in lines:
        for items, after in _simple_commands(tokens):
            words, targets = _command_words(items)
            start = _after_wrappers([_plain(word) for word in words])
            literal = [_plain(word, literal=True) for word in words]
            words = [_plain(word) for word in words][max(start, 0) :]  # the command behind sudo, env, X=1 ...
            if not words and not targets:
                continue
            tool = os.path.basename(words[0]) if words else ""
            targets.extend(_tee_targets(words))
            edited = _editor_target(words) if words else ""
            if edited:
                targets.append(edited)
            copied = _copy_target(tool, words)
            if copied:
                targets.append(copied)
            for target in targets:
                if not _HARMLESS.fullmatch(target):
                    found.append(_resolve(cwd, target, redefined))
            for inner in _inner_lines(words, literal):  # what an inner shell line writes, from this folder
                for target in _write_targets(inner, depth=depth + 1):
                    found.append(target if target.startswith(UNRESOLVED) else _resolve(cwd, target, redefined))
            if tool == "mkdir" and cwd is not None:
                for arg in [
                    word for word in words[1:] if not word.startswith("-")
                ]:  # with -p, every folder above it too
                    folder = os.path.normpath(_expand(_from(cwd, arg), redefined))
                    while folder not in made and folder not in (os.sep, "."):
                        made.add(folder)
                        folder = os.path.dirname(folder)
            if tool in ("cd", "pushd", "popd", "chdir"):
                plain = (
                    tool == "cd"
                    and len(words) == 2
                    and not words[1].startswith("-")
                    and not targets
                    and not moved_inside
                )
                folder = _from(cwd, words[1]) if plain and cwd is not None else None
                real = os.path.normpath(_expand(folder, redefined)) if folder is not None else ""
                exists = bool(real) and (os.path.isdir(real) or real in made)
                if folder is None or after in ("|", "&", "|&"):
                    cwd = None
                elif exists and not conditional and certain:
                    cwd = folder
                elif after == "&&":
                    cwd, certain = folder, False
                else:
                    cwd = None
                conditional = conditional and after not in (";", "\n")
                continue
            if after in (";", "\n", "||", "&") and not certain:
                cwd = None
            conditional = after in ("&&", "||") or (conditional and after in ("|", "|&"))
    return found


def _expand(path: str, redefined=()) -> str:
    """~ and the variables the line does not set itself, as the shell would expand them."""
    names = re.findall(r"\$\{?([A-Za-z_]\w*)", path or "")
    if any(name in redefined for name in names):
        return path
    return os.path.expanduser(os.path.expandvars(path))


def _from(cwd: str, path: str) -> str:
    """`path` seen from `cwd`, the folder a `cd` moved to. A path from the root, from home or from a variable stays as it is."""
    path = path.strip("'\"")
    if not cwd or path.startswith(("/", "~", "$")):
        return path
    return os.path.join(cwd, path)


def _resolve(cwd, path: str, redefined=()) -> str:
    path = path.strip("'\"")
    names = re.findall(r"\$\{?([A-Za-z_]\w*)", path)
    if any(name in redefined for name in names):
        return UNRESOLVED + path
    if cwd is None and not path.startswith(("/", "~", "$")):
        return UNRESOLVED + path
    return _from(cwd, path)


# Where each seat kind may write besides its pack's egress.write_roots. A worker writes in its ticket checkouts.
WRITE_ROOTS = {
    "intake": ("qa", "outbox"),
    "analyst": ("qa", "outbox"),
    "reviewer": ("qa", "outbox"),
    "tester": ("qa", "outbox"),
    "gatekeeper": ("outbox",),
}


def pack_write_roots(pack, kind: str) -> list:
    """egress.write_roots.<kind>: absolute, or starting at {workspace} or {root}."""
    from .paths import root, workspace

    listed = (((pack or {}).get("egress") or {}).get("write_roots") or {}).get(kind) or []
    return [os.path.normpath(str(item).format(workspace=workspace(), root=root())) for item in listed]


def _inside(target: str, roots) -> bool:
    if target.startswith(UNRESOLVED):
        return False
    real = os.path.realpath(os.path.abspath(os.path.expandvars(os.path.expanduser(target))))
    for root in roots:
        base = os.path.realpath(os.path.abspath(root))
        if real == base or real.startswith(base + os.sep):
            return True
    return False


def _readonly_write(command: str, pack, targets=None, shell: bool = True) -> str:
    """A seat other than a worker writes only under its kind's roots, the pack's scratch, and its write_roots."""
    lane = os.environ.get("COCKPIT_LANE") or ""
    kind = lane.split("-")[0]
    if kind not in WRITE_ROOTS:
        return ""
    from . import paths

    roots = [getattr(paths, name)() for name in WRITE_ROOTS[kind]] + pack_write_roots(pack, kind)
    if pack:
        from .pack import policy

        scratch = policy(pack)["scratch"]
        if scratch:
            roots.append(scratch)
    for target in _write_targets(command, shell) if targets is None else targets:
        if target.startswith(UNRESOLVED):
            return _blocked(
                f"a write whose folder or variable this line changes ({target[len(UNRESOLVED) :]}); write to a "
                f"full path under: {', '.join(roots)}"
            )
        if not _inside(target, roots):
            return _blocked(f"a write outside your roots ({target}); a {kind} writes under: {', '.join(roots)}")
    return ""


def _git_deny(command: str, pack) -> str:
    """egress.git_deny.<kind>: the git moves refused to that seat kind, judged on the command's argv (shell lines only)."""
    kind = (os.environ.get("COCKPIT_LANE") or "").split("-")[0]
    entries = ((((pack or {}).get("egress") or {}).get("git_deny") or {}).get(kind) or []) if kind else []
    hit = git_moves(command, entries) if entries else ""
    if hit == UNREADABLE:
        return _blocked(f"refused to a {kind} (git on a line the fence cannot read: fix the quoting)")
    if hit:
        return _blocked(f"refused to a {kind} (git {hit})")
    return ""


def _role_deny(texts, pack) -> str:
    """egress.role_deny.<kind>: patterns refused for that seat kind only."""
    kind = (os.environ.get("COCKPIT_LANE") or "").split("-")[0]
    patterns = ((((pack or {}).get("egress") or {}).get("role_deny") or {}).get(kind) or []) if kind else []
    for text in texts:
        for pattern in patterns:
            if re.search(pattern, text):
                return _blocked(f"refused to a {kind} (rule {pattern[:80]})")
    return ""


# An MCP tool (mcp__<server>__<tool>) whose own name says it changes something is refused unless the pack lists it.
MCP_PREFIX = "mcp__"
MCP_WRITE_VERBS = re.compile(
    r"(^|_)(create|update|upsert|delete|remove|add|edit|write|post|put|patch|set|send|comment|reply|transition|assign|"
    r"merge|close|reopen|move|upload|publish|submit|approve|archive|link|attach|insert|drop|execute|exec|run|push|"
    r"deploy|trigger|invite|grant|revoke|rename|import)(_|$)",
    re.IGNORECASE,
)


CONNECTOR_PREFIX = "connectors__"


def _mcp_write(name: str, pack) -> str:
    import fnmatch

    if name.startswith(CONNECTOR_PREFIX):
        # A hosted connector is an MCP server by another name. Only the one the pack's tracker publishes through is
        # the outbox's to guard, and only for a card: a card writing to Jira through it would skip the endorsement,
        # the auto-publish policy and the record. The owner's own sessions, and other connectors, are left alone.
        if not os.environ.get("COCKPIT_LANE"):
            return ""
        from .tracker import _config, tracker_kind

        config = _config(pack)
        parts = name[len(CONNECTOR_PREFIX) :].split("__", 1)
        if len(parts) != 2 or tracker_kind(config) != "connector" or parts[0] != str(config.get("connector") or "jira"):
            return ""
        tool = parts[1]
    elif not name.startswith(MCP_PREFIX) or "__" not in name[len(MCP_PREFIX) :]:
        return ""
    else:
        tool = name[len(MCP_PREFIX) :].split("__", 1)[1]
    if not MCP_WRITE_VERBS.search(tool):
        return ""
    allowed = ((pack or {}).get("egress") or {}).get("mcp_allow") or []
    if any(fnmatch.fnmatchcase(name, str(item)) for item in allowed):
        return ""
    return "an MCP write goes through the outbox"


def protected(real: str) -> bool:
    """Files no tool may touch: every vault (root and seat), Hermes's credentials, and the board database."""
    from .paths import hermes_home, volumes

    home = os.path.realpath(hermes_home())
    slots = os.path.realpath(volumes())
    if real == home or not real.startswith(home + os.sep):
        return os.path.basename(real) == "login.json" and real.startswith(slots + os.sep)
    parts = os.path.relpath(real, home).split(os.sep)
    if parts[0] == "profiles" and len(parts) > 1:
        parts = parts[2:]
    if not parts:
        return False
    if parts[0] == "vault" or parts[0] in (".env", "auth.json"):
        return True
    return parts[0] == "kanban" and any(part.startswith("kanban.db") for part in parts)


def _secret_read(text: str) -> str:
    """A tool may not read the slot login, a vault, Hermes's credentials, or the board database."""
    # a shell drops a NUL byte from its input, so the path it would open is the token without one (and no path holds one)
    raw = str(text or "").replace("\x00", "").strip()
    if not raw:
        return ""
    for token in re.split(r"[\s=<>]+", raw):
        cleaned = token.strip("'\"()`;")
        if not cleaned or cleaned.startswith("http://") or cleaned.startswith("https://"):
            continue
        expanded = os.path.expandvars(os.path.expanduser(cleaned))
        candidate = expanded if os.path.isabs(expanded) else os.path.abspath(expanded)
        if protected(os.path.realpath(candidate)):
            return _blocked("a read of a protected secret file")
    return ""


def check_bound(command: str, shell: bool = True) -> str:
    """Every check for one command. `shell`: a shell line (terminal); code (execute_code, a browser script) is not."""
    if _secret_read(command):
        return "blocked"
    pack = {}
    try:
        from .pack import load, policy
        from .paths import pack_path

        pack = load(pack_path())
        rules = policy(pack)
    except Exception:  # noqa: BLE001 - a pack that cannot be read adds no rule of its own
        rules = {"hosts": [], "commands": [], "reads": []}
    if _allowed(command, rules.get("reads")):
        # a pack's list answers for the pack's denies only: what the kernel refuses, it refuses first
        return kernel_refusal(command, pack)
    deny, hosts, sacred, paths = pack_rules()
    literal_hosts = [re.escape(str(item)) for item in (rules.get("hosts") or []) if str(item)]
    literal_commands = [re.escape(str(item)) for item in (rules.get("commands") or []) if str(item)]
    reason = check(command, list(deny) + literal_commands, list(hosts) + literal_hosts, sacred, paths)
    if reason:
        return reason
    if _http_write(str(command or ""), forge_hosts(pack)):
        return _blocked("a write to the forge over HTTP: publishing goes through the outbox")
    if _role_deny([str(command or "")], pack):
        return "blocked"
    if shell and _git_deny(str(command or ""), pack):
        return "blocked"
    shared = _shared_browser(command, pack)
    if shared:
        return shared
    worker = _worker_write(command, pack, shell=shell)
    if worker:
        return worker
    return _readonly_write(command, pack, shell=shell)


def _worktree_roots() -> list:
    from .paths import wt

    found = []
    base = wt()
    if os.path.isdir(base):
        for ticket in os.listdir(base):
            folder = worktree_of(ticket)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.isdir(path):
                    found.append(os.path.realpath(path))
    return found


# What the hook that fired gave for this one tool call: the command hook's stdin payload, or the plugin hook's keyword
# arguments. Per call and per thread of execution; nothing is kept between calls.
_HOOK_INPUT = contextvars.ContextVar("cockpit_hook_input", default=None)
_SEEN_SOURCES = set()
CARD_KEYS = (
    "kanban_task_id",
    "kanban_task",
)  # Hermes names the card `extra.kanban_task_id` in a command hook's payload


@contextlib.contextmanager
def hook_input(payload):
    token = _HOOK_INPUT.set(payload if isinstance(payload, dict) else None)
    try:
        yield
    finally:
        _HOOK_INPUT.reset(token)


def _card_from_hook(given: dict, board: str) -> tuple:
    extra = given.get("extra") if isinstance(given.get("extra"), dict) else {}
    for where, holder in (("extra.", extra), ("", given)):
        for key in CARD_KEYS:
            if str(holder.get(key) or "").strip():
                return str(holder[key]).strip(), f"hook {where}{key}"
    # Hermes's own `task_id` is the session's task, not the card: it counts only when it is a card cockpit made here
    for where, holder in (("", given), ("extra.", extra)):
        value = str(holder.get("task_id") or "").strip()
        if value and _known_card(board, value):
            return value, f"hook {where}task_id"
    return "", ""


def _known_card(board: str, card: str) -> bool:
    try:
        from .kanban import card_entry

        return bool(card_entry(board, card))
    except Exception:  # noqa: BLE001 - an unreadable index knows no card
        return False


def _card_from_hermes() -> str:
    """Inside Hermes (the plugin hook): the card this execution owns, as Hermes itself answers. Never imported here:
    a command hook is its own process and has no Hermes loaded."""
    import sys

    module = sys.modules.get("agent.delegation_context")
    owned = getattr(module, "owned_kanban_task", None)
    if not callable(owned):
        return ""
    try:
        return str(owned() or "").strip()
    except Exception:  # noqa: BLE001 - Hermes's answer is a help, never a reason to fail a call
        return ""


def running_card(pack=None) -> tuple:
    """(card, where it was learned) of the kanban card the lane's tool call belongs to, or ("", "").

    Hermes removes HERMES_KANBAN_TASK from the environment of every process a worker starts, and the command hook is
    one: there the card is only in the hook's payload (`extra.kanban_task_id`). So: the hook's input first, then
    Hermes's own answer when this runs inside Hermes, then the environment (a lane's own shell, older Hermes)."""
    if not os.environ.get("COCKPIT_LANE"):
        return "", ""
    board = os.environ.get("HERMES_KANBAN_BOARD") or str((pack or {}).get("board") or "")
    given = _HOOK_INPUT.get()
    card, source = _card_from_hook(given, board) if isinstance(given, dict) else ("", "")
    if not card:
        card, source = _card_from_hermes(), "hermes owned_kanban_task"
    if not card:
        card, source = (os.environ.get("HERMES_KANBAN_TASK") or "").strip(), "env HERMES_KANBAN_TASK"
    if not card:
        return "", ""
    if source not in _SEEN_SOURCES:  # once per process: an install can be checked from its log
        _SEEN_SOURCES.add(source)
        try:
            from .store import log

            log(f"FENCE the running card comes from {source}")
        except Exception:  # noqa: BLE001, S110 - a log line never refuses a call
            pass
    return card, source


READ_TOOLS = {"read", "read_file", "grep", "search", "search_files", "list", "glob"}
WRITE_TOOLS = {"write", "write_file", "edit", "patch", "search_replace", "apply_patch", "str_replace", "strreplace"}


def _edit_path(name: str, tool_input) -> str:
    """A file-edit tool's path. A read tool is not an edit."""
    if not isinstance(tool_input, dict):
        return ""
    if (name or "").lower() in READ_TOOLS:
        return ""
    writing = (name or "").lower() in WRITE_TOOLS
    if (
        not writing
        and tool_input.get("contents") is None
        and tool_input.get("new_string") is None
        and tool_input.get("old_string") is None
    ):
        return ""
    for key in ("path", "file_path", "file"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _note_review_read(name, tool_input) -> None:
    """A reviewer read of path and line is the record a finding may cite."""
    lane = os.environ.get("COCKPIT_LANE") or ""
    if not lane.startswith("reviewer") or not isinstance(tool_input, dict):
        return
    from .skill_log import current_ticket

    ticket = current_ticket()
    if not ticket:
        return
    if (name or "").lower() not in READ_TOOLS:
        return
    path = ""
    for key in ("path", "file_path", "file"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            path = value.strip()
            break
    line = tool_input.get("line")
    if line in (None, "") or not path:
        return
    from .outbox import note_read

    note_read(ticket, f"{path}:{line}")


# Hermes 0.22/0.23 tool inputs (tests/contract/hermes-tools.json; browser_console and the other 0.22 browser_* tools
# left core in 0.23 and live on in the camofox plugin, so their inputs stay checked). What runs is checked like a shell line; what is
# fetched is checked for refused hosts; any other tool's string leaves are checked for refused hosts too.
EXEC_INPUTS = {
    "terminal": ("command",),
    "execute_code": ("code",),
    "browser_exec": ("code",),
    "browser_console": ("expression",),
    "process_manage": ("data",),
    "browser_cdp": ("method", "params"),
}
PATH_KEYS = ("path", "file_path", "file")
CODE_TOOLS = (
    "execute_code",
    "browser_exec",
    "browser_console",
    "process_manage",
    "browser_cdp",
)  # code, not shell lines
LANE_REFUSED_TOOLS = {"cronjob_manage": "a lane does not schedule jobs"}


def _leaves(value) -> list:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    if isinstance(value, (list, tuple)):
        return [leaf for item in value for leaf in _leaves(item)]
    return []


def _exec_texts(name: str, tool_input) -> list:
    if isinstance(tool_input, str):
        return [tool_input]
    if not isinstance(tool_input, dict):
        return []
    keys = EXEC_INPUTS.get(name, ("command",))
    return [leaf for key in keys for leaf in _leaves(tool_input.get(key))]


def _refused_host(texts, pack) -> str:
    """A production or refused host anywhere in a fetched URL or another tool's arguments."""
    from .pack import policy

    hosts = list(pack_rules()[1])
    if pack:
        hosts += [re.escape(str(item)) for item in policy(pack).get("hosts") or [] if str(item)]
    for text in texts:
        for pattern in hosts:
            if pattern and re.search(pattern, text):
                return _blocked(f"a refused host ({pattern[:60]})")
    return ""


def _touch_slot(pack) -> None:
    """A lane's tool call on its ticket keeps that ticket's slot from being collected as idle."""
    if not os.environ.get("COCKPIT_LANE") or not pack:
        return
    from .skill_log import current_ticket
    from .slots import touch_ticket

    ticket = current_ticket()
    if ticket:
        touch_ticket(ticket)


def _bound_pack() -> dict:
    try:
        from .pack import load
        from .paths import pack_path

        return load(pack_path())
    except Exception:  # noqa: BLE001 - a pack that cannot be read is an empty one here
        return {}


def _browser_session(name: str, tool_input, pack) -> str:
    """Under the pack's `lanes.browser_session`, a lane's browser_exec names its session: the default session is one
    browser-harness daemon for every profile on the machine, so a lane without a name drives another lane's browser (and
    its vault fills a blank tab). The human's own calls are not touched."""
    lane = os.environ.get("COCKPIT_LANE") or ""
    if name != "browser_exec" or not lane or not ((pack or {}).get("lanes") or {}).get("browser_session"):
        return ""
    if isinstance(tool_input, dict) and str(tool_input.get("session") or "").strip():
        return ""
    from .skill_log import current_ticket

    return (
        "browser_exec needs a session: a lane's browser runs in its own session, never the default one shared by every "
        f'lane; pass session "{lane}-{current_ticket() or "<ticket>"}" on every call of this card'
    )


def _external_browser_tool(name: str, pack) -> str:
    """A Chrome DevTools MCP tool drives the external browser: only a test kickoff card the human started with it may
    call one (cockpitlib.browser_card). Every other card, a supervisor card above all, runs on the built-in browser."""
    from .browser_card import chrome_mcp, external_refusal

    if not chrome_mcp(name):
        return ""
    return external_refusal(pack)


# What a seat may still do while its bound pack cannot be read: look at local files and report on its own card.
PACK_DOWN_TOOLS = {"read_file", "search_files", "skill_view", "skills_list", "todo", "clarify"}


def pack_down(name: str) -> str:
    """A pack is bound (COCKPIT_PACK or the binding names one) and cannot be loaded: every tool that can reach the
    network or change anything is refused until `cockpit pack check` passes. No binding at all is no adoption, and
    leaves the kernel's own checks."""
    try:
        from .paths import load_binding

        bound = bool(os.environ.get("COCKPIT_PACK") or load_binding().get("pack"))
    except Exception:  # noqa: BLE001 - a binding that cannot be read counts as bound
        bound = True
    if not bound or name in PACK_DOWN_TOOLS or name.startswith("kanban_"):
        return ""
    try:
        from .pack import load
        from .paths import pack_path

        load(pack_path())
    except Exception:  # noqa: BLE001 - a pack that cannot be read refuses the tool
        return "pack unreadable: cockpit refuses this tool until `cockpit pack check` passes"
    return ""


def check_tool(name: str, tool_input, payload=None) -> str:
    """Every tool's input. A shell line, code, and browser scripts get every check; a URL or any other argument is
    checked for refused hosts; file paths are fenced. A worker edit outside a ticket checkout is refused. `payload` is
    what the hook that fired was given (the command hook's stdin payload, the plugin hook's keywords): the running
    card is read from it (running_card)."""
    with hook_input(payload):
        return _check_tool(name, tool_input)


def _check_tool(name: str, tool_input) -> str:
    name = str(name or "")
    _WHY.text = ""
    down = pack_down(name)
    if down:
        return down
    if os.environ.get("COCKPIT_LANE") and name in LANE_REFUSED_TOOLS:
        action = str((tool_input or {}).get("action") or "") if isinstance(tool_input, dict) else ""
        if action != "list":
            return LANE_REFUSED_TOOLS[name]
    # Hermes's browser_vault is how a secret is used; it takes handles. Any other input holding one is refused.
    from .scrub import holds_secret

    if name != "browser_vault" and holds_secret(_leaves(tool_input)):
        return "a secret may not leave in a tool call"
    # A tool off the map that takes a command (a shell MCP server, say) is checked as a shell line too.
    runs = _exec_texts(name, tool_input)
    for text in runs:
        if _secret_read(text):
            return "blocked"
    if isinstance(tool_input, dict):
        for key in PATH_KEYS:
            if _secret_read(str(tool_input.get(key) or "")):
                return "blocked"
        if name == "search_files" and wide_root(str(tool_input.get("path") or "")):
            return _blocked("a search of a whole disk or home folder: search one project root")
    for text in runs or [""]:
        reason = check_bound(text, shell=name not in CODE_TOOLS) if text else ""
        if reason:
            return reason
    pack = _bound_pack()
    # The pack names tools no lane may call at all, e.g. raw CDP when its browser rule allows only one driver.
    if os.environ.get("COCKPIT_LANE") and name in ((pack.get("egress") or {}).get("deny_tools") or []):
        return _blocked(f"a tool the pack refuses on lanes ({name})")
    _touch_slot(pack)
    reason = (
        _staging_write(runs, pack)
        or _shared_browser_leaves(name, tool_input, pack)
        or _browser_session(name, tool_input, pack)
        or _external_browser_tool(name, pack)
    )
    if reason:
        return reason
    reason = _mcp_write(name, pack) or _advisor_report(name, tool_input, pack) or _failure_videos(name, pack)
    if reason:
        return reason
    if name not in EXEC_INPUTS and not isinstance(tool_input, str):
        reason = _refused_host(_leaves(tool_input), pack)
        if reason:
            return reason
    target = _edit_path(name, tool_input)
    if not target:
        _note_review_read(name, tool_input)
        return ""
    for path in pack_rules()[3]:
        if path and str(path) in target:
            return _blocked(f"an infrastructure path ({path})")
    # the path as the tool names it, whole: never read through a shell line, where `(` or a space would cut it
    worker = _worker_write("", pack, targets=[target])
    if worker:
        return worker
    return _readonly_write("", pack, targets=[target])


def _advisor_report(name: str, tool_input, pack) -> str:
    """A worker's board complete must carry the advisor's line when the pack's advisor runs inside the coding tool."""
    if name != "kanban_complete" or (os.environ.get("COCKPIT_LANE") or "").split("-")[0] != "worker":
        return ""
    advisor = (pack or {}).get("advisor") or {}
    if not advisor.get("in_tool"):
        return ""
    kinds = advisor.get("report_on")
    if kinds is not None:  # only the card kinds the pack names (a packaging-only rework runs no advisor)
        from .kanban import _index

        entry = (_index().get(str(pack.get("board") or "")) or {}).get(running_card(pack)[0]) or {}
        kind = entry.get("kind") if isinstance(entry, dict) else ""
        if kind and kind not in kinds:
            return ""
    from .advise import report_refusal

    fields = tool_input if isinstance(tool_input, dict) else {}
    return report_refusal(pack, "\n".join(str(fields.get(key) or "") for key in ("summary", "result")))


def _failure_videos(name: str, pack) -> str:
    """A test kickoff's run card closes as done only with a failure video for every Fail row (testflow.video_refusal)."""
    if name != "kanban_complete" or not os.environ.get("COCKPIT_LANE"):
        return ""
    from .test_flow import video_refusal

    return video_refusal(pack)


def _worker_write(command: str, pack, targets=None, shell: bool = True) -> str:
    """A worker edit lands in a ticket checkout. Anywhere else is refused."""
    lane = os.environ.get("COCKPIT_LANE") or ""
    if lane.split("-")[0] != "worker":
        return ""
    targets = _write_targets(command, shell) if targets is None else targets
    if not targets:
        return ""
    roots = _worktree_roots() + pack_write_roots(pack, "worker")
    for target in targets:
        if target.startswith(UNRESOLVED):
            return _blocked(
                f"a write whose folder or variable this line changes ({target[len(UNRESOLVED) :]}); write to a "
                "full path in your ticket checkout"
            )
        if _inside(target, roots):
            continue
        return _blocked(f"a write outside your ticket checkouts ({target}); records change through cockpit verbs")
    return ""


def _lend_phrase(text: str) -> bool:
    """The loan a kickoff or the human wrote on a card. Text the card quotes from outside never lends."""
    from .quoted import without

    lowered = without(text).lower()
    return "browser lent" in lowered or "chrome: shared" in lowered


def _card_says_lent(pack, ticket: str) -> bool:
    """The human browser stays closed until a card for this ticket says it was lent."""
    from .kanban import board_cards, db_path

    slug = str((pack or {}).get("board") or "")
    if not slug or not ticket:
        return False
    matched = []
    for card in board_cards(slug):
        if card.get("ticket") != ticket:
            continue
        matched.append(card["id"])
        if _lend_phrase(card.get("body") or ""):
            return True
    if not matched:
        return False
    path = db_path(slug)
    if not os.path.isfile(path):
        return False
    import sqlite3

    connection = read_db(path)
    try:
        columns = {row[1] for row in connection.execute("pragma table_info(task_comments)")}
        if "body" not in columns or "task_id" not in columns:
            return False
        for card_id in matched:
            rows = connection.execute("select body from task_comments where task_id = ?", (card_id,)).fetchall()
            for row in rows:
                if _lend_phrase(row[0] or ""):
                    return True
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return False


def _loan_expired(record, pack) -> bool:
    """The page's loan duration is the timer. A record with no start keeps its stored end."""
    now = int(time.time())
    started = record.get("at") if isinstance(record, dict) else None
    if started in (None, ""):
        deadline = int((record or {}).get("until") or 0)
        return bool(deadline and now > deadline)
    try:
        from .settings import load

        hours = float(load(pack)["shared_chrome_hours"])
    except (TypeError, ValueError, KeyError):
        hours = float((record or {}).get("hours") or 0)
    if hours <= 0:
        return True
    return now > int(started) + int(hours * 3600)


CDP = re.compile(r"/json(/|\b)|/devtools/|connect_over_cdp|puppeteer\.connect|chrome-remote-interface|remote-debugging")


def _uses_human_browser(text: str, pack) -> bool:
    """The human browser's port anywhere, a tab verb, or a DevTools connection that names no other port."""
    port = str((pack or {}).get("human_browser_port") or "")
    if port and re.search(rf"(?<!\d){re.escape(port)}(?!\d)", text):
        return True
    if re.search(r"\b(open|close)-tab\s", text):
        return True
    return bool(CDP.search(text)) and not re.search(r":\d{2,5}\b|\bport\b\W{0,3}\d{2,5}\b", text, re.IGNORECASE)


def _shared_browser_leaves(name: str, tool_input, pack) -> str:
    """A URL or another tool's argument that reaches the human browser needs the loan too."""
    if name in EXEC_INPUTS or isinstance(tool_input, str):
        return ""
    text = "\n".join(_leaves(tool_input))
    return _shared_browser(text, pack) if text else ""


def _shared_browser(command: str, pack) -> str:
    """A lane may use the human browser port only while the card's loan is current. It may close only a tab it opened."""
    if not os.environ.get("COCKPIT_LANE"):
        return ""
    text = str(command or "")
    if not _uses_human_browser(text, pack):
        return ""
    closing = re.findall(r"\bclose-tab\s+(\S+)", text)
    opening = re.findall(r"\bopen-tab\s+(\S+)", text)

    from .paths import watch_dir

    path = os.path.join(watch_dir(), "shared-chrome.json")
    record = {}
    if os.path.isfile(path):
        try:
            record = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = {}
    if not isinstance(record, dict) or not record.get("ticket"):
        return _blocked("the human's Chrome is not lent to a ticket")
    from .skill_log import current_ticket

    if current_ticket() != record.get("ticket"):
        return "the browser is lent to another ticket"
    if _loan_expired(record, pack):
        return _blocked("the loan of the human's Chrome has expired")
    from .skill_log import current_card

    if current_card()[1]:
        # a card's run: only the test kickoff card the human started with the external browser drives it
        from .browser_card import current

        if not current(pack).get("external"):
            return _blocked("the external browser is a test kickoff's option: this card runs on the built-in browser")
    elif not _card_says_lent(pack, str(record.get("ticket") or "")):
        return _blocked("the card does not say `chrome: shared`")
    tabs = [str(item) for item in (record.get("tabs") or [])]
    if any(tab not in tabs for tab in closing):
        return _blocked("a tab of the human's Chrome you did not open")
    added = [tab for tab in opening if tab not in tabs]
    if added:
        tabs.extend(added)
        record["tabs"] = tabs
        try:
            dump_json(path, record)
        except OSError:
            return _blocked("the loan record of the human's Chrome cannot be written")
    return ""


# Hermes's delegation tool. A spawn names its children in tasks[] (or one legacy goal).
DELEGATE_TOOLS = ("delegate_task",)
DELEGATE_SEATS = ("intake", "analyst", "reviewer")
MAX_DELEGATES = 3


def delegate_tasks(request) -> list:
    """The children one delegate_task spawn would start. The legacy single-goal shape is one child."""
    if not isinstance(request, dict):
        return []
    tasks = request.get("tasks")
    if isinstance(tasks, list):
        return tasks
    if request.get("goal"):
        return [{"goal": request.get("goal"), "context": request.get("context")}]
    return []


def check_delegate(request, kind: str = "") -> str:
    """A read-only seat may give at most three children a goal in one spawn. Other seats do not delegate.

    Listing, steering, and stopping children start nothing. Hermes caps how many children run at once
    (delegation.max_concurrent_children, which setup writes for the delegating seats).
    """
    if isinstance(request, dict) and str(request.get("action") or "spawn") != "spawn":
        return ""
    seat = (kind or os.environ.get("COCKPIT_LANE") or "").split("-")[0]
    if seat and seat not in DELEGATE_SEATS:
        return "this seat does not delegate"
    tasks = delegate_tasks(request)
    if not tasks:
        return "a delegate needs a goal"
    if len(tasks) > MAX_DELEGATES:
        return "at most three delegates"
    for task in tasks:
        if not isinstance(task, dict) or not str(task.get("goal") or "").strip():
            return "a delegate needs a goal"
    return ""


def fence_explain(pack, card: str, path: str, lane: str = "worker-1") -> dict:
    """The worker write fence's decision for one path as the given card's lane would get it, and why: where the card
    resolved and the ticket's worktrees. Reads only; the lane named here is in force only for the check."""
    from . import worktree
    from .kanban import card_entry

    board = str((pack or {}).get("board") or "")
    entry = card_entry(board, card)
    ticket = str(entry.get("ticket") or "")
    before = {key: os.environ.get(key) for key in ("COCKPIT_LANE", "HERMES_KANBAN_BOARD")}
    os.environ["COCKPIT_LANE"] = lane
    os.environ["HERMES_KANBAN_BOARD"] = board
    lines = []
    try:
        with hook_input({"extra": {"kanban_task_id": card}}):
            source = running_card(pack)[1]
            _WHY.text = ""
            verdict = _worker_write("", pack, targets=[path])
            why = getattr(_WHY, "text", "")
        lines.append(
            f"card {card}: ticket {ticket}, repos {', '.join(entry.get('repos') or []) or 'none named'}; lane {lane}; resolved from {source}"
            if entry
            else f"card {card}: not a card cockpit made on this board ({board}); lane {lane}"
        )
        if lane.split("-", maxsplit=1)[0] != "worker":
            lines.append(
                "the worker write fence applies to worker lanes only: other lanes are fenced by their own rules"
            )
        for folder in worktree.list_worktrees(ticket) if ticket else []:
            lines.append(f"{os.path.basename(folder)}: worktree {folder}")
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return {"allowed": not verdict, "why": why, "lines": lines}
