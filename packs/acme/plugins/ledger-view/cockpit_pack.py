# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixture validator: the block the acme pack gives this plugin."""


def validate(block, pack_dir):
    unknown = sorted(set(block) - {"pages", "currency"})
    if unknown:
        raise ValueError(f"unknown key {unknown[0]}")
    if not isinstance(block.get("pages", 1), int):
        raise ValueError("pages must be a whole number")
    return {"pages": 1, "currency": "EUR", **block}
