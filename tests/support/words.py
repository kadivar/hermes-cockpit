# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The words and names a pack's test reports are written with, for a test that writes one for either fixture pack:
one fixture pack names its own and the other takes the kernel's, so a test spells them through here."""

from cockpitlib import test_flow


def title(pack=None) -> str:
    return test_flow.title(pack)


def ok(pack=None) -> str:
    return test_flow.banners(pack)["ok"]


def not_ok(pack=None) -> str:
    return test_flow.banners(pack)["not_ok"]


def evidence(pack=None) -> str:
    return test_flow.evidence_dir(pack)


def review_mark(pack=None) -> str:
    return str(((pack or {}).get("testflow") or {}).get("review_mark") or test_flow.REVIEW_MARK)


WRITTEN = {  # the words of the fixture pack that names its own, which the tests' texts are written in
    "not_ok": "Tested and Not Ok",
    "ok": "Tested and Ok",
    "title": "Test Run",
    "review_mark": "ready for your review",
    "evidence": "evidences",
}


def worded(pack, text: str) -> str:
    """A text written in WRITTEN's words, in the words of the pack at hand (None: the kernel's own)."""
    for name, read in (("not_ok", not_ok), ("ok", ok), ("title", title), ("review_mark", review_mark)):
        text = text.replace(WRITTEN[name], read(pack))
    return text.replace(WRITTEN["evidence"] + "/", evidence(pack) + "/")
