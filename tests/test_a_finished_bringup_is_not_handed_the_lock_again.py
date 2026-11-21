# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A bring-up that finished before the parent recorded its pid is not locked again."""

import os

from cockpitlib.slots import _acquire, _hand_lock, _lock_path, lock_busy


def test_a_finished_bringup_is_not_handed_the_lock_again(bare):
    assert _acquire(1) is True
    os.remove(_lock_path(1))
    _hand_lock(1, os.getpid())
    assert not os.path.isfile(_lock_path(1)) and not lock_busy(1)
