# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A review whose body asks nothing but a folded nitpick is not comments to treat."""

from cockpitlib import pr_watch

PACK = {"finding_labels": ["Blocker", "CS", "NTH"]}
NITPICK = (
    '<!-- bot -->\n\n<details>\n<summary><picture><img src="x.svg"></picture> Nitpick comments: 1</summary><blockquote>\n\n'
    "<details>\n<summary>tests/KpiTest.php: 1</summary><blockquote>\n\n`521-522`: **Trivial**\n\n"
    "NTH: **Test the role restriction separately.**\n\n<details>\n<summary>Prompt</summary>\n\ntext\n\n</details>\n\n"
    "</blockquote></details>\n\n</blockquote></details>\n"
)


def _review(body):
    return {"id": "review:1", "kind": "review", "author": "review-bot", "review_state": "COMMENTED", "body": body}


def test_a_review_of_one_folded_nitpick_asks_nothing_and_is_skipped():
    assert pr_watch.without_asides(NITPICK).strip() == "<!-- bot -->"
    assert pr_watch._skip(PACK, "me", _review(NITPICK)) == "only nitpicks in its body: nothing is asked"


def test_a_finding_outside_the_nitpick_section_still_counts():
    outside = (
        NITPICK
        + "\n<details>\n<summary>Outside diff range comments: 1</summary>\n\nCS: **This guard is wrong.**\n\n</details>\n"
    )
    assert "This guard is wrong" in pr_watch.without_asides(
        outside
    ) and "role restriction" not in pr_watch.without_asides(outside)
    assert pr_watch._skip(PACK, "me", _review(outside)) == ""
    assert pr_watch._skip(PACK, "me", _review("NTH: rename this\n")) == ""  # said in the open: asked
    assert (
        pr_watch._skip(PACK, "me", _review("<details>\n<summary>Details</summary>\n\nNTH: rename this\n\n</details>"))
        == ""
    )
    assert pr_watch._skip(PACK, "me", _review("Walkthrough only")).startswith("no finding tag")


def test_a_body_with_no_folds_or_a_fold_left_open_is_left_as_it_is():
    assert (
        pr_watch.without_asides("") == ""
        and pr_watch.without_asides(None) == ""
        and pr_watch.without_asides("plain") == "plain"
    )
    unclosed = "</details> stray close, then <details><summary>Nitpick comments: 2</summary> never closed"
    assert pr_watch.without_asides(unclosed) == unclosed
    assert pr_watch.without_asides("a <details>no summary</details> b") == "a <details>no summary</details> b"
