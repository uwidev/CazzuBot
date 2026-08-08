"""Backwards-compatible alias.

    python -m cazzubot.channels <verb> ...   ==   python -m cazzubot.cli channels <verb> ...

The real implementation lives in ``cazzubot.cli``.
"""

from __future__ import annotations

import sys

from cazzubot.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["channels", *sys.argv[1:]]))
