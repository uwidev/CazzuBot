"""Backwards-compatible alias.

    python -m cazzubot.roles <verb> ...   ==   python -m cazzubot.cli roles <verb> ...

The real implementation lives in ``cazzubot.cli``.
"""

from __future__ import annotations

import sys

from cazzubot.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["roles", *sys.argv[1:]]))
