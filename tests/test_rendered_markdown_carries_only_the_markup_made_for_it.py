# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The page gets only the markup the renderer made: a link's target is never scanned again for more links or emphasis."""

import re
from html.parser import HTMLParser

import pytest

from cockpitlib.render import _inline, adf, forge_markdown, markdown

# the exact HTML of the renderer before links were protected from later passes: every row stays byte-identical
INLINE = (
    ("plain text", "plain text"),
    ("a < b & c > d", "a &lt; b &amp; c &gt; d"),
    ("say \"hi\" and 'bye'", "say \"hi\" and 'bye'"),
    ("`code`", "<code>code</code>"),
    ("use `a < b` here", "use <code>a &lt; b</code> here"),
    ("`**not bold**` and `https://example.test`", "<code>**not bold**</code> and <code>https://example.test</code>"),
    ("an ` unpaired backtick", "an ` unpaired backtick"),
    ("**bold**", "<strong>bold</strong>"),
    ("a **bold** word and **another**", "a <strong>bold</strong> word and <strong>another</strong>"),
    ("*italic*", "<em>italic</em>"),
    ("an *italic* word", "an <em>italic</em> word"),
    ("***both***", "<em><strong>both</strong></em>"),
    ("**bold** and *italic* together", "<strong>bold</strong> and <em>italic</em> together"),
    ("2 * 3 * 4", "2 <em> 3 </em> 4"),
    ("snake*case*word", "snake*case*word"),
    ("** not bold **", "<strong> not bold </strong>"),
    ("a lone * star", "a lone * star"),
    ("[label](https://example.test)", '<a href="https://example.test" rel="noopener noreferrer">label</a>'),
    (
        "[label](https://example.test/a?b=1&c=2)",
        '<a href="https://example.test/a?b=1&amp;c=2" rel="noopener noreferrer">label</a>',
    ),
    (
        "[label](http://example.test/path#frag)",
        '<a href="http://example.test/path#frag" rel="noopener noreferrer">label</a>',
    ),
    ("[mail](mailto:someone@example.test)", '<a href="mailto:someone@example.test" rel="noopener noreferrer">mail</a>'),
    (
        "[**bold label**](https://example.test)",
        '<a href="https://example.test" rel="noopener noreferrer"><strong>bold label</strong></a>',
    ),
    (
        "[*italic label*](https://example.test)",
        '<a href="https://example.test" rel="noopener noreferrer"><em>italic label</em></a>',
    ),
    (
        "**[label](https://example.test)**",
        '<strong><a href="https://example.test" rel="noopener noreferrer">label</a></strong>',
    ),
    ("*[label](https://example.test)*", '<em><a href="https://example.test" rel="noopener noreferrer">label</a></em>'),
    (
        "**see [label](https://example.test) now**",
        '<strong>see <a href="https://example.test" rel="noopener noreferrer">label</a> now</strong>',
    ),
    (
        "see [one](https://example.test/1) and [two](https://example.test/2)",
        'see <a href="https://example.test/1" rel="noopener noreferrer">one</a> and <a href="https://example.test/2" rel="noopener noreferrer">two</a>',
    ),
    ("[a < b](https://example.test)", '<a href="https://example.test" rel="noopener noreferrer">a &lt; b</a>'),
    ("[label](https://example.test/a_b_c)", '<a href="https://example.test/a_b_c" rel="noopener noreferrer">label</a>'),
    ("[label](relative/path.md)", "label"),
    ("[label](#anchor)", "label"),
    ("[label](/abs/path)", "label"),
    (
        "[label]( https://example.test )",
        '[label]( <a href="https://example.test" rel="noopener noreferrer">https://example.test</a> )',
    ),
    (
        "[label] (https://example.test)",
        '[label] (<a href="https://example.test)" rel="noopener noreferrer">https://example.test)</a>',
    ),
    ("[]()", "[]()"),
    (
        "[TASK-100](https://tracker.example.test/browse/TASK-100): the title",
        '<a href="https://tracker.example.test/browse/TASK-100" rel="noopener noreferrer">TASK-100</a>: the title',
    ),
    ("https://example.test", '<a href="https://example.test" rel="noopener noreferrer">https://example.test</a>'),
    (
        "see https://example.test now",
        'see <a href="https://example.test" rel="noopener noreferrer">https://example.test</a> now',
    ),
    (
        "see http://example.test/a/b?c=d&e=f#g now",
        'see <a href="http://example.test/a/b?c=d&amp;e=f#g" rel="noopener noreferrer">http://example.test/a/b?c=d&amp;e=f#g</a> now',
    ),
    ("(https://example.test)", '(<a href="https://example.test)" rel="noopener noreferrer">https://example.test)</a>'),
    (
        "(see https://example.test/a)",
        '(see <a href="https://example.test/a)" rel="noopener noreferrer">https://example.test/a)</a>',
    ),
    ("https://example.test.", '<a href="https://example.test." rel="noopener noreferrer">https://example.test.</a>'),
    (
        "https://example.test, then",
        '<a href="https://example.test," rel="noopener noreferrer">https://example.test,</a> then',
    ),
    (
        "is it https://example.test?",
        'is it <a href="https://example.test?" rel="noopener noreferrer">https://example.test?</a>',
    ),
    ("https://example.test!", '<a href="https://example.test!" rel="noopener noreferrer">https://example.test!</a>'),
    (
        "https://example.test; next",
        '<a href="https://example.test;" rel="noopener noreferrer">https://example.test;</a> next',
    ),
    ('"https://example.test"', '"https://example.test"'),
    ("'https://example.test'", "'https://example.test'"),
    ("key=https://example.test", "key=https://example.test"),
    (
        "<https://example.test>",
        '&lt;<a href="https://example.test&gt;" rel="noopener noreferrer">https://example.test&gt;</a>',
    ),
    (
        "https://example.test/a https://example.test/b",
        '<a href="https://example.test/a" rel="noopener noreferrer">https://example.test/a</a> <a href="https://example.test/b" rel="noopener noreferrer">https://example.test/b</a>',
    ),
    (
        "https://example.test/[x](https://example.test/b)",
        '<a href="https://example.test/" rel="noopener noreferrer">https://example.test/</a><a href="https://example.test/b" rel="noopener noreferrer">x</a>',
    ),
    (
        "[x](https://example.test/a)https://example.test/b",
        '<a href="https://example.test/a" rel="noopener noreferrer">x</a>https://example.test/b',
    ),
    (
        "[x](https://example.test/a) https://example.test/b",
        '<a href="https://example.test/a" rel="noopener noreferrer">x</a> <a href="https://example.test/b" rel="noopener noreferrer">https://example.test/b</a>',
    ),
    (
        "**bold** https://example.test/a *italic*",
        '<strong>bold</strong> <a href="https://example.test/a" rel="noopener noreferrer">https://example.test/a</a> <em>italic</em>',
    ),
    (
        "*see* https://example.test/a",
        '<em>see</em> <a href="https://example.test/a" rel="noopener noreferrer">https://example.test/a</a>',
    ),
    (
        "`code` then https://example.test/a then **bold**",
        '<code>code</code> then <a href="https://example.test/a" rel="noopener noreferrer">https://example.test/a</a> then <strong>bold</strong>',
    ),
    (
        "https://example.test/a `code` [l](https://example.test/b) *i* **b**",
        '<a href="https://example.test/a" rel="noopener noreferrer">https://example.test/a</a> <code>code</code> <a href="https://example.test/b" rel="noopener noreferrer">l</a> <em>i</em> <strong>b</strong>',
    ),
    ("ftp://example.test/file", "ftp://example.test/file"),
    ("www.example.test", "www.example.test"),
    ("mailto:someone@example.test", "mailto:someone@example.test"),
    (
        "TASK-100: fix the *thing* in `module.py` (see https://example.test/pull/1).",
        'TASK-100: fix the <em>thing</em> in <code>module.py</code> (see <a href="https://example.test/pull/1)." rel="noopener noreferrer">https://example.test/pull/1).</a>',
    ),
    (
        "path https://example.test/a%20b/c~d/e+f/@g:h",
        'path <a href="https://example.test/a%20b/c~d/e+f/@g:h" rel="noopener noreferrer">https://example.test/a%20b/c~d/e+f/@g:h</a>',
    ),
    (
        "unicode https://example.test/ünï/путь ok",
        'unicode <a href="https://example.test/ünï/путь" rel="noopener noreferrer">https://example.test/ünï/путь</a> ok',
    ),
    ("", ""),
    ("   ", "   "),
)
BLOCK = (
    (
        "# Title\n\nA paragraph with **bold** and https://example.test.\nSecond line.",
        '<h1>Title</h1>\n<p>A paragraph with <strong>bold</strong> and <a href="https://example.test." rel="noopener noreferrer">https://example.test.</a><br>Second line.</p>',
    ),
    (
        "- one\n- two with `code`\n- [three](https://example.test)",
        '<ul><li>one</li><li>two with <code>code</code></li><li><a href="https://example.test" rel="noopener noreferrer">three</a></li></ul>',
    ),
    (
        "1. first\n2) second https://example.test/a\n",
        '<ol><li>first</li><li>second <a href="https://example.test/a" rel="noopener noreferrer">https://example.test/a</a></li></ol>',
    ),
    (
        "> a quote with *italic* and https://example.test",
        '<blockquote>a quote with <em>italic</em> and <a href="https://example.test" rel="noopener noreferrer">https://example.test</a></blockquote>',
    ),
    (
        "| a | b |\n|---|---|\n| [x](https://example.test) | https://example.test/b |\n| **c** | `d` |",
        '<div class="cockpit-table"><table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td><a href="https://example.test" rel="noopener noreferrer">x</a></td><td><a href="https://example.test/b" rel="noopener noreferrer">https://example.test/b</a></td></tr><tr><td><strong>c</strong></td><td><code>d</code></td></tr></tbody></table></div>',
    ),
    (
        "```python\nprint('<a href=\"https://example.test\">')\n```",
        '<pre><code class="language-python">print(&#x27;&lt;a href=&quot;https://example.test&quot;&gt;&#x27;)</code></pre>',
    ),
    (
        "```mermaid\ngraph TD; A-->B\n```\ntext",
        '<pre><code class="language-mermaid">graph TD; A--&gt;B</code></pre>\n<p>text</p>',
    ),
    ("---\n\n## Two\n\ntext *here*", "<hr>\n<h2>Two</h2>\n<p>text <em>here</em></p>"),
    (
        "para\n- item\n1. num\npara again",
        "<p>para</p>\n<ul><li>item</li></ul>\n<ol><li>num</li></ol>\n<p>para again</p>",
    ),
    (
        "###### deep [link](https://example.test) heading",
        '<h6>deep <a href="https://example.test" rel="noopener noreferrer">link</a> heading</h6>',
    ),
)
FORGE = (
    (
        "<!-- hidden -->visible **text** https://example.test",
        '<p>visible <strong>text</strong> <a href="https://example.test" rel="noopener noreferrer">https://example.test</a></p>',
    ),
    (
        "<details><summary>Fold <b>me</b></summary>\n\nbody [l](https://example.test)\n</details>",
        '<p><strong>Fold me</strong></p>\n<p>body <a href="https://example.test" rel="noopener noreferrer">l</a></p>',
    ),
    ("line one<br>line two<br/>line three", "<p>line one<br>line two<br>line three</p>"),
    (
        '<p>para</p> <img src="https://example.test/a.png"> <a href="https://example.test">link text</a>',
        "<p>para  link text</p>",
    ),
    ("<script>alert(1)</script> text", "<p>&lt;script&gt;alert(1)&lt;/script&gt; text</p>"),
)


