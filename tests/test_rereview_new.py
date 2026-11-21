# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A PR the human reviews: the comments a re-review covered are no longer counted as new; what arrives after it is."""

import json
import os

import pytest

from cockpitlib.pack import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = (os.path.join(ROOT, "packs", "acme", "pack.yaml"), os.path.join(ROOT, "packs", "bravo", "pack.yaml"))


@pytest.mark.parametrize("pack_file", PACKS)
def test_a_rereview_covers_the_comments_so_far_and_only_later_ones_count_as_new(env, pack_file, monkeypatch):
    from cockpitlib import pr_watch
    from cockpitlib.outbox import create
    from tests.support import fake_gh

    monkeypatch.setenv("COCKPIT_PACK", pack_file)
    monkeypatch.delenv("COCKPIT_LANE", raising=False)
    pack = load(pack_file)
    me = pack["forge"]["human_login"]
    repo = pack["repos"]["repos"][0]["name"]
    full = f"{pack['forge']['org']}/{repo}"
    ticket = f"{pack['tracker']['project']}-2001"
    fake_gh.setup(me=me, repos=[full])
    fake_gh.pull(full, 5, "their-branch", "b" * 40, author="colleague")
    create(pack, ticket, "pr-review-submit", "c", "r", {"repo": repo, "number": 5, "sha": "b" * 40})
    fake_gh.review(full, 5, me, "CHANGES_REQUESTED", body="needs work", commit="b" * 40, at="2026-10-21T08:00:00Z")
    now = pr_watch._stamp("2026-10-21T08:00:00Z")
    pr_watch.watch(pack, now=now + 60)  # the baseline
    fake_gh.comment(full, 5, "colleague", "fixed the cache, please look again", at="2026-10-21T09:00:00Z")
    pr_watch.watch(pack, now=now + 3600)
    path = pr_watch.record_path(ticket, repo, 5)
    assert json.load(open(path))["new_count"] == 1
    pr_watch.request_rereview(pack, ticket, repo, 5, note="look again")
    record = json.load(open(path))
    assert record["new_count"] == 0 and record["new"] == [] and record["rereview"]["card"]
    pr_watch.watch(pack, now=now + 7200)
    assert json.load(open(path))["new_count"] == 0  # covered comments do not come back
    fake_gh.comment(full, 5, "colleague", "one more thing on the export", at="2026-10-21T11:00:00Z")
    pr_watch.watch(pack, now=now + 9000)
    assert json.load(open(path))["new_count"] == 1  # what came after the re-review counts


def test_a_forge_comment_is_rendered_without_its_hidden_html():
    from cockpitlib.pr_watch import normal
    from cockpitlib.render import forge_markdown

    body = (
        "_⚠️ Potential issue_ | _🟠 Major_\n\n**The kill switch keeps serving cached PDFs.**\n\n<details>\n<summary>🤖 Prompt for AI Agents</summary>\n\n"
        "```\nIn @src/a.php around line 4\n```\n\n</details>\n\n<!-- fingerprinting:phantom:abc -->\n<!-- This is an auto-generated comment -->\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\nline<br>break <script>x</script>"
    )
    html = forge_markdown(body)
    assert "<strong>The kill switch keeps serving cached PDFs.</strong>" in html
    assert "<strong>🤖 Prompt for AI Agents</strong>" in html and "details" not in html and "fingerprinting" not in html
    assert (
        '<div class="cockpit-table"><table>' in html and "&lt;script&gt;" in html
    )  # anything left is escaped, never live
    record = normal({"new": [{"id": "c1", "body": "**bold**"}], "replies": [{"text": "a `code`"}], "skipped": "x"})
    assert (
        record["new"][0]["html"] == "<p><strong>bold</strong></p>"
        and "<code>code</code>" in record["replies"][0]["html"]
    )
