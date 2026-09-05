"""Migration: rename the effects store to statuses.

Part of the 2026-08-31 terminology rename: the generic persistent
modifier store is now **statuses** (``cazzubot/statuses.py``,
``bot.statuses``). This migration renames the store's table
``effect_contribution`` → ``status_contribution`` (no column or value
changes: scope_kind/scope_id/seam/source/payload/expires_at and every
stored seam/source string stay byte-identical) and rewrites the
scheduler's convergence tag ``effect.converge`` → ``status.converge``
(a ``tasks`` projection update, idempotent for rows that already fired).

Two legacy shapes are reconciled, because the current code boots and
creates ``status_contribution`` itself:

- **target missing** — the store was never touched by the new code: plain
  ``ALTER TABLE ... RENAME``;
- **target already exists** — the new code booted while the legacy table
  was still present (e.g. prod pulled the statuses refactor, booted, and
  ``run_schema`` created the new table): fold any legacy rows into the
  existing table (they are byte-identical in shape; ``INSERT OR IGNORE``
  skips keys the new table already holds), then ``DROP`` the legacy one.

Idempotent: ``needs_migration`` is False once ``effect_contribution`` is
gone. Run through ``scripts/migrate.py`` (all pending) or
``--only 007_status_contribution``; dry-run by default, ``--commit`` to
write, backup before mutation, bot stopped.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """What the migration found — the dry-run report."""

    tables: int  # effected contribution tables (0 or 1)
    converger_rows: int  # tasks rows still tagged effect.converge


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True while the legacy ``effect_contribution`` table is present."""
    return "effect_contribution" in _table_names(conn)


def plan(conn: sqlite3.Connection) -> MigrationPlan:
    """Read-only report of what :func:`migrate` would reconcile."""
    converger_rows = 0
    if "tasks" in _table_names(conn):
        (converger_rows,) = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE tag = 'effect.converge'"
        ).fetchone()
    return MigrationPlan(
        tables=1 if "effect_contribution" in _table_names(conn) else 0,
        converger_rows=converger_rows,
    )


def migrate(conn: sqlite3.Connection) -> MigrationPlan:
    """Apply in one transaction; returns what it did.

    When the target is absent, ``ALTER TABLE ... RENAME`` preserves row
    data, the PK and indexes; no FK references the table. When the target
    already exists (the current code booted and created it), fold the
    legacy rows in with ``INSERT OR IGNORE`` — the two tables share the
    same shape and PK, so a key the new table already holds is left as-is
    — then drop the legacy table. The tag rewrite touches only the
    scheduler's ``tasks`` projection for the status store's converge
    jobs (no-op when the scheduler table does not exist yet), leaving
    every other tag untouched.
    """
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        if "effect_contribution" in _table_names(conn):
            if "status_contribution" in _table_names(conn):
                conn.execute(
                    "INSERT OR IGNORE INTO status_contribution "
                    + "SELECT * FROM effect_contribution"
                )
                conn.execute("DROP TABLE effect_contribution")
            else:
                conn.execute(
                    "ALTER TABLE effect_contribution RENAME TO"
                    + " status_contribution"
                )
        if "tasks" in _table_names(conn):
            conn.execute(
                "UPDATE tasks SET tag = 'status.converge'"
                + " WHERE tag = 'effect.converge'"
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


def verify(conn: sqlite3.Connection) -> None:
    """Post-commit checks: the rename landed and no stale tag remains."""
    tables = _table_names(conn)
    assert "effect_contribution" not in tables, "legacy table not renamed"
    assert "status_contribution" in tables, "status_contribution missing"
    if "tasks" in tables:
        (rows,) = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE tag = 'effect.converge'"
        ).fetchone()
        assert rows == 0, "stale effect.converge task rows remain"


MIGRATION = Migration(
    id="007_status_contribution",
    doc="rename effect_contribution -> status_contribution + converge tag",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"reconcile {p.tables} table(s), re-tag {p.converger_rows} task"
        + " row(s)"
    ),
    migrate=migrate,
    verify=verify,
)
