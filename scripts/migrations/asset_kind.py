"""Migration: asset kinds ``'species'`` -> ``'image'``.

The asset kind enum changed (``AssetKind.IMAGE`` replaces ``SPECIES``:
the kind now describes how an asset is stored/accessed — a CDN-published
image vs. an inline emoji glyph — not what the asset depicts). Rows still
storing ``'species'`` cannot boot the renamed code: the schema guard's
enum coercion (``cazzubot.db._coerce_field``) raises on the stale value,
and the boot reconcile would otherwise force every IMAGE asset to
re-publish (new CDN URLs, the old ones deleted).

This renames the stored kind in place so existing published references
(CDN URLs) stay live across the rename.

Idempotent: ``needs_renaming`` is False once no ``'species'`` rows remain
(or the table is absent). Run through ``scripts/migrate.py`` (all pending)
or the thin wrapper ``scripts/rename_asset_kind.py``; dry-run by default,
``--commit`` to write, backup before mutation, bot stopped.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_renaming`` / ``plan`` / ``migrate`` directly against a
temp DB.
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

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


MIGRATION = Migration(
    id="004_asset_kind",
    doc="re-key stored asset kinds from 'species' to 'image'",
    needs=needs_renaming,
    plan=plan,
    summary=lambda p: (
        f"re-key {p.rows} asset row(s) from 'species' to 'image'"
    ),
    migrate=migrate,
)
