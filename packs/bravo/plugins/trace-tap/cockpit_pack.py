# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixture validator: the block the bravo pack gives this plugin."""


def validate(block, pack_dir):
    rate = block.get("sample_rate", 1.0)
    if set(block) - {"sample_rate"}:
        raise ValueError("only sample_rate is known")
    if not isinstance(rate, (int, float)) or not 0 < rate <= 1:
        raise ValueError("sample_rate is between 0 and 1")
    return {"sample_rate": float(rate)}
