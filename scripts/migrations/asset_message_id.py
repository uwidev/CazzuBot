"""Migration: add ``asset.message_id`` (the published CDN message id).

Media asset rows stored only the CDN attachment URL as their published
reference. Discord's current attachment URL shape is
``…/attachments/<channel>/<attachment>/<file>`` — that second segment is
the **attachment** id, not the message id (the legacy shape embedded the
message id) — so the boot verification's ``fetch_message`` 404'd on every
media row and re-uploaded the asset on every boot. ``asset.message_id``
now records the message at publish time (``core.assets``).

Existing rows keep NULL: the id cannot be recovered from the URL, so the
next boot discovers the pre-existing message by matching the URL's
attachment id against the asset channel's recent messages and stores the
id (``Assets._published_message``) — the media is not re-uploaded.

Idempotent: ``needs_migration`` is False once the column exists (or the
asset table never existed). Run through ``scripts/migrate.py`` (all
pending) — dry-run by default, ``--commit`` to write, backup before
mutation, bot stopped.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_migration`` / ``plan`` / ``migrate`` directly against
a temp DB.
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# Mirrors core/assets.py _SCHEMA. Appended last because ALTER TABLE adds
# columns at the end — that keeps the on-disk column order identical to
# the DDL the boot-time schema guard compares against.
COLUMN_DDL = "ALTER TABLE asset ADD COLUMN message_id INTEGER"


@dataclass(frozen=True, slots=True)
class ColumnPlan:
    """What the column add found — the dry-run report."""

    rows: int  # published media rows whose message id is unknown


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(asset)")}


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True when a real asset table lacks the ``message_id`` column.

    Gated on the ``asset`` table existing (the assets service ran there),
    so a fresh DB that never published an asset is skipped like the other
    shape-gated migrations.
    """
    return _has_table(conn, "asset") and "message_id" not in _columns(conn)


def plan(conn: sqlite3.Connection) -> ColumnPlan:
    """Read-only count of media rows awaiting message discovery."""
    (rows,) = conn.execute(
        "SELECT COUNT(*) FROM asset WHERE kind = 'image' AND url IS NOT NULL"
    ).fetchone()
    return ColumnPlan(rows=rows)


def migrate(conn: sqlite3.Connection) -> ColumnPlan:
    """Add the column in one transaction; returns what it did."""
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        conn.execute(COLUMN_DDL)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


MIGRATION = Migration(
    id="011_asset_message_id",
    doc="add asset.message_id — the published CDN message id",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"add asset.message_id; {p.rows} published media row(s) adopt "
        + "their message on the next boot"
    ),
    migrate=migrate,
)
