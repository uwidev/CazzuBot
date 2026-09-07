"""Backwards-compatible alias.

    python -m core.channels <verb> ...   ==   python -m core.cli channels <verb> ...

The real implementation lives in ``core.cli``.
"""

from __future__ import annotations

import sys

from core.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["channels", *sys.argv[1:]]))
