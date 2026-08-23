"""One-off migration: asset kinds ``'species'`` -> ``'image'``.

The asset kind enum changed (``AssetKind.IMAGE`` replaces ``SPECIES``:
the kind now describes how an asset is stored/accessed — a CDN-published
image vs. an inline emoji glyph — not what the asset depicts). Rows still
storing ``'species'`` cannot boot the renamed code: the schema guard's
enum coercion (``cazzubot.db._coerce_field``) raises on the stale value,
and the boot reconcile would otherwise force every IMAGE asset to
re-publish (new CDN URLs, the old ones deleted).

This renames the stored kind in place so existing published references
(CDN URLs) stay live across the rename.

Run while the bot is stopped, BEFORE booting the renamed code. Defaults
to a dry run; pass ``--commit`` to write. The database is backed up to
``data/asset_kind_backup-<timestamp>.db`` before any mutation.
Idempotent: skips when no ``'species'`` rows remain.

Call graph (per the self-documenting rule): ``main()`` is the CLI entry
(``python scripts/rename_asset_kind.py``); it uses ``plan`` for the
dry-run report and ``migrate`` for the write. Tests drive ``plan`` /
``migrate`` / ``needs_renaming`` directly against a temp DB.
"""

import argparse
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_log = logging.getLogger("rename_asset_kind")

# mirrors cazzubot/assets.py AssetKind.IMAGE.value
LEGACY_KIND = "species"
CURRENT_KIND = "image"


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """What the rename found — the dry-run report."""

    rows: int  # asset rows to re-key


def needs_renaming(conn: sqlite3.Connection) -> bool:
    """True when any ``asset.kind`` row still stores ``'species'``.

    The idempotence gate: after the rename (or on a DB that never stored
    the old value) this is False.
    """
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "asset" not in tables:
        return False
    (hits,) = conn.execute(
        "SELECT COUNT(*) FROM asset WHERE kind = 'species'"
    ).fetchone()
    return hits > 0


def plan(conn: sqlite3.Connection) -> RenamePlan:
    """Read-only count of what :func:`migrate` would do."""
    (rows,) = conn.execute(
        "SELECT COUNT(*) FROM asset WHERE kind = 'species'"
    ).fetchone()
    return RenamePlan(rows=rows)


def migrate(conn: sqlite3.Connection) -> RenamePlan:
    """Apply the kind rename in one transaction; returns what it did."""
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE asset SET kind = 'image' WHERE kind = 'species'"
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


def main() -> int:
    """Rename stored asset kinds from ``'species'`` to ``'image'`` (CLI
    entry)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="data/cazzubot-prod.db",
        help="sqlite database file",
    )
    parser.add_argument(
        "--backup-dir",
        default="data",
        help="where to write the pre-rename backup (default data/)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="apply the change (dry-run by default)",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        if not needs_renaming(conn):
            print(
                f"{args.db}: no legacy 'species' kinds (already renamed or "
                "absent) — nothing to do"
            )
            return 0

        report = plan(conn)
        print(
            f"{args.db}: would re-key {report.rows} asset row(s) "
            "from 'species' to 'image'"
        )
        if not args.commit:
            print("dry run — pass --commit to apply")
            return 0

        backup = (
            Path(args.backup_dir)
            / f"asset_kind_backup-{time.strftime('%Y%m%d-%H%M%S')}.db"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(args.db)
        dst = sqlite3.connect(backup)
        src.backup(dst)
        dst.close()
        src.close()
        print(f"backed up to {backup}")

        did = migrate(conn)
        assert not needs_renaming(conn), "rename did not complete"
        print(f"renamed: {did.rows} asset row(s) to 'image'")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
