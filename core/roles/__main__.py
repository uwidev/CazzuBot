"""Backwards-compatible alias.

    python -m core.roles <verb> ...   ==   python -m core.cli roles <verb> ...

The real implementation lives in ``core.cli``.
"""

from __future__ import annotations

import sys

from core.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["roles", *sys.argv[1:]]))
