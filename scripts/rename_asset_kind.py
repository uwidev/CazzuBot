"""Thin wrapper: runs the ``asset_kind`` migration through the shared
runner.

The real logic lives in ``scripts/migrations/asset_kind.py``; every
migration now shares the harness in ``scripts/migrations/common.py`` —
dry run by default, ``--commit`` to write, backup before mutation, run
while the bot is stopped. Equivalent to
``python scripts/migrate.py --only 004_asset_kind``; kept so the original
invocation keeps working.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrations.asset_kind import MIGRATION  # noqa: E402
from scripts.migrations.common import wrapper_main  # noqa: E402


def main() -> int:
    """Run the asset-kind rename (CLI entry)."""
    return wrapper_main(MIGRATION, __doc__)


if __name__ == "__main__":
    sys.exit(main())
