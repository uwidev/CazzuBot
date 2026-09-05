"""Migration: fold retired frog species keys into their current species.

Two legacy key values can still sit in a database that was live through
the frog catalog's history and no longer resolve in the item registry
(hidden, non-consumable in ``/inventory``):

- ``frog:classy_frog:*`` — the pre-2026-08-23 Classy Frog: the species was
  keyed ``classy_frog`` until the catalog trimmed it, then re-added as
  ``classy`` (``FrogItemKey.CLASSY = "classy"``) with no data fold, so old
  holdings degraded to invisible dust while new catches took the new key;
- ``frog:leaf_frog:*`` — renamed to ``basic`` by ``005_frog_species_key``
  (``FrogItemKey.BASIC = "basic"``); included defensively for databases
  that never ran it.

This migration folds each legacy stack into the current species' stack —
same frog, new key — and rewrites the capture-log types to match (:func:`migrate`
sums, never overwrites: a member can hold the same species under both keys
simultaneously, and the ``(uid, item)`` primary key forbids duplicate rows).

Idempotent: ``needs_cleanup`` is False once no legacy value remains in
inventory or ``member_frog_log``. Run through ``scripts/migrate.py``
(all pending) or ``--only 008_frog_species_cleanup``; dry-run by default,
``--commit`` to write, backup before mutation, bot stopped.

Call graph: the harness registers this module's ``MIGRATION`` in
``scripts/migrations/__init__.py``; tests drive ``needs_cleanup`` /
``plan`` / ``migrate`` directly against a temp DB.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# retired species key value -> the key it currently lives under (mirror of
# plugins/frogs/species.py FrogItemKey values). The state suffix is
# preserved, so "frog:<legacy>:<state>" folds into "frog:<current>:<state>".
SPECIES_RENAMES: dict[str, str] = {
    "classy_frog": "classy",
    "leaf_frog": "basic",
}

# inventory rows carrying any legacy species key (shared by the gate/plan)
_LEGACY_INVENTORY_WHERE = (
    "item LIKE 'frog:classy_frog:%' OR item LIKE 'frog:leaf_frog:%'"
)


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    """What the cleanup found — the dry-run report."""

    inventory_rows: int  # legacy-key stacks to fold
    log_rows: int  # capture-log rows to rewrite


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """User table names in ``conn`` (sqlite-internal ones excluded)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r[0] for r in rows if not r[0].startswith("sqlite_")}


def needs_cleanup(conn: sqlite3.Connection) -> bool:
    """True while any legacy frog species key remains in the database.

    Checks both stored surfaces — inventory stacks and capture-log types
    (either table may be absent on a DB that never saw the frog work).
    The idempotence gate: after the fold (or on a DB born after the key
    changes) this is False.
    """
    tables = _table_names(conn)
    if "inventory" in tables:
        (hits,) = conn.execute(
            f"SELECT COUNT(*) FROM inventory WHERE {_LEGACY_INVENTORY_WHERE}"
        ).fetchone()
        if hits:
            return True
    if "member_frog_log" in tables:
        (hits,) = conn.execute(
            "SELECT COUNT(*) FROM member_frog_log WHERE type IN (?, ?)",
            (*SPECIES_RENAMES,),
        ).fetchone()
        if hits:
            return True
    return False


def plan(conn: sqlite3.Connection) -> CleanupPlan:
    """Read-only counts of what :func:`migrate` would do."""
    tables = _table_names(conn)
    inventory_rows = 0
    log_rows = 0
    if "inventory" in tables:
        (inventory_rows,) = conn.execute(
            f"SELECT COUNT(*) FROM inventory WHERE {_LEGACY_INVENTORY_WHERE}"
        ).fetchone()
    if "member_frog_log" in tables:
        (log_rows,) = conn.execute(
            "SELECT COUNT(*) FROM member_frog_log WHERE type IN (?, ?)",
            (*SPECIES_RENAMES,),
        ).fetchone()
    return CleanupPlan(inventory_rows=inventory_rows, log_rows=log_rows)


def migrate(conn: sqlite3.Connection) -> CleanupPlan:
    """Apply the fold in one transaction; returns what it did.

    Steps: fold each legacy inventory stack into its current species' stack
    (summing quantities when the target already exists, then dropping the
    legacy row — per-uid, per-state, so a member holding both `frog:classy:normal`
    and `frog:classy_frog:normal` ends with one merged stack); rewrite
    capture-log types to the current key. No DDL changes — the column
    defaults already carried the current values since ``003_frog_species``.
    Callers gate on :func:`needs_cleanup` — with no legacy rows there is
    nothing to do.
    """
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        if "inventory" in _table_names(conn):
            legacy = conn.execute(
                "SELECT uid, item, qty FROM inventory "
                + f"WHERE {_LEGACY_INVENTORY_WHERE}"
            ).fetchall()
            for uid, item, qty in legacy:
                _, legacy_species, state = item.split(":", 2)
                target = f"frog:{SPECIES_RENAMES[legacy_species]}:{state}"
                conn.execute(
                    "INSERT INTO inventory (uid, item, qty) "
                    + "VALUES (?, ?, ?) ON CONFLICT (uid, item) DO UPDATE "
                    + "SET qty = inventory.qty + excluded.qty",
                    (uid, target, qty),
                )
                conn.execute(
                    "DELETE FROM inventory WHERE uid = ? AND item = ?",
                    (uid, item),
                )
        if "member_frog_log" in _table_names(conn):
            for legacy, current in SPECIES_RENAMES.items():
                conn.execute(
                    "UPDATE member_frog_log SET type = ? WHERE type = ?",
                    (current, legacy),
                )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


MIGRATION = Migration(
    id="008_frog_species_cleanup",
    doc=(
        "fold retired frog species keys (classy_frog->classy, "
        "leaf_frog->basic) into their current species"
    ),
    needs=needs_cleanup,
    plan=plan,
    summary=lambda p: (
        f"fold {p.inventory_rows} inventory row(s) and rewrite "
        f"{p.log_rows} log row(s)"
    ),
    migrate=migrate,
)
