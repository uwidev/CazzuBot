"""Status-contribution migration — effect_contribution -> status_contribution.

Builds a temp DB shaped like the post-006 store (``effect_contribution``
plus a live converge task row), then drives ``needs_migration`` /
``plan`` / ``migrate`` / ``verify``; asserts the table rename preserves
rows and the tag rewrite lands. A fresh DB is skipped (idempotence gate).
"""

from __future__ import annotations

import sqlite3

from scripts.migrations.status_contribution import (
    migrate,
    needs_migration,
    plan,
    verify,
)

SCHEMA = """
CREATE TABLE effect_contribution (
    scope_kind TEXT NOT NULL,
    scope_id   INTEGER NOT NULL,
    seam       TEXT NOT NULL,
    source     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (scope_kind, scope_id, seam, source)
);
"""


def _conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        SCHEMA
        + """
        CREATE TABLE tasks (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            tag     TEXT NOT NULL,
            run_at  TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (run_at);
        """
    )
    return conn


def test_needs_gate_is_fresh_db_skipped(tmp_path) -> None:
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    try:
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_migrate_renames_table_and_rewrites_tag(tmp_path) -> None:
    conn = _conn(str(tmp_path / "live.db"))
    try:
        conn.execute(
            "INSERT INTO effect_contribution VALUES"
            " ('member', 1, 'classy_role', 'classy_role', '{}', NULL)"
        )
        conn.execute(
            "INSERT INTO tasks (tag, run_at, payload) VALUES"
            " ('effect.converge', '2026-01-01T00:00:00+00:00', '{}')"
        )
        conn.commit()

        assert needs_migration(conn) is True
        assert plan(conn).converger_rows == 1
        migrate(conn)
        verify(conn)

        row = conn.execute("SELECT * FROM status_contribution").fetchone()
        assert (row["scope_kind"], row["source"]) == (
            "member",
            "classy_role",
        )
        (tags,) = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE tag = 'status.converge'"
        ).fetchone()
        assert tags == 1
    finally:
        conn.close()