@pytest.mark.parametrize("source,expected", INLINE)
def test_a_benign_line_renders_exactly_as_it_did(source, expected):
    assert _inline(source) == expected


@pytest.mark.parametrize("source,expected", BLOCK)
def test_a_benign_document_renders_exactly_as_it_did(source, expected):
    assert markdown(source) == expected


@pytest.mark.parametrize("source,expected", FORGE)
def test_a_benign_forge_comment_renders_exactly_as_it_did(source, expected):
    assert forge_markdown(source) == expected


PLAIN = {
    "strong",
    "em",
    "p",
    "br",
    "hr",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
VOID = {"br", "hr"}
SAFE = re.compile(r"^(https?://|mailto:)", re.I)
MADE = re.compile(
    r'<a href="[^"<>]*" rel="noopener noreferrer">|<code(?: class="language-[A-Za-z0-9_+-]+")?>|<div class="cockpit-table">'
    r"|</?(?:a|code|div|" + "|".join(sorted(PLAIN)) + ")>"
)


class Seen(HTMLParser):
    """Every tag of a rendered page, with the problems found on the way."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems, self.open, self.targets = [], [], []

    def handle_starttag(self, tag, attrs):
        names = [name for name, _ in attrs]
        if tag == "a":
            if names != ["href", "rel"] or dict(attrs)["rel"] != "noopener noreferrer":
                self.problems.append(f"a link with attributes {names}")
            target = dict(attrs).get("href") or ""
            self.targets.append(target)
            if not SAFE.match(target):
                self.problems.append(f"a link to {target!r}")
            if "a" in self.open:
                self.problems.append("a link inside a link")
        elif tag == "code":
            if names not in ([], ["class"]):
                self.problems.append(f"code with attributes {names}")
        elif tag == "div":
            if attrs != [("class", "cockpit-table")]:
                self.problems.append(f"div with attributes {attrs}")
        elif tag not in PLAIN:
            self.problems.append(f"a tag the renderer never makes: {tag}")
        elif attrs:
            self.problems.append(f"{tag} with attributes {names}")
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag):
        if not self.open or self.open[-1] != tag:
            self.problems.append(f"</{tag}> closes {self.open[-1:] or 'nothing'}")
        else:
            self.open.pop()


def problems(page: str) -> list:
    """What is wrong with a rendered page: a tag or attribute the renderer never makes, a quote or bracket loose in markup,
    a target that is not http(s) or mailto, or tags that do not nest."""
    seen = Seen()
    seen.feed(page)
    seen.close()
    found = list(seen.problems)
    if seen.open:
        found.append(f"left open: {seen.open}")
    rest = MADE.sub("", page)
    if "<" in rest or ">" in rest:
        found.append(f"a bracket outside the markup made here: {rest!r}")
    if "\x00" in page:
        found.append("a placeholder left in the page")
    return found


ATTACKS = (
    "[x](https://a.example.test/https://b.example.test/onmouseover=alert(1)//)",
    "[x](https://a.example.test/http://b.example.test/onmouseover=alert(1)//)",
    '[x](https://a.example.test/https://b.example.test/"onmouseover="alert(1))',
    "[x](HTTPS://a.example.test/https://b.example.test/onmouseover=alert(1)//)",
    "[x](mailto:a@example.test/https://b.example.test/onmouseover=alert(1)//)",
    "[x](https://a.example.test/https://b.example.test/https://c.example.test/onfocus=alert(1)//)",
    '[x](https://a.example.test/"onmouseover="alert(1))',
    "[x](https://a.example.test/'onmouseover='alert(1))",
    "[x](https://a.example.test/&quot;onmouseover=&quot;alert(1))",
    "[x](https://a.example.test/&#34;onmouseover=&#34;alert(1))",
    "[x](https://a.example.test/&amp;quot;onmouseover=alert(1))",
    '[x](mailto:a@example.test"onmouseover="alert(1))',
    "[x](https://a.example.test/><img/src=x/onerror=alert(1)>)",
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](data:text/html,<script>alert(1)</script>)",
    "[x](vbscript:msgbox(1))",
    "[x](&#106;avascript:alert(1))",
    "[x](&#x6a;avascript:alert(1))",
    "[x](&amp;#106;avascript:alert(1))",
    "[x](java&#9;script:alert(1))",
    "[x](&Tab;javascript:alert(1))",
    "[x](//evil.example.test/a)",
    "[x](\\\\evil.example.test\\a)",
    "[x](javascript:https://a.example.test/)",
    "[x](javascript://a.example.test/%0Aalert(1))",
    "[x](https://a.example.test/**b**)",
    "[x](https://a.example.test/*b*)",
    '[x](https://a.example.test/**b**"onfocus="alert(1))',
    "[x](https://a.example.test/`code`)",
    "[<img src=x onerror=alert(1)>](https://a.example.test)",
    '[" onmouseover="alert(1)](https://a.example.test)',
    '[https://a.example.test/"onmouseover="alert(1)](https://b.example.test)',
    '[see https://a.example.test/"onmouseover="alert(1)](https://b.example.test)',
    "[see https://a.example.test/x](https://b.example.test)",
    "[a [b](https://a.example.test/1)](https://b.example.test/2)",
    'https://a.example.test/"onmouseover="alert(1)',
    "https://a.example.test/'onmouseover='alert(1)",
    'https://a.example.test/https://b.example.test/"onmouseover="alert(1)',
    "https://a.example.test/&quot;onmouseover=alert(1)",
    "https://a.example.test/<script>alert(1)</script>",
    "**https://a.example.test/a** done",
    "**see https://a.example.test/a**",
    "*see https://a.example.test/a*",
    "*a [x](https://a.example.test/*b*) c*",
    "**a [x](https://a.example.test/**b**) c**",
    "**a [b** c](https://a.example.test/)",
    "*a [b* c](https://a.example.test/)",
    "https://a.example.test/*a*/**b**",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)" onmouseover="alert(1)">x</a>',
    "\x000\x00 [x](https://a.example.test/) \x001\x00",
    "\x0099\x00 **b** \x00",
    "[\x000\x00](https://a.example.test/\x000\x00)",
    "https://a.example.test/\x000\x00",
)


def test_the_nested_scheme_no_longer_breaks_out_of_the_target():
    page = _inline("[x](https://a.example.test/https://b.example.test/onmouseover=alert//)")
    assert (
        page
        == '<a href="https://a.example.test/https://b.example.test/onmouseover=alert//" rel="noopener noreferrer">x</a>'
    )


@pytest.mark.parametrize("source", ATTACKS)
def test_a_hostile_line_yields_only_the_markup_made_here(source):
    assert problems(_inline(source)) == []


@pytest.mark.parametrize("source", ATTACKS)
@pytest.mark.parametrize(
    "shape", ("{}", "# {}", "- {}", "1. {}", "> {}", "| a |\n|---|\n| {} |", "| {} |\n|---|\n| b |", "text\n{}\nmore")
)
def test_a_hostile_line_is_as_harmless_in_every_block(source, shape):
    assert problems(markdown(shape.format(source))) == []


@pytest.mark.parametrize("source", ATTACKS)
def test_a_hostile_forge_comment_yields_only_the_markup_made_here(source):
    assert problems(forge_markdown(source)) == []
    assert (
        problems(
            forge_markdown(f"<details><summary>{source}</summary>\n{source}<br>{source}</details><!-- {source} -->")
        )
        == []
    )


def test_every_link_made_from_hostile_text_goes_to_the_web_or_to_mail():
    for source in ATTACKS:
        seen = Seen()
        seen.feed(_inline(source))
        assert all(SAFE.match(target) for target in seen.targets), source


def test_a_target_keeps_its_stars_and_inner_addresses_as_written():
    assert (
        _inline("[x](https://a.example.test/**b**)")
        == '<a href="https://a.example.test/**b**" rel="noopener noreferrer">x</a>'
    )
    assert (
        _inline("[x](https://a.example.test/*b*)")
        == '<a href="https://a.example.test/*b*" rel="noopener noreferrer">x</a>'
    )
    assert _inline("https://a.example.test/http://b.example.test/c") == (
        '<a href="https://a.example.test/http://b.example.test/c" rel="noopener noreferrer">https://a.example.test/http://b.example.test/c</a>'
    )


def test_a_bare_address_is_one_link_and_emphasis_never_reaches_into_it():
    link = '<a href="https://a.example.test/a**" rel="noopener noreferrer">https://a.example.test/a**</a>'
    assert _inline("**https://a.example.test/a** done") == f"**{link} done"
    assert _inline("*see https://a.example.test/a*") == (
        '*see <a href="https://a.example.test/a*" rel="noopener noreferrer">https://a.example.test/a*</a>'
    )


def test_an_address_inside_a_label_is_not_a_second_link():
    assert _inline("[see https://a.example.test/x](https://b.example.test)") == (
        '<a href="https://b.example.test" rel="noopener noreferrer">see https://a.example.test/x</a>'
    )


def test_a_label_with_an_unsafe_target_stays_text_and_its_address_still_links():
    assert _inline("[see https://a.example.test/x](javascript:alert)") == (
        'see <a href="https://a.example.test/x" rel="noopener noreferrer">https://a.example.test/x</a>'
    )
    assert _inline("[**b**](javascript:alert)") == "<strong>b</strong>"


def test_a_nul_in_the_text_never_stands_for_markup():
    page = _inline("\x000\x00 [x](https://a.example.test/)")
    assert page == '�0� <a href="https://a.example.test/" rel="noopener noreferrer">x</a>'
    assert _inline("`a\x00b`") == "<code>a\x00b</code>"


HOSTILE_TARGETS = (
    "javascript:alert(1)",
    "data:text/html,x",
    "vbscript:x",
    "&#106;avascript:alert(1)",
    "//evil.example.test",
    'https://a.example.test/"onmouseover="alert(1)',
    "https://a.example.test/https://b.example.test/onmouseover=alert(1)//",
    "https://a.example.test/'><img src=x onerror=alert(1)>",
    " javascript:alert(1)",
)


@pytest.mark.parametrize("target", HOSTILE_TARGETS)
def test_a_tracker_document_links_only_to_the_web_or_to_mail(target):
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": '<b onmouseover="x">t</b> https://a.example.test/"onx="1',
                        "marks": [
                            {"type": "strong"},
                            {"type": "link", "attrs": {"href": target}},
                            {"type": "em"},
                            {"type": "code"},
                        ],
                    },
                    {"type": "inlineCard", "attrs": {"url": target}},
                    {"type": "mention", "attrs": {"text": '<img src=x onerror="alert(1)">'}},
                ],
            },
            {"type": "blockCard", "attrs": {"url": target}},
            {"type": "codeBlock", "content": [{"type": "text", "text": '</code></pre><img src=x onerror="alert(1)">'}]},
            {"type": "heading", "attrs": {"level": 9}, "content": [{"type": "text", "text": "<script>"}]},
            '<script>alert("1")</script>',
        ],
    }
    assert problems(adf(document)) == []
