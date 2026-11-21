# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Markdown and tracker documents (ADF) to safe HTML for the page. Text is escaped first; only the markup made here
reaches the page, and a link keeps only an http(s) or mailto target."""

import html
import re

LIMIT = 200_000
SAFE_LINK = re.compile(r"^(https?://|mailto:)", re.I)


def _href(url: str) -> str:
    url = html.unescape(url or "").strip()
    return html.escape(url, quote=True) if SAFE_LINK.match(url) else ""


MARK = "\x00"  # fences a number that stands for markup already made; the text itself never carries one
LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
BARE = re.compile(r"(?<![\"'=>\x00])(https?://[^\s<\x00]+)")
BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
KEPT = re.compile(r"\x00(\d+)\x00")


def _inline(text: str) -> str:
    """Escaped text with `code`, **bold**, *italic*, [label](url) and bare http(s) links. Markup is made once and set
    aside: no later pattern reads a tag or a target made here, so a target cannot grow a second link or an attribute."""
    parts = re.split(r"(`[^`\n]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        made = []

        def keep(markup: str) -> str:
            made.append(markup)
            return f"{MARK}{len(made) - 1}{MARK}"

        def restore(piece: str) -> str:
            return KEPT.sub(lambda found: made[int(found.group(1))], piece)

        def emphasis(piece: str) -> str:
            piece = BOLD.sub(lambda found: keep("<strong>") + found.group(1) + keep("</strong>"), piece)
            return ITALIC.sub(lambda found: keep("<em>") + found.group(1) + keep("</em>"), piece)

        def link(match):
            target = _href(match.group(2))
            if not target:
                return match.group(1)  # the label stays text, read like the text around it
            return keep(f'<a href="{target}" rel="noopener noreferrer">{restore(emphasis(match.group(1)))}</a>')

        piece = html.escape(part.replace(MARK, "\ufffd"), quote=False)
        piece = LINK.sub(link, piece)
        piece = BARE.sub(
            lambda found: keep(f'<a href="{_href(found.group(1))}" rel="noopener noreferrer">{found.group(1)}</a>'),
            piece,
        )
        out.append(restore(emphasis(piece)))
    return "".join(out)


def forge_markdown(text: str) -> str:
    """A forge comment as rendered markdown: hidden HTML comments dropped, a <details>/<summary> fold read as its summary in bold,
    <br> as a line break, other tags left out (their text kept). The rest goes through markdown(), which escapes everything."""
    body = re.sub(r"<!--.*?-->", "", str(text or ""), flags=re.S)
    body = re.sub(
        r"<summary>\s*(.*?)\s*</summary>",
        lambda found: "\n**" + re.sub(r"<[^>]+>", "", found.group(1)).strip() + "**\n",
        body,
        flags=re.S | re.I,
    )
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(
        r"</?(details|div|p|span|sub|sup|b|strong|i|em|blockquote|table|thead|tbody|tr|td|th|ul|ol|li|img|a|code|pre|h[1-6])(\s[^>]*)?/?>",
        "",
        body,
        flags=re.I,
    )
    return markdown(re.sub(r"\n{3,}", "\n\n", body).strip())


def markdown(text: str) -> str:
    """Headings, paragraphs, bullet and numbered lists, fenced code, quotes, simple tables and rules."""
    lines = str(text or "")[:LIMIT].splitlines()
    out, para, items, kind = [], [], [], ""

    def flush():
        nonlocal para, items, kind
        if para:
            out.append("<p>" + "<br>".join(_inline(line) for line in para) + "</p>")
            para = []
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + f"</{kind}>")
            items, kind = [], ""

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            language = re.sub(
                r"[^A-Za-z0-9_+-]", "", stripped[3:].strip().split(" ")[0]
            )  # the page draws a mermaid block as a diagram
            code = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            out.append(
                (f'<pre><code class="language-{language}">' if language else "<pre><code>")
                + html.escape("\n".join(code))
                + "</code></pre>"
            )
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        number = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if not stripped:
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            flush()
            out.append("<hr>")
        elif stripped.startswith(">"):
            flush()
            out.append(f"<blockquote>{_inline(stripped.lstrip('>').strip())}</blockquote>")
        elif (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and re.fullmatch(r"\|?\s*:?-{2,}.*", lines[index + 1].strip())
        ):
            flush()
            rows = [stripped]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index].strip())
                index += 1
            cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]
            head = "".join(f"<th>{_inline(cell)}</th>" for cell in cells[0])
            body = "".join("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>" for row in cells[1:])
            out.append(
                f'<div class="cockpit-table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            )  # scrolls sideways
            continue
        elif bullet or number:
            want = "ul" if bullet else "ol"
            if para or (items and kind != want):
                flush()
            kind = want
            items.append((bullet or number).group(1))
        else:
            if items:
                flush()
            para.append(stripped)
        index += 1
    flush()
    return "\n".join(out)


def _adf_text(node: dict) -> str:
    text = html.escape(str(node.get("text") or ""), quote=False)
    for mark in node.get("marks") or []:
        kind = mark.get("type")
        if kind == "strong":
            text = f"<strong>{text}</strong>"
        elif kind == "em":
            text = f"<em>{text}</em>"
        elif kind == "code":
            text = f"<code>{text}</code>"
        elif kind == "link":
            target = _href(str((mark.get("attrs") or {}).get("href") or ""))
            text = f'<a href="{target}" rel="noopener noreferrer">{text}</a>' if target else text
    return text


ADF_BLOCKS = {
    "paragraph": "p",
    "bulletList": "ul",
    "orderedList": "ol",
    "listItem": "li",
    "blockquote": "blockquote",
    "table": "table",
    "tableRow": "tr",
    "tableHeader": "th",
    "tableCell": "td",
}


def adf(node) -> str:
    """A tracker document (Atlassian Document Format) as HTML. An unknown node keeps its children."""
    if isinstance(node, list):
        return "".join(adf(child) for child in node)
    if not isinstance(node, dict):
        return html.escape(str(node or ""), quote=False)
    kind = node.get("type")
    inner = adf(node.get("content") or [])
    if kind == "text":
        return _adf_text(node)
    if kind == "hardBreak":
        return "<br>"
    if kind == "rule":
        return "<hr>"
    if kind == "heading":
        level = min(max(int((node.get("attrs") or {}).get("level") or 1), 1), 6)
        return f"<h{level}>{inner}</h{level}>"
    if kind == "codeBlock":
        return (
            "<pre><code>"
            + "".join(
                html.escape(str(child.get("text") or ""))
                for child in node.get("content") or []
                if isinstance(child, dict)
            )
            + "</code></pre>"
        )
    if kind in ("mention", "emoji"):
        return html.escape(str((node.get("attrs") or {}).get("text") or ""), quote=False)
    if kind in ("inlineCard", "blockCard"):
        target = _href(str((node.get("attrs") or {}).get("url") or ""))
        return f'<a href="{target}" rel="noopener noreferrer">{target}</a>' if target else ""
    if kind == "table":
        return f"<table><tbody>{inner}</tbody></table>"
    tag = ADF_BLOCKS.get(kind)
    return f"<{tag}>{inner}</{tag}>" if tag else inner
