"""Migration: fold ``member_effect`` rows into the effects seam store.

The legacy shape (``cazzubot/member_effects.py``) is one scalar REAL value
per ``(uid, key)`` with replacement-on-set, member-only. The new shape
(``cazzubot/effects.py``) is the generic scope-aware seam store: each
modifier becomes a contribution with a ``source`` identity, a JSON
``payload`` the seam interprets, and the same lazy ``expires_at`` (NULL =
permanent). Migrated rows map uid → member scope, the legacy key → its
seam key, and the scalar ``value`` → the ``{"op": "mult", "value": v}``
payload the ``message_exp_multiplier`` pull expects.

Idempotent: ``needs_migration`` is False once ``member_effect`` is gone
(or never existed). Run through ``scripts/migrate.py`` (all pending) or
the thin wrapper ``scripts/migrate_effect_contributions.py``; dry-run by
default, ``--commit`` to write, backup before mutation, bot stopped.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_migration`` / ``plan`` / ``migrate`` directly against
a temp legacy DB and boot the bot on the result (schema guard acceptance).
"""

import json
import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# Mirrors cazzubot/effects.py exactly: the boot-time schema guard compares
# column order, defaults and constraints, so migrated tables must match the
# Python DDL.
EFFECT_CONTRIBUTION_DDL = """
CREATE TABLE IF NOT EXISTS effect_contribution (
    scope_kind TEXT NOT NULL,
    scope_id   INTEGER NOT NULL,
    seam       TEXT NOT NULL,
    source     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (scope_kind, scope_id, seam, source)
)
"""

# Legacy MemberEffectKey value -> seam key. The only legacy member effect
# is EXP_MULTIPLIER ("exp_multiplier"); its new home is experience's
# message_exp_multiplier seam. Unknown keys pass through unchanged (the
# store only ever sees seam strings).
LEGACY_SEAM_MAP = {"exp_multiplier": "message_exp_multiplier"}

# The synthetic source for migrated rows: there was no publisher identity
# in the legacy table, and live rows are ~zero (EXP_MULTIPLIER was only
# set in tests), so one shared tag is honest.
LEGACY_SOURCE = "legacy"


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """What the migration found — the dry-run report."""

    rows: int  # member_effect rows to fold


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True while the legacy ``member_effect`` table is present.

    The idempotence gate: after the migration (or on a fresh/new DB) the
    table is gone, so this is False.
    """
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return "member_effect" in tables


def plan(conn: sqlite3.Connection) -> MigrationPlan:
    """Read-only count of what :func:`migrate` would fold (the dry-run report)."""
    (rows,) = conn.execute("SELECT COUNT(*) FROM member_effect").fetchone()
    return MigrationPlan(rows=rows)


def migrate(conn: sqlite3.Connection) -> MigrationPlan:
    """Apply the migration in one transaction; returns what it did.

    Steps: create the generic ``effect_contribution``; fold every
    ``member_effect`` row (uid → member scope, key → seam key via
    ``LEGACY_SEAM_MAP``, ``value`` → ``{"op": "mult", "value": v}`` payload
    under the shared ``legacy`` source, ``expires_at`` carried over); drop
    the legacy table. Callers gate on :func:`needs_migration`.
    """
    before = plan(conn)
    rows = conn.execute(
        "SELECT uid, key, value, expires_at FROM member_effect"
    ).fetchall()
    conn.execute("BEGIN")
    try:
        conn.execute(EFFECT_CONTRIBUTION_DDL)
        for uid, key, value, expires_at in rows:
            conn.execute(
                """
                INSERT INTO effect_contribution
                    (scope_kind, scope_id, seam, source, payload, expires_at)
                VALUES ('member', ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    LEGACY_SEAM_MAP.get(key, key),
                    LEGACY_SOURCE,
                    json.dumps({"op": "mult", "value": value}),
                    expires_at,
                ),
            )
        conn.execute("DROP TABLE member_effect")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


def verify(conn: sqlite3.Connection) -> None:
    """Post-commit checks: the fold landed and the legacy table is gone."""
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "member_effect" not in tables, "member_effect was not dropped"
    assert "effect_contribution" in tables, "effect_contribution missing"


MIGRATION = Migration(
    id="006_effect_contributions",
    doc="fold member_effect rows into the effect_contribution seam store",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"fold {p.rows} member_effect row(s) into effect_contribution"
    ),
    migrate=migrate,
    verify=verify,
)
