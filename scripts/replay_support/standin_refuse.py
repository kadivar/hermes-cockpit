#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A command a replay never runs (the runtime's CLI, a transfer tool, a remote shell): it notes the call and refuses.

REPLAY_STANDIN names the command it stands in for; REPLAY_CALLS the file the call is appended to.
"""

import json
import os
import sys


def main(argv: list) -> int:
    name = os.environ.get("REPLAY_STANDIN") or os.path.basename(sys.argv[0])
    path = os.environ.get("REPLAY_CALLS")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "tool": name,
                        "kind": "refused",
                        "what": " ".join(argv[:2]),
                        "view": os.environ.get("REPLAY_VIEW") or "",
                    }
                )
                + "\n"
            )
    print(f"replay: {name} is not run during a replay", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
